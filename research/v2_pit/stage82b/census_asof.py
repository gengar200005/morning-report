"""Frozen June 1, 2021 observable 2021Q1 report version, no outcomes and no carryback."""
import argparse
import csv
from fractions import Fraction
import json
from pathlib import Path


def build(ledger, amendments, output):
    with ledger.open(encoding='utf8',newline='') as f:
        inputs=list(csv.DictReader(f))
    if len(inputs)!=782 or len({r['isin'] for r in inputs})!=782:raise ValueError('Expected the fixed 782')
    versions=json.loads(amendments.read_text())['bounded_version_rows']
    out=[]
    formation='20210601'
    for r in inputs:
        isin=r['isin']
        cols={'isin':isin,'stock_code':r['stock_code'],'issuer_as_of':r['issuer_as_of'],
              'corp_code':r['corp_code'],'original_receipt':r['receipt'],'identity_status':r['identity_status'],
              'industry_20210331':r['industry_group'],'formation':formation,'quarter_end':'20210331',
              'scope':'CFS','unit':'KRW','period_current':'20210101/20210331','period_prior':'20200101/20200331',
              'receipt':'','version':'','published':'','available_session':'','sha256':'','source':'',
              'revenue_current_KRW':None,'revenue_prior_KRW':None,'operating_profit_current_KRW':None,
              'operating_profit_prior_KRW':None,'revenue_reason':'','operating_profit_reason':'',
              'F2_pp':None,'F3_fraction':None,'F2_status':'','F3_status':''}
        issue=''
        series=[v for v in versions if v['isin']==isin]
        known=[v for v in series if v['start_session'] and v['start_session']<=formation and
               (v['stop_session_exclusive'] is None or formation<v['stop_session_exclusive'])]
        if len(known)>1:raise ValueError('Overlapping versions at formation')
        if r['identity_status']!='PASS':issue='identity_unresolved'
        elif not r['next_krx_session'] or r['next_krx_session']>formation:issue='not_available_at_formation'
        elif series and not known:issue='no_unambiguous_latest_version'
        elif known and known[0]['version']!='original':
            v=known[0]
            cols.update(receipt=v['receipt'],version=v['version'],published=v['filed'],available_session=v['start_session'],
                        sha256=v['sha256'] or '',source=v['source'] or '')
            if not v['sha256']:issue='missing_effective_amendment'
            for field in ('revenue','operating_profit'):
                pair=v[field]
                if pair is None:cols[field+'_reason']='current_amendment_has_no_supported_pair'
                else:
                    cols[field+'_current_KRW'],cols[field+'_prior_KRW']=map(int,pair)
                    cols[field+'_reason']='PASS'
        else:
            if r['verified_original_version']!='True':issue='original_version_unverified'
            if not issue:
                cols.update(receipt=r['receipt'],version='original',published=r['original_filed'],
                            available_session=r['next_krx_session'],
                            sha256='|'.join(s for s in (r['xbrl_source_sha256'],r['display_source_sha256']) if s),
                            source='|'.join(sorted({s for f in ('revenue','operating_profit')
                                           for s in r[f+'_source_urls'].split('|') if s})))
                for field in ('revenue','operating_profit'):
                    cols[field+'_reason']=r[field+'_raw_status']
                    for period in ('current','prior'):
                        k=f'{field}_{period}_KRW'
                        cols[k]=int(r[k]) if r[k] else None
        if cols['published'] and (cols['published']>='20210601' or cols['available_session']>formation):
            raise ValueError('Future filing admitted')
        c,p=cols['revenue_current_KRW'],cols['revenue_prior_KRW']
        for signal in ('F2','F3'):
            if issue:reason=issue
            elif not cols['sha256']:reason='missing_source'
            elif cols['industry_20210331']!='nonfinancial':reason='outside_March_nonfinancial_group'
            elif c is None or p is None:reason='missing_revenue_pair'
            elif p<=0 or c<0 or (signal=='F2' and c==0):reason='ineligible_revenue_base'
            elif signal=='F2' and cols['operating_profit_current_KRW'] is None:reason='missing_profit_pair'
            else:
                reason='PASS'
                if signal=='F2':
                    value=100*(Fraction(cols['operating_profit_current_KRW'],c)-Fraction(cols['operating_profit_prior_KRW'],p))
                    cols['F2_pp']=float(value)
                else:cols['F3_fraction']=float(Fraction(c,p)-1)
            cols[signal+'_status']=reason
        out.append(cols)
    with output.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
    print({k:sum(r[k+'_status']=='PASS' for r in out) for k in ('F2','F3')})


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for key in ('ledger','amendments','output'):a.add_argument(key,type=Path)
    build(**vars(a.parse_args()))
