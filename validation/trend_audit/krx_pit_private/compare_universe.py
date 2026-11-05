"""Read existing private archives in memory and persist derived evidence privately."""
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.drive_collect import existing, folder, validate
from validation.trend_audit.krx_pit_private.drive_collect_history import (
    sessions, verify_private_archive,
)
from validation.trend_audit.krx_pit_private.drive_retry import read_retry, upload_archive
import exchange_calendars as xc

def independent_sessions():
    return xc.get_calendar("XKRX",start="2016-01-04",end="2016-12-29").sessions

FIRST = "20160108"
LAST = "20261030"

def classification(row):
    if row.get("KIND_STKCERT_TP_NM") != "보통주":
        return "excluded_share_class"
    if row.get("SECUGRP_NM") not in ("주권", "외국주권"):
        return "excluded_security_group"
    name = row.get("ISU_NM", "")
    if any(word in name.upper() for word in ("스팩", "SPAC", "기업인수목적")):
        return "uncertain_spac_name"
    return "common"

def compare_day(day, basic, daily, fixed):
    b = validate("basic", day, basic)
    d = validate("daily", day, daily)
    if b.keys() != d.keys():
        raise RuntimeError("Basic/daily mismatch")
    common = {c for c,r in b.items() if classification(r) == "common"}
    overlap = common & fixed
    missing = common - fixed
    outside = fixed - common
    return dict(
        date=day, pit=len(common), fixed_configured=len(fixed),
        overlap=len(overlap), missing_fixed=len(missing), fixed_not_pit=len(outside),
        jaccard=len(overlap)/len(common | fixed),
        pit_coverage=len(overlap)/len(common),
        zero_volume_common=sum(int(d[c]["ACC_TRDVOL"].replace(",",""))==0 for c in common),
        uncertain=sum(classification(r).startswith("uncertain") for r in b.values()),
    ), common, missing, outside, b, d

def main():
    report_path = ROOT/"backtest/data/validation_report.json"
    report = json.loads(report_path.read_text())
    fixed_rows = [r for r in report["tickers"] if r["status"] == "ok"]
    fixed = {r["ticker"] for r in fixed_rows}
    if len(fixed) != 162:
        raise RuntimeError("Reference universe differs")
    keys = ("GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN")
    drive = _build_service(*(os.environ[k] for k in keys))
    fid = read_retry(lambda: folder(drive))
    if fid != "1f_FAl_IL31nhw69gSgU5UCfW8P9LBbKY":
        raise RuntimeError("Wrong private destination")
    all_days = []
    private_days = []
    archives = {}
    seen = {}
    missing_codes = set()
    fixed_absent = Counter()
    identity = defaultdict(set)
    isin_codes = defaultdict(set)
    name_history = defaultdict(set)
    previous_common = set()
    boundary_events = []
    years = defaultdict(list)
    known_delist = {"117930": "20170307"} # Independently tested original anchor.
    for year in range(2016,2027):
        for month in range(1,11 if year == 2026 else 13):
            dates = ([x.strftime("%Y%m%d") for x in independent_sessions() if x.month == month]
                     if year == 2016 else sessions(year,month))
            name = f"KRX_PIT_{year}_{month:02d}_v1.json.gz"
            obj = read_retry(lambda: existing(drive,fid,name))
            if not obj:
                raise RuntimeError("Missing archive")
            data = read_retry(lambda: drive.files().get_media(fileId=obj["id"]).execute())
            sha = hashlib.sha256(data).hexdigest()
            if (obj.get("shared") is not False or hashlib.md5(data).hexdigest()!=obj["md5Checksum"]
                or sha not in obj.get("description","")):
                raise RuntimeError("Archive integrity failure")
            doc=json.loads(gzip.decompress(data))
            if doc.get("source")!="KRX OPEN API" or doc.get("year")!=year or doc.get("month")!=month:
                raise RuntimeError("Archive provenance mismatch")
            if [r["date"] for r in doc["records"]] != dates:
                raise RuntimeError("Archive calendar mismatch")
            archives[name] = sha
            for rec in doc["records"]:
                day = rec["date"]
                if not FIRST <= day <= LAST:
                    continue
                counts, common, missing, outside, b, d = compare_day(
                    day,rec["basic"],rec["daily"],fixed)
                if len({r["ISU_CD"] for r in b.values()}) != len(b):
                    raise RuntimeError("Same-day ISIN collision")
                counts["fixed_reported_price_span"] = sum(
                    bool(r.get("first") and r.get("last")) and
                    r["first"].replace("-","") <= day <= r["last"].replace("-","")
                    for r in fixed_rows)
                all_days.append(counts)
                years[year].append(counts)
                missing_codes.update(missing)
                fixed_absent.update(outside)
                for code in common:
                    row=b[code]
                    seen.setdefault(code,[day,day])[1]=day
                    identity[code].add(row["ISU_CD"])
                    isin_codes[row["ISU_CD"]].add(code)
                    name_history[(code,row["ISU_CD"])].add(row["ISU_NM"])
                boundary_events.append(dict(date=day,
                    newly_observed=sorted(common-previous_common),
                    no_longer_observed=sorted(previous_common-common)))
                previous_common=common
                # Keep full derived listing and differences only in owner-only Drive.
                private_days.append(dict(date=day,
                    members=[dict(code=c,isin=b[c]["ISU_CD"],name=b[c]["ISU_NM"],
                                  listing_date=b[c]["LIST_DD"],classification=classification(b[c]),
                                  zero_volume=int(d[c]["ACC_TRDVOL"].replace(",",""))==0,
                                  volume=d[c]["ACC_TRDVOL"])
                             for c in sorted(common)],
                    uncertain=[dict(code=c,isin=r["ISU_CD"],name=r["ISU_NM"])
                               for c,r in b.items() if classification(r).startswith("uncertain")],
                    missing_fixed=sorted(missing),
                    fixed_not_pit=[dict(code=c,reason=classification(b[c]) if c in b else
                                        "absent_KOSPI_snapshot_not_proof_of_delisting")
                                   for c in sorted(outside)]))
            print(f"COMPARE_MONTH_PASS year={year} month={month:02d}",flush=True)
    dates=[r["date"] for r in all_days]
    if dates != sorted(set(dates)) or len(archives)!=130:
        raise RuntimeError("Duplicate dates or missing archives")
    expected=[d for year in range(2016,2027) for month in range(1,11 if year==2026 else 13)
              for d in ([x.strftime("%Y%m%d") for x in independent_sessions() if x.month==month]
                        if year==2016 else sessions(year,month)) if FIRST<=d<=LAST]
    if dates != expected:
        raise RuntimeError("Evaluation calendar gap")
    annual=[]
    for year,rows in years.items():
        summary=dict(year=year,sessions=len(rows))
        for key in ("pit","overlap","missing_fixed","fixed_not_pit","jaccard","zero_volume_common","uncertain","fixed_reported_price_span"):
            summary[key+"_mean"]=sum(r[key] for r in rows)/len(rows)
        annual.append(summary)
        print("COMPARE_YEAR "+json.dumps(summary,sort_keys=True),flush=True)
    summary=dict(
        sessions=len(dates),archives_verified=len(archives),pit_unique_codes=len(seen),
        missing_fixed_unique=len(missing_codes),
        configured_fixed_codes=len(fixed),
        missing_fixed_code_days=sum(r["missing_fixed"] for r in all_days),
        fixed_not_pit_code_days=sum(r["fixed_not_pit"] for r in all_days),
        missing_codes_no_longer_observed_at_end=sum(seen[c][1]<LAST for c in missing_codes),
        independently_confirmed_delisted_missing_minimum=sum(c in missing_codes for c in known_delist),
        exact_delisted_missing_count=None,
        codes_multiple_isins=sum(len(x)>1 for x in identity.values()),
        isins_multiple_codes=sum(len(x)>1 for x in isin_codes.values()),
        price_reuse_verified=False,signal_impact_computed=False,
        verdict="FAIL_STATIC_UNIVERSE_PIT_COVERAGE",
    )
    source_files=["backtest/universe.py","backtest/01_fetch_data.py",
                  "backtest/02_validate_data.py","backtest/strategy.py",
                  "backtest/data/validation_report.json"]
    payload=dict(source="Derived KRX PIT universe comparison",schema=1,summary=summary,
        annual=annual,daily_counts=all_days,daily_membership=private_days,
        observed_boundary_events=boundary_events,
        identity_history=[dict(code=c,isins=sorted(v)) for c,v in identity.items()],
        isin_code_history={k:sorted(v) for k,v in isin_codes.items()},
        reference=dict(kind="repository validation_ok fixed snapshot",ordered_codes=[r["ticker"] for r in fixed_rows],
                       validated_at=report.get("validated_at"),price_spans=fixed_rows),
        caveats=["Absence is not a legal delisting date","positive volume does not prove execution",
                 "Name-only SPAC classification is unresolved","Original fixed snapshot includes deliberate selected-universe effects",
                 "Full original corrected replay input equivalence and 879 PIT panel comparison remain unverified"],
        input_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_files},
        archives_sha256=archives)
    compressed=gzip.compress(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(),mtime=0)
    sha=hashlib.sha256(compressed).hexdigest()
    name=f"KRX_PIT_UNIVERSE_COMPARE_{sha[:16]}.json.gz"
    def verify(obj):
        raw=read_retry(lambda: drive.files().get_media(fileId=obj["id"]).execute())
        if (obj.get("shared") is not False or hashlib.sha256(raw).hexdigest()!=sha
            or hashlib.md5(raw).hexdigest()!=obj.get("md5Checksum")):
            raise RuntimeError("Derived report upload integrity failure")
    upload_archive(drive,fid,name,f"Private PIT comparison sha256={sha}",compressed,existing,verify)
    print("COMPARE_SUMMARY "+json.dumps(summary,sort_keys=True),flush=True)
    print(f"PRIVATE_COMPARISON_SAVED sha256={sha}",flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        # Deliberately omit provider errors, URLs, identifiers and source rows.
        print("PRIVATE_COMPARISON_FAILED exception="+type(exc).__name__,flush=True)
        raise SystemExit(2)
