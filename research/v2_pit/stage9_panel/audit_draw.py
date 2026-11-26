"""Freeze issuer-disjoint document checks using only membership, size and audit-only exit labels."""
import argparse
import csv
import gzip
import hashlib
import sqlite3
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

BASE = Path(__file__).resolve().parent
SALT = 'mr-v2-stage9-independent-20261126-v1'
# Two reports per study year, preserving all four calendar quarter ends in this small subset.
TECH_CELLS = [('2017-03-31','small'),('2017-12-31','later_delist'),
              ('2018-06-30','middle'),('2018-09-30','large'),
              ('2019-03-31','later_delist'),('2019-12-31','small'),
              ('2020-06-30','large'),('2020-09-30','middle'),
              ('2021-03-31','small'),('2021-09-30','later_delist')]
STRATA = ['small','middle','large','later_delist']


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def digest(*parts):
    return hashlib.sha256('|'.join((SALT,*parts)).encode()).hexdigest()


def store(path, data):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=data[0])
        w.writeheader()
        w.writerows(data)
    print(path.name, len(data), hashlib.sha256(path.read_bytes()).hexdigest())


def run(panel, formations, economic, out):
    legacy={'005930','066570','000660','117930','002000','003560','033270','005030','014820'}
    for file in ('evidence_20261126/qc_receipts.csv','stage82b/holdout_frozen.csv','stage82b/quarter_holdout_frozen.csv'):
        legacy.update(r['stock_code'] for r in rows(BASE.parent/file))
    tech=rows(BASE/'technical_draw.csv')
    database=sqlite3.connect(f'file:{economic.resolve()}?mode=ro',uri=True)
    # No price, signal, profitability or return tables are read.
    exits={r[0] for r in database.execute("SELECT isin FROM exit_audit WHERE status='MATCH' AND isin IS NOT NULL")}
    seen=set(legacy)
    selected=[]
    for end,desired in TECH_CELLS:
        pool=[r for r in tech if r['period_end']==end and r['stock_code'] not in seen]
        if not pool:
            raise ValueError(f'Empty preflight cell at {end}')
        r=min(pool,key=lambda r:(r['stratum']!=desired, digest('technical',end,r['isin'])))
        seen.add(r['stock_code'])
        selected.append((end,r['cap_formation'],desired,r['stratum'],r['cap_cell'],r['isin'],r['stock_code']))
    main=[]
    members=defaultdict(dict)
    for r in rows(panel):
        members[r['formation']][r['historical_isin']]=r['historical_code']
    dates={r['period_end']:r['cap_formation'] for r in tech}
    needed=set(dates.values())
    caps={}
    with ZipFile(formations) as z, z.open('formations.csv.gz') as raw, gzip.open(raw,'rt') as f:
        for r in csv.DictReader(f):
            if r['day'] in needed and r['isin'] in members[r['day']] and r['cap_cell'] in ('0.0','1.0','2.0'):
                caps[r['day'],r['isin']]=int(float(r['cap_cell']))
    seen.update(r['stock_code'] for r in tech)
    for i,(end,d) in enumerate(sorted(dates.items())):
        # The rotation shifts every year so Q4 is not systematically a size/exit stratum.
        stratum=STRATA[(i+i//4)%4]
        candidates=[isin for isin,code in members[d].items() if code not in seen and
                    (isin in exits if stratum=='later_delist' else caps.get((d,isin))==STRATA.index(stratum))]
        if not candidates:
            raise ValueError(f'Empty main cell at {end}, {stratum}')
        isin=min(candidates,key=lambda isin:(digest('main',end,isin),isin))
        code=members[d][isin]
        seen.add(code)
        main.append((end,d,stratum,stratum,caps.get((d,isin),''),isin,code))
    for phase,draw in [('technical',selected),('main',main)]:
        result=[]
        for end,d,desired,actual,cap,isin,code in draw:
            name=database.execute('SELECT name FROM membership WHERE day=? AND isin=? AND code=? AND common=1',(d,isin,code)).fetchone()
            if not name:
                raise ValueError(f'No historical identity for {d} {isin}')
            result.append(dict(period_end=end,formation_for_size=d,desired_stratum=desired,selected_stratum=actual,
                               size_tercile_zero_based=cap,later_exit_for_audit=isin in exits,isin=isin,stock_code=code,
                               issuer_on_formation=name[0],rank_sha256=digest(phase,end,isin)))
        store(out/f'audit_{phase}_frozen.csv', result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('panel','formations','economic','out'):
        p.add_argument('--'+arg,required=True,type=Path)
    run(**vars(p.parse_args()))
