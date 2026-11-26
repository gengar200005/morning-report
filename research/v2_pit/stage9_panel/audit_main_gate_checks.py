"""Verify the independent holdout's accepted Q4 row and excluded post-delisting financial row."""
from argparse import ArgumentParser
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path


def check(ledger,summary,basis,daily,output):
    raw=ledger.read_bytes()
    entries=list(csv.DictReader(io.StringIO(raw.decode())))
    fixed=json.loads(summary.read_bytes())
    corrections=json.loads(daily.read_bytes())
    reviews=json.loads(basis.read_bytes())
    totals=fixed['totals']
    if (len(entries),totals['fixed'],totals['primary_display_reads'])!=(14400,21,21):
        raise ValueError('wrong ledger or independent holdout size')
    amounts=[r for r in fixed['rows'] if r['category']=='quarter']
    for r in amounts:
        sources=r['per_format']
        if sources['xbrl']['matched_numeric']!=4 or not any(sources.get(k,{}).get('matched_numeric')==4 for k in ('dart_html','kind_html')):
            raise ValueError('direct quarter lacks two-format independent confirmation')
    if len(amounts)!=12:
        raise ValueError('direct quarter count')
    hite=next(r for r in fixed['rows'] if r['stock_code']=='000080')
    a=hite['original_fy_minus_original_nine_KRW']
    h,=[r for r in entries if r['stock_code']=='000080' and r['formation']=='20180402']
    fields=('revenue_current','revenue_prior','operating_profit_current','operating_profit_prior')
    if {k:int(h[k]) for k in fields}!=a or not all(h[k]=='annual_minus_nine' for k in ('method_F2','method_F3')):
        raise ValueError('accepted as-of amount mismatch')
    r,p,o,op=[Decimal(a[k]) for k in fields]
    if Decimal(h['F2'])!=100*(o/r-op/p) or Decimal(h['F3'])!=r/p-1:
        raise ValueError('accepted Q4 growth or margin mismatch')
    admitted=[v for v in reviews if v['component_receipts'][0]==h['receipt'] and v['verdict']=='PASS']
    if {v['field'] for v in admitted}!={'revenue','operating_profit'} or h['available_session']!='20180402':
        raise ValueError('absent independent basis or wrong session')
    kb=next(v for v in fixed['rows'] if v['stock_code']=='002550')
    kb_months=[v for v in entries if v['stock_code']=='002550']
    if (len(kb_months)!=7 or any(v['F2'] or v['F3'] or v['industry_group']!='financial' for v in kb_months)
            or any(v['receipt']==kb['original_receipt'] for v in entries)):
        raise ValueError('post-delisting financial leakage')
    if corrections['amendment_change_prior_quarter_op_KRW']!=-106559859:
        raise ValueError('amendment difference')
    result={'ledger_sha256':hashlib.sha256(raw).hexdigest(),'sample_sha256':fixed['frozen_sha256'],
            'counts':totals,'dual_format_matched_cells':4*len(amounts),
            'KB_insurance':{'receipt':kb['original_receipt'],'sampled_months':len(kb_months),'all_sectors_financial':True,
                            'eligible_signals':0,'uses_of_post_delisting_filing':0,'latest_formation':max(v['formation'] for v in kb_months)},
            'Hite_Jinro':{k:h[k] for k in ('formation','receipt','available_session','F2','F3','method_F2','method_F3')},
            'Hite_Jinro_amounts_KRW':a,'q4_basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
            'Sundo_Electric':{'daily_replay_sha256':hashlib.sha256(daily.read_bytes()).hexdigest(),
                               'amendment_change_prior_quarter_op_KRW':corrections['amendment_change_prior_quarter_op_KRW']}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    for k in ('ledger','summary','basis','daily','output'):p.add_argument(k,type=Path)
    check(**vars(p.parse_args()))
