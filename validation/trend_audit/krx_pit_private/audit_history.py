"""Read-only independent historical audit of private KRX monthly PIT archives.

Rows stay within private Drive and runner memory. Only aggregate checks are logged.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.drive_collect import validate,folder,existing
from validation.trend_audit.krx_pit_private.drive_collect_history import sessions

SENTINELS={
  2017:[("20170306","117930",True),("20170307","117930",False)],
  2018:[("20180208","068270",False),("20180209","068270",True)],
  2026:[("20261030","0120G0",True)]
}

def audit(year):
    keys=("GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN")
    if any(not os.environ.get(k) for k in keys):
        raise RuntimeError("Drive secret missing")
    drive=_build_service(*(os.environ[k] for k in keys))
    fid=folder(drive)
    all_dates=set()
    all_codes=set()
    code_to_isin={}
    isin_to_code={}
    zero_volume=0
    samples={}
    hashes=[]
    months=range(1,11 if year==2026 else 13)
    for month in months:
        dates=sessions(year,month)
        name=f"KRX_PIT_{year}_{month:02d}_v1.json.gz"
        obj=existing(drive,fid,name)
        if not obj or obj.get("shared") is not False:
            raise RuntimeError("Missing or insecure KRX archive")
        data=drive.files().get_media(fileId=obj["id"]).execute()
        if hashlib.md5(data).hexdigest()!=obj.get("md5Checksum"):
            raise RuntimeError("Drive MD5 mismatch")
        sha=hashlib.sha256(data).hexdigest()
        if sha not in (obj.get("description") or ""):
            raise RuntimeError("Collector SHA mismatch")
        doc=json.loads(gzip.decompress(data))
        if (doc.get("source")!="KRX OPEN API" or doc.get("schema")!=1 or
            doc.get("year")!=year or doc.get("month")!=month):
            raise RuntimeError("Unexpected provenance or period")
        records=doc.get("records")
        if not isinstance(records,list) or [r.get("date") for r in records]!=dates:
            raise RuntimeError("Trading calendar differs from KRX archive")
        for rec in records:
            day=rec["date"]
            if day in all_dates:
                raise RuntimeError("Duplicate day")
            basic=validate("basic",day,rec["basic"])
            daily=validate("daily",day,rec["daily"])
            if basic.keys()!=daily.keys():
                raise RuntimeError("Official KRX endpoints disagree")
            if len({r["ISU_CD"] for r in basic.values()})!=len(basic):
                raise RuntimeError("Duplicated same-day ISIN")
            all_dates.add(day)
            all_codes.update(basic)
            for code,r in basic.items():
                isin=r["ISU_CD"]
                code_to_isin.setdefault(code,set()).add(isin)
                isin_to_code.setdefault(isin,set()).add(code)
            zero_volume+=sum(str(r.get("ACC_TRDVOL","")).replace(",","")=="0" for r in daily.values())
            for d,code,_ in SENTINELS.get(year,[]):
                if day==d:
                    samples[(d,code)]=code in basic
        hashes.append(sha)
        print(f"ARCHIVE_AUDIT_PASS year={year} month={month:02d} sessions={len(dates)}",flush=True)

    expected={d for month in months for d in sessions(year,month)}
    if all_dates!=expected:
        raise RuntimeError("Historical KOSPI calendar gap")
    for day,code,want in SENTINELS.get(year,[]):
        if samples.get((day,code)) is not want:
            raise RuntimeError("Historical listing boundary contradiction")
    collisions=sum(len(v)>1 for v in code_to_isin.values())
    reroutes=sum(len(v)>1 for v in isin_to_code.values())
    print(
        f"YEAR_AUDIT_PASS year={year} sessions={len(all_dates)} months={len(list(months))} "
        f"unique_codes={len(all_codes)} zero_volume_rows={zero_volume} "
        f"codes_with_multiple_isins={collisions} isins_with_multiple_codes={reroutes} "
        f"archive_sha256_set={hashlib.sha256(''.join(hashes).encode()).hexdigest()}",
        flush=True
    )

if __name__=="__main__":
    try:
        p=argparse.ArgumentParser()
        p.add_argument("--year",type=int,required=True)
        audit(p.parse_args().year)
    except Exception as exc:
        print("PRIVATE_YEAR_AUDIT_FAILED "+type(exc).__name__,flush=True)
        sys.exit(2)
