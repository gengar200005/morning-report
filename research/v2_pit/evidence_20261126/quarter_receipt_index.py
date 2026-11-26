"""Retrieve quarterly report metadata only. Keep originals, amendments and unverified matches separate."""
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from lxml import html

ENDPOINT = 'https://dart.fss.or.kr/dsab007/detailSearch.ax'
BASE = dict(currentPage=1,maxResults=100,maxLinks=10,startDate='20210401',endDate='20210630',publicType='A003',corporationType='P',businessCode='all',option='report',sort='date',series='asc')
HEADER = {'User-Agent':'Mozilla/5.0','Referer':'https://dart.fss.or.kr/dsab007/main.do','X-Requested-With':'XMLHttpRequest'}
def page_data(cache,params):
    page=params['currentPage']; path=cache / f"{params['corporationType']}-{page:03d}.html"
    if not path.exists():
        req=Request(ENDPOINT+'?'+urlencode(params),headers=HEADER)
        for attempt in range(3):
            try:
                with urlopen(req,timeout=25) as response: body=response.read()
                doc=html.fromstring(body.decode('utf-8'))
                if not doc.xpath('//*[@class="pageInfo"]'): raise ValueError('search response without pagination')
                path.write_bytes(body)
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(1+attempt)
        time.sleep(0.15)
    body=path.read_bytes()
    tree=html.fromstring(body.decode('utf-8'))
    info=tree.xpath('string(//*[@class="pageInfo"])').strip()
    n,pages,total=map(int,re.fullmatch(r'\[(\d+)/(\d+)\]\s*\[총 ([\d,]+)건\]',info.replace(',','')).groups())
    if n!=page: raise ValueError('unexpected page number')
    rows=[]
    for row in tree.xpath('//tbody/tr[td]'):
        tds=row.xpath('./td')
        ordinal=int(tds[0].text_content().strip())
        ca,=tds[1].xpath('.//a[contains(@href,"openCorpInfoNew")]')
        ra,=tds[2].xpath('.//a[contains(@href,"rcpNo=")]')
        corp=re.search(r"openCorpInfoNew\('(\d{8})'",ca.get('href')).group(1)
        receipt=re.search(r'rcpNo=(\d{14})$',ra.get('href')).group(1)
        title=' '.join(ra.text_content().split())
        filed=tds[4].text_content().strip().replace('.','')
        if not params['startDate']<=filed<=params['endDate']: raise ValueError(f'out of range {filed}')
        rows.append(dict(ordinal=ordinal,corp_code=corp,dart_display_name=ca.text_content().strip(),receipt=receipt,filed=filed,title=title))
    if [r['ordinal'] for r in rows]!=list(range((page-1)*100+1,min(page*100,total)+1)): raise ValueError('ordinal gap')
    return rows,pages,total,hashlib.sha256(body).hexdigest()

def export(out,rows):
    with out.open('w',encoding='utf-8',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    universe_file,output,market=sys.argv[1:4];p=Path(output);p.mkdir(parents=True,exist_ok=True);cache=p/'pages';cache.mkdir(exist_ok=True)
    params={**BASE,'corporationType':market}
    rows,pages,total,h=page_data(cache,params); hashes={1:h}
    for i in range(2,pages+1):
        new,pp,tt,hh=page_data(cache,{**params,'currentPage':i})
        if (pages,total)!=(pp,tt):raise ValueError('result count changed')
        rows.extend(new);hashes[i]=hh
    if len(rows)!=total or len({r['receipt'] for r in rows})!=total: raise ValueError('missing or repeated receipt')
    all_dates=[r['filed'] for r in rows]
    if sorted(all_dates)!=all_dates: raise ValueError('incorrect filing date sort')
    universe=list(csv.DictReader(Path(universe_file).open(encoding='utf-8')))
    names={}
    for u in universe: names.setdefault(u['issuer_as_of'],[]).append(u)
    filtered=[r for r in rows if re.search(r'분기보고서\s*\(2021\.03\)$',r['title'])]
    for r in filtered:
        r['type']='original' if re.fullmatch(r'분기보고서\s*\(2021\.03\)',r['title']) else 'amendment_or_other'
        candidates=names.get(r['dart_display_name'],[])
        match=candidates[0] if len(candidates)==1 else {}
        r.update(match_method='name_only_provisional' if match else 'unmatched',stock_code_candidate=match.get('stock_code',''),isin_candidate=match.get('isin',''))
    export(p/f'{market}_202103_receipts.csv',filtered)
    summary=dict(query=params,total_all_periods=total,total_pages=pages,page_hashes=hashes,target_title_receipts=len(filtered),unique_corps=len({r['corp_code'] for r in filtered}),types=dict(Counter(r['type'] for r in filtered)),unique_originals=len({r['corp_code'] for r in filtered if r['type']=='original'}),unique_name_candidates=len({r['isin_candidate'] for r in filtered if r['isin_candidate']}))
    (p/f'{market}_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
    print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
