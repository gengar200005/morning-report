"""Freeze a small 2016 warm-up through 2021 instrument check without reading outcomes."""
import argparse
import csv
from collections import defaultdict, Counter
from datetime import date
from hashlib import sha256
import gzip
import json
from pathlib import Path
from zipfile import ZipFile

SALT='mr-v2-stage9-technical-v1|'
def run(panel,formations,evidence,output):
    with panel.open() as f:members=list(csv.DictReader(f))
    dates=sorted({r['formation'] for r in members})
    month={d:set() for d in dates}
    codes={}
    for r in members:
        month[r['formation']].add(r['historical_isin'])
        codes[r['formation'],r['historical_isin']]=r['historical_code']
    caps={}
    with ZipFile(formations) as z, z.open('formations.csv.gz') as a, gzip.open(a,'rt') as f:
        for r in csv.DictReader(f):
            if r['day'] in month and r['isin'] in month[r['day']] and r['cap_cell'] in ('0.0','1.0','2.0'):
                caps[r['day'],r['isin']]=int(float(r['cap_cell']))
    with evidence.open() as f:exits={r['isin'] for r in csv.DictReader(f) if r['exit_status']=='confirmed_delisted'}
    draws=[]
    for y in range(2016,2022):
        for q,(m,de) in enumerate(((3,31),(6,30),(9,30),(12,31)),1):
            end=date(y,m,de)
            eligible=[d for d in dates if 0<=(date.fromisoformat(d)-end).days<=180]
            if not eligible:continue
            # First available formation with a source size split. If January warm-up has none, February is explicit.
            d=next((d for d in eligible if any((d,k) in caps for k in month[d])),None)
            if not d:raise ValueError('No formation with contemporaneous size information')
            used=set()
            order=sorted(month[d],key=lambda s:(sha256(f'{SALT}{end}|{s}'.encode()).digest(),s))
            for stratum in ('later_delist','small','middle','large'):
                cell={'small':0,'middle':1,'large':2}.get(stratum)
                candidates=[s for s in order if s not in used and ((s in exits) if cell is None else (caps.get((d,s))==cell))]
                if not candidates:continue
                isin=candidates[0];used.add(isin)
                draws.append(dict(period_end=end.isoformat(),year=y,quarter=q,isin=isin,stock_code=codes[d,isin],
                                  cap_formation=d,cap_cell=caps.get((d,isin),''),stratum=stratum,
                                  previously_confirmed_exit=isin in exits))
    with output.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(draws[0]));w.writeheader();w.writerows(draws)
    print(len(draws),dict(Counter(r['stratum'] for r in draws)),sha256(output.read_bytes()).hexdigest())
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for k in ('panel','formations','evidence','output'):a.add_argument(k,type=Path)
    run(**vars(a.parse_args()))
