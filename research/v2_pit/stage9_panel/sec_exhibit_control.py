"""One bounded official SEC exhibit check for the preselected POSCO annual comparison."""
import argparse
from datetime import datetime,timezone
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,build_opener
from lxml import html
from dart_receipts import NoRedirect

ROOT='https://www.sec.gov/Archives/edgar/data/889132/000119312517017283/'
INDEX=ROOT+'0001193125-17-017283-index.htm'

def fetch(url,folder,name,audit):
    if not url.startswith(ROOT):raise ValueError('outside submitted SEC accession')
    audit['requests'].append({'url':url,'started_utc':datetime.now(timezone.utc).isoformat()})
    req=Request(url,headers={'User-Agent':'Historical market research, receipt-bound public filing review'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=20) as res:
            body=res.read(20*1024*1024+1)
            audit['requests'][-1].update(http=res.status,bytes=len(body))
    except HTTPError as e:
        audit['requests'][-1].update(http=e.code)
        raise
    if not body or len(body)>20*1024*1024:raise ValueError('size outside bound')
    (folder/name).write_bytes(body)
    audit['requests'][-1]['sha256']=sha256(body).hexdigest()
    return body

def run(folder,raw_store):
    folder.mkdir(parents=True,exist_ok=True)
    result=folder/'sec_control.json'
    if result.exists():return
    out=dict(accession='0001193125-17-017283',cik='889132',reporter='POSCO',expected_filing='2017-01-25',expected_form='6-K',requests=[])
    with raw_store.with_suffix('.collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            archive=fetch(INDEX,folder,'index.htm',out)
            tree=html.fromstring(archive)
            text=' '.join(tree.text_content().split())
            if '2017-01-25' not in text or '6-K' not in text or 'POSCO' not in text.upper():
                raise ValueError('unexpected SEC index issuer/form/date')
            candidates=[]
            for row in tree.xpath('//tr'):
                cells=row.xpath('./td')
                if len(cells)<4 or ''.join(cells[3].text_content().split()).upper()!='EX-99.1':continue
                for ref in cells[2].xpath('.//a/@href'):
                    link=urljoin(INDEX,ref)
                    if link.startswith(ROOT) and re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:htm|html|pdf)',link[len(ROOT):]):candidates.append(link)
            if len(candidates)!=1:raise ValueError('no unique SEC accession exhibit 99.1')
            url=candidates[0];ext=Path(urlsplit(url).path).suffix
            b=fetch(url,folder,'exhibit99.1'+ext,out)
            out.update(status='body_received_content_review_pending',source_url=url,source_sha256=sha256(b).hexdigest())
        except (OSError,ValueError) as e:out.update(status='BLOCKED',reason=str(e)[:330])
        finally:result.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('folder',type=Path);p.add_argument('raw_store',type=Path)
    run(**vars(p.parse_args()))
