"""Conditional M4 outcome comparisons on the frozen Stage 5 cache."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from candidate_study import open_db
from foundation import digest
from momentum_statistics import holm, stress
from momentum_study import CUT, benchmark_quotes, load_panel

REGIMES = ('trend','volatile','broad','rebound')
WIDTHS = (1,5,10,20)


def features(db, frame, quotes):
    days = [d for d, in db.execute('SELECT day FROM sessions WHERE day<=? ORDER BY day',(CUT,))]
    index = {d:i for i,d in enumerate(days)}
    panel = load_panel(db,days)
    rows = []
    for day, group in frame.groupby('day'):
        i = index[day]
        breadth = group.M4.ge(-.05).mean()
        market = [quotes.get(d,(None,None))[1] for d in days[max(0,i-60):i+1]]
        trend = volatile = rebound = None
        if len(market)==61 and all(market):
            trend = market[-1]>market[0]
            volatile = np.std(np.diff(np.log(market)),ddof=1)*np.sqrt(252)>.20
            rebound = market[-1]<market[0] and market[-1]>market[-21]
        for isin in group['isin']:
            bars = panel[isin]
            prices = [bars[j][6] for j in range(i-20,i+1)]
            rows.append((day,isin,prices[-1]/prices[0]-1,
                         np.std(np.diff(np.log(prices)),ddof=1)*np.sqrt(252),
                         trend,volatile,breadth>=.20,rebound,breadth))
    return pd.DataFrame(rows,columns=['day','isin','recent','volatility',*REGIMES,'breadth'])


def compare(top, rest, base):
    cells = ['cap_cell','turn_cell']
    matched = top.join(rest.groupby(cells).price.mean().rename('control'),on=cells)
    paired = matched.price-matched.control
    cash = top.economic.mean()
    return dict(top=top.price.mean(), spread=top.price.mean()-rest.price.mean(),
                matched=paired.mean(), etf=top.price.mean()-top.etf_price.mean(),
                economic=cash, economic_spread=cash-rest.economic.mean(),
                economic_etf=cash-top.etf_economic.mean(),
                lower=stress(top,base,-1)-stress(rest,base,1),
                upper=stress(top,base,1)-stress(rest,base,-1),
                count=len(top), observed=top.price.count(), matched_count=paired.count(),
                unresolved=int(top.status.str.contains('corporate_action|unverified_reference').sum()),
                halted_exit=int(top.status.str.contains('pit_exit|suspended').sum()),
                entry_missing=int(top.status.eq('entry_unavailable').sum()),
                cap_median=top.cap.median(), turnover_median=top.turnover.median(),
                volatility=top.volatility.mean())


def monthly_rows(data):
    rows, contributions = [], []
    for (day,horizon), group in data.groupby(['day','horizon']):
        s = group.sort_values(['M4','isin'],ascending=[False,True])
        base = s.price.mean()
        key = dict(day=day,phase='development' if day<'2022' else 'exploratory',horizon=horizon)
        regimes = {k:s[k].iloc[0] for k in REGIMES}
        for width in WIDTHS:
            n = math.ceil(len(s)*width/100)
            top,rest = s.iloc[:n],s.iloc[n:]
            rows.append(key|regimes|dict(test=f'top{width}')|compare(top,rest,base))
            for sign,subgroup in ((1,top),(-1,rest)):
                weights = sign*subgroup.price/max(1,subgroup.price.count())
                contributions.extend((key['phase'],horizon,width,day,t,v)
                                     for t,v in zip(subgroup['isin'],weights) if pd.notna(v))
        for i,indices in enumerate(np.array_split(np.arange(len(s)),10),1):
            q = s.iloc[indices]
            rows.append(key|dict(test=f'decile{i:02}')|compare(q,s.drop(q.index),base))
        if horizon!=5:
            m4 = s.iloc[:math.ceil(len(s)*.20)].sort_values(['recent','isin'])
            thirds = np.array_split(np.arange(len(m4)),3)
            for name,a,b in [('pullback',0,2),('middle',1,2),('hot',2,0)]:
                rows.append(key|dict(test=name)|compare(m4.iloc[thirds[a]],m4.iloc[thirds[b]],base))
    return pd.DataFrame(rows), pd.DataFrame(contributions,columns=['phase','horizon','width','day','isin','weight'])


def block_stats(values, state=None):
    x = np.asarray(values,dtype=float)
    n = len(x)
    if state is None:
        mask = np.isfinite(x)
        other = None
    else:
        mask = pd.Series(state).eq(True).to_numpy() & np.isfinite(x)
        other = pd.Series(state).eq(False).to_numpy() & np.isfinite(x)
    count = int(mask.sum())
    effect = x[mask].mean() if count else np.nan
    if other is not None:
        effect = effect-x[other].mean() if other.any() else np.nan
    result = dict(effect=effect,n=count,other_n=int(other.sum()) if other is not None else None,
                  low=None,high=None,p=None)
    if n<12 or count<(8 if other is not None else 12) or other is not None and other.sum()<8:
        return result
    rng = np.random.default_rng(20261106)
    starts = rng.integers(n,size=(5000,math.ceil(n/6),1))
    idx = ((starts+np.arange(6))%n).reshape(5000,-1)[:,:n]
    def samples(m):
        sample = np.where(m,x,np.nan)[idx]
        counts = np.isfinite(sample).sum(axis=1)
        return np.divide(np.nansum(sample,axis=1),counts,out=np.full(len(sample),np.nan),where=counts>0)
    draws = samples(mask)
    if other is not None:
        draws -= samples(other)
    draws = draws[np.isfinite(draws)]
    if len(draws)<4500:
        return result
    low,high = np.quantile(draws,[.025,.975])
    return result|dict(low=low,high=high,p=(1+(abs(draws-effect)>=abs(effect)).sum())/(1+len(draws)))


def analyze(data, output):
    monthly, contrib = monthly_rows(data)
    summary, tests, regimes, sensitivity = [],[],[],[]
    monthly['year'] = monthly.day.str[:4]
    for (phase,horizon,test), group in monthly.groupby(['phase','horizon','test']):
        group = group.sort_values('day')
        key = dict(phase=phase,horizon=int(horizon),test=test)
        metrics = group.select_dtypes('number').drop(columns='horizon')
        summary.append(key|metrics.mean().to_dict()|dict(months=len(group)))
        if test in {'top1','top5','top10','top20','pullback'}:
            tests.append(key|dict(metric='matched')|block_stats(group.matched))
            tests.append(key|dict(metric='spread')|block_stats(group.spread))
        if test=='top20':
            for regime in REGIMES:
                for state in (True,False):
                    g = group[group[regime].eq(state)]
                    regimes.append(key|dict(regime=regime,state=state,months=len(g))|
                                   g[['top','spread','matched','etf','economic_etf']].mean().to_dict())
                tests.append(key|dict(metric=regime+'_matched_delta')|
                             block_stats(group.matched,group[regime]))
        if test.startswith('top'):
            width = int(test[3:])
            c = contrib[(contrib.phase==phase)&(contrib.horizon==horizon)&(contrib.width==width)]
            names = c.groupby('isin').weight.sum().abs().nlargest(5).index
            spreads = []
            for day,g in data[(data.horizon==horizon)&data.day.isin(group.day)].groupby('day'):
                ranked = g.sort_values(['M4','isin'],ascending=[False,True])
                n = math.ceil(len(ranked)*width/100)
                clean = ranked[~ranked['isin'].isin(names)]
                spreads.append(clean.loc[clean.index.isin(ranked.index[:n]),'price'].mean()
                               -clean.loc[clean.index.isin(ranked.index[n:]),'price'].mean())
            sensitivity.append(key|dict(removed=list(names),without_five=float(np.nanmean(spreads)),
                without_year={y:group.loc[group.year!=y,'spread'].mean() for y in group.year.unique()}))
    for phase in monthly.phase.unique():
        holm([r for r in tests if r['phase']==phase])
    monthly.to_csv(output/'signal_monthly.csv',index=False)
    monthly.groupby(['phase','year','horizon','test'])[['top','spread','matched','etf']].mean().to_csv(output/'signal_annual.csv')
    for name, rows in [('signal_summary',summary),('signal_inference',tests),('regimes',regimes)]:
        pd.DataFrame(rows).to_csv(output/f'{name}.csv',index=False)
    (output/'signal_sensitivity.json').write_text(pd.DataFrame(sensitivity).to_json(orient='records',indent=2))


def verify(path, manifest):
    expected = dict(line.strip().split(maxsplit=1)[::-1] for line in manifest.read_text().splitlines())
    if digest(path)!=expected[path.name]:
        raise ValueError(f'Stale or corrupted cache: {path.name}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','cache','etf','secondary','output'):
        p.add_argument(name,type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    paths = [a.cache/f'{n}.csv.gz' for n in ('formations','outcomes')]
    for path in paths:
        verify(path,a.cache/'SHA256SUMS')
    frame, labels = [pd.read_csv(path,dtype={'day':str,'entry':str,'exit':str}) for path in paths]
    if (frame.day.max()>CUT or labels.exit.max()>CUT or (labels.loc[labels.day<'2022','exit']>='2022').any()):
        raise ValueError('Sealed period or phase boundary violated')
    quotes = benchmark_quotes(a.etf,a.secondary)
    with open_db(a.database) as db:
        extra = features(db,frame,quotes)
    extra.to_csv(a.output/'formation_conditions.csv.gz',index=False)
    data = labels.merge(frame,on=['day','isin'],validate='many_to_one').merge(
        extra,on=['day','isin'],validate='many_to_one')
    analyze(data,a.output)
    hashes = {str(f.name):digest(f) for f in [a.database,*paths,a.etf,a.secondary]}
    (a.output/'signal_inputs.json').write_text(json.dumps(hashes,indent=2))


if __name__=='__main__':
    main()
