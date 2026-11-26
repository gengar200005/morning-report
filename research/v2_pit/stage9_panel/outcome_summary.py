"""Aggregate fixed monthly development groups; this module does not load market data."""
import csv
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'stage82b'))
from single_formation import cells, diff, groups, matched, summaries, top

CONTRASTS=(('top','remainder','eligible'),('C','A','joint'),('C','B','joint'))
HORIZONS=(20,60,120)


def calendar(days, formations):
    at={d:i for i,d in enumerate(days)}
    june=at['20210601']
    pilot_start,pilot_end=days[june+1],days[june+120]
    output=[]
    for day in formations:
        i=at[day]
        exits={str(h):days[i+h] if i+h<len(days) and days[i+h]<='20211231' else None for h in HORIZONS}
        start=days[i+1]
        overlaps=start<=pilot_end and (exits['120'] is None or exits['120']>=pilot_start)
        output.append(dict(formation=day,entry=start,exits=exits,june_overlap=overlaps))
    return output


def eligibility(g,left):
    required=('top','remainder') if left=='top' else ('A','B','C')
    return all(len(g[k])>=5 for k in required)


def label_stats(periods):
    """Average each numeric contrast over its valid months, never over pooled issuers."""
    buckets=defaultdict(list)
    for r in periods:
        keys=[('overall','all'),('year',r['formation'][:4]),('regime',r['regime'])]
        if r['formation']!='20210601':
            keys.append(('exclude_june_formation_only','retained'))
        if not r['june_overlap']:
            keys.append(('exclude_june_holding_overlap','retained'))
        for label,slot in keys:
            key=(r['signal'],r['horizon'],r['contrast'],label,slot)
            buckets[key].append(r)
    output=[]
    for key,items in sorted(buckets.items()):
        eligible=[r for r in items if r['eligible_month']]
        names=('price','economic','matched_cap_turnover','matched_sector','adverse_price',
               'matched_cap_share_turnover','economic_matched_cap_share_turnover',
               'economic_matched_cap_turnover','economic_matched_sector','adverse_economic')
        def summarize(column):
            values=[r[column] for r in eligible if r[column] is not None]
            return {'n_months':len(values),'mean':mean(values) if values else None,
                    'positive_month_fraction':sum(v>0 for v in values)/len(values) if values else None}
        output.append(dict(zip(('signal','horizon','contrast','slice','category'),key))|
                      {'candidate_months':len(items),'min_size_months':len(eligible),
                       'effects':{k:summarize(k) for k in names}})
    return output


def group_period_statistics(monthly):
    """Monthly equal-weight descriptive aggregates, including absolute ETF comparisons."""
    by=defaultdict(lambda:defaultdict(list))
    for r in monthly:
        for kind,slot in [('overall','all'),('year',r['formation'][:4]),('regime',r['regime'])]:
            bucket=by[r['signal'],r['horizon'],kind,slot]
            for label,g in r['stats']['groups'].items():
                for metric in ('price','partial_economic'):
                    for field in ('mean','median','minus_etf','minus_universe','observed'):
                        bucket[(label,metric,field)].append(g[metric][field])
                bucket[(label,'membership','assigned')].append(g['n'])
            for metric,di in r['stats']['diagnostics'].items():
                bucket[('eligible',metric,'spearman_ic')].append(di['spearman_ic'])
                for q,group in enumerate(di['quintiles_high_to_low'],1):
                    for field in ('n','mean','observed'):
                        bucket[(f'quintile_{q}_high_first',metric,field)].append(group[field])
            for metric,value in r['stats']['joint_scope_top_minus_remainder']['effects'].items():
                bucket[('joint_top_minus_remainder',metric,'difference')].append(value)
    output=[]
    for key,bucket in sorted(by.items()):
        metrics=[]
        for fields,values in sorted(bucket.items()):
            known=[v for v in values if v is not None]
            metrics.append(dict(zip(('group','metric','field'),fields))|
                           {'valid_months':len(known),'total_months':len(values),'equal_month_mean':mean(known) if known else None,
                             'positive_month_fraction':sum(v>0 for v in known)/len(known) if known and fields[2] in ('minus_etf','minus_universe') else None})
        output.append(dict(zip(('signal','horizon','slice','category'),key))|{'metrics':metrics})
    return output


def name_diagnostics(rows):
    """Rows contain original assigned names and both metrics; do not rerank after deletion."""
    by_month=defaultdict(list)
    for r in rows:
        if r['eligible_month']:
            by_month[r['formation']].append(r)
    valid_months={}
    contribution=Counter()

    def leg(rows,side,metric,omit=()):
        return [r[metric] for r in rows if r['side']==side and r['isin'] not in omit and r[metric] is not None]

    for day,items in by_month.items():
        valid=[r for r in items if r['price'] is not None]
        counts=Counter(r['side'] for r in valid)
        if not counts['target'] or not counts['comparison']:
            continue
        valid_months[day]=items
        for r in valid:
            contribution[r['isin']]+=(1 if r['side']=='target' else -1)*r['price']/counts[r['side']]
    removed=sorted(contribution, key=lambda k:(-abs(contribution[k]),k))[:5]

    def effect(metric,omit,drop_year=None):
        effects=[]
        for day,items in sorted(valid_months.items()):
            if day[:4]==drop_year:
                continue
            left,right=(leg(items,side,metric,omit) for side in ('target','comparison'))
            if left and right:
                effects.append(mean(left)-mean(right))
        return {'n_months':len(effects),'effect':mean(effects) if effects else None}
    result={'removed_by_primary_price':[
        {'isin':k,'signed_contribution_to_time_mean':contribution[k]/len(valid_months)} for k in removed],
        'valid_before_leave5':len(valid_months)}
    for metric in ('price','economic'):
        result[metric]={'baseline':effect(metric,()),'after_leave5':effect(metric,removed),
                        'leave_one_year':{str(y):effect(metric,(),str(y)) for y in range(2017,2022)}}
    return result


def analyze(formation_calendar, data, market, output):
    """Each day has only preformed covariates. A missing outcome has an explicit reason."""
    output.mkdir(exist_ok=True,parents=True)
    all_periods=[]
    monthly=[]
    contributions=defaultdict(list)
    missing=Counter()
    inference_fields=('formation','isin','corp_code','signal','contrast','side','price','economic','status',
                      'sector','cap','turnover','cap_cell','turn_cell')
    with gzip.open(output/'inference_rows.csv.gz','wt',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=inference_fields,lineterminator='\n')
        writer.writeheader()
        for cal in formation_calendar:
            day=cal['formation']
            features=data[day]
            session=market[day]
            sector={i:r['sector'] for i,r in features.items() if r['sector']}
            liq={i:(r['cap'],r['turnover']) for i,r in features.items()}
            rate_inputs={i:(r['cap'],r['share_turnover']) for i,r in features.items()}
            prices=session['records']
            benchmark=session['benchmark']
            for signal in session['signals']:
                signal_values={i:r[signal] for i,r in features.items() if r.get(signal) is not None}
                score4=session['m4']
                group=groups(signal_values,score4)
                hrows={h:(prices[h],benchmark[h]) for h in HORIZONS if cal['exits'][str(h)]}
                details=summaries(group,hrows,liq,sector,signal_values)
                # The M4-restricted standalone spread quantifies the scope change from stage 9 to 10.
                joint={i:signal_values[i] for i in group['joint']}
                joint_top=top(joint)
                joint_rest=set(joint)-joint_top
                for h,outcome in details.items():
                    records=prices[h]
                    joint_metrics={}
                    for col,field in enumerate(('price','economic')):
                        a=[records[i][col] for i in sorted(joint_top) if records[i][col] is not None]
                        b=[records[i][col] for i in sorted(joint_rest) if records[i][col] is not None]
                        joint_metrics[field]=diff(mean(a) if a else None,mean(b) if b else None)
                    outcome['joint_scope_top_minus_remainder']={'top':len(joint_top),'remainder':len(joint_rest),'effects':joint_metrics}
                    meta={'formation':day,'signal':signal,'horizon':h,'regime':session['regime'],
                          'june_overlap':cal['june_overlap']}
                    monthly.append(meta|{'assigned_monthly_sample':len(features),'stats':outcome})
                    for i,r in features.items():
                        missing[(day[:4],signal,h,r.get('industry_group','unknown'),r.get('sector',''),
                                 r.get('cap_quartile','unknown'),r.get('subsequent_exit','unverified'),
                                 'available' if i in signal_values else 'missing',
                                 r.get(signal+'_reason','PASS' if i in signal_values else 'unclassified'),
                                 records[i][2] if i in signal_values else 'no_signal')]+=1
                    for left,right,base in CONTRASTS:
                        key=f'{left}-{right}'
                        both=outcome['contrasts'][key]
                        pri=both['price'];eco=both['partial_economic']
                        rate_cells=cells(group[base],rate_inputs)
                        for ix,metric in enumerate((pri,eco)):
                            metric['matched_cap_share_turnover']=matched(group[left],group[right],
                                {i:rec[ix] for i,rec in records.items()},rate_cells)
                        valid=eligibility(group,left)
                        all_periods.append(meta|{'contrast':key,'eligible_month':valid,
                            'price':pri['difference'],'economic':eco['difference'],
                            'matched_cap_turnover':pri['matched_cap_turnover']['effect'],
                            'matched_cap_share_turnover':pri['matched_cap_share_turnover']['effect'],
                            'economic_matched_cap_share_turnover':eco['matched_cap_share_turnover']['effect'],
                            'matched_sector':pri['matched_sector']['effect'],'adverse_price':pri['adverse_unresolved_stress'],
                            'economic_matched_cap_turnover':eco['matched_cap_turnover']['effect'],
                            'economic_matched_sector':eco['matched_sector']['effect'],
                            'adverse_economic':eco['adverse_unresolved_stress']})
                        if h!=120:
                            continue
                        bins=cells(group[base],liq)
                        for side,label in [('target',left),('comparison',right)]:
                            for i in sorted(group[label]):
                                px,er,st,_=records[i]
                                row={'formation':day,'isin':i,'corp_code':features[i]['corp_code'],'signal':signal,'contrast':key,'side':side,
                                     'price':px,'economic':er,'status':st,'sector':sector.get(i),
                                     'cap':liq[i][0],'turnover':liq[i][1],
                                     'cap_cell':bins.get(i,(None,None))[0],'turn_cell':bins.get(i,(None,None))[1]}
                                writer.writerow(row)
                                contributions[(signal,key)].append(row|{'eligible_month':valid})
    def save(name,content):
        (output/name).write_text(json.dumps(content,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    save('calendar.json',formation_calendar)
    save('monthly_detail.json',monthly)
    save('monthly_contrasts.json',all_periods)
    save('summary.json',label_stats(all_periods))
    save('group_statistics.json',group_period_statistics(monthly))
    save('concentration.json',{s:{k:name_diagnostics(v) for (f,k),v in contributions.items() if f==s}
                               for s in sorted({f for f,k in contributions})})
    save('missingness.json',[dict(zip(('year','signal','horizon','industry','sector','cap_quartile','exit_diagnostic','field_state','field_reason','return_status'),key))|
                             {'count':n} for key,n in sorted(missing.items())])
