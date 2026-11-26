"""Count exactly one fixed primary issuer-period per case and report quarterly arithmetic separately."""
from argparse import ArgumentParser
from collections import Counter
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path


def summarize(fixed,checks,register,output,xml_checks=None,basis=None):
    with fixed.open() as f:cases=list(csv.DictReader(f))
    checked=json.loads(checks.read_bytes())
    merged=checked['rows'][:]
    if xml_checks:
        extra=json.loads(xml_checks.read_bytes())
        known={v['receipt'] for v in merged}
        merged.extend(v for v in extra['rows'] if v['receipt'] not in known)
    with register.open() as f:meta=list(csv.DictReader(f))
    approvals=json.loads(basis.read_bytes()) if basis else []
    summary=[]
    for r in cases:
        code,end=r['stock_code'],r['period_end']
        registry=[v for v in meta if v['stock_code']==code and v['period_end'] and date.fromisoformat(v['period_end']).isoformat()==end]
        originals=[v for v in registry if v['version']=='original']
        rec=originals[0]['receipt'] if len(originals)==1 else ''
        primary=next((v for v in merged if v['receipt']==rec),None)
        item=dict(stock_code=code,isin=r['isin'],company=r['issuer_on_formation'],period_end=end,
                  stratum=r['selected_stratum'],later_exit=r['later_exit_for_audit'],original_receipt=rec,
                  identity=originals[0]['identity_status'] if len(originals)==1 else 'unresolved',
                  evidence=None,category='source_unavailable',manual_nonmissing=0,verified_numeric=0,false_numeric=0)
        if primary:
            item.update(category=primary['role'],review_format=primary.get('format','human_read_display'),evidence=primary['sha256'],source=primary['source_url'],
                        first_public=primary['filing_kst'] or primary.get('filing_date',''),available_session=primary['available_session'])
            expected=primary['manual']
            item['manual_nonmissing']=sum(v is not None for v in expected.values())
            item['manual']=expected
            per_format={}
            for fmt in ('kind_html','xbrl','dart_html'):
                if fmt not in primary:continue
                observed=primary[fmt]['values']
                per_format[fmt]={'supported':sum(v is not None for v in observed.values()),'matched_numeric':sum(v is not None and (expected[k]==v) for k,v in observed.items()),
                                 'missed':sum(v is None and expected[k] is not None for k,v in observed.items()),
                                 'incorrect_nonmissing':sum(v is not None and expected[k]!=v for k,v in observed.items())}
            item['per_format']=per_format
            item['false_numeric']=sum(v['incorrect_nonmissing'] for v in per_format.values())
            item['verified_numeric']=sum(v is not None and any(primary[f]['values'][k]==v for f in per_format) for k,v in expected.items())
            if primary['role']=='annual':
                supports=[v for v in merged if v['stock_code']==code and v['role']=='nine_month_support' and
                          v['period_end'][:4]==end[:4] and any(g['receipt']==v['receipt'] and g['version']=='original' for g in meta)]
                if len(supports)==1:
                    nine=supports[0]
                    item['original_fy_minus_original_nine_KRW']={k:value-nine['manual'][k] if value is not None and nine['manual'][k] is not None else None for k,value in expected.items()}
                    item['supporting_9m_receipt']=nine['receipt']
                    item['arithmetic_status']='reproduced from displayed annual and nine-month consolidated amounts'
                    if basis:
                        accepted=[a for a in approvals if a['component_receipts'][:2]==[rec,nine['receipt']] and a['verdict']=='PASS']
                        for a in accepted:
                            field=a['field']
                            expected_pair=[item['original_fy_minus_original_nine_KRW'][field+'_'+side] for side in ('current','prior')]
                            if a['arithmetic_pair']!=expected_pair:
                                raise ValueError('basis approval differs from human-reproduced pair')
                        item['same_basis_fields']=sorted({a['field'] for a in accepted})
                        item['basis_status']='same_basis_approved' if item['same_basis_fields']==['operating_profit','revenue'] else 'arithmetic_only'
            if len(registry)>1:
                item['registered_versions']=[dict(receipt=v['receipt'],version=v['version'],available_session=v['available_session']) for v in registry]
        summary.append(item)
    totals={'fixed':len(cases),'primary_document_reads':sum(bool(r['evidence']) for r in summary),
            'primary_display_reads':sum(r.get('review_format')=='human_read_display' for r in summary),
            'primary_xbrl_only_reads':sum(r.get('review_format')=='xbrl_only_independent_raw_context_read' for r in summary),
            'categories':dict(Counter(r['category'] for r in summary)),
            'direct_numeric_cells':sum(r['manual_nonmissing'] for r in summary if r['category']=='quarter'),
            'direct_numeric_verified_one_or_more':sum(r['verified_numeric'] for r in summary if r['category']=='quarter'),
            'post_delist_financial_op_cells':sum(r['verified_numeric'] for r in summary if r['category']=='post_delist_financial'),
            'in_scope_direct_incorrect':sum(r['false_numeric'] for r in summary if r['category']=='quarter'),
            'incorrect_nonmissing_across_sources':sum(r['false_numeric'] for r in summary)}
    if basis:
        totals['annual_basis_status']=dict(Counter(r['basis_status'] for r in summary if r['category']=='annual'))
    out=dict(supplemental_xml_sha256=sha256(xml_checks.read_bytes()).hexdigest() if xml_checks else None,frozen_sha256=sha256(fixed.read_bytes()).hexdigest(),checks_sha256=sha256(checks.read_bytes()).hexdigest(),totals=totals,rows=summary)
    if basis:
        out['q4_basis_sha256']=sha256(basis.read_bytes()).hexdigest()
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    for name in ('fixed','checks','register','output'):p.add_argument(name,type=Path)
    p.add_argument('--xml-checks',type=Path)
    p.add_argument('--basis',type=Path)
    summarize(**vars(p.parse_args()))
