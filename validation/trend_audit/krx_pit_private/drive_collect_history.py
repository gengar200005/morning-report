"""Read-only KOSPI historical PIT collection 2017-2026 into owner-only Drive.

- Uses repository's existing approved KRX_API_KEY and Google Drive OAuth secrets.
- Preserves raw KRX responses only in private Drive, never uploads Actions artifacts.
- Exact market sessions from pinned XKRX calendar. No fixed 2016 holiday guesses.
- Archives are immutable and verified on resume; mismatches fail closed.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

import exchange_calendars as xc
import requests
from googleapiclient.http import MediaIoBaseUpload
from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.drive_collect import fetch,validate,folder,existing

from validation.trend_audit.krx_pit_private.drive_retry import read_retry, upload_archive, diagnostic
from googleapiclient.errors import HttpError

FIRST_YEAR=2017
LAST_YEAR=2026
LAST_DAY="20261030"
# Published exchange closure notices. Never infer a closure from an empty API result.
CLOSURES = frozenset(("20260603", "20260717"))
CLOSURE_SOURCE = "https://www.myasset.com/myasset/customer/notice/CU_0201000_P2.cmd?SEQ=202605281454350000000004&gubun=norNotice"
CONTEXT = {"stage": "startup", "date": "none", "year": 0, "month": 0}
VALIDATION_RULES = {
    "Invalid KRX row count": "KRX_ROW_COUNT",
    "Invalid or duplicate code": "KRX_CODE_FORMAT_OR_DUPLICATE",
    "Invalid market or ISIN": "KRX_MARKET_OR_ISIN",
    "Invalid listing date": "KRX_LISTING_DATE",
    "Incorrect daily market/date": "KRX_DAILY_MARKET_OR_DATE",
    "Invalid volume": "KRX_VOLUME",
}

def context(stage, day="none", year=0, month=0):
    CONTEXT.update(stage=stage, date=day, year=year, month=month)

def failure_details(exc):
    rule = VALIDATION_RULES.get(str(exc), "UNCLASSIFIED")
    if isinstance(exc, HttpError):
        status, reasons = diagnostic(exc)
        rule = "DRIVE_HTTP_" + str(status) + "_" + (",".join(reasons) or "unclassified")
    frames = traceback.extract_tb(exc.__traceback__)
    origin = next((f for f in reversed(frames) if Path(f.filename).name in
                   ("drive_collect.py", "drive_collect_history.py")), None)
    location = f"{Path(origin.filename).name}/{origin.name}/{origin.lineno}" if origin else "unknown"
    return dict(CONTEXT, exception=type(exc).__name__, rule=rule, location=location)


def sessions(year:int,month:int):
    if not (FIRST_YEAR<=year<=LAST_YEAR and 1<=month<=12):
        raise ValueError("Unsupported KRX period")
    if year==LAST_YEAR and month>10:
        raise ValueError("Future/unsupported 2026 months")
    stop=f"{year}-12-31" if year<LAST_YEAR else "2026-10-30"
    cal=xc.get_calendar("XKRX",start=f"{year}-01-01",end=stop)
    dates=[d for d in cal.sessions.strftime("%Y%m%d") if
           int(d[:4])==year and int(d[4:6])==month and d<=LAST_DAY and d not in CLOSURES]
    if not dates or len(dates)>23 or len(set(dates))!=len(dates):
        raise ValueError("Unexpected trading calendar month")
    return dates

def verify_private_archive(drive,obj,year,month,dates):
    if obj.get("shared") is not False or int(obj.get("size") or 0)<500:
        raise RuntimeError("Private archive metadata invalid")
    context("drive_read_archive", year=year, month=month)
    data=read_retry(lambda: drive.files().get_media(fileId=obj["id"]).execute())
    if hashlib.md5(data).hexdigest()!=obj.get("md5Checksum"):
        raise RuntimeError("Existing Drive MD5 mismatch")
    sha=hashlib.sha256(data).hexdigest()
    if sha not in str(obj.get("description") or ""):
        raise RuntimeError("Existing data checksum missing or wrong")
    doc=json.loads(gzip.decompress(data))
    if (doc.get("source")!="KRX OPEN API" or doc.get("schema")!=1 or
        doc.get("year")!=year or doc.get("month")!=month):
        raise RuntimeError("Wrong provenance or year/month")
    records=doc.get("records")
    if not isinstance(records,list) or [x.get("date") for x in records]!=dates:
        raise RuntimeError("Existing archive trading dates incomplete")
    # Verify every row again before accepting a previous upload as done.
    for x in records:
        context("verify_cached_basic", x["date"], year, month)
        b=validate("basic",x["date"],x["basic"])
        context("verify_cached_daily", x["date"], year, month)
        d=validate("daily",x["date"],x["daily"])
        if b.keys()!=d.keys() or len({row["ISU_CD"] for row in b.values()})!=len(b):
            raise RuntimeError("Existing archive code/ISIN mismatch")
    return sha

def run(year:int,months:list[int]):
    required=("KRX_API_KEY","GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN")
    if any(not os.environ.get(k) for k in required):
        raise RuntimeError("GitHub secret unavailable")
    drive=_build_service(*(os.environ[k] for k in required[1:]))
    fid=read_retry(lambda: folder(drive))
    if fid != "1f_FAl_IL31nhw69gSgU5UCfW8P9LBbKY":
        raise RuntimeError("Unexpected private destination")
    with requests.Session() as http:
        if year == 2026:
            # Exact failed date, limited to one read per service. Raw rows stay in memory.
            for kind in ("basic", "daily"):
                context("closure_diagnostic_" + kind, "20260603", 2026, 6)
                rows = fetch(http, kind, "20260603", os.environ["KRX_API_KEY"])
                try:
                    validate(kind, "20260603", rows)
                except ValueError as exc:
                    code = VALIDATION_RULES.get(str(exc), "UNCLASSIFIED")
                    print(f"CLOSURE_DIAGNOSTIC date=20260603 service={kind} rows={len(rows)} rule={code}", flush=True)
                else:
                    print(f"CLOSURE_DIAGNOSTIC date=20260603 service={kind} rows={len(rows)} rule=PASS", flush=True)
        for month in sorted(set(months)):
            context("drive_find_month", year=year, month=month)
            days=sessions(year,month)
            name=f"KRX_PIT_{year}_{month:02d}_v1.json.gz"
            prev=read_retry(lambda: existing(drive,fid,name))
            if prev is not None:
                sha=verify_private_archive(drive,prev,year,month,days)
                print(f"PRIVATE_ARCHIVE_VERIFIED_REUSED year={year} month={month:02d} days={len(days)} sha256={sha}",flush=True)
                continue
            records=[]
            for day in days:
                context("krx_fetch_basic", day, year, month)
                basic=fetch(http,"basic",day,os.environ["KRX_API_KEY"])
                context("krx_fetch_daily", day, year, month)
                daily=fetch(http,"daily",day,os.environ["KRX_API_KEY"])
                context("krx_validate_basic", day, year, month)
                b=validate("basic",day,basic)
                context("krx_validate_daily", day, year, month)
                d=validate("daily",day,daily)
                if b.keys()!=d.keys():
                    raise RuntimeError("Basic and daily listings diverged")
                if len({row["ISU_CD"] for row in b.values()})!=len(b):
                    raise RuntimeError("Duplicate ISIN")
                records.append({"date":day,"basic":basic,"daily":daily})
                # Only aggregate counts ever enter public CI logs.
                print(f"VALIDATED year={year} day={day} codes={len(b)}",flush=True)
            obj={"source":"KRX OPEN API","schema":1,"year":year,"month":month,"records":records}
            raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            compressed=gzip.compress(raw,mtime=0)
            sha=hashlib.sha256(compressed).hexdigest()
            desc=f"Private KRX PIT {year}-{month:02d}; days={len(records)}; sha256={sha}"
            def verify_upload(obj):
                actual = verify_private_archive(drive, obj, year, month, days)
                if actual != sha:
                    raise RuntimeError("Immutable archive differs from collected payload")
            context("drive_upload_month", year=year, month=month)
            upload_archive(drive, fid, name, desc, compressed, existing, verify_upload)
            print(f"PRIVATE_ARCHIVE_SAVED year={year} month={month:02d} days={len(records)} sha256={sha}",flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--months",nargs="+",type=int,required=True)
    args=p.parse_args()
    run(args.year,args.months)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        # Do not print exception body, API raw response, or OAuth URLs.
        print("HISTORY_ERROR " + json.dumps(failure_details(exc), sort_keys=True), flush=True)
        print("HISTORICAL_PRIVATE_KRX_FAILED "+type(exc).__name__,flush=True)
        sys.exit(2)
