"""Read-only historical KOSPI collection into the user's unshared Google Drive folder.
No GitHub artifacts or public raw data; no production strategy changes.
"""
import argparse
from collections import Counter
from datetime import date,timedelta
import gzip,hashlib,io,json,os,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import requests
from googleapiclient.http import MediaIoBaseUpload
from gdrive_upload import _build_service

FOLDER="KRX_PIT_GITHUB_ACTIONS_PRIVATE"
API={"basic":"stk_isu_base_info","daily":"stk_bydd_trd"}
BASE="https://data-dbg.krx.co.kr/svc/apis/sto/"
HOLIDAYS=set("2016-02-08 2016-02-09 2016-02-10 2016-03-01 2016-04-13 2016-05-05 2016-05-06 2016-06-06 2016-08-15 2016-09-14 2016-09-15 2016-09-16 2016-10-03".split())
CODE=re.compile("[0-9A-Z]{6}")
ISIN=re.compile("[0-9A-Z]{12}")

def calendar(month):
    if not 1<=month<=12: raise ValueError("invalid month")
    d=date(2016,1,4)
    end=date(2016,12,29)
    dates=[]
    while d<=end:
        if d.weekday()<5 and d.isoformat() not in HOLIDAYS and d.month==month:
            dates.append(d.strftime("%Y%m%d"))
        d+=timedelta(days=1)
    return dates

def validate(kind,day,rows):
    if not isinstance(rows,list) or not 600<=len(rows)<=1600:
        raise ValueError("Invalid KRX row count")
    field="ISU_SRT_CD" if kind=="basic" else "ISU_CD"
    entries={}
    for r in rows:
        code=r.get(field) if isinstance(r,dict) else None
        if not isinstance(code,str) or not CODE.fullmatch(code) or code in entries:
            raise ValueError("Invalid or duplicate code")
        if kind=="basic":
            if r.get("MKT_TP_NM")!="KOSPI" or not ISIN.fullmatch(str(r.get("ISU_CD",""))):
                raise ValueError("Invalid market or ISIN")
            dt=str(r.get("LIST_DD",""))
            if not re.fullmatch("[0-9]{8}",dt) or dt>day:
                raise ValueError("Invalid listing date")
        else:
            if r.get("MKT_NM")!="KOSPI" or r.get("BAS_DD")!=day:
                raise ValueError("Incorrect daily market/date")
            if not str(r.get("ACC_TRDVOL","")).replace(",","").isdigit():
                raise ValueError("Invalid volume")
        entries[code]=r
    return entries

def fetch(session,kind,day,key):
    for attempt in range(3):
        time.sleep(1.1+attempt)
        try:
            response=session.get(BASE+API[kind],headers={"AUTH_KEY":key,"Accept":"application/json"},
                                 params={"basDd":day},timeout=(8,25),allow_redirects=False)
            if response.status_code==200:
                obj=response.json()
                if not isinstance(obj,dict) or not isinstance(obj.get("OutBlock_1"),list):
                    raise RuntimeError("Unexpected response schema")
                return obj["OutBlock_1"]
            if response.status_code not in (429,500,502,503,504):
                raise RuntimeError("API rejected request")
        except requests.RequestException:
            pass
    raise RuntimeError("API retry limit reached")

def folder(drive):
    q="name = '%s' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"%FOLDER
    x=drive.files().list(q=q,spaces="drive",fields="nextPageToken,files(id,name,mimeType,shared)",pageSize=100).execute()
    files=x.get("files",[])
    if x.get("nextPageToken") or len(files)!=1:
        raise RuntimeError("Private destination unavailable")
    fid=files[0]["id"]
    info=drive.files().get(fileId=fid,fields="id,name,mimeType,shared").execute()
    if info.get("name")!=FOLDER or info.get("shared") is not False:
        raise RuntimeError("Destination not verified private")
    return fid

def existing(drive,fid,name):
    q="name = '%s' and '%s' in parents and trashed = false"%(name,fid)
    x=drive.files().list(q=q,spaces="drive",fields="nextPageToken,files(id,name,md5Checksum,size,shared,description)",pageSize=100).execute()
    rows=x.get("files",[])
    if x.get("nextPageToken") or len(rows)>1: raise RuntimeError("Duplicate Drive archive")
    return rows[0] if rows else None

def run(months):
    if len([d for m in range(1,13) for d in calendar(m)])!=246:
        raise ValueError("Unreviewed calendar")
    required=("KRX_API_KEY","GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN")
    if any(not os.environ.get(x) for x in required):
        raise RuntimeError("Missing repository secret")
    drive=_build_service(*(os.environ[x] for x in required[1:]))
    fid=folder(drive)
    with requests.Session() as session:
        for month in sorted(set(months)):
            name="KRX_PIT_2016_%02d_v1.json.gz"%month
            old=existing(drive,fid,name)
            if old:
                if old.get("shared") is not False or not old.get("md5Checksum") or int(old.get("size") or 0)<100:
                    raise RuntimeError("Unverifiable existing archive")
                print("PRIVATE_ARCHIVE_REUSED month=%02d"%month,flush=True)
                continue
            records=[]
            for day in calendar(month):
                b=fetch(session,"basic",day,os.environ["KRX_API_KEY"])
                d=fetch(session,"daily",day,os.environ["KRX_API_KEY"])
                ib=validate("basic",day,b)
                id=validate("daily",day,d)
                if ib.keys()!=id.keys(): raise ValueError("Market panel code mismatch")
                commons=sum(x.get("KIND_STKCERT_TP_NM")=="보통주" for x in ib.values())
                records.append({"date":day,"basic":b,"daily":d})
                print("VALIDATED date=%s all=%d commons=%d"%(day,len(ib),commons),flush=True)
            payload={"source":"KRX OPEN API","schema":1,"year":2016,"month":month,"records":records}
            raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            data=gzip.compress(raw,mtime=0)
            digest=hashlib.sha256(data).hexdigest()
            description="Private KRX PIT 2016-%02d; dates=%d; sha256=%s"%(month,len(records),digest)
            media=MediaIoBaseUpload(io.BytesIO(data),mimetype="application/gzip",resumable=True)
            entry=drive.files().create(body={"name":name,"parents":[fid],"description":description},
                      media_body=media,fields="id,name,md5Checksum,size,shared").execute()
            if (entry.get("md5Checksum")!=hashlib.md5(data).hexdigest()
                or str(entry.get("size"))!=str(len(data)) or entry.get("shared") is not False):
                raise RuntimeError("Private Drive upload verification failed")
            print("PRIVATE_ARCHIVE_SAVED month=%02d days=%d sha256=%s"%(month,len(records),digest),flush=True)

if __name__=="__main__":
    try:
        ap=argparse.ArgumentParser()
        ap.add_argument("--months",nargs="+",type=int,required=True)
        args=ap.parse_args()
        run(args.months)
    except Exception as e:
        # Do not log provider responses, auth errors, private rows, or credentials.
        print("PRIVATE_KRX_COLLECTION_FAILED: "+type(e).__name__,flush=True)
        sys.exit(2)
