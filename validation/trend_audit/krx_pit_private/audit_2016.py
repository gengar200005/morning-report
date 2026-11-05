"""Audit 2016 KRX private Drive archives against an independent XKRX calendar.

Only aggregate counts and checksum results are emitted. Official KRX rows stay in Drive.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import exchange_calendars as xc
from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.drive_collect import validate,folder,existing

def main():
    keys=("GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN")
    if any(not os.environ.get(k) for k in keys):
        raise RuntimeError("Missing Drive OAuth credentials")
    drive=_build_service(*(os.environ[k] for k in keys))
    fid=folder(drive)
    exchange=xc.get_calendar("XKRX",start="2016-01-04",end="2016-12-29")
    expected=set(exchange.sessions.strftime("%Y%m%d"))
    if len(expected)!=246: raise ValueError("Calendar version changed")
    archive_digests=[]
    observed=set()
    universe=set()
    mincount=100000
    maxcount=0
    zero_volume_days=0
    previous=set()
    for m in range(1,13):
        name="KRX_PIT_2016_%02d_v1.json.gz"%m
        obj=existing(drive,fid,name)
        if not obj or obj.get("shared") is not False:
            raise RuntimeError("Monthly archive missing or unsafe")
        data=drive.files().get_media(fileId=obj["id"]).execute()
        if hashlib.md5(data).hexdigest()!=obj.get("md5Checksum"):
            raise RuntimeError("Google Drive MD5 mismatch")
        digest=hashlib.sha256(data).hexdigest()
        if digest not in (obj.get("description") or ""):
            raise RuntimeError("Producer checksum not found")
        doc=json.loads(gzip.decompress(data))
        if doc.get("source")!="KRX OPEN API" or doc.get("schema")!=1 or doc.get("year")!=2016 or doc.get("month")!=m:
            raise ValueError("Wrong private archive provenance")
        records=doc.get("records")
        if not isinstance(records,list) or not records: raise ValueError("Empty month")
        mon_days=[r.get("date") for r in records]
        if len(mon_days)!=len(set(mon_days)) or mon_days!=sorted(mon_days):
            raise ValueError("Duplicate or unordered dates")
        if set(mon_days)!={d for d in expected if d[4:6]==f"{m:02d}"}:
            raise ValueError("Archive does not match independent calendar")
        for item in records:
            day=item["date"]
            if day in observed: raise ValueError("Duplicate trading day across archives")
            b=validate("basic",day,item["basic"])
            d=validate("daily",day,item["daily"])
            if b.keys()!=d.keys(): raise ValueError("KRX basic/daily code set mismatch")
            if len({r["ISU_CD"] for r in b.values()})!=len(b):
                raise ValueError("Duplicate ISIN for same trading day")
            observed.add(day)
            universe.update(b)
            mincount=min(mincount,len(b))
            maxcount=max(maxcount,len(b))
            zero_volume_days+=sum(str(v.get("ACC_TRDVOL","0")).replace(",","")=="0" for v in d.values())
        archive_digests.append(digest)
        print("AUDIT_MONTH_PASS month=%02d days=%d"%(m,len(records)),flush=True)
    if observed!=expected: raise ValueError("Missing 2016 trading sessions")
    print("AUDIT_2016_PASS days=%d months=12 unique_codes=%d daily_codes_min=%d daily_codes_max=%d zero_volume_rows=%d archive_sha256_set=%s"%(
          len(observed),len(universe),mincount,maxcount,zero_volume_days,
          hashlib.sha256("".join(archive_digests).encode()).hexdigest()),flush=True)

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("AUDIT_2016_FAILED "+type(e).__name__,flush=True)
        sys.exit(2)
