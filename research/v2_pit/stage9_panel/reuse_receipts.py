"""Populate the raw filing store from earlier independently hashed audit receipts."""
import argparse
import gzip
import json
import re
import zlib
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from stage9_panel.collect_receipts import connect, initialize, read_csv, store, sha
from stage9_panel.fss_section import statement_pointer

def run(path,panel,prior,archives):
    universe={r['historical_isin'] for r in read_csv(panel)}
    codes={r['historical_code'] for r in read_csv(panel)}
    known={r['corp_code']:r for r in read_csv(prior/'census_rows.csv') if r['isin'] in universe and r['corp_code']}
    initialize(path)
    with connect(path) as out:
        for name in ('portal','amendments'):
            f=archives/'stage82b-frozen'/(name+'.sqlite')
            if not f.exists():continue
            with connect(f) as source:
                for receipt,doc,corp,digest,ev,body in source.execute('SELECT * FROM originals'):
                    if corp in known:
                        store(out,receipt,doc,corp,'xbrl',json.loads(ev)['source_url'],body,digest)
        directory=archives/'mr-hist-preflight'
        for f in sorted(directory.glob('*-??????.json')):
            r=json.loads(f.read_text())
            if r['isin'] in universe:
                store(out,r['receipt'],r['document'],r['corp_code'],'xbrl',r['source'],f.with_suffix('.zip').read_bytes(),r['sha256'])
        directory=archives/'mr82-periods'
        for r in json.loads((directory/'package_manifest.json').read_text()):
            if r['corp'] not in known or r['receipt'][:8]>'20211201':continue
            f=directory/(r['kind']+'.zip')
            if f.exists():
                store(out,r['receipt'],r['document'],r['corp'],'xbrl',r['source_url'],f.read_bytes(),r['archive_sha256'])
        for r in json.loads((directory/'crosslinks.json').read_text()):
            f=directory/(r['kind']+'-src.json')
            if not f.exists():continue
            v=json.loads(f.read_text())
            if v['code'] not in codes or r['dart_receipt'][:8]>'20211201':continue
            store(out,r['dart_receipt'],v['kind_docno'],r['corp_code'],'kind_html',v['url'],
                  (directory/(r['kind']+'.htm')).read_bytes(),v['sha256'])
        for r in json.loads((archives/'mr-delisted'/'field_receipt_validation.json').read_text())['facts']:
            if r['isin'] in universe:known.setdefault(r['corp_code'],r)
        directory=archives/'mr-delisted'
        for r in json.loads((directory/'packages.json').read_text()):
            f=directory/r['filename']
            if f.suffix!='.zip':continue
            corp=next((re.match(r'(\d{8})_',n)[1] for n in r['members'] if re.match(r'\d{8}_',n)),None)
            if corp not in known:continue
            doc=re.search(r'dcm_no=(\d+)',r['url'])[1]
            store(out,f.stem,doc,corp,'xbrl',r['url'],f.read_bytes(),r['sha256'])
        directory=archives/'mr-qc-xbrl'
        for r in json.loads((directory/'checked_versions.json').read_text()):
            f=directory/(r['receipt']+'.zip')
            if r['corp'] in known and f.exists():
                store(out,r['receipt'],r['document'],r['corp'],'xbrl',r['source_url'],f.read_bytes(),r['archive_sha256'])
        evi=json.load(gzip.open(prior/'census_xbrl_evidence.json.gz','rt'))
        for r in evi:
            if r['corp'] not in known:continue
            files=[archives/'mr-lgsk'/(r['receipt']+'.zip')]
            if r['receipt']=='20210517001185':files.append(archives/'mr-samsung'/'2021-xbrl.zip')
            for f in files:
                if f.is_file():store(out,r['receipt'],r['document'],r['corp'],'xbrl',r['source_url'],f.read_bytes(),r['archive_sha256'])
        ev=json.load(gzip.open(prior/'census_display_evidence.json.gz','rt'))
        with connect(archives/'stage82b-frozen'/'filings.sqlite') as old:
            for r in ev:
                if r.get('isin') not in universe:continue
                url=r['source_url']
                row=old.execute('SELECT hash,raw FROM page WHERE url=?',(url,)).fetchone()
                if row:
                    store(out,r['receipt'],r['document'],r['corp_code'],'kind_html',url,zlib.decompress(row[1]),r['source_sha256'])
        directory=archives/'mr82hold'
        for f in sorted(directory.glob('??????-source.json')):
            r=json.loads(f.read_text())
            if r['isin'] in universe:
                store(out,r['dart_receipt_candidate'],r['doc_no'],r['corp_code'],'kind_html',r['url'],
                      (directory/(r['kind_receipt']+'.htm')).read_bytes(),r['sha256'])
        dc=json.loads((directory/'dasco_correction.json').read_text())
        if dc['stock_code'] in codes:
            issuer=json.loads((directory/(dc['stock_code']+'-source.json')).read_text())
            store(out,dc['amendment_DART_receipt'],dc['url'].split('/')[-2],issuer['corp_code'],'kind_html',dc['url'],
                  (directory/(dc['amendment_KIND_receipt']+'.htm')).read_bytes(),dc['full_amendment_html_sha256'])
        for f in (archives/'mr82-kind').glob('special_*.json'):
            r=json.loads(f.read_text())
            if r['isin'] in universe:
                body=archives/'mr-identity'/'nondec'/(r['kind_receipt']+'.htm')
                store(out,r['receipt'],r['source_url'].split('/')[-2],r['corp_code'],'kind_html',
                      r['source_url'],body.read_bytes(),r['source_sha256'])
        # A pre-listing filing may have an FSS viewer but no KRX report body yet.
        # Respect the exact historic main-to-CFS section link supplied by identity review.
        identity=panel.parent/'identity'
        for f in identity.glob('prelisting-*-source.json'):
            r=json.loads(f.read_text())
            u=urlsplit(r['url']);params=parse_qs(u.query)
            if (r['stock_code'] not in codes or u.scheme!='https' or u.netloc!='dart.fss.or.kr'
                    or u.path!='/report/viewer.do' or params.get('rcpNo')!=[r['receipt']]
                    or params.get('dcmNo')!=[r['document']] or r['section']!='2. 연결재무제표'):
                raise ValueError('prelisting receipt/section identity mismatch')
            body=identity/'raw'/('ipo-'+r['receipt']+'-cfs.htm')
            store(out,r['receipt'],r['document'],r['corp_code'],'dart_html',r['url'],body.read_bytes(),r['sha256'])
            with out:
                out.execute('INSERT OR IGNORE INTO reservations VALUES(?,?,?)',(r['receipt'],'dart_html','identity_source_handoff'))
        # Reuse earlier original main menus when an alternate original DART
        # statement view is called for; their selected receipt must match.
        candidates=list((identity/'raw').glob('fss-*-*-*.html'))+list((identity/'raw').glob('ipo-*-original.html'))
        for directory in [archives/'mr-lgsk',archives/'mr-delisted']:
            candidates.extend(directory.glob('*.html'))
        for f in candidates:
            ids=re.findall(r'(?<!\d)\d{14}(?!\d)',f.name)
            if len(ids)!=1:continue
            try:body=f.read_bytes();statement_pointer(body,ids[0])
            except (UnicodeError,ValueError):continue
            url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+ids[0]
            with out:out.execute('INSERT OR IGNORE INTO pointers VALUES(?,?,?)',(url,sha(body),body))
        print(out.execute('SELECT kind,count(*),sum(length(body)) FROM packages GROUP BY kind').fetchall())

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for name in ('path','panel','prior','archives'):a.add_argument(name,type=Path)
    run(**vars(a.parse_args()))
