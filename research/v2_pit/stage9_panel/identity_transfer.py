"""Pair official KOSDAQ exit and KOSPI admission notices for uninterrupted transfers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request,urlopen

from lxml import html

BASE='https://kind.krx.co.kr/common/disclsviewer.do?'
def page(path,url):
    if not path.exists():
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:body=response.read()
        if len(body)<250:raise ValueError('Incomplete KIND response')
        path.write_bytes(body)
    return path.read_bytes()
def capture(work,r):
    rid=r['kind'];raw=work/'raw';vurl=BASE+urlencode({'method':'search','acptno':rid})
    v=page(raw/f'transfer-{rid}-view.html',vurl);tree=html.fromstring(v.decode())
    if '('+r['code']+')' not in tree.xpath('string(//header//h1)'):raise ValueError('KIND viewer security differs')
    available=[o for o in tree.xpath('//select[@id="mainDoc"]/option[@value!=""]') if o.text_content().strip().endswith('('+r['date'][:10].replace('-','.')+')')]
    if len(available)!=1:raise ValueError('Original not unique')
    document=available[0].get('value').split('|')[0];purl=BASE+urlencode({'method':'searchContents','docNo':document})
    pointer=page(raw/f'transfer-{rid}-pointer.html',purl)
    match=re.search(r"parent\.setPath\('[^']*','([^']*)'",pointer.decode());url=match[1]
    if not url.startswith('https://kind.krx.co.kr/external/') or rid[-6:] not in url or document not in url:
        raise ValueError('Unexpected external document identity')
    body=page(raw/f'transfer-{rid}.htm',url);doc=html.fromstring(body.decode())
    for elem in doc.xpath('//style|//script'):elem.drop_tree()
    text=' '.join(doc.text_content().split())
    prior=re.search(r'보통주\s+A'+r['code']+r'\s+[\d,]+\s+(\d{4}-\d{2}-\d{2})',text)
    leave=re.search(r'상장폐지일\s+(\d{4}-\d{2}-\d{2})',text)
    return {**r,'document':document,'url':url,'body_sha256':sha256(body).hexdigest(),'index_sha256':sha256(v).hexdigest(),
            'pointer_sha256':sha256(pointer).hexdigest(),'isos_in_notice':sorted(set(re.findall(r'KR7[\dA-Z]{9}',text))),
            'previous_listing_date':prior[1].replace('-','') if prior else None,'transfer_date':leave[1].replace('-','') if leave else None,
            'market_transfer':any(word in text.replace(' ','') for word in ('유가증권시장상장','이전상장','유가증권시장에상장')),'text':text[:380]}
def main(work):
    issuers={r['stock_code']:r for r in csv.DictReader((work/'issuers.csv').open())}
    records=[r for p in sorted(work.glob('transfer-??????.json')) for r in json.loads(p.read_bytes()) if r['title'].startswith(('신규상장(', '상장폐지('))]
    with ThreadPoolExecutor(2) as pool:proof=list(pool.map(lambda r:capture(work,r),records))
    results=[]
    for code in sorted({r['code'] for r in proof}):
        a=[r for r in proof if r['code']==code];isin=issuers[code]['isin']
        enter=[r for r in a if r['title'].startswith('신규상장(') and isin in r['isos_in_notice']]
        leave=[r for r in a if r['title'].startswith('상장폐지(') and r['market_transfer']]
        # A transfer requires the exchange's original KOSDAQ exit notice under the same security
        # and KOSPI listing notice with the actual ISIN that appears in dated KRX membership.
        valid=len(enter)==len(leave)==1 and bool(leave[0]['previous_listing_date'] and leave[0]['transfer_date'])
        results.append({'stock_code':code,'isin':isin,'verified_transfer':valid,'previous_listing_date':leave[0]['previous_listing_date'] if valid else None,
                        'transfer_date':leave[0]['transfer_date'] if valid else None,'filings':a})
    (work/'transfer_proof.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('directory',type=Path);main(a.parse_args().directory)
