"""DART public corporate directory code corroboration. Current directory is not an as-of certification."""
import sys
import time
import re
import csv
import json
import hashlib
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from lxml import html

p=Path(sys.argv[1]); market=sys.argv[2];directory=p/'directory';directory.mkdir(exist_ok=True)
q=dict(currentPage='1',maxResults='100',maxLinks='10',sort='',series='',gubun='',selectKey='',searchIndex='',textCrpCik='',autoSearch='true',businessCode='all',bsnRgsNo='',corpTypeAll='',autoSearchCorp='Y',textCrpNm='',bsnRgsNo_1='',bsnRgsNo_2='',bsnRgsNo_3='',crpRgsNo='',corpType=market,searchType='1')
headers={'User-Agent':'Mozilla/5.0','Referer':'https://dart.fss.or.kr/dsae001/main.do','X-Requested-With':'XMLHttpRequest'}
def get(i):
    path=directory/f'{market}-{i:03d}.html'
    if not path.exists():
        params = urlencode({**q,'currentPage':i})
        for attempt in range(3):
            try:
                url = 'https://dart.fss.or.kr/dsae001/search.ax'
                req = Request(url, data=params.encode(), headers=headers) if attempt == 0 else Request(url+'?'+params, headers=headers)
                with urlopen(req,timeout=20) as r:b=r.read()
                assert b'class="pageInfo"' in b
                path.write_bytes(b);break
            except Exception:
                if attempt==2: raise
                time.sleep(1+attempt)
        time.sleep(0.8)
    body=path.read_bytes()
    tree=html.fromstring(body.decode())
    num,pages,total=map(int,re.fullmatch(r'\[(\d+)/(\d+)\]\s*\[총 ([\d,]+)건\]',tree.xpath('string(//*[@class="pageInfo"])').strip().replace(',','')).groups());assert i==num
    entries=[]
    for row in tree.xpath('//tbody/tr[td]'):
        tds=row.xpath('./td');a,=tds[0].xpath('.//a');entries.append(dict(corp_code=re.fullmatch(r"javascript:select\('(\d{8})'\);",a.get('href','')).group(1),display_name=a.text_content().strip(),stock_code=tds[1].text_content().strip()))
    return entries,pages,total,hashlib.sha256(body).hexdigest()
entries,pages,total,h=get(1);hashes={1:h}
for i in range(2,pages+1):
    rows,pp,tt,hh=get(i);assert (pp,tt)==(pages,total);entries.extend(rows);hashes[i]=hh
assert len(entries)==total==len({r['corp_code'] for r in entries})
with (p/f'current_directory_{market}.csv').open('w',newline='',encoding='utf8') as out:
    w=csv.DictWriter(out,fieldnames=list(entries[0]));w.writeheader();w.writerows(entries)
(p/f'current_directory_{market}_summary.json').write_text(json.dumps(dict(total=total,pages=pages,hashes=hashes),indent=2))
print(market,total,pages)
