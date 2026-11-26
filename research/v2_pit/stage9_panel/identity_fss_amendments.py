"""Verify FSS-only amendment metadata and emit receipt-bound CFS display coordinates for the shared collector."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from lxml import html

from identity_collect import save
from identity_ledger import read,save as write_csv

PARAMS=('rcpNo','dcmNo','eleId','offset','length','dtd')
def run(w,database):
    records=read(w/'receipts.csv')
    db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    eligible=[]
    for r in records:
        if r['receipt']=='20170814001250' and r['stock_code']=='002550':
            eligible.append(r)
            continue
        if r['kind_receipt'] or r['version']!='amendment' or not r['receipt'] or r['filing_date']<'20160104':continue
        if not r['original_receipt'] or not db.execute('select 1 from membership where isin=? and day=? and common=1',(r['isin'],r['filing_date'])).fetchone():continue
        eligible.append(r)
    db.close()
    def fetch(event):
        rid=event['receipt'];dst=w/'raw'/('fss-amendment-'+rid+'-viewer.html')
        output=w/'parsed'/('fss-amendment-'+rid+'.json')
        if output.is_file():return
        url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+rid
        if not dst.exists():
            try:
                with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://dart.fss.or.kr/dsab007/main.do'}),timeout=20) as resp:raw=resp.read()
                if len(raw)>600:dst.write_bytes(raw)
            except OSError as ex:print(rid,str(ex)[:90]);return
        if not dst.is_file():return
        raw=dst.read_bytes();src=raw.decode();doc=html.fromstring(src)
        selected=[a for a in doc.xpath('//option[@selected]') if re.fullmatch('rcpNo='+rid+r'(&dcmNo=\d+)?',a.get('value',''))]
        ids={m[1] for h in doc.xpath('//span[contains(@onclick,"openCorpInfoNew")]/@onclick') if (m:=re.search(r"openCorpInfoNew\('(\d{8})'",h))}
        if len(selected)!=1 or ids!={event['corp_code']}:return
        choices=[]
        for block in re.split(r'var node\d+\s*=\s*\{\s*\}\s*;',src)[1:]:
            n=dict(re.findall(r'''node\d+\['(\w+)'\]\s*=\s*"([^"]*)"\s*;''',block));label=n.get('text','')
            if re.fullmatch(r'\d+\.\s*연결\s*재무제표',label):
                try:q={k:n[k] for k in PARAMS}
                except KeyError:continue
                if all(re.fullmatch(r'\d+',q[k]) for k in PARAMS[:-1]) and re.fullmatch(r'dart\d*\.xsd',q['dtd']):choices.append((label,q))
        sel=' '.join(selected[0].text_content().split())
        attach=selected[0].getparent().get('id')=='att'
        family=[{'receipt':m[1],'label':' '.join(o.text_content().split())} for o in doc.xpath('//select[@id="family"]/option')
                if (m:=re.fullmatch(r'rcpNo=(\d{14})',o.get('value','')))]
        if attach and event['original_receipt'] not in {v['receipt'] for v in family}:return
        attachment_name=re.sub(r'^\d{4}[.]\d{2}[.]\d{2}\s*(?:\[정정\]\s*)?', '',sel) if attach else ''

        # Attachments may select the parent main receipt. Only the authority's own coordinates for this
        # exact requested receipt are sent for numeric extraction.
        meta=dict(receipt=rid,corp_code=event['corp_code'],stock_code=event['stock_code'],selected=sel,original_receipt=event['original_receipt'],
                  main_url=url,source_main_sha256=sha256(raw).hexdigest(),title=doc.xpath('string(//title)').strip(),document='',section='',url='',
                  attachment_name=attachment_name,family=family,
                  event_scope=('nonfinancial_attachment_only' if attachment_name in ('정관','내부회계관리제도운영보고서') else 'financial_attachment_only' if attach else 'periodic_main_body'))
        if len(choices)==1 and choices[0][1]['rcpNo']==rid:
            label,q=choices[0];meta.update(document=q['dcmNo'],section=label,url='https://dart.fss.or.kr/report/viewer.do?'+urlencode(q))
        if len(choices)==1:meta['authority_main_body_rcp']=choices[0][1]['rcpNo']
        save(output,meta)
    with ThreadPoolExecutor(2) as pool:list(pool.map(fetch,eligible))
    import json
    files=[json.loads(p.read_text()) for p in sorted((w/'parsed').glob('fss-amendment-*.json'))]
    req=[x for x in files if x['url']]
    write_csv(w/'dart_display_requests.csv',req,['receipt','document','corp_code','stock_code','url','section','source_main_sha256'])
    print(len(eligible),len(files),len(req))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('work',type=Path);p.add_argument('database',type=Path)
    a=p.parse_args();run(a.work,a.database)
