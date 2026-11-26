"""Download the dated WICS sector indexes and join original KRX formation-day covariates."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from threading import Lock
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'stage82b'))
from census_context import SECTORS, get_sectors, mr_snapshot


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as src:
        return list(csv.DictReader(src))


def fetch(days, cache):
    lock = Lock()
    previous = [0.]
    def acquire(key):
        day, sector = key
        path = cache / day / (sector + '.data')
        path.parent.mkdir(exist_ok=True, parents=True)
        if path.exists():
            return
        request = Request('https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt='+day+'&sec_cd='+sector,
                          headers={'User-Agent':'Mozilla/5.0'})
        for attempt in range(3):
            try:
                with lock:
                    time.sleep(max(0., previous[0]+0.5-time.monotonic()))
                    previous[0] = time.monotonic()
                with urlopen(request, timeout=20) as response:
                    data = response.read()
                parsed = json.loads(data)
                if parsed['info']['CNT'] != len(parsed['list']):
                    raise ValueError('index count mismatch')
                path.write_bytes(data)
                return
            except HTTPError as exc:
                if exc.code in (401,403,429):
                    raise
                if attempt == 2:
                    print(day, sector, type(exc).__name__, flush=True)
                    return
            except (OSError, ValueError, KeyError) as exc:
                if attempt == 2:
                    print(day, sector, type(exc).__name__, flush=True)
                    return
            time.sleep(2**attempt)
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(acquire, [(d, s) for d in days for s in SECTORS]))


def build(panel, database, wics, krx, output):
    selected = {(r['formation'],r['historical_isin']) for r in read_csv(panel)}
    days = sorted({d for d,_ in selected})
    rows, manifest = [], {}
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        for day in days:
            sectors = get_sectors(wics/day,day)
            month = krx / f'KRX_PIT_{day[:4]}_{day[4:6]}_v1.json.gz'
            snapshot = mr_snapshot(month,day)
            if (db.execute('select sha256 from provenance where source=?',(month.name,)).fetchone() or [None])[0] != sha256(month.read_bytes()).hexdigest():
                raise ValueError('KRX archive checksum differs: '+month.name)
            market = {r['ISU_CD']:(int(r['MKTCAP'].replace(',','')),int(r['ACC_TRDVAL'].replace(',',''))) for r in snapshot['daily']}
            membership = db.execute('select isin,code,name,listing_date from membership where common=1 and day=? order by isin',(day,))
            daily = []
            for isin,code,name,listed in membership:
                sector, industry = sectors.get(code,('',''))
                cap, value = market[code]
                daily.append(dict(formation=day,isin=isin,code=code,issuer=name,listing_date=listed,sector_code=sector,sector_name=industry,
                                  industry_group=('financial' if sector=='G40' else 'nonfinancial' if sector else 'unknown'),
                                  sampled=int((day,isin) in selected),cap_krw=cap,turnover_krw=value))
            for i,r in enumerate(sorted(daily,key=lambda z:(z['cap_krw'],z['isin']))):
                r['cap_quartile']=1+4*i//len(daily)
            rows.extend(daily)
            manifest[day]={'wics':{s:sha256((wics/day/(s+'.data')).read_bytes()).hexdigest() for s in SECTORS},
                           'krx':month.name,'sha256':sha256(month.read_bytes()).hexdigest(),'n':len(daily)}
    if len(rows)!=46106 or sum(r['sampled'] for r in rows)!=14400: raise ValueError('Universe changed')
    with output.open('w',newline='',encoding='utf-8') as stream:
        w=csv.DictWriter(stream,list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    (output.parent/'context_sources.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['fetch','build']);p.add_argument('root',type=Path);p.add_argument('database',type=Path)
    a=p.parse_args();path=a.root/'limited_issuer_months.csv'
    if a.mode=='fetch':fetch(sorted({r['formation'] for r in read_csv(path)}),a.root/'wics')
    else:build(path,a.database,a.root/'wics',a.root/'krx',a.root/'context.csv')
