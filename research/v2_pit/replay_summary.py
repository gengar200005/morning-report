"""Publish account diagnostics while keeping unresolved path returns unset."""
import argparse
from collections import Counter
from decimal import Decimal as D
import json
from pathlib import Path
from statistics import mean, stdev

from economic_account import metrics


def statistics(rows):
    if len(rows)<2 or any(x['nav'] is None for x in rows):
        return None
    rows = [dict(r,nav=D(r['nav'])) for r in rows]
    moves = [float(b['nav']/a['nav']-1) for a,b in zip(rows,rows[1:])]
    return dict(**metrics(rows),total_return=float(rows[-1]['nav']/rows[0]['nav']-1),
                annualized_volatility=stdev(moves)*252**.5 if len(moves)>1 else None,
                mean_market_exposure=mean(float(D(r['stock'])/r['nav']) for r in rows),
                mean_cash_weight=mean(float(D(r['cash'])/r['nav']) for r in rows))


def summarize(path):
    rows, journal = path['daily'],path['journal']
    windows = []
    for r in rows:
        if r['nav'] is None:
            if windows and windows[-1][1]==previous:
                windows[-1][1] = r['day']
            else:
                windows.append([r['day'],r['day']])
        previous = r['day']
    fills = [r for r in journal if r['event']=='fill']
    annual = {}
    for year in sorted({r['day'][:4] for r in rows}):
        idx = [i for i,r in enumerate(rows) if r['day'].startswith(year)]
        annual[year] = statistics(rows[max(idx[0]-1,0):idx[-1]+1])
    return dict(days=len(rows),unresolved_days=sum(r['nav'] is None for r in rows),
                unresolved_windows=windows,whole_period=statistics(rows),annual=annual,
                fills=dict(Counter(r['side'] for r in fills)),events=dict(Counter(r['event'] for r in journal)),
                distinct_bought=len({r['isin'] for r in fills if r['side']=='BUY'}),
                any_position_sessions=sum(bool(r['positions']) for r in rows),
                modeled_costs={k:str(sum((D(r[k]) for r in fills),D(0)))
                               for k in ('fee','slippage','sell_tax')},
                cash_interest=str(sum((D(r['cash']) for r in journal if r['event']=='cash_interest'),D(0))),
                final_nav=rows[-1]['nav'],counts=path.get('counts'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stock','strict','bonus','benchmark'):
        parser.add_argument(name,type=Path)
    args = parser.parse_args()
    paths = {name:json.loads(getattr(args,name).read_text()) for name in ('stock','strict','bonus','benchmark')}
    etf = paths.pop('benchmark')
    results = {name:summarize(path) for name,path in paths.items()}
    for name in ('gross','retail_withholding'):
        results['etf_'+name] = summarize(etf[name])
    prefix_stock,prefix_etf = [],[]
    for s,b in zip(paths['stock']['daily'],etf['gross']['daily'],strict=True):
        if s['day']!=b['day']:
            raise ValueError('Date alignment mismatch')
        if s['nav'] is None or b['nav'] is None:
            break
        prefix_stock.append(s)
        prefix_etf.append(b)
    results['observed_joint_prefix'] = dict(first=prefix_stock[0]['day'],last=prefix_stock[-1]['day'],
                                          days=len(prefix_stock),stock=statistics(prefix_stock),etf=statistics(prefix_etf))
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
