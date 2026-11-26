"""Reconstruct correction effective sessions from two distinct public filing registers."""
import argparse
import csv
import json
import re
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
from pathlib import Path


def run(draw, pages, db, output, packages=None):
    with draw.open() as f:
        cases=list(csv.DictReader(f))
    with sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True) as c:
        sessions=[v[0] for v in c.execute('select day from sessions order by day')]
    kind=defaultdict(dict)
    for p in pages.glob('K*.json'):
        for r in json.loads(p.read_bytes()).get('records',[]):
            title=r['title']
            period=re.search(r'\((\d{4}\.\d\d)\)$',title)
            if period:
                k=(r['stock_code'],period[1],r['kind_timestamp'][:10].replace('-',''),'정정' in title)
                kind[k][r['kind_receipt']]=r
    raw_db=sqlite3.connect('file:'+str(packages.resolve())+'?mode=ro',uri=True) if packages else None
    found=0
    chains=[]
    missing=[]
    for case in cases:
        code,end=case['stock_code'],case['period_end']
        period=end[:7].replace('-','.')
        p=pages/f'D-{code}-ALL.json'
        if not p.is_file():
            missing.append([code,end,'DART issuer index unavailable'])
            continue
        page=json.loads(p.read_bytes())
        regs=[r for r in page['records'] if r['title'].replace(' ','').endswith('('+period+')')]
        orig=[v for v in regs if '정정' not in v['title']]
        if len(orig)!=1:
            missing.append([code,end,'DART unique original count='+str(len(orig))])
            continue
        found+=1
        if len(regs)==1:
            continue
        chain=[]
        for r in regs:
            is_correction='정정' in r['title']
            rows=list(kind[code,period,r['filing_date'],is_correction].values())
            k=rows[0] if len(rows)==1 else {}
            known=max(r['receipt'][:8],r['filing_date'],k.get('kind_timestamp','')[:10].replace('-',''))
            following=sessions[bisect_right(sessions,known)]
            chain.append(dict(receipt=r['receipt'],title=r['title'],dart_filed=r['filing_date'],dart_row_page_sha256=r['source_sha256'],
                              kind_receipt=k.get('kind_receipt'),kind_kst=k.get('kind_timestamp'),kind_page_sha256=k.get('source_kind_sha256'),
                              next_session=following,kind_status='unique' if len(rows)==1 else 'missing_or_multiple'))
        if raw_db:
            for v in chain:
                v['archived_sources']=[dict(source_type=kind,url=url,sha256=h,bytes=len(body)) for kind,url,h,body in raw_db.execute(
                    'SELECT kind,source,sha256,body FROM packages AS p WHERE receipt=? AND NOT EXISTS(SELECT 1 FROM quarantine AS q WHERE (q.receipt,q.kind)=(p.receipt,p.kind)) ORDER BY kind',(v['receipt'],)) if sha256(body).hexdigest()==h]
        same_day=defaultdict(list)
        for v in chain:
            same_day[v['next_session']].append(v)
        for group in same_day.values():
            if len(group)==1:
                group[0]['effective_order']='single_publication'
            elif all(v['kind_kst'] for v in group) and len({v['kind_kst'] for v in group})==len(group):
                for i,v in enumerate(sorted(group,key=lambda v:v['kind_kst']),1):
                    v['effective_order']=f'{i}/{len(group)}'
            else:
                for v in group:v['effective_order']='same_day_unresolved'
        chains.append(dict(stock_code=code,period_end=end,versions=chain))
    out={'draw_sha256':sha256(draw.read_bytes()).hexdigest(),'fixed_rows':len(cases),'uniquely_original_dart':found,
         'with_corrections_in_DART_register':len(chains),'correction_chains':chains,'unresolved_register':missing,
         'scope':'Version index only. No financial values were inferred. A same-day correction does not become eligible on its publication day.'}
    output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('draw','pages','db','output'):p.add_argument(name,type=Path)
    p.add_argument('--packages',type=Path)
    run(**vars(p.parse_args()))
