"""Freeze small cross-quarter format samples from historical KRX security attributes only."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

from lxml import html


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def source_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fiscal_candidates(paths):
    records = []
    for source in paths:
        for row in html.fromstring(source.read_text()).xpath("//tbody/tr[td]"):
            cells = row.xpath("./td")
            if len(cells) < 4:
                continue
            companies = cells[2].xpath('.//a[contains(@onclick,"companysummary_open")]')
            reports = cells[3].xpath('.//a[contains(@onclick,"openDisclsViewer")]')
            if len(companies) != 1 or len(reports) != 1:
                continue
            title = "".join(reports[0].text_content().split())
            if not title.endswith("(2021.03)") or "[정정]" in title:
                continue
            if not re.search(r"(사업|반기)보고서", title):
                continue
            code = re.search(r"'(\d{5})'", companies[0].get("onclick"))
            receipt = re.search(r"'(\d{14})'", reports[0].get("onclick"))
            if code and receipt:
                records.append((code[1], receipt[1], title))
    return set(records)


def run(archives, kind_pages, qc8, qc11, output_directory):
    nondec = fiscal_candidates(kind_pages)
    skip = {"005930", "066570", "000660", "117930", "002000"}
    skip.update(row["stock_code"] for path in (qc8,qc11) for row in read_csv(path))
    selected = []
    metadata = []
    for q, archive in zip((2,3,4), archives, strict=True):
        quarter = f"2021Q{q}"
        obj = json.loads(gzip.decompress(archive.read_bytes()))
        day = max(obj["records"], key=lambda r:r["date"])
        if not day["date"].startswith(f"2021{q*3:02}"):
            raise ValueError("Wrong month for frozen universe")
        members = [r for r in day["basic"] if (r["MKT_TP_NM"],r["SECUGRP_NM"],r["KIND_STKCERT_TP_NM"]) == ("KOSPI","주권","보통주")]
        if len({r["ISU_CD"] for r in members}) != len(members):
            raise ValueError("Duplicate quarter-end identity")
        nondec_map = {}
        for prefix, receipt, report in sorted(nondec):
            possible = [r for r in members if r["ISU_SRT_CD"].startswith(prefix)]
            if len(possible) == 1 and receipt[:8] <= day["date"]:
                nondec_map.setdefault(possible[0]["ISU_CD"], []).append([receipt, report])
        eligible = [r for r in members if r["ISU_SRT_CD"] not in skip]
        def ranking(row):
            key = f"MR-v2-period-forms-1|{quarter}|"+row["ISU_CD"]
            return hashlib.sha256(key.encode()).hexdigest(),row["ISU_CD"]
        eligible.sort(key=ranking)
        for label,count,subset in (("fiscal_form_challenge",1,True),("general",2,False)):
            draws = [r for r in eligible if (r["ISU_CD"] in nondec_map)==subset][:count]
            if len(draws)!=count:
                raise ValueError("Missing preregistered stratum; do not replace")
            for row in draws:
                selected.append(dict(quarter=quarter,denominator_date=day["date"],stratum=label,
                                     stock_code=row["ISU_SRT_CD"],isin=row["ISU_CD"],issuer=row["ISU_ABBRV"],
                                     rank_sha256=ranking(row)[0],challenge_metadata=json.dumps(nondec_map.get(row["ISU_CD"],[]),ensure_ascii=False)))
                skip.add(row["ISU_SRT_CD"])
        metadata.append({"quarter":quarter, "date":day["date"],"historical_universe":len(members),
                         "eligible_after_exclusions":len(eligible),"eligible_fiscal_challenges":sum(r["ISU_CD"] in nondec_map for r in eligible),
                         "archive":archive.name,"archive_sha256":source_hash(archive)})
    output_directory.mkdir(exist_ok=True, parents=True)
    out=output_directory/"quarter_holdout_frozen.csv"
    with out.open("w",newline="",encoding="utf-8") as stream:
        w=csv.DictWriter(stream,fieldnames=list(selected[0]));w.writeheader();w.writerows(selected)
    (output_directory/"quarter_holdout_sources.json").write_text(json.dumps(dict(
        quarters=metadata,prior_evidence={p.name:source_hash(p) for p in (*kind_pages,qc8,qc11)},
        assignment_sha256=source_hash(out)),indent=2,ensure_ascii=False)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archives",nargs=3,required=True,type=Path)
    p.add_argument("--kind-pages",nargs=2,required=True,type=Path)
    for arg in ("qc8","qc11","out"):
        p.add_argument("--"+arg,type=Path,required=True)
    args=p.parse_args()
    run(args.archives,args.kind_pages,args.qc8,args.qc11,args.out)
