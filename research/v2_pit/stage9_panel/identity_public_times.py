"""Fetch official FSS publication minutes only for issuer-days with competing or unattached revisions."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
from lxml import html
from identity_collect import fetch,rows,save
from identity_ledger import event

ENDPOINT='https://dart.fss.or.kr/dsac001/search.ax'
def audit(w,work):
    co,day,corp=work;key=f'time-{co}-{day}';dest=w/'parsed'/(key+'.json')
    if dest.exists():return
    evidence={};pg=1;count=None
    while True:
        form=dict(currentPage=pg,maxResults=100,maxLinks=10,sort='',series='',pageGrouping='Y',mdayCnt='0',selectDate=day[:4]+'.'+day[4:6]+'.'+day[6:],
                  textCrpCik=corp,selDate='',selDate4=day,corpType='P')
        f=w/'raw'/f'{key}-p{pg}.html';body=fetch(f,ENDPOINT,form,'D')
        root=html.fromstring(body.decode());pagination=root.xpath('string(//*[@class="pageInfo"])').strip().replace(',','')
        m=re.fullmatch(r'\[(\d+)/(\d+)\]\s*\[총 (\d+)건\]',pagination)
        if not m or int(m[1])!=pg or (count is not None and count!=int(m[3])):raise ValueError('Uncertain timestamp index pagination')
        count=int(m[3]);h=hashlib.sha256(body).hexdigest();n=0
        for tr in root.xpath('//tbody/tr[td]'):
            cells=tr.xpath('td')
            if len(cells)<5:continue
            n+=1
            a=cells[2].xpath('.//a[contains(@href,"rcpNo=")]')[0];c=cells[1].xpath('.//a[contains(@href,"openCorpInfoNew")]')[0]
            rid=re.search(r'rcpNo=(\d{14})',a.get('href'))[1];cik=re.search(r"'(\d{8})'",c.get('href'))[1]
            stamp=cells[0].text_content().strip();published=cells[4].text_content().strip().replace('.','')
            if published!=day or not re.fullmatch(r'\d\d:\d\d',stamp):raise ValueError('Uncertain publication date/time')
            if cik==corp:evidence[rid]={'corp_code':corp,'receipt':rid,'date':day,'minute':stamp,'title':' '.join(a.text_content().split()),'source':h}
        if pg>=int(m[2]):break
        pg+=1
    save(dest,{'queried_corp':corp,'queried_date':day,'total':count,'records':list(evidence.values())})
def main(w):
    r=rows(w/'receipts.csv');by=defaultdict(list)
    for x in r:by[(x['stock_code'],x['filing_date'],x['period_end'],x['report_type'])].append(x)
    todo=set()
    for (co,day,_,_),group in by.items():
        kr=[a for a in group if a['kind_receipt']];dr=[a for a in group if a['receipt']]
        if not kr or not dr:continue
        if len(kr)<2 and not any(x['reason']=='ambiguous_same_day_or_issuer' for x in group):continue
        if not any(x['identity_status']=='BLOCKED' for x in group) and len({x['kind_timestamp'] for x in kr})==len(kr):continue
        for c in {x['corp_code'] for x in dr if x['corp_code']}:todo.add((co,day,c))
    def run(item):
        try:audit(w,item)
        except Exception as e:print('time search',item,type(e).__name__,str(e)[:100])
    with ThreadPoolExecutor(2) as pool:list(pool.map(run,sorted(todo)))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('work',type=Path);main(p.parse_args().work)
