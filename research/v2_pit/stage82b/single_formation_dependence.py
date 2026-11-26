"""June 1 only: remove the five largest absolute contributions to each 120-day price spread.

This diagnostic uses the frozen signal group assignments and the ordinary Stage 5
earnings-study price outcome. It is not a decision rule or a stock selection filter.
"""
import json
from statistics import mean

from single_formation import arguments, diff, run


def group_stats(names, records, ix):
    observed=[records[k][ix] for k in sorted(names) if records[k][ix] is not None]
    return {'assigned':len(names),'observed':len(observed),
            'equal_weight_mean':mean(observed) if observed else None}


def measure(left, right, records, ix):
    a=group_stats(left,records,ix)
    b=group_stats(right,records,ix)
    return {'target':a,'comparison':b,'difference':diff(a['equal_weight_mean'],b['equal_weight_mean'])}


def contrast(left, right, records):
    if left & right:
        raise ValueError('Expected disjoint fixed signal groups')
    observed=[]
    for sign,name,identifiers in [(1,'target',left),(-1,'comparison',right)]:
        valid=[isin for isin in identifiers if records[isin][0] is not None]
        for isin in valid:
            r=records[isin][0]
            observed.append({'isin':isin,'side':name,'price_return':r,
                             'signed_contribution':sign*r/len(valid)})
    # Each group's contribution sums to its own equal-weight observed mean
    # with the sign of that group in the contrast. Do not rerank the portfolios.
    observed.sort(key=lambda v:(-abs(v['signed_contribution']),v['isin']))
    subgroups_observed=any(r['side']=='target' for r in observed) and any(r['side']=='comparison' for r in observed)
    removed=observed[:5] if subgroups_observed else []
    omit={item['isin'] for item in removed}
    output={'removed_by_primary_price_contribution':removed,
            'diagnostic_status':'computed' if subgroups_observed else 'one_side_has_no_observed_price'}
    for ix,metric in ((0,'price'),(1,'partial_economic_same_exclusions')):
        before=measure(left,right,records,ix)
        after=measure(left-omit,right-omit,records,ix)
        output[metric]={'before':before,'after':after,'after_minus_before':diff(after['difference'],before['difference'])}
    return output


def dependence(groups, records):
    return {f'{a}-{b}':contrast(groups[a],groups[b],records)
            for a,b in (('top','remainder'),('C','A'),('C','B'))}


if __name__=='__main__':
    result=run(arguments(__doc__),diagnostic=dependence)
    result.update(selection='Five largest absolute signed contributions to the observed equal-weight price spread; ties by ISIN.',
                  reweighting='Keep original classifications, remove selected names from both sides, renormalize observed names separately in each original group. Missing remains excluded.',
                  partial_economic='Same removed ISINs as the primary price contrast. No additional search.')
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
