"""Describe the frozen panel and missingness, without consulting prospective returns."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def run(context, delist, terminal, dest, ledger=None):
    context_rows=read_csv(context)
    panel=[r for r in context_rows if r['sampled']=='1']
    with gzip.open(terminal,'rt') as source:
        ending=json.load(source)
    end_rec,=[rec for rec in ending['records'] if rec['date']=='20261030']
    listed={r['ISU_CD'] for r in end_rec['basic']}
    exits=defaultdict(set)
    for r in read_csv(delist):
        if (r['Market'],r['SecuGroup'],r['Kind'])==('KOSPI','주권','보통주'):
            key=(r['Symbol'],r['ListingDate'][:10].replace('-',''))
            exits[key].add(r['DelistingDate'][:10].replace('-',''))
    for r in context_rows:
        dates={d for d in exits[r['code'],r['listing_date']] if r['formation']<d<='20261030'}
        if len(dates)==1 and r['isin'] not in listed:
            r['later_status']='confirmed_delisted'
        elif not dates and r['isin'] in listed:
            r['later_status']='present_20261030'
        else:
            r['later_status']='unresolved'
        r['year']=r['formation'][:4]
        r['cap_quartile']=str(r['cap_quartile'])
    def summarize(rows):
        return {field:dict(sorted(Counter(x[field] or 'unknown' for x in rows).items()))
                for field in ('year','industry_group','sector_name','cap_quartile','later_status')}
    dates=sorted({r['formation'] for r in panel})
    result={'all':summarize(context_rows),'sample':summarize(panel),
            'n_all':len(context_rows),'n_panel':len(panel),'dates':len(dates),
            'unique_all':len({r['isin'] for r in context_rows}),'unique_panel':len({r['isin'] for r in panel}),
            'formation_counts':{},'monthly_max_percentage_point_difference':{},
            'diagnostic_exit_references':{p.name:sha256(p.read_bytes()).hexdigest() for p in (delist,terminal)}}
    monthly_diff=defaultdict(list)
    for day in dates:
        a=[r for r in context_rows if r['formation']==day]
        b=[r for r in panel if r['formation']==day]
        result['formation_counts'][day]={'all':len(a),'selected':len(b)}
        for field in ('cap_quartile','industry_group','sector_name','later_status'):
            ac,bc=Counter(r[field] for r in a),Counter(r[field] for r in b)
            monthly_diff[field].extend((abs(100*(bc[k]/len(b)-ac[k]/len(a))),day,k) for k in set(ac)|set(bc))
    result['monthly_max_percentage_point_difference']={k:max(x) for k,x in monthly_diff.items()}
    if ledger:
        recs=read_csv(ledger)
        entries={(r['formation'],r['isin']):r for r in recs}
        if len(entries)!=14400 or len(recs)!=len(entries):
            raise ValueError('Wrong ledger keys')
        by_group=defaultdict(lambda:Counter())
        for r in panel:
            original=entries[r['formation'],r['isin']]
            for field in ('year','sector_name','cap_quartile','later_status'):
                key=field+'|'+(r[field] or 'unknown')
                if r['industry_group']=='nonfinancial':
                    by_group[key]['n']+=1
                    for signal in ('F2','F3'):by_group[key][signal]+=int(bool(original.get(signal,'')))
        result['eligible_nonfinancial_coverage']=dict(sorted(by_group.items()))
    dest.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('context','delist','terminal','dest'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--ledger',type=Path)
    run(**vars(parser.parse_args()))
