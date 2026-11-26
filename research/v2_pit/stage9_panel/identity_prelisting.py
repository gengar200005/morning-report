"""Corroborate pre-listing fiscal-period cases with dated IPO notices and the FSS corporate registry."""
import argparse
import csv
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from lxml import html
from identity_collect import KIND,digest,save
from identity_transfer import capture
from identity_ledger import event,read

REGISTRY='https://dart.fss.or.kr/dsae001/selectPopup.ax'
def fetch(path,url,form):
    if not path.exists():
        last=None
        for get in (False,True):
            try:
                data=urlencode(form).encode();req=Request(url+'?'+data.decode() if get else url,data=None if get else data,
                    headers={'User-Agent':'Mozilla/5.0','Referer':('https://dart.fss.or.kr/dsab007/main.do' if url==REGISTRY else KIND+'?method=searchDetailsMain'),'X-Requested-With':'XMLHttpRequest'})
                with urlopen(req,timeout=20) as result:b=result.read()
                if len(b)<300:raise ValueError('empty public page')
                path.write_bytes(b);break
            except Exception as ex:last=ex
        if not path.exists():raise last
    return path.read_bytes()
def issuer(work,record,base):
    code=record['code'];raw=work/'raw';dt=date.fromisoformat(record['listing_date'])
    cf=raw/f'ipo-{code}-corp.html';c=fetch(cf,REGISTRY,{'selectKey':record['corp_code']});tree=html.fromstring(c.decode())
    vals={}
    for tr in tree.xpath('//tr[th and td]'):
        cells=tr.xpath('./th|./td')
        for a,b in zip(cells,cells[1:]):
            if a.tag=='th' and b.tag=='td':vals[''.join(a.text_content().split())]=' '.join(b.text_content().split())
    established=re.sub(r'[^0-9]','',vals.get('설립일',''))
    if len(established)!=8 or vals.get('종목코드','')!=code:raise ValueError('FSS registry code/establishment not identified: '+code)
    f=raw/f'ipo-{code}-offer.html';query={**base,'method':'searchDetailsSub','forward':'details_sub','currentPageSize':100,'pageIndex':1,
        'fromDate':str(dt-timedelta(days=15)),'toDate':str(dt+timedelta(days=1)),'repIsuSrtCd':'A'+code,'marketType':'','searchCorpName':'',
        'searchCodeType':'number','allRepIsuSrtCd':'','orderMode':'','orderStat':''}
    b=fetch(f,KIND,query);t=html.fromstring(b.decode());notices=[]
    for tr in t.xpath('//tbody/tr[td]'):
        cells=tr.xpath('td')
        if len(cells)<5:continue
        a=cells[3].xpath('.//a')[0];title=' '.join(a.text_content().split())
        if not ('상장' in title and ('신규상장(' in title or '재상장(' in title or '분할재상장' in title)):continue
        rid=re.search(r"'(\d{14})'",a.get('onclick'))[1]
        notes=capture(work,{'code':code,'source':digest(b),'kind':rid,'title':title,'date':' '.join(cells[1].text_content().split())})
        if record['isin'] in notes['isos_in_notice']:notices.append(notes)
    if not notices:raise ValueError('no original IPO notice bearing ISIN '+code)
    return dict(stock_code=code,isin=record['isin'],corp_code=record['corp_code'],listed=record['listing_date'],established=established,
                registry_url=REGISTRY,registry_sha256=sha256(c).hexdigest(),official_listing=notices)
def identify(work,roster,foundation):
    members=read(roster)
    supplement=work.parent/'identity_supplement/issuer_resolution.csv'
    anchored={r['stock_code']:r['corp_code'] for r in read(supplement)} if supplement.is_file() else {}
    companies={};cases={}
    with sqlite3.connect(foundation.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        for row in members:
            isin,co,day=row['historical_isin'],row['historical_code'],row['formation']
            if co in ('035720','036420','097520','178920'):continue
            if isin not in companies:
                companies[isin]=db.execute('select name,listing_date from membership where day=? and isin=?',(day,isin)).fetchone()
            name,first=companies[isin]
            if (date.fromisoformat(day)-date.fromisoformat(first)).days>180:continue
            f=work/'parsed'/('D-'+co+'-ALL.json')
            if not f.is_file():continue
            relevant=[]
            for filing in json.loads(f.read_bytes())['records']:
                info=event(filing['title'])
                if not info or info[2]!='original' or filing['filing_date']>=day or info[0]>day:continue
                if (date.fromisoformat(day)-date.fromisoformat(info[0])).days>180:continue
                if co in anchored and filing['corp_code']!=anchored[co]:continue
                relevant.append((info[0],filing))
            if not relevant:continue
            end,filing=max(relevant,key=lambda v:v[0])
            if min(end,filing['filing_date'])>=first:continue
            record=dict(code=co,isin=isin,name=name,listing_date=first,first_sample=day,
                        prior_legal_filing=filing['receipt'],corp_code=filing['corp_code'],title=filing['title'],
                        declared_filed=filing['filing_date'],end=end)
            cases.setdefault((co,filing['receipt']),record)
    save(work/'prelisting_candidates.json',list(cases.values()))
def main(work):
    requested=json.loads((work/'prelisting_candidates.json').read_text())
    unique={r['code']:r for r in requested}
    base=dict(html.fromstring((work/'kind-form.html').read_bytes().decode()).xpath('//form[@id="searchForm"]')[0].form_values())
    def run(r):
        try:return issuer(work,r,base)
        except Exception as e:print(r['code'],type(e).__name__,str(e)[:160],flush=True);return {'stock_code':r['code'],'blocked':str(e)}
    with ThreadPoolExecutor(2) as pool:proof=list(pool.map(run,unique.values()))
    save(work/'prelisting_proof.json',proof)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--roster',type=Path);p.add_argument('--foundation',type=Path)
    args=p.parse_args()
    if args.roster and args.foundation:identify(args.directory,args.roster,args.foundation)
    main(args.directory)
