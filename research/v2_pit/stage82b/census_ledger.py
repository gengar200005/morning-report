"""Join receipt-checked XBRL and KIND/DART displays without dropping unavailable securities."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

if __package__:
    from .census_collect import prior_facts
else:
    from census_collect import prior_facts

FIELDS = ('revenue', 'operating_profit')
PERIODS = [['2021-01-01','2021-03-31'], ['2020-01-01','2020-03-31']]


def csv_rows(path):
    with path.open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))


def integer(value):
    if value is None:
        return None
    v = Decimal(str(value))
    if not v.is_finite() or v != v.to_integral_value():
        raise ValueError('Non-integral KRW amount')
    return int(v)


def load_sources(cache, displays):
    xbrl=prior_facts()
    if cache.suffix=='.gz':
        records=json.loads(gzip.decompress(cache.read_bytes()))
        for r in records:xbrl[r['receipt']]=r
    else:
        with sqlite3.connect(f'file:{cache}?mode=ro',uri=True) as db:
            for receipt,expected,evidence,raw in db.execute('select receipt,sha,evidence,raw from originals'):
                r=json.loads(evidence)
                if sha256(raw).hexdigest()!=expected or r['archive_sha256']!=expected or r['receipt']!=receipt:
                    raise ValueError('Archive or parsed evidence digest mismatch')
                xbrl[receipt]=r
    by_receipt=defaultdict(dict)
    for p in displays:
        obj=json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
        for r in obj if isinstance(obj,list) else [obj]:
            if not {'fields','receipt','periods','scope','source_sha256','source_url'}.issubset(r):
                raise ValueError(f'Not a filing evidence result: {p.name}')
            if r['periods']!=PERIODS or r['scope']!='CFS':
                raise ValueError('Unexpected display period or scope')
            by_receipt[r['receipt']][r['source_sha256']]=r
    return xbrl, by_receipt


def raw_pair(field,xbrl,displays):
    pairs=defaultdict(list)
    problems=[]
    if xbrl:
        if xbrl.get('parser_blocker'):
            problems.append(xbrl['parser_blocker'])
        else:
            if list(map(xbrl['periods'].get, ('current','prior_as_reported'))) != PERIODS:
                raise ValueError('Unexpected XBRL periods')
            fs=[xbrl['fields'][t][field] for t in ('current','prior_as_reported')]
            if all(f['status']=='PASS' for f in fs):
                pair=tuple(integer(f['value']) for f in fs)
                pairs[pair].append(('XBRL',xbrl['archive_sha256'],xbrl['source_url']))
            else:
                problems.extend(f['reason'] for f in fs if f['status']!='PASS')
    for r in displays:
        f=r['fields'][field]
        # A syntactically valid income row can be observed before a sector is assigned.
        if f.get('observed') or f['status']=='PASS':
            current,prior=integer(f.get('current')),integer(f.get('prior'))
            if None in (current,prior):
                raise ValueError('An observed display amount is missing')
            pairs[current,prior].append(('display',r['source_sha256'],r['source_url']))
        elif f.get('reason'):
            problems.append(f['reason'])
    if len(pairs)==1:
        pair,sources=next(iter(pairs.items()))
        return pair,'PASS',sources
    if pairs:
        return (None,None),'source_disagreement',[src for items in pairs.values() for src in items]
    return (None,None),'; '.join(sorted(set(problems))) or 'no_accepted_receipt_payload',[]


def row_result(r,sector,xbrl,displays,idx,sessions,versions):
    receipt=r['receipt_candidate']
    passes=r['identity_status']=='PASS'
    if not passes:
        xbrl=None; displays=[]
    if xbrl and (xbrl['corp']!=r['corp_code_candidate'] or xbrl['receipt']!=receipt):
        raise ValueError('Financial evidence is for another entity or receipt')
    for d in displays:
        if (d.get('corp_code')!=r['corp_code_candidate'] or d['isin']!=r['isin']
                or (d.get('kind_receipt') and d['kind_receipt']!=r['kind_receipt'])):
            raise ValueError('Display is for another security, receipt or entity')
    sector_flag=sector['financial'].strip().lower()
    if sector_flag not in ('true','false',''):
        raise ValueError('Unrecognized industry flag')
    group={'true':'financial','false':'nonfinancial','':'unknown'}[sector_flag]
    filed=r['filing_date'].replace('-','') if passes else ''
    if filed and receipt in idx:
        filed=max(filed,idx[receipt]['received'].replace('.',''))
    day=next((s for s in sessions if s>filed),None) if filed else None
    series=versions.get(r['corp_code_candidate'],[])
    orig=[v['receipt'] for v in series if v['type']=='original']
    amended=sorted((v['filed'],v['receipt']) for v in series if v['type']!='original')
    version_ok=(orig==[receipt] and bool(filed) and all(d>filed for d,_ in amended))
    out={'stock_code':r['stock_code'],'isin':r['isin'],'issuer_as_of':r['issuer_as_of'],
         'identity_status':r['identity_status'],'identity_reason':r['reason'],'corp_code':r['corp_code_candidate'],
         'receipt':receipt,'kind_receipt':r['kind_receipt'],'original_filed':filed,'next_krx_session':day,
         'verified_original_version':bool(passes and version_ok),
         'first_next_filing_date_in_window':amended[0][0] if amended else '',
         'amendment_receipts_through_20210630':'|'.join(n for _,n in amended),
         'industry_group':group,'sector_code':sector['sector_code'],'sector_name':sector['sector_name'],
         'cap_quartile':sector.get('cap_quartile',''),'exit_status':sector.get('exit_status',''),
         'xbrl_indexed':bool(passes and receipt in idx),'xbrl_obtained':bool(xbrl),
         'display_obtained':bool(displays),'original_obtained':bool(xbrl or displays),
         'explicit_no_cfs':any(d.get('explicit_no_cfs') for d in displays),
         'xbrl_source_sha256':xbrl['archive_sha256'] if xbrl else '',
         'display_source_sha256':'|'.join(sorted(d['source_sha256'] for d in displays))}
    for field in FIELDS:
        pair,status,sources=raw_pair(field,xbrl,displays)
        if not passes:status='identity_unresolved'
        out.update({f'{field}_current_KRW':pair[0], f'{field}_prior_KRW':pair[1],
                    f'{field}_raw_status':status, f'{field}_evidence':'|'.join(sorted({s[0] for s in sources})),
                    f'{field}_source_urls':'|'.join(sorted({s[2] for s in sources}))})
    c=out['revenue_current_KRW'];p=out['revenue_prior_KRW']
    for key in ('F2','F3'):
        if not passes:reason='identity_unresolved'
        elif group!='nonfinancial':reason='industry_'+group
        elif not out['original_obtained']:reason='original_not_obtained'
        elif out['explicit_no_cfs']:reason='no_consolidated_statement'
        elif c is None or p is None:reason='revenue_'+out['revenue_raw_status']
        elif p<=0 or c<0 or (key=='F2' and c==0):reason='ineligible_revenue_base'
        elif key=='F2' and out['operating_profit_current_KRW'] is None:reason='operating_profit_'+out['operating_profit_raw_status']
        elif not version_ok:reason='original_version_or_same_day_amendment_unresolved'
        elif not day:reason='next_session_not_verified'
        else:reason='PASS'
        out[key+'_original_pair_QC']=reason
    for field in FIELDS:
        obs={tuple(integer(d['separate_only']['fields'][field][k]) for k in ('current','prior'))
             for d in displays if d.get('explicit_no_cfs') and d.get('separate_only')
             and d['separate_only']['fields'][field].get('observed')}
        pair=obs.pop() if len(obs)==1 else (None,None)
        out.update({f'OFS_{field}_current_KRW':pair[0],f'OFS_{field}_prior_KRW':pair[1]})
    return out


def counts(rows):
    return dict(n=len(rows),identity=sum(r['identity_status']=='PASS' for r in rows),
                original=sum(r['original_obtained'] for r in rows),xbrl=sum(r['xbrl_obtained'] for r in rows),
                display=sum(r['display_obtained'] for r in rows),
                revenue_raw=sum(r['revenue_raw_status']=='PASS' for r in rows),
                operating_profit_raw=sum(r['operating_profit_raw_status']=='PASS' for r in rows),
                F2=sum(r['F2_original_pair_QC']=='PASS' for r in rows),
                F3=sum(r['F3_original_pair_QC']=='PASS' for r in rows),
                explicit_no_cfs=sum(r['explicit_no_cfs'] for r in rows),
                separate_revenue=sum(r['OFS_revenue_current_KRW'] is not None for r in rows),
                separate_profit=sum(r['OFS_operating_profit_current_KRW'] is not None for r in rows))


def run(identity,context,index,cache,version_index,display_files,output,calendar_path=None):
    universe=csv_rows(identity);sectors={r['isin']:r for r in csv_rows(context)}
    if len(universe)!=782 or set(sectors)!={r['isin'] for r in universe} or len(sectors)!=782:
        raise ValueError('Historical denominator mismatch')
    idx={r['receipt']:r for r in json.loads(index.read_text())['rows']}
    xbrl,display=load_sources(cache,display_files)
    versions=defaultdict(list)
    for v in csv_rows(version_index):versions[v['corp_code']].append(v)
    cal=json.loads((calendar_path or Path(__file__).with_name('calendar_qc.json')).read_text())
    sessions=cal['sessions']
    if sessions!=sorted(set(sessions)) or sessions[0]>'20210401' or sessions[-1]<'20210701':
        raise ValueError('Missing Q1 filing-window trading calendar')
    rows=[row_result(r,sectors[r['isin']],xbrl.get(r['receipt_candidate']),
                     list(display.get(r['receipt_candidate'],{}).values()),idx,sessions,versions) for r in universe]
    base_counts=counts(rows)
    supplements=json.loads(Path(__file__).with_name('identity_nondec.json').read_text())['rows']
    supplements={r['isin']:r for r in supplements if r.get('identity')=='PASS' and
                 r.get('statement',{}).get('quarter_only_status')=='PASS'}
    for i,base in enumerate(universe):
        extra=supplements.get(base['isin'])
        if not extra:
            rows[i]['source_report_type']='Q1' if rows[i]['identity_status']=='PASS' else 'unresolved'
            continue
        d=extra['dart'];receipt=d['receipt']
        if (base['identity_status']=='PASS' or extra['document_type']!='반기보고서'
                or extra['kind_corrections_to_20210630'] or extra['opendart_xbrl_corrections_to_20210630']
                or extra['statement']['calendar_periods']!=PERIODS):
            raise ValueError('Unexpected half-year supplement scope or revision history')
        effective={**base,'identity_status':'PASS','reason':'unique_nondec_halfyear_original',
                   'corp_code_candidate':d['corp_code'],'receipt_candidate':receipt,
                   'filing_date':extra['filing_date'],'kind_receipt':extra['kind_receipt']}
        supplement_versions={d['corp_code']:[{'type':'original','receipt':receipt,'filed':receipt[:8]}]}
        out=row_result(effective,sectors[base['isin']],xbrl.get(receipt),
                       list(display.get(receipt,{}).values()),{receipt:d},sessions,supplement_versions)
        if (out['next_krx_session']!=extra['first_available_session'] or
                any(out[field+'_'+period+'_KRW']!=extra['statement'][field][period]
                    for field in FIELDS for period in ('current','prior'))):
            raise ValueError('Non-December independent transcription disagreement')
        out['source_report_type']='half_year_explicit_three_months'
        rows[i]=out
    summary={'calendar_database_sha256':cal['database_sha256'],'regular_Q1_index_before_halfyear_supplements':base_counts,'all':counts(rows),
             'by_industry':{g:counts([r for r in rows if r['industry_group']==g])
                            for g in ('nonfinancial','financial','unknown')},
             'nonfinancial_plus_unknown_sensitivity':counts([r for r in rows if r['industry_group']!='financial']),
             'nonfinancial_failures':{f:dict(Counter(r[f+'_original_pair_QC'] for r in rows if r['industry_group']=='nonfinancial'))
                                      for f in ('F2','F3')},
             'by_cap_quartile':{g:counts([r for r in rows if r['cap_quartile']==g]) for g in sorted({r['cap_quartile'] for r in rows})},
             'by_exit_status':{g:counts([r for r in rows if r['exit_status']==g]) for g in sorted({r['exit_status'] for r in rows})},
             'scope':'original quarterly-report extraction QC; amendment replay and timing audit separate; no outcomes read'}
    output.mkdir(exist_ok=True,parents=True)
    with (output/'census_rows.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (output/'census_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary['all']))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('identity','context','index','cache','version_index','output'):p.add_argument(name,type=Path)
    p.add_argument('--calendar',dest='calendar_path',type=Path)
    p.add_argument('--display',nargs='*',type=Path,default=[],dest='display_files')
    run(**vars(p.parse_args()))
