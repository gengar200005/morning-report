"""Compare the final original-receipt ledger to the eight earlier and eleven frozen transcriptions."""
import argparse
import csv
from fractions import Fraction
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def signals(revenue,op,applicable):
    c,p=revenue
    if not applicable or None in revenue or p<=0 or c<0:
        return {},{}
    f3=Fraction(c,p)-1
    if None in op or c==0:
        return {},{'F3':str(f3)}
    return {'F2':str(100*(Fraction(op[0],c)-Fraction(op[1],p)))},{'F3':str(f3)}


def audit(ledger):
    with ledger.open() as f:rows={r['isin']:r for r in csv.DictReader(f)}
    old=json.loads((HERE.parent/'evidence_20261126/qc_manual.json').read_text())['rows']
    new=json.loads((HERE/'holdout_manual.json').read_text())['rows']
    result=[]
    for cohort,group in (('previous',old),('frozen_holdout',new)):
        for m in group:
            row=rows[m['isin']]
            if cohort=='previous':
                receipt=m['receipt']
                expected={}
                for name in ('revenue','operating_profit'):
                    v=m['fields'][name]
                    scale={'KRW':1,'KRW million':10**6,None:1}[v.get('unit')]
                    expected[name]=tuple(None if v.get(t) is None else scale*v[t] for t in ('current','prior'))
                source=m['viewer_sha256']
                timing=None
            else:
                receipt=m['dart_receipt_candidate']
                expected={f:tuple(m[prefix+'_'+t] for t in ('current','prior'))
                          for f,prefix in (('revenue','revenue'),('operating_profit','op'))}
                source=m['sha256']
                timing=m['conservative_next_session']
            observed={f:tuple(int(row[f+'_'+t+'_KRW']) if row[f+'_'+t+'_KRW'] else None for t in ('current','prior'))
                      for f in expected}
            e2,e3=signals(expected['revenue'],expected['operating_profit'],row['industry_group']=='nonfinancial')
            a2,a3=signals(observed['revenue'],observed['operating_profit'],row['industry_group']=='nonfinancial')
            exp={**e2,**e3}
            act={k:v for k,v in {**a2,**a3}.items() if row[k+'_original_pair_QC']=='PASS'}
            detail={'cohort':cohort,'stock_code':m['stock_code'],'isin':m['isin'],'receipt':receipt,
                    'receipt_match':row['receipt']==receipt,'corp_match':row['corp_code']==m['corp_code'],
                    'display_hash_linked':source in row['display_source_sha256'].split('|'),
                    'session_match':row['next_krx_session']==timing if timing else None,
                    'manual':expected,'ledger':observed,'manually_expected_signals':exp,'ledger_signals':act,
                    'ledger_revenue_sources':row['revenue_evidence'],'ledger_profit_sources':row['operating_profit_evidence']}
            detail['match']=(detail['receipt_match'] and detail['corp_match'] and detail['display_hash_linked']
                             and detail['session_match'] is not False and expected==observed and exp==act)
            result.append(detail)
    return {'filings':len(result),'field_pairs':2*len(result),'cells':4*len(result),
            'observed_numeric_pairs':sum(pair[0] is not None for d in result for pair in d['manual'].values()),
            'exact_field_pairs':sum(d['manual'][k]==d['ledger'][k] for d in result for k in d['manual']),
            'mismatched_filings':sum(not d['match'] for d in result),'rows':result}


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('ledger',type=Path);a.add_argument('output',type=Path)
    args=a.parse_args();summary=audit(args.ledger)
    args.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print({k:v for k,v in summary.items() if k!='rows'})
    if summary['mismatched_filings']:raise SystemExit(1)
