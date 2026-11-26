"""Count exactly one fixed primary issuer-period per case and report quarterly arithmetic separately."""
from argparse import ArgumentParser
from collections import Counter
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path


def summarize(fixed,checks,register,output):
    with fixed.open() as f:cases=list(csv.DictReader(f))
    checked=json.loads(checks.read_bytes())
    with register.open() as f:meta=list(csv.DictReader(f))
    summary=[]
    for r in cases:
        code,end=r['stock_code'],r['period_end']
        registry=[v for v in meta if v['stock_code']==code and v['period_end'] and date.fromisoformat(v['period_end']).isoformat()==end]
        originals=[v for v in registry if v['version']=='original']
        rec=originals[0]['receipt'] if len(originals)==1 else ''
        primary=next((v for v in checked['rows'] if v['receipt']==rec),None)
        item=dict(stock_code=code,isin=r['isin'],company=r['issuer_on_formation'],period_end=end,
                  stratum=r['selected_stratum'],later_exit=r['later_exit_for_audit'],original_receipt=rec,
                  identity=originals[0]['identity_status'] if len(originals)==1 else 'unresolved',
                  evidence=None,category='source_unavailable',manual_nonmissing=0,verified_numeric=0,false_numeric=0)
        if primary:
            item.update(category=primary['role'],evidence=primary['sha256'],source=primary['source_url'],
                        first_public=primary['filing_kst'],available_session=primary['available_session'])
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
                supports=[v for v in checked['rows'] if v['stock_code']==code and v['role']=='nine_month_support' and
                          v['period_end'][:4]==end[:4] and any(g['receipt']==v['receipt'] and g['version']=='original' for g in meta)]
                if len(supports)==1:
                    nine=supports[0]
                    item['original_fy_minus_original_nine_KRW']={k:value-nine['manual'][k] if value is not None and nine['manual'][k] is not None else None for k,value in expected.items()}
                    item['supporting_9m_receipt']=nine['receipt']
                    item['arithmetic_status']='reported-amount subtraction only; independent basis evidence is separate'
            if len(registry)>1:
                item['registered_versions']=[dict(receipt=v['receipt'],version=v['version'],available_session=v['available_session']) for v in registry]
        summary.append(item)
    totals={'fixed':len(cases),'primary_display_reads':sum(bool(r['evidence']) for r in summary),
            'categories':dict(Counter(r['category'] for r in summary)),
            'direct_numeric_cells':sum(r['manual_nonmissing'] for r in summary if r['category']=='quarter'),
            'direct_numeric_verified_one_or_more':sum(r['verified_numeric'] for r in summary if r['category']=='quarter'),
            'incorrect_nonmissing_across_sources':sum(r['false_numeric'] for r in summary)}
    out=dict(frozen_sha256=sha256(fixed.read_bytes()).hexdigest(),checks_sha256=sha256(checks.read_bytes()).hexdigest(),totals=totals,rows=summary)
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    for name in ('fixed','checks','register','output'):p.add_argument(name,type=Path)
    summarize(**vars(p.parse_args()))
