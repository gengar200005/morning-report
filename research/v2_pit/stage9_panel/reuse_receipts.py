"""Populate the raw filing store from earlier independently hashed audit receipts."""
import argparse
import gzip
import json
import re
import zlib
from pathlib import Path
from stage9_panel.collect_receipts import connect, initialize, read_csv, store

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
        print(out.execute('SELECT kind,count(*),sum(length(body)) FROM packages GROUP BY kind').fetchall())

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for name in ('path','panel','prior','archives'):a.add_argument(name,type=Path)
    run(**vars(a.parse_args()))
