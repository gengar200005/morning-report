"""Bounded OpenDART metadata and receipt-version archives for an approved pilot."""
import argparse
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import ZipFile

ROOT = 'https://opendart.fss.or.kr/api/'
ALLOWED = {'list.json','document.xml','fnlttXbrl.xml','corpCode.xml'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(key, endpoint, **params):
    if endpoint not in ALLOWED:
        raise ValueError('Unsupported OpenDART endpoint')
    url = ROOT+endpoint+'?'+urlencode({'crtfc_key':key,**params})
    try:
        with build_opener(NoRedirect()).open(url, timeout=30) as response:
            content = response.read(32*1024*1024+1)
    except OSError:
        raise RuntimeError(f'OpenDART transport failure at {endpoint}') from None
    if len(content)>32*1024*1024:
        raise ValueError('Pilot response exceeds 32 MiB')
    return content


def listing(key, corp, start, end, category='A'):
    if not re.fullmatch(r'\d{8}',corp) or category not in ('A','I'):
        raise ValueError('Invalid corporation or disclosure category')
    if not all(re.fullmatch(r'\d{8}', value) for value in (start,end)) or not date.fromisoformat(start)<=date.fromisoformat(end)<=date(2023,12,31):
        raise ValueError('Invalid pilot date window')
    pages, total = [],1
    while len(pages)<total:
        payload = fetch(key,'list.json',corp_code=corp,bgn_de=start,end_de=end,
                        pblntf_ty=category,last_reprt_at='N',page_no=len(pages)+1,page_count=100)
        page = json.loads(payload)
        if page['status']=='013' and not pages:
            return [payload]
        if page['status']!='000':
            raise RuntimeError(f'OpenDART list status {page["status"]}')
        if int(page['page_no'])!=len(pages)+1 or pages and total!=int(page['total_page']):
            raise ValueError('Inconsistent pagination')
        total = int(page['total_page'])
        pages.append(payload)
    rows = [r for p in pages for r in json.loads(p)['list']]
    if len(rows)!=int(page['total_count']) or len({r['rcept_no'] for r in rows})!=len(rows):
        raise ValueError('Incomplete or duplicate filing list')
    for r in rows:
        if r['corp_code']!=corp or not start<=r['rcept_dt']<=end or not r['rcept_no'].startswith(r['rcept_dt']):
            raise ValueError('Filing identity or chronology mismatch')
    return pages


def archive(key, endpoint, **params):
    data = fetch(key,endpoint,**params)
    if not data.startswith(b'PK'):
        raise ValueError(f'OpenDART did not return a ZIP at {endpoint}')
    with ZipFile(io.BytesIO(data)) as z:
        if sum(f.file_size for f in z.infolist())>128*1024*1024 or z.testzip():
            raise ValueError('Oversized or corrupted receipt archive')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    mode = p.add_subparsers(dest='mode',required=True)
    lst = mode.add_parser('list')
    for n in ('corporation','start','end'):
        lst.add_argument(n)
    lst.add_argument('--category',choices=('A','I'),default='A')
    doc = mode.add_parser('receipt')
    doc.add_argument('number')
    doc.add_argument('--xbrl',choices=('11011','11012','11013','11014'))
    mode.add_parser('corporations')
    a = p.parse_args()
    key = os.environ.get('OPENDART_API_KEY','')
    if len(key)!=40:
        p.error('Set OPENDART_API_KEY in the local environment')
    if a.mode=='list':
        pages = listing(key,a.corporation,a.start,a.end,a.category)
        entries = {f'{a.corporation}-{a.category}-{a.start}-{a.end}-page{i}.json':body
                   for i,body in enumerate(pages,1)}
    elif a.mode=='receipt':
        if not re.fullmatch(r'\d{14}',a.number) or date.fromisoformat(a.number[:8])>date(2023,12,31):
            p.error('Receipt must be valid and within pilot cutoff')
        if a.xbrl:
            entries = {f'{a.number}-xbrl-{a.xbrl}.zip':archive(key,'fnlttXbrl.xml',rcept_no=a.number,reprt_code=a.xbrl)}
        else:
            entries = {f'{a.number}-document.zip':archive(key,'document.xml',rcept_no=a.number)}
    else:
        entries = {'corpCode.zip':archive(key,'corpCode.xml')}
    a.output.mkdir(mode=0o700,parents=True,exist_ok=True)
    for name,body in entries.items():
        with (a.output/name).open('xb') as stream:
            stream.write(body)
        print(name,hashlib.sha256(body).hexdigest())


if __name__=='__main__':
    main()
