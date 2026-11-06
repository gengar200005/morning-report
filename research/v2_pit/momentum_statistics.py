"""Date-level signal diagnostics and dependence-aware inference."""
import argparse
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from momentum_study import SIGNALS


def inference(values, block=6, draws=5000):
    values = np.asarray(values.dropna())
    n = len(values)
    if n<2*block:
        return dict(n=n, low=None, high=None, p=None)
    rng = np.random.default_rng(20261106)
    start = rng.integers(n,size=(draws,math.ceil(n/block),1))
    indices = ((start+np.arange(block))%n).reshape(draws,-1)[:,:n]
    sims = values[indices].mean(axis=1)
    avg = values.mean()
    low, high = np.quantile(sims,[.025,.975])
    p = (1+(np.abs(sims-avg)>=abs(avg)).sum())/(draws+1)
    return dict(n=n,low=low,high=high,p=p)


def holm(rows):
    tested = sorted((r for r in rows if r['p'] is not None),key=lambda r:r['p'])
    largest = 0
    for i,row in enumerate(tested):
        largest = max(largest,min(1,(len(rows)-i)*row['p']))
        row['holm_p'] = largest


def stress(group, base, sign):
    fill = max(-1,base+sign*.20) if np.isfinite(base) else np.nan
    return group.price.where(group.price.notna()|group.status.eq('entry_unavailable'),fill).mean()


def summarize(group, signal):
    s = group.sort_values([signal,'isin'],ascending=[False,True])
    n = len(s)
    q = math.ceil(n*.2)
    decile = s.iloc[:math.ceil(n*.1)]
    if signal=='MA_gate':
        top = s[s.MA_gate]
        rest = s[~s.MA_gate]
    else:
        top, rest = s.iloc[:q], s.iloc[q:]
    bottom = s.iloc[-q:]
    mid = s.iloc[q:-q]
    base = s.price.mean()
    cell = ['cap_cell','turn_cell']
    cell_mean = rest.groupby(cell).price.mean().rename('control')
    matched = top.join(cell_mean,on=cell)
    paired = matched.price-matched.control
    high_turn = s[s.turn_cell>=1]
    high_top = top[top.turn_cell>=1]
    high_rest = rest[rest.turn_cell>=1]
    px = top.price
    etf = s.etf_price.iloc[0]
    econ = s.etf_economic.iloc[0]
    observed = s.dropna(subset=['price'])
    contributions = pd.concat([top.set_index('isin').price/max(1,px.count()),
                               -rest.set_index('isin').price/max(1,rest.price.count())]).dropna()
    return dict(
        count=n, observed=s.price.count(), top_count=len(top), top_observed=px.count(),
        top10=decile.price.mean() if signal!='MA_gate' else np.nan,
        top_mean=px.mean(), top_median=px.dropna().median(), middle=mid.price.mean(), bottom=bottom.price.mean(),
        top_bottom=px.mean()-bottom.price.mean(), top_universe=px.mean()-base,
        spread=px.mean()-rest.price.mean(), matched=paired.mean(), matched_count=paired.count(),
        etf=etf, etf_excess=px.mean()-etf, economic=top.economic.mean(),
        economic_spread=top.economic.mean()-rest.economic.mean(),
        economic_etf_excess=top.economic.mean()-econ,
        win_etf=(px.dropna()>etf).mean() if pd.notna(etf) else np.nan,
        win_universe=(px.dropna()>base).mean(), win_matched=(paired.dropna()>0).mean(),
        ic=observed[signal].astype(float).corr(observed.price,method='spearman')
        if observed[signal].nunique()>1 and observed.price.nunique()>1 else np.nan,
        high_turn_spread=high_top.price.mean()-high_rest.price.mean(),
        high_turn_count=len(high_turn),
        lower_stress=stress(top,base,-1)-stress(rest,base,1),
        upper_stress=stress(top,base,1)-stress(rest,base,-1),
        missing_ca=int(s.status.str.contains('corporate_action|unverified_reference').sum()),
        missing_exit=int(s.status.str.contains('pit_exit|suspended').sum()),
        missing_entry=int(s.status.eq('entry_unavailable').sum()),
        missing_top_ca=int(top.status.str.contains('corporate_action|unverified_reference').sum()),
        missing_top_exit=int(top.status.str.contains('pit_exit|suspended').sum()),
        missing_top_entry=int(top.status.eq('entry_unavailable').sum()),
    ), contributions


def analyze(cohort, labels, output):
    data = labels.merge(cohort,on=['day','isin'],validate='many_to_one')
    data['MA_gate'] = (data.ma_distance>0)&(data.ma_slope>0)
    all_rows, names = [], []
    for (day,horizon), group in data.groupby(['day','horizon']):
        for signal in (*SIGNALS,'MA_gate'):
            values, contributions = summarize(group,signal)
            phase = 'development' if day<'2022' else 'validation'
            key = dict(day=day, horizon=horizon, signal=signal, phase=phase, regime=group.regime.iloc[0])
            all_rows.append(key|values)
            names.extend((phase,signal,horizon,day,isin,value) for isin,value in contributions.items())
    months = pd.DataFrame(all_rows)
    months['year'] = months.day.str[:4]
    summary, sensitivity = [], []
    contribution = pd.DataFrame(names,columns=['phase','signal','horizon','day','isin','contribution'])
    for (phase,signal,horizon), group in months.groupby(['phase','signal','horizon']):
        stats = inference(group.spread)
        summary.append(dict(phase=phase,signal=signal,horizon=horizon)|stats|
                       group.select_dtypes('number').drop(columns='horizon').mean().to_dict())
        mask = (contribution.phase==phase)&(contribution.signal==signal)&(contribution.horizon==horizon)
        subset = contribution.loc[mask]
        five = subset.groupby('isin').contribution.sum().abs().nlargest(5).index
        removed = []
        for day, g in data[(data.horizon==horizon)&data.day.isin(group.day)].groupby('day'):
            ranked = g.sort_values([signal,'isin'],ascending=[False,True])
            if signal=='MA_gate':
                selected = ranked.MA_gate
            else:
                selected = np.arange(len(ranked))<math.ceil(len(ranked)*.2)
            top = ranked[selected & ~ranked['isin'].isin(five)]
            rest = ranked[~selected & ~ranked['isin'].isin(five)]
            removed.append(top.price.mean()-rest.price.mean())
        leave_year = {year:group[group.year!=year].spread.mean() for year in group.year.unique()}
        sensitivity.append(dict(phase=phase,signal=signal,horizon=horizon,removed_five=list(five),
                                removed_five_spread=np.nanmean(removed), leave_year=leave_year))
    for phase in months.phase.unique():
        holm([r for r in summary if r['phase']==phase and r['signal'] in SIGNALS])
    pairs = []
    for (phase,horizon), group in months.groupby(['phase','horizon']):
        for a,b,metric in [('M2','M3','spread'),('MA_gate','M1','top_mean')]:
            pivot = group.pivot(index='day',columns='signal',values=metric)
            delta = pivot[a]-pivot[b]
            pairs.append(dict(phase=phase,horizon=horizon,pair=f'{a}-{b}',delta=delta.mean())|inference(delta))
    months.to_csv(output/'monthly.csv',index=False)
    result = pd.DataFrame(summary)
    result.to_csv(output/'summary.csv',index=False)
    pd.DataFrame(pairs).to_csv(output/'paired.csv',index=False)
    for subgroup in ('year','regime'):
        group = months.groupby(['phase','signal','horizon',subgroup])
        group[['top_mean','spread','matched','etf_excess','ic']].mean().join(
            group.size().rename('months')).to_csv(output/f'{subgroup}.csv')
    (output/'sensitivity.json').write_text(pd.DataFrame(sensitivity).to_json(orient='records',indent=2))
    pd.DataFrame(data.groupby(['horizon','status']).size(),columns=['count']).to_csv(output/'coverage.csv')
    plot(result,output)


def plot(result, output):
    fig, axes = plt.subplots(2,2,figsize=(11,7),sharex=True,sharey='row')
    for col,phase in enumerate(('development','validation')):
        for row,(key,label) in enumerate((('spread','Top 20% minus other stocks'),('etf_excess','Top 20% minus KODEX 200'))):
            ax = axes[row,col]
            for signal in SIGNALS:
                rows = result[(result.phase==phase)&(result.signal==signal)]
                ax.plot(rows.horizon,100*rows[key],marker='o',label=signal)
            ax.axhline(0,color='gray',linewidth=1)
            ax.set(title=f'{phase.title()} | {label}',ylabel='Percentage points',
                   xticks=[5,20,60,120],xlabel='Trading sessions')
    axes[0,0].legend(ncol=5,loc='best',fontsize=8)
    fig.tight_layout()
    fig.savefig(output/'Momentum_Stage5_Forward_Returns.png',dpi=150)
    plt.close(fig)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    folder = parser.parse_args().output
    analyze(pd.read_csv(folder/'formations.csv.gz',dtype={'day':str,'code':str}),
            pd.read_csv(folder/'outcomes.csv.gz',dtype={'day':str}),folder)
