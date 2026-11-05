"""Export only Jan 7 derived membership; leave all KRX raw archives private."""
import gzip,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.compare_signals import MEMBERSHIP_SHA,MEMBERSHIP_NAME
from validation.trend_audit.krx_pit_private.drive_collect import existing,folder,validate
from validation.trend_audit.krx_pit_private.drive_retry import read_retry,upload_archive
from validation.trend_audit.krx_pit_private.compare_universe import classification

def main():
 s=_build_service(*(os.environ[k] for k in ['GDRIVE_OAUTH_CLIENT_ID','GDRIVE_OAUTH_CLIENT_SECRET','GDRIVE_OAUTH_REFRESH_TOKEN']))
 fid=read_retry(lambda:folder(s))
 if fid!='1f_FAl_IL31nhw69gSgU5UCfW8P9LBbKY':raise ValueError('PRIVATE_FOLDER')
 def load(name,expected):
  o=read_retry(lambda:existing(s,fid,name));raw=read_retry(lambda:s.files().get_media(fileId=o['id']).execute())
  if o.get('shared') is not False or hashlib.sha256(raw).hexdigest()!=expected or hashlib.md5(raw).hexdigest()!=o['md5Checksum']:raise ValueError('INPUT_HASH')
  return raw
 m=json.loads(gzip.decompress(load(MEMBERSHIP_NAME,MEMBERSHIP_SHA)))
 h=m['archives_sha256']['KRX_PIT_2016_01_v1.json.gz'];jan=json.loads(gzip.decompress(load('KRX_PIT_2016_01_v1.json.gz',h)))
 rec=next(x for x in jan['records'] if x['date']=='20160107');b=validate('basic','20160107',rec['basic']);d=validate('daily','20160107',rec['daily'])
 if b.keys()!=d.keys():raise ValueError('BASIC_DAILY')
 data=dict(source_archive_sha256=h,membership={'20160107':[dict(code=c,isin=r['ISU_CD'],listing_date=r['LIST_DD']) for c,r in b.items() if classification(r)=='common']})
 raw=gzip.compress(json.dumps(data,ensure_ascii=False,sort_keys=True).encode(),mtime=0);sha=hashlib.sha256(raw).hexdigest();name='KRX_PIT_SIGNAL_PRIOR_'+sha[:16]+'.json.gz'
 def verify(o):
  a=read_retry(lambda:s.files().get_media(fileId=o['id']).execute())
  if o.get('shared') is not False or hashlib.sha256(a).hexdigest()!=sha:raise ValueError('OUTPUT_HASH')
 upload_archive(s,fid,name,'Private derived prior membership sha256='+sha,raw,existing,verify)
 obj=read_retry(lambda:existing(s,fid,name));verify(obj)
 print('PRIOR_MEMBERSHIP_PASS date=20160107 count='+str(len(data['membership']['20160107']))+' sha256='+sha+' file_id='+obj['id'])
if __name__=='__main__':
 try:main()
 except Exception as e:
  print('PRIOR_MEMBERSHIP_FAILED type='+type(e).__name__);raise SystemExit(2)
