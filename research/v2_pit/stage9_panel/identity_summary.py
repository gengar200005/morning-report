"""Produce a source-only census from the frozen roster and archived official search pages."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from identity_ledger import read, save


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(work, roster, output):
    members=read(roster)
    current=read(work/'issuers.csv')
    supplements={r['stock_code']:r for r in read(work.parent/'identity_supplement/issuer_resolution.csv')}
    resolved=[]
    for r in current:
        s=supplements.get(r['stock_code'],{})
        if s:
            assert s['isin']==r['isin'] and s['issuer_verdict']=='historical_isin_anchored'
        if r['corp_code'] and s:
            assert s['corp_code']==r['corp_code']
        resolved.append({**r,'corp_code':r['corp_code'] or s['corp_code'],
                         'query_corp_code':r['corp_code'],
                         'historical_resolution':'supplement_dated_KRX_KIND_DART' if s else 'per_receipt_validation_required',
                         'earliest_supplement_anchor':s.get('earliest_matched_filed','')})
    save(work/'issuers_resolved.csv',resolved,resolved[0].keys())
    receipts=read(work/'receipts.csv')
    coverage=read(work/'monthly_coverage.csv')
    assert len(members)==len(coverage)==len({(r['formation'],r['isin']) for r in coverage})
    assert {(r['formation'],r['isin']) for r in coverage}=={(r['formation'],r['historical_isin']) for r in members}
    monthly=Counter(r['formation'] for r in coverage)
    assert set(monthly.values())=={240} and len(monthly)==60
    api={path.stem for path in (work/'parsed').glob('X-*.json')}
    directory=[]
    for r in resolved:
        for form in ('11011','11012','11013'):
            code=r['stock_code'];key='X-'+code+'-'+form
            item={'stock_code':code,'corp_code':r['corp_code'],'form':form,'queried':int(key in api),'response_hashes':'','rows_for_confirmed_corp':''}
            if key in api:
                obj=json.loads((work/'parsed'/(key+'.json')).read_bytes())
                hashes=[sha(work/'raw'/(key+'-p'+str(n)+'.html')) for n in range(1,len(obj['hashes'])+1)]
                if hashes!=obj['hashes']:raise ValueError('OpenDART archive hash mismatch '+key)
                if len(obj['records'])!=obj['count']:raise ValueError('OpenDART total '+key)
                item.update(response_hashes='|'.join(hashes),rows_for_confirmed_corp=sum(v['corp_code']==r['corp_code'] for v in obj['records']))
            directory.append(item)
    save(work/'xbrl_directory_manifest.csv',directory,directory[0].keys())
    def grouped(*keys):
        return dict(sorted(Counter('|'.join(r.get(k,'') or '(none)' for k in keys) for r in receipts).items()))
    outcome={'scope':'2017-01 through 2021-12 formation-time KOSPI common-stock roster. Archive includes earlier comparison reports.',
        'roster_rows':len(members),'formation_months':len(monthly),'each_formation_count':240,'distinct_isin':len(resolved),
        'issuer_corp_codes':sum(bool(r['corp_code']) for r in resolved),
        'kind_complete_quarter_windows':len([p for p in (work/'parsed').glob('KP-*.json') if '-p' not in p.stem]),
        'dart_issuer_full_periodic_indexes':len(list((work/'parsed').glob('D-*-ALL.json'))),
        'exchange_sessions_rules':'Use strictly next known session after latest public source date. Leave dates before verified calendar blank.',
        'issuer_month_complete_index':sum(r['complete']=='1' for r in coverage),
        'xbrl_directory_queries_verified':len(api),'xbrl_directory_queries_expected':len(directory),
        'events':len(receipts),'version_status':grouped('version','identity_status'),
        'precalendar_comparator_periodic_main_links':sum(bool(r.get('comparator_original_receipt')) for r in receipts),
        'xbrl_lookup':grouped('xbrl_index_lookup_status'),'amendment_scope':grouped('amendment_scope','identity_status'),
        'identity_BLOCKED_reasons':dict(sorted(Counter(r['reason'].split(';')[0] for r in receipts if r['identity_status']=='BLOCKED').items())),
        'source_manifest_sha256':{f:sha(work/f) for f in ('receipts.csv','issuers_resolved.csv','monthly_coverage.csv','coverage.csv','xbrl_directory_manifest.csv')},
        'frozen_roster_sha256':sha(roster)}
    if (work/'comparator_chains.csv').is_file():
        outcome['source_manifest_sha256']['comparator_chains.csv']=sha(work/'comparator_chains.csv')
    output.write_text(json.dumps(outcome,indent=2,ensure_ascii=False)+'\n')
    return outcome


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('work',type=Path);p.add_argument('roster',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();summarize(a.work,a.roster,a.output)
