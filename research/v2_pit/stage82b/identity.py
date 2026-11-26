"""Link a historical KRX security to a KIND filing and a unique DART original.

Uses the stock code printed in KIND's date-filtered disclosure export. The KIND
and DART receipt identifiers belong to different namespaces. Correspondence is
an independent cross-index match, never an equality of those identifiers.
"""
import argparse
import csv
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from lxml import html

KIND = "https://kind.krx.co.kr/disclosure/details.do"
PARAMS = dict(method="searchDetailsSub", fromDate="2021-04-01", toDate="2021-06-30",
              marketType="1", disclosureType05="0503", disclosureTypeArr05="0503",
              pDisclosureType05="0503", disTypevalue="05", currentPageSize="100",
              orderMode="", orderStat="", reportNm="", reportNmTemp="")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": KIND+"?method=searchDetailsMain",
           "X-Requested-With": "XMLHttpRequest"}


def clean(value):
    return " ".join(value.split())


def issuer_key(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).upper().replace("주식회사", "").replace("(주)", "")


def read_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def obtain(cache, name, url, params=None):
    path = cache / name
    if path.exists():
        return path
    req = Request(url, data=urlencode(params).encode() if params is not None else None, headers=HEADERS)
    with urlopen(req, timeout=30) as response:
        data = response.read()
    if not data.strip():
        raise ValueError(f"empty response {name}")
    decode = "cp949" if name.startswith("xls") else "utf-8"
    doc = html.fromstring(data.decode(decode))
    if name.startswith(("xls", "page")) and not doc.xpath("//tr[td]"):
        raise ValueError(f"invalid KIND results {name}")
    path.write_bytes(data)
    return path


def kind_index(cache):
    cache.mkdir(parents=True, exist_ok=True)
    form_file = obtain(cache, "kind.html", KIND + "?method=searchDetailsMain")
    form, = html.fromstring(form_file.read_bytes().decode()).xpath('//form[@id="searchForm"]')
    params = {**dict(form.form_values()), **PARAMS}
    result, hashes = [], {}
    page = 1
    while True:
        base = {**params, "pageIndex": str(page)}
        path = obtain(cache, f"page{page}.html", KIND, {**base, "forward": "details_sub"})
        file_export = obtain(cache, f"xls{page}.html", KIND, {**base, "forward": "details_down"})
        tree = html.fromstring(path.read_bytes().decode())
        export = html.fromstring(file_export.read_bytes().decode("cp949"))
        headers = [clean(x.text_content()) for x in export.xpath("//tr[1]/th|//tr[1]/td")]
        if headers != ["번호", "시간", "회사명", "종목코드", "공시제목", "제출인"]:
            raise ValueError("unexpected KIND export schema")
        hashes[str(page)] = {"screen": fingerprint(path), "export": fingerprint(file_export)}
        info, = tree.xpath('//section[contains(@class,"paging-group")]//div[contains(@class,"info")]')
        total = int(info.xpath("string(em)").replace(",", ""))
        actual_page = int(info.xpath("string(strong)"))
        if page != actual_page or (page > 1 and expected_total != total):
            raise ValueError("inconsistent KIND pagination")
        expected_total = total
        xrows = export.xpath("//tr[td]")[1:] if export.xpath("//tr[1]/td") else export.xpath("//tr[td]")
        webrows = tree.xpath("//tbody/tr[td]")
        if len(webrows) != min(100, total-(page-1)*100):
            raise ValueError("missing KIND rows")
        for i,(web, xls) in enumerate(zip(webrows, xrows, strict=True)):
            cols = web.xpath("./td")
            values = [clean(col.text_content()) for col in xls.xpath("./td")]
            number, timestamp, name, stock, title, submitter = values
            display = cols[2].xpath(".//a")[0]
            filing = cols[3].xpath(".//a")[0]
            lhs = [clean(cols[0].text_content()), clean(cols[1].text_content()), clean(display.text_content()),
                   clean(filing.text_content()).replace(" ", ""), clean(cols[4].text_content())]
            if lhs != [number, timestamp, name, title.replace("[정]", "").replace(" ", ""), submitter] or int(number) != total-(page-1)*100-i:
                raise ValueError("KIND export and filing page disagree")
            prefix = re.fullmatch(r"companysummary_open\('([0-9A-Z]{5})'\); return false;",display.get("onclick")).group(1)
            if not re.fullmatch(r"[0-9A-Z]{6}", stock) or (prefix.isdigit() and not stock.startswith(prefix)):
                raise ValueError("KIND export code disagrees with HTML issuer key")
            receipt = re.fullmatch(r"openDisclsViewer\('(\d{14})',''\)",filing.get("onclick")).group(1)
            if not "2021-04-01" <= timestamp[:10] <= "2021-06-30":
                raise ValueError("KIND filing outside query period")
            result.append(dict(kind_receipt=receipt, stock_code=stock, kind_name=name, title=clean(filing.text_content()).replace(" ", ""),
                               submitter=submitter, timestamp=timestamp, page=page))
        if len(result) >= total:
            break
        page += 1
    if len(result) != total or len({r["kind_receipt"] for r in result}) != total:
        raise ValueError("duplicate or missing KIND receipt")
    return result, hashes


def official_securities(archives, days):
    evidence = {}
    for month in sorted({d[:6] for d in days}):
        source = Path(archives) / f"KRX_PIT_{month[:4]}_{month[4:]}_v1.json.gz"
        if not source.exists():
            continue
        archive = json.loads(gzip.decompress(source.read_bytes()))
        for session in archive["records"]:
            if session["date"] not in days:
                continue
            evidence[session["date"]] = {r["ISU_SRT_CD"]:r["ISU_CD"] for r in session["basic"]
                if (r["MKT_TP_NM"],r["SECUGRP_NM"],r["KIND_STKCERT_TP_NM"]) == ("KOSPI","주권","보통주")}
    return evidence


def build(universe, receipts, kind_rows, archives):
    declared = [r for r in kind_rows if re.fullmatch(r"분기보고서\([^()]+\)\(2021\.03\)",r["title"])]
    groups = defaultdict(list)
    for r in declared:
        groups[r["stock_code"]].append(r)
    events = defaultdict(list)
    for r in receipts:
        if r["type"] == "original" and clean(r["title"]) == "분기보고서 (2021.03)":
            events[(r["filed"],issuer_key(r["dart_display_name"]))].append(r)
    days = {"20210331"} | {r["timestamp"][:10].replace("-","") for r in declared}
    krx = official_securities(archives, days)
    outputs = []
    kind_by_alias = defaultdict(set)
    for record in declared:
        filed = record["timestamp"][:10].replace("-","")
        for alias in {issuer_key(record["kind_name"]), issuer_key(record["submitter"])}:
            kind_by_alias[(filed, alias)].add(record["kind_receipt"])
    for sec in universe:
        code = sec["stock_code"]
        if krx.get("20210331", {}).get(code) != sec["isin"]:
            raise ValueError("universe conflicts with quarter end ISIN")
        result = {**sec,"kind_receipt":"","kind_name":"","kind_timestamp":"","kind_page":"","dart_name":"",
                  "filing_date":"","corp_code_candidate":"","receipt_candidate":"","identity_status":"BLOCKED",
                  "reason":"no_unique_KIND_202103_original"}
        choices = groups[code]
        if len(choices)==1:
            k = choices[0]
            day = k["timestamp"][:10].replace("-","")
            result.update(kind_receipt=k["kind_receipt"],kind_name=k["kind_name"],kind_timestamp=k["timestamp"],
                          kind_page=k["page"],filing_date=day)
            aliases = {issuer_key(k["kind_name"]), issuer_key(k["submitter"])}
            dart_matches = {r["receipt"]:r for alias in aliases for r in events[(day, alias)]}
            linked_aliases = [alias for alias in aliases if events[(day, alias)]]
            if len(dart_matches) == 1 and all(len(kind_by_alias[(day, alias)]) == 1 for alias in linked_aliases):
                d = next(iter(dart_matches.values()))
                result.update(dart_name=d["dart_display_name"],corp_code_candidate=d["corp_code"],receipt_candidate=d["receipt"])
                if krx.get(day,{}).get(code) == sec["isin"]:
                    result.update(identity_status="PASS",reason="same_ISIN_on_both_dates_unique_KIND_DART_original")
                else:
                    result["reason"] = "no_matching_filing_day_KRX_ISIN"
            else:
                result["reason"]="no_unambiguous_cross_index_issuer_date_period_type"
        outputs.append(result)
    counts = Counter(row["receipt_candidate"] for row in outputs if row["identity_status"]=="PASS")
    for row in outputs:
        if counts[row["receipt_candidate"]] > 1:
            row.update(identity_status="BLOCKED",reason="receipt_collision")
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("universe","dart_index","krx_archives","cache","output"):
        parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    krx_universe = read_rows(args.universe)
    if len({r['isin'] for r in krx_universe})!=len(krx_universe) or len({r['stock_code'] for r in krx_universe})!=len(krx_universe):
        raise ValueError("ambiguous historical KRX universe")
    kind, hashes = kind_index(args.cache)
    rows=build(krx_universe,read_rows(args.dart_index),kind,args.krx_archives)
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, values in (("identity_universe.csv",rows),("identity_kind.csv",kind)):
        with (args.output/filename).open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    summary={"denominator":len(rows),"statuses":dict(Counter(r['identity_status'] for r in rows)),
             "reasons":dict(Counter(r['reason'] for r in rows)),"kind_rows":len(kind),
             "source_sha256":{"kind":hashes,"dart_index":fingerprint(args.dart_index),
                              "krx_archives":{f.name:fingerprint(f) for f in sorted(args.krx_archives.glob("KRX_PIT_2021_0[3456]_v1.json.gz"))}}}
    (args.output/"identity_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print({k:v for k,v in summary.items() if k!="source_sha256"})
if __name__=="__main__":
    main()
