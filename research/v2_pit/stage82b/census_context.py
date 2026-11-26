"""Reproduce sector, size and diagnostic exit strata without reading forward returns."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re

DATE = '20210331'
SECTORS = ('G10','G15','G20','G25','G30','G35','G40','G45','G50','G55')


def mr_snapshot(path, day):
    data = json.loads(gzip.decompress(path.read_bytes()))
    rec, = [r for r in data['records'] if r['date'] == day]
    return rec


def get_sectors(root, day=DATE):
    by_code = {}
    for sector in SECTORS:
        data = json.loads((root / (sector+'.data')).read_bytes())
        stamp = re.fullmatch(r'/Date\((\d+)\)/', data['info']['TRD_DT'])
        seoul = timezone(timedelta(hours=9))
        if not stamp or datetime.fromtimestamp(int(stamp[1])/1000, seoul).strftime('%Y%m%d') != day:
            raise ValueError('WICS trading date mismatch')
        if data['info']['CNT'] != len(data['list']):
            raise ValueError('Truncated sector membership')
        for row in data['list']:
            code = row['CMP_CD']
            if row['IDX_CD'] != sector or row['SEC_CD'] != sector or code in by_code:
                raise ValueError('WICS membership conflict')
            by_code[code] = (sector,row['SEC_NM_KOR'])
    return by_code


def build(march, october, delist, sectors):
    snapshot = mr_snapshot(march, DATE)
    ending = {r['ISU_CD'] for r in mr_snapshot(october,'20261030')['basic']}
    membership = [r for r in snapshot['basic'] if (r['MKT_TP_NM'],r['SECUGRP_NM'],r['KIND_STKCERT_TP_NM']) == ('KOSPI','주권','보통주')]
    cap = {r['ISU_CD']:int(r['MKTCAP'].replace(',','')) for r in snapshot['daily']}
    by_issue = defaultdict(list)
    with delist.open(encoding='utf-8-sig',newline='') as fp:
        for r in csv.DictReader(fp):
            end = r['DelistingDate'][:10].replace('-','')
            if DATE < end <= '20261030' and (r['Market'],r['SecuGroup'],r['Kind']) == ('KOSPI','주권','보통주'):
                by_issue[(r['Symbol'],r['ListingDate'][:10].replace('-',''))].append(end)
    if len({r['ISU_CD'] for r in membership}) != 782:
        raise ValueError('Historical universe differs')
    result = []
    for i,row in enumerate(sorted(membership,key=lambda r:(cap[r['ISU_SRT_CD']], r['ISU_CD']))):
        code,isin = row['ISU_SRT_CD'],row['ISU_CD']
        sec,name = sectors.get(code,('',''))
        dates = by_issue.get((code,row['LIST_DD']),[])
        if len(dates)==1 and isin not in ending:
            exit_status='confirmed_delisted'
        elif not dates and isin in ending:
            exit_status='present_20261030'
        else:
            exit_status='unresolved'
        result.append(dict(stock_code=code,isin=isin,sector_code=sec,sector_name=name,
                           financial=str(sec=='G40').lower() if sec else '',cap_quartile=1+4*i//len(membership),
                           exit_status=exit_status,exit_date=dates[0] if exit_status=='confirmed_delisted' else ''))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('march','october','delisting','sector_dir','output'):
        p.add_argument(key,type=Path)
    a=p.parse_args()
    rows=build(a.march,a.october,a.delisting,get_sectors(a.sector_dir))
    with a.output.open('w',newline='',encoding='utf-8') as fp:
        w=csv.DictWriter(fp,fieldnames=list(rows[0]),lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    paths=[a.march,a.october,a.delisting]+[a.sector_dir/(s+'.data') for s in SECTORS]
    result=dict(asof=DATE,universe=len(rows),sector=Counter(r['sector_name'] or 'unknown' for r in rows),
                exits=Counter(r['exit_status'] for r in rows),context_sha256=sha256(a.output.read_bytes()).hexdigest(),
                source_sha256={p.name:sha256(p.read_bytes()).hexdigest() for p in paths},
                sector_source='https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt=20210331&sec_cd={sector}',
                delisting_source='https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/delisting/2026-10-30.csv',
                diagnostics_only='Future delisting and end-of-window ISIN presence never form portfolio inputs.')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
