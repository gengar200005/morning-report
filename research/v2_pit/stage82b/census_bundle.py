"""Export checksum-verified receipt-level evidence used by the census; raw archives stay in the cache."""
import argparse
import csv
import gzip
import json
from pathlib import Path

if __package__:
    from .census_ledger import load_sources
else:
    from census_ledger import load_sources


def save(path,records):
    raw=json.dumps(records,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    path.write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))


def run(identity,cache,version_index,display_files,output):
    with identity.open(encoding='utf8') as f:
        candidates={r['corp_code_candidate'] for r in csv.DictReader(f) if r['identity_status']=='PASS'}
    with version_index.open(encoding='utf8') as f:
        versions=[r for r in csv.DictReader(f) if r['corp_code'] in candidates]
    with (output/'census_versions.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=('corp_code','receipt','filed','type','title'),extrasaction='ignore')
        w.writeheader();w.writerows(versions)
    xbrl,display=load_sources(cache,display_files)
    save(output/'census_xbrl_evidence.json.gz',[xbrl[k] for k in sorted(xbrl)])
    save(output/'census_display_evidence.json.gz',[display[k][h] for k in sorted(display) for h in sorted(display[k])])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('identity','cache','version_index','output'):p.add_argument(name,type=Path)
    p.add_argument('--display',nargs='*',type=Path,default=[],dest='display_files')
    run(**vars(p.parse_args()))
