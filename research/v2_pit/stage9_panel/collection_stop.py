"""Freeze new acquisition after hard upper bounds for both inputs fail in one year."""
import argparse
import hashlib
import json
from pathlib import Path
import time

def check(directory):
    f=directory/'ledger'/'coverage_limits.json'
    if not f.is_file():return None
    raw=f.read_bytes()
    data=json.loads(raw)
    if data['metadata_sha256']!=hashlib.sha256((directory/'identity'/'receipts.csv').read_bytes()).hexdigest():
        return None
    reasons={}
    for year,info in data['by_year'].items():
        if info['sample']!=2880:continue
        hard={field:info['fields'][field]['structural_and_confirmed_rules'] for field in ('F2','F3')}
        if all(v['impossible_at_80pct'] and v['maximum_observations']*5<v['denominator']*4 for v in hard.values()):
            reasons[year]=hard
    if not reasons:return None
    return dict(reason='both_annual_hard_upper_bounds_below_80pct',source=f.name,
                quality_save_sha256=hashlib.sha256(raw).hexdigest(),years=reasons)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);args=p.parse_args()
    stop=args.directory/'raw'/'final.stop'
    while not stop.exists():
        out=check(args.directory)
        if out:
            stop.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
            print(out);break
        time.sleep(15)
