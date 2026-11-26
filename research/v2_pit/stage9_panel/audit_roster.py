"""Recreate the sample from historical membership and audit size, turnover, industry and exit composition."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def run(panel,context,db,output):
    with panel.open() as f:
        fixed={(r['formation'],r['historical_isin']):r['historical_code'] for r in csv.DictReader(f)}
    with context.open() as f:
        rows=list(csv.DictReader(f))
    with sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True) as c:
        exits={r[0]:r[1] for r in c.execute("SELECT isin,delisted FROM exit_audit WHERE status='MATCH'")}
        days=sorted({r['formation'] for r in rows})
        bydate=defaultdict(list)
        for r in rows:bydate[r['formation']].append(r)
        data=[]
        for day in days:
            members={r[0]:r[1] for r in c.execute('SELECT isin,code FROM membership WHERE day=? AND common=1',(day,))}
            ranked=sorted(members,key=lambda isin:(sha256(('mr-v2-restricted-2017-21-v1|'+isin).encode()).digest(),isin))
            chosen=set(ranked[:240])
            if {(isin,members[isin]) for isin in chosen}!={(isin,code) for (d,isin),code in fixed.items() if d==day}:
                raise ValueError('sample ranking drift '+day)
            if {(r['isin'],r['code']) for r in bydate[day]}!=set(members.items()):
                raise ValueError('historical universe drift '+day)
            for i,r in enumerate(sorted(bydate[day],key=lambda r:(int(r['turnover_krw']),r['isin']))):
                r['turnover_quartile']=str(1+i*4//len(members))
                r['exit_in_check_register']='matched_later_exit' if exits.get(r['isin'],'')>day else 'other_or_unmatched'
                if (r['sampled']=='1')!=(r['isin'] in chosen):
                    raise ValueError('sampling label drift '+day)
            data.extend(bydate[day])
    counts={}
    for key in ('sector_name','industry_group','cap_quartile','turnover_quartile','exit_in_check_register'):
        full=Counter(r[key] or 'unknown' for r in data)
        sample=Counter(r[key] or 'unknown' for r in data if r['sampled']=='1')
        counts[key]={k:dict(population=full[k],sample=sample[k],percentage_point_difference=round(100*(sample[k]/len(fixed)-full[k]/len(data)),4)) for k in sorted(full)}
    result={'population_issuer_months':len(data),'selected_issuer_months':len(fixed),'formation_dates':len(days),
            'selected_distinct_isins':len({i for _,i in fixed}),'entire_market_distinct_isins':len({r['isin'] for r in data}),
            'historical_membership_and_top_240_roster_match':True,'audited_dimensions':counts,
            'scope':'Monthly stocks counted repeatedly. Confirmed later exits used exclusively for descriptive audit. Unmatched is not confirmed survival.',
            'input_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (panel,context)}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for a in ('panel','context','db','output'):parser.add_argument(a,type=Path)
    run(**vars(parser.parse_args()))
