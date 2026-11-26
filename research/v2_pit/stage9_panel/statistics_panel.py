"""Pre-registered six-contrast, monthly-block × issuer bootstrap for 120-session returns.

Inputs are the already gated long-form panel and its complete official formation calendar.
Returns are decimal price returns. No file is opened by import or by run_statistics().
"""
import argparse
from collections import defaultdict
import csv
from datetime import date
import gzip
import json
import math
import re
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from momentum_statistics import holm

SIGNALS = ('F2', 'F3')
CONTRASTS = ('top-remainder', 'C-A', 'C-B')
SIDES = ('target', 'comparison')
PHASE = {'development': (2017, 2021, 36), 'validation': (2022, 2023, 12)}
DRAWS = 5000
MIN_VALID = 4500
SEED = 20261126


def calendar_spec(calendar, phase):
    first, last, _ = PHASE[phase]
    expected = [f'{year:04d}{month:02d}' for year in range(first, last+1) for month in range(1, 13)]
    days = [row['formation'] for row in calendar]
    if [day[:6] for day in days] != expected:
        raise ValueError('Pass the entire ordered official calendar, including censored and missing months')
    usable = set()
    for row in calendar:
        day = row['formation']
        if date.fromisoformat(day).strftime('%Y%m%d') != day:
            raise ValueError('Unexpected formation format')
        end = row['exits']['120']
        if end is not None:
            entry = row['entry']
            if not all(isinstance(d,str) and date.fromisoformat(d).strftime('%Y%m%d') == d for d in (entry,end)):
                raise ValueError('Unexpected entry/exit date format')
            if not day < entry < end <= f'{last}1231':
                raise ValueError('Return extends outside the phase or has an invalid entry')
            usable.add(day)
    return days, usable


def assignments(rows, usable):
    issuers = {}
    securities = {}
    groups = defaultdict(dict)
    price = {}
    for row in rows:
        day, isin = row['formation'],row['isin']
        signal, contrast, side = row['signal'],row['contrast'],row['side']
        if day not in usable or not isin or signal not in SIGNALS or contrast not in CONTRASTS or side not in SIDES:
            raise ValueError('Unrecognized or phase-censored 120-session observation')
        corp = row['corp_code']
        if not re.fullmatch(r'[0-9]{8}',corp):
            raise ValueError('Missing validated historical DART corporate identifier')
        if issuers.setdefault((day,isin),corp)!=corp or securities.setdefault((day,corp),isin)!=isin:
            raise ValueError('Conflicting same-day issuer/security assignment')
        val = None if row['price'] in ('',None) else float(row['price'])
        if val is not None and (not math.isfinite(val) or val < -1):
            raise ValueError('Invalid decimal price return')
        if 'status' in row and ((row['status']=='observed') != (val is not None) or not row['status']):
            raise ValueError('Outcome status disagrees with return availability')
        if (day,isin) in price and price[day,isin] != val:
            raise ValueError('Conflicting returns for one issuer and formation')
        price[day,isin] = val
        arm = groups[signal,contrast,day]
        if isin in arm:
            raise ValueError('Duplicate security or overlapping sides within a contrast')
        arm[isin] = side
    return groups, price, issuers


def block_counts(n, block, rng):
    starts = rng.integers(n, size=(DRAWS, math.ceil(n/block), 1))
    index = ((starts+np.arange(block)) % n).reshape(DRAWS,-1)[:, :n]
    weights = np.zeros((DRAWS,n),dtype=np.int16)
    np.add.at(weights,(np.arange(DRAWS)[:,None],index),1)
    return weights


def contrast_arrays(signal, contrast, days, usable, names, groups, price, issuers):
    column = {isin:j for j,isin in enumerate(names)}
    result = np.zeros((2,len(days),len(names)),dtype=float)
    observed = np.zeros_like(result)
    valid = np.zeros(len(days),dtype=bool)
    monthly = []
    for i,day in enumerate(days):
        arm = groups.get((signal,contrast,day),{})
        assigned = {side:{s for s,t in arm.items() if t==side} for side in SIDES}
        counts = [len(assigned[side]) for side in SIDES]
        if contrast != 'top-remainder':
            ca = groups.get((signal,'C-A',day),{})
            cb = groups.get((signal,'C-B',day),{})
            c1 = {s for s,t in ca.items() if t=='target'}
            c2 = {s for s,t in cb.items() if t=='target'}
            a = set(ca)-c1
            b = set(cb)-c2
            if c1!=c2 or a & b:
                raise ValueError('Inconsistent C group or overlapping A and B')
            counts = [len(a),len(b),len(c1)]
        side_means = []
        obs_counts = []
        for j,side in enumerate(SIDES):
            for isin in assigned[side]:
                y = price[day,isin]
                if y is not None:
                    corporate_column = column[issuers[day,isin]]
                    result[j,i,corporate_column] = y
                    observed[j,i,corporate_column] = 1
            count = int(observed[j,i].sum())
            obs_counts.append(count)
            side_means.append(result[j,i].sum()/count if count else None)
        if day not in usable:
            reason = 'phase_censored'
        elif min(counts)<5:
            reason = 'insufficient_preformed_group'
        elif min(obs_counts)==0:
            reason = 'no_observed_comparison'
        else:
            reason = 'included'
            valid[i] = True
        monthly.append(dict(formation=day,status=reason,assigned=[len(assigned[s]) for s in SIDES],
                            observed=obs_counts,effect=float(side_means[0]-side_means[1]) if valid[i] else None))
    return result,observed,valid,monthly


def bootstrap_summary(draw_stats, point):
    good = draw_stats[np.isfinite(draw_stats)]
    n = len(good)
    out = dict(valid_draws=n,requested_draws=DRAWS,ci95=None,p=None)
    if n>=MIN_VALID:
        lo,hi = np.quantile(good,[.025,.975])
        count = np.count_nonzero(np.abs(good-point)>=abs(point))
        out.update(ci95=[float(lo),float(hi)],p=float((1+count)/(1+n)))
    return out


def sample_means(month_effects,block_weights):
    # Invalid original months have already been masked out of block_weights.
    # A selected originally-valid month losing either observed group voids this replicate.
    bad = ~np.isfinite(month_effects)
    count = block_weights.sum(axis=1)
    possible = (count>0) & ~np.any((block_weights>0) & bad,axis=1)
    sums = (np.where(bad,0.,month_effects)*block_weights).sum(axis=1)
    return np.divide(sums,count,out=np.full(len(count),np.nan),where=possible)


def simulations(result,observed,valid,issuer_weights,blocks,point):
    n = len(issuer_weights)
    main = np.full(n,np.nan)
    longer = np.full(n,np.nan)
    # Chunking caps temporary arrays; classification never changes after formation.
    for start in range(0,n,128):
        sl = slice(start,min(start+128,n))
        w = issuer_weights[sl]
        group_means = []
        for j in (0,1):
            totals = np.einsum('bi,mi->bm',w,result[j],optimize=False)
            counts = np.einsum('bi,mi->bm',w,observed[j],optimize=False)
            group_means.append(np.divide(totals,counts,out=np.full_like(totals,np.nan),where=counts>0))
        effects = group_means[0]-group_means[1]
        main[sl] = sample_means(effects,blocks[6][sl]*valid)
        longer[sl] = sample_means(effects,blocks[12][sl]*valid)
    monthly = []
    for j in (0,1):
        num = result[j].sum(axis=1)
        den = observed[j].sum(axis=1)
        monthly.append(np.divide(num,den,out=np.full_like(num,np.nan),where=den>0))
    time_only = sample_means((monthly[0]-monthly[1])[None,:],blocks[6]*valid)
    return {k:bootstrap_summary(a,point) for k,a in (
        ('issuer_and_6_month',main),('issuer_and_12_month',longer),('6_month_only',time_only))}


def run_statistics(records, calendar, phase='development'):
    days,usable = calendar_spec(calendar,phase)
    groups,price,issuers = assignments(records,usable)
    names = sorted(set(issuers.values()))
    issuer_seed,short_seed,long_seed = np.random.SeedSequence(SEED).spawn(3)
    # One multiplicity per issuer and replicate, shared across all months and contrasts.
    issuer_weights = (np.random.default_rng(issuer_seed).multinomial(
        len(names),np.full(len(names),1/len(names)),size=DRAWS).astype(float) if names else None)
    blocks = {n:block_counts(len(days),n,np.random.default_rng(seed)) for n,seed in ((6,short_seed),(12,long_seed))}
    contrasts = []
    for s in SIGNALS:
        for c in CONTRASTS:
            result,observed,valid,monthly = contrast_arrays(s,c,days,usable,names,groups,price,issuers)
            effects = [r['effect'] for r in monthly if r['status']=='included']
            point = math.fsum(effects)/len(effects) if effects else None
            boot = {}
            status = 'insufficient_months'
            if len(effects)>=PHASE[phase][2]:
                boot = simulations(result,observed,valid,issuer_weights,blocks,point)
                status = 'tested' if boot['issuer_and_6_month']['p'] is not None else 'insufficient_valid_replicates'
            years = {}
            for year in range(PHASE[phase][0],PHASE[phase][1]+1):
                y = [r['effect'] for r in monthly if r['formation'].startswith(str(year)) and r['effect'] is not None]
                years[str(year)] = {'months':len(y),'effect':math.fsum(y)/len(y) if y else None}
            contrasts.append({'signal':s,'contrast':c,'valid_months':len(effects),'all_calendar_months':len(days),
                'effect':point,'status':status,'annual':years,'monthly':monthly,
                'issuers_observed_in_included_months':int(np.count_nonzero(observed[:,valid,:].any(axis=(0,1)))),
                'bootstrap':boot,'p':boot['issuer_and_6_month']['p'] if status=='tested' else 1.0})
    holm(contrasts)
    return {'phase':phase,'horizon_sessions':120,'metric':'split-adjusted price return difference, equal valid months',
            'family_size':6,'issuer_unit':'historical DART corporation code','unique_assigned_issuers':len(names),
            'unique_assigned_isins':len({isin for _,isin in issuers}),
            'seed':SEED,'draws':DRAWS,'min_valid_draws':MIN_VALID,'minimum_valid_months':PHASE[phase][2],
            'monthly_counts_order':list(SIDES),'untested_holm_input':1.0,'contrasts':contrasts}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('long_csv',type=Path)
    p.add_argument('calendar',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--phase',choices=PHASE,default='development')
    args=p.parse_args()
    opener = gzip.open if args.long_csv.suffix=='.gz' else open
    with opener(args.long_csv,'rt',encoding='utf-8',newline='') as f:
        result=run_statistics(csv.DictReader(f),json.loads(args.calendar.read_text()),args.phase)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
