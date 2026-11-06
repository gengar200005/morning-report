"""Attribute missing NAV to opening/closing issues and compare fixed paths."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from replay_summary import statistics


def issue_history(run):
    active, episodes = {}, []
    events = defaultdict(list)
    for row in run['journal']:
        events[row['day']].append(row)
    invalid_days = set()
    new_days = set()
    extra_missing = Counter()
    for row in run['daily']:
        day = row['day']
        for event in events[day]:
            key = event['block']
            if key:
                issue = dict(key=key,isin=event['isin'],opened=day,resolved=None,
                             blocked_sessions=0,
                             category=event.get('category',event['event']))
                active[key] = issue
                episodes.append(issue)
                new_days.add(day)
            key = event['unblock']
            if key:
                active.pop(key)['resolved'] = day
        if row['nav'] is None:
            invalid_days.add(day)
        for key,issue in active.items():
            if key in row['unresolved']:
                issue['blocked_sessions'] += 1
        for key in set(row['unresolved'])-active.keys():
            extra_missing[key] += 1
    return dict(episodes=episodes,registered=len(episodes),new_issue_days=len(new_days),
                new_issue_days_with_null_nav=len(invalid_days & new_days),
                continuation_only_null_days=len(invalid_days-new_days),
                unvalued_days=len(invalid_days),mark_only_occurrences=dict(extra_missing),
                unresolved_at_end=sorted(active),
                first_unvalued=min(invalid_days,default=None),
                repeated_reasons=sum(x['blocked_sessions'] for x in episodes))


def compare_selections(left,right):
    a,b = left['selections'],right['selections']
    changed = {d for d in a.keys()|b.keys() if a.get(d,[])!=b.get(d,[])}
    different_set = {d for d in changed if set(a.get(d,[]))!=set(b.get(d,[]))}
    return dict(ordered_selection_days_changed=len(changed),selected_set_days_changed=len(different_set),
                same_set_reordered_days=len(changed-different_set),first_changed=min(changed,default=None))


def run_metrics(run, key):
    rows = [dict(r,nav=r[key]) for r in run['daily']]
    fills = Counter(r['side'] for r in run['journal'] if r['event']=='fill')
    return dict(stats=statistics(rows),fills=dict(fills),end_nav=rows[-1]['nav'],
                null_days=sum(r['nav'] is None for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('original','verified','exploratory','stress','valuation_stress','benchmark'):
        p.add_argument(field,type=Path)
    p.add_argument('--liquidity',type=Path)
    a = p.parse_args()
    runs = {field:json.loads(path.read_text()) for field,path in vars(a).items() if path is not None}
    base, valuation, stress = (runs[k] for k in ('exploratory','valuation_stress','stress'))
    if (base['journal']!=valuation['journal'] or base['selections']!=valuation['selections'] or
            any(x['cash']!=y['cash'] or x['positions']!=y['positions']
                for x,y in zip(base['daily'],valuation['daily'],strict=True))):
        raise ValueError('Evaluation-only changes altered orders, fills or cash')
    benchmark = runs['benchmark']['gross']
    dates = [r['day'] for r in base['daily']]
    if [r['day'] for r in benchmark['daily']]!=dates:
        raise ValueError('Benchmark calendar mismatch')
    metrics = {k:run_metrics(runs[k],'research_nav') for k in ('exploratory','stress','valuation_stress')}
    metrics['verified'] = run_metrics(runs['verified'],'nav')
    metrics['benchmark'] = run_metrics(benchmark,'nav')
    for k in ('exploratory','stress','valuation_stress'):
        if metrics[k]['stats'] and metrics['benchmark']['stats']:
            metrics[k]['cagr_spread_vs_kodex'] = metrics[k]['stats']['cagr']-metrics['benchmark']['stats']['cagr']
    result = dict(original=issue_history(runs['original']),verified=issue_history(runs['verified']),
                  metrics=metrics,selection_differences={
                     'valuation_only':compare_selections(base,valuation),
                     'stress':compare_selections(base,stress),
                     'verified_vs_exploratory':compare_selections(runs['verified'],base)},
                  valuation_only_invariance=True)
    if 'liquidity' in runs:
        result['metrics']['liquidity'] = run_metrics(runs['liquidity'],'research_nav')
        result['selection_differences']['liquidity'] = compare_selections(base,runs['liquidity'])
        if result['metrics']['liquidity']['stats'] and metrics['benchmark']['stats']:
            result['metrics']['liquidity']['cagr_spread_vs_kodex'] = (
                result['metrics']['liquidity']['stats']['cagr']-metrics['benchmark']['stats']['cagr'])
    print(json.dumps(result,indent=2,default=str))


if __name__=='__main__':
    main()
