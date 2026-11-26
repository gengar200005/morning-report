"""Reproduce the frozen manual/automated quarterly comparisons from the receipt archive."""
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys

from filing_xbrl import extract


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(facts):
    return {
        name: [int(value) if value is not None else None for value in
               (facts["fields"][period][name]["value"] for period in ("current", "prior_as_reported"))]
        for name in ("revenue","operating_profit")
    }


def audit(raw, output):
    here=Path(__file__).parent
    manual=load(here/"quarter_holdout_manual.json")
    automated=load(here/"quarter_holdout_automated.json")
    machine={r["kind_receipt"]:r for r in automated}
    with (here/"quarter_holdout_frozen.csv").open(encoding="utf-8", newline="") as stream:
        roster={(s["quarter"],s["stock_code"],s["isin"]) for s in csv.DictReader(stream)}
    joined={(r["requested_quarter"],r["stock_code"],r["isin"]) for r in automated}
    if roster!=joined or len(machine)!=9 or len(automated)!=9:
        raise ValueError("Nine frozen filings required")
    package_records=load(raw/"package_manifest.json")
    package_by_kind={r["kind"]:r for r in package_records}
    if len(package_by_kind)!=14:
        raise ValueError("Expected 14 distinct original or amended filings")
    calendar=load(raw/"next_sessions.json")
    links={r["kind"]:r for r in load(raw/"crosslinks.json")}
    source, fact_values, checked = {},{},[]
    supplemental={"20201116001159","20210318001184","20220816001160"}
    manual_id={m["kind"] for m in manual}
    if set(package_by_kind)!=manual_id|supplemental or set(links)!=set(package_by_kind):
        raise ValueError("Incomplete source set")
    for receipt,r in package_by_kind.items():
        meta=load(raw/(receipt+"-src.json"))
        index=links[receipt]
        if (sha(raw/(receipt+".htm"))!=meta["sha256"] or sha(raw/(receipt+".dartlist.html"))!=index["sha256"]
                or r["receipt"]!=index["dart_receipt"] or r["corp"]!=index["corp_code"]):
            raise ValueError("Source hash or identity changed")
        report_period=meta["title"].rsplit("(",1)[1].strip(")")
        year,month=map(int,report_period.split("."))
        # Only the approved audited Q4 method uses cumulative inputs. All ordinary quarterly
        # reads use their own 3-month contexts even for the two non-December fiscal calendars.
        cumulative=meta["code"]=="192820" and month in (9,12)
        ff=extract(raw/(receipt+".zip"),r["receipt"],r["document"],r["corp"],
                   year,month//3,r["archive_sha256"],cumulative=cumulative)
        fact_values[receipt]=fields(ff)
        source[receipt]={"company":meta["name"],"code":meta["code"],"title":meta["title"],"kind_receipt":receipt,
                         "kind_doc":meta["kind_docno"],"dart_receipt":r["receipt"],"corp_code":r["corp"],
                         "kind_url":meta["url"],"kind_html_sha256":meta["sha256"],"xbrl_url":r["source_url"],
                         "zip_sha256":r["archive_sha256"],"xbrl_instance_sha256":ff["instance_sha256"],
                         "kind_published_kst":meta["kst"],"available_session":calendar[meta["kst"][:10].replace("-","")],
                         "target_contexts":ff["periods"]}
    for m in manual:
        n=m["kind"]; observed=fact_values[n]; reference={
            "revenue":[m["revenue_current"],m["revenue_comparison"]],
            "operating_profit":[m["op_current"],m["op_comparison"]]}
        if observed!=reference:
            raise ValueError(f"Submitted XBRL/independent manual differ at {n}: {observed} != {reference}")
        if n in machine:
            cf=machine[n]
            expected=reference if m["method"]!="annual" else dict(revenue=[None,None],operating_profit=[None,None])
            evidence={k:[cf["fields"][k].get(v) for v in ("current","prior")] for k in expected}
            if (expected!=evidence or cf["source_sha256"]!=m["sha256"] or cf["stock_code"]!=m["code"]
                    or cf["explicit_no_cfs"]!=(m["method"]=="explicit_no_cfs")):
                raise ValueError(f"Frozen direct extractor differs at {n}")
        checked.append(dict(receipt=n,method=m["method"],manual=reference,submitted_xbrl=observed))
    annual=fact_values["20220322001011"]
    nine=fact_values["20211115001552"]
    if (annual!=fact_values["20220816001160"] or any(annual[k][1]!=fact_values["20210318001184"][k][0]
            or nine[k][1]!=fact_values["20201116001159"][k][0] for k in annual)):
        raise ValueError("COSMAX prior publication, comparative or amendment differs; require basis review")
    derived={k:[a-b for a,b in zip(annual[k],nine[k],strict=True)] for k in annual}
    independent_ir=dict(revenue=[4212,3545],operating_profit=[304,105])
    rounded={k:[int((Decimal(v)/Decimal(100_000_000)).quantize(Decimal(1),rounding=ROUND_HALF_UP)) for v in values] for k,values in derived.items()}
    if independent_ir!=rounded:
        raise ValueError("Independent fourth-quarter release differs at its reported precision")
    by_quarter = {}
    direct_filings = []
    for n, auto in machine.items():
        quarter = auto["requested_quarter"]
        by_quarter.setdefault(quarter, [0,0])[1] += 1
        record = next(m for m in manual if m["kind"] == n)
        if record["method"] == "direct":
            direct_filings.append(n)
            by_quarter[quarter][0] += 1
        elif n == "20220322001011":
            by_quarter[quarter][0] += 1
    summary={"method":"9 fixed security/calendar-quarter cases. Separate audited outcomes from extraction eligibility.",
             "manual_sha256":sha(here/"quarter_holdout_manual.json"),"frozen_direct_sha256":sha(here/"quarter_holdout_automated.json"),
             "direct_numeric_filings":len(direct_filings),"direct_numeric_cells":sum(v is not None for n in direct_filings for vals in fact_values[n].values() for v in vals),
             "explicit_no_cfs_issuers":len({m["code"] for m in manual if m["method"]=="explicit_no_cfs"}),
             "q4_derived_filings":1,"eligible_amounts_by_quarter":{q:f"{n}/{total}" for q,(n,total) in by_quarter.items()},
             "cosmax_q4":{"computed_krw":derived,"issuer_IR_units_KRW_100m":independent_ir,
                   "issuer_dated":"2022-03-07","issuer_ir_url":"https://www.cosmax.com/new/upload/ckeditor/Files/20220307_131002_0293987.pdf",
                   "issuer_archive_status":"Search-indexed PDF text available; original PDF binary unavailable at legacy URL during replay. Hash not asserted.",
                   "periodic_signal_start":source["20220322001011"]["available_session"],"later_amendment_start":source["20220816001160"]["available_session"],
                   "basis":"Same-parent CFS exact-KRW YTD and FY; published prior-year columns reproduce both prior originals. Later amendment does not alter values. IR checks all four results only to its reported KRW 100m precision. The pool of subsidiaries can change during a year; this is consolidated performance as reported."},
             "sources":list(source.values()),"inputs_checked":checked}
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    audit(Path(sys.argv[1]),Path(sys.argv[2]))
