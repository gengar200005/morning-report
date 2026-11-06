"""Measure dated public earnings releases on the Stage 5 outcome model."""
import argparse
from bisect import bisect_right
import json
import math
from pathlib import Path

import pandas as pd

from candidate_study import open_db
from foundation import digest
from momentum_study import (CUT, benchmark_quotes, eligible, formation_liquidity,
                            load_actions, load_panel, outcome)

HORIZONS = (20,60,120)
PLANNED = {('005930','2021Q1'),('066570','2021Q1'),('000660','2021Q1'),
           ('005930','2023Q1'),('066570','2023Q1'),('000660','2023Q1'),
           ('117930','2016Q3'),('002000','2018Q3')}


def metrics(amounts):
    rev, op, previous_rev, previous_op = amounts
    if min(rev,previous_rev)<=0:
        raise ValueError('Quarter revenue must be positive')
    return dict(margin=op/rev,previous_margin=previous_op/previous_rev,
                margin_change=op/rev-previous_op/previous_rev,revenue_growth=rev/previous_rev-1,
                operating_growth=op/previous_op-1 if previous_op>0 else None)


def entry_window(days, released, horizon):
    entry = bisect_right(days,released)
    end = entry+horizon-1
    boundary = '20211231' if released<'20220101' else CUT
    return (entry,end) if end<len(days) and days[end]<=boundary else None


def analyze(db, events, archives, quotes, distributions):
    if {(e['code'],e['quarter']) for e in events}!=PLANNED or len(events)!=len(PLANNED):
        raise ValueError('Unexpected pilot sample')
    days = [r[0] for r in db.execute('SELECT day FROM sessions WHERE day<=? ORDER BY day',(CUT,))]
    panel = load_panel(db,days)
    actions, exits = load_actions(db,days)
    observed, audit = [],[]
    for event in events:
        code = event['code']
        record = dict(event)
        history = db.execute('SELECT min(day),max(day),isin FROM membership WHERE code=? AND common=1 AND day<=? GROUP BY isin',
                             (code,CUT)).fetchall()
        record['pit_identity_history'] = history
        record['exit_history'] = db.execute('SELECT delisted,category FROM exit_audit WHERE code=? AND delisted<=?',
                                            (code,CUT)).fetchall()
        audit.append(record)
        if 'amounts' not in event:
            continue
        day = event['released']
        if not '20170101'<=day<=CUT or event['basis']!='consolidated_quarter_krw':
            raise ValueError('Unapproved release timing or scope')
        i = bisect_right(days,day)-1
        universe,_ = eligible(panel,i,formation_liquidity(db,archives,days[i]))
        u = pd.DataFrame(universe,columns=['isin','code','cap','turnover','M1','M2','M3','M4','distance','slope'])
        u = u.sort_values(['M4','isin'],ascending=[False,True]).reset_index(drop=True)
        u['cap_cell'] = (u.cap.rank(pct=True,method='first')*3).apply(math.ceil)
        u['turn_cell'] = (u.turnover.rank(pct=True,method='first')*3).apply(math.ceil)
        s = u[u.code==code]
        if len(s)!=1 or s.iloc[0]['isin']!=event['isin']:
            record['evaluation_status'] = 'NO_ELIGIBLE_IDENTITY_OR_HISTORY'
            continue
        s = s.iloc[0]
        peers = u[(u.cap_cell==s.cap_cell)&(u.turn_cell==s.turn_cell)&(u['isin']!=s['isin'])]
        values = metrics(event['amounts'])
        strong = s.name<math.ceil(len(u)*.2)
        group = {(True,False):'A',(False,True):'B',(True,True):'C',(False,False):'D'}[
            strong,values['margin_change']>0]
        record.update(values,formation=days[i],group=group,m4=float(s.M4),rank=int(s.name)+1,
                      eligible=len(u),peer_count=len(peers),evaluation_status='DATED_RELEASE_PILOT_ONLY')
        for horizon in HORIZONS:
            window = entry_window(days,day,horizon)
            if window is None:
                observed.append(dict(code=code,quarter=event['quarter'],group=group,horizon=horizon,status='PHASE_CENSORED'))
                continue
            entry,end = window
            def label(isin):
                return outcome(panel[isin],actions[isin],exits[isin],entry,[end])[end]
            price,economic,status,_ = label(s['isin'])
            peer_returns = [label(isin)[0] for isin in peers['isin']]
            available = [v for v in peer_returns if v is not None]
            peer = sum(available)/len(available) if available else None
            op = quotes.get(days[entry],(None,None))[0]
            cl = quotes.get(days[end],(None,None))[1]
            etf = cl/op-1 if op and cl else None
            etf_economic = etf+sum(distributions.get(d,0) for d in days[entry+1:end+1])/op if etf is not None else None
            observed.append(dict(code=code,quarter=event['quarter'],group=group,horizon=horizon,
                entry=days[entry],end=days[end],price=price,economic=economic,status=status,etf=etf,
                etf_economic=etf_economic,matched=peer,peer_count=len(peers),peer_observed=len(available),
                etf_excess=price-etf if price is not None and etf is not None else None,
                matched_excess=price-peer if price is not None and peer is not None else None))
    return observed,audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('database','archives','events','etf','secondary','distributions','output'):
        p.add_argument(n,type=Path)
    a = p.parse_args()
    quotes = benchmark_quotes(a.etf,a.secondary)
    payouts = {d:float(v[3]) for d,v in json.loads(a.distributions.read_text())['issuer_events'].items() if d<=CUT}
    with open_db(a.database) as db:
        results,audit = analyze(db,json.loads(a.events.read_text()),a.archives,quotes,payouts)
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'identity_and_events.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    pd.DataFrame(results).to_csv(a.output/'event_outcomes.csv',index=False)
    (a.output/'inputs.json').write_text(json.dumps({n:digest(getattr(a,n)) for n in
        ('database','events','etf','secondary','distributions')},indent=2))


if __name__=='__main__':
    main()
