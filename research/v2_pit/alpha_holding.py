"""Compare monthly rotation with 120-session single and staggered cohorts."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal as D
import gzip
import json
import multiprocessing as mp
from pathlib import Path

import pandas as pd

from alpha_conditions import verify
from candidate_study import open_db
from economic_account import FEE, SLIPPAGE, VALID
from execution_models import Execution
from execution_rights_diagnostic import EXTRA
from foundation import digest
from full_replay import load_config, replay
from momentum_study import CUT
from sizing_study import CAPS, INITIAL, PHASES, SEEDS, report, sessions, targets

COUNT = 10
MODES = ('fixed','staggered')
CONTEXT = None


class Lots:
    def __init__(self, days, *, holding=120):
        self.ordinal = {day:i for i,day in enumerate(days)}
        self.holding = holding
        self.positions = defaultdict(Counter)
        self.entitlements = {}
        self.closed = Counter()
        self.cursor = 0

    @staticmethod
    def allocate(lots, amount):
        total = sum(lots.values())
        if not total:
            raise ValueError('Share adjustment has no originating lot')
        assigned, seen = Counter(), 0
        for born, quantity in sorted(lots.items()):
            assigned[born] = amount*(seen+quantity)//total-amount*seen//total
            seen += quantity
        return assigned

    def sync(self, journal, *, require_mature=True):
        for row in journal[self.cursor:]:
            event = row['event']
            t = self.ordinal[row['day']]
            asset, qty = row['isin'],row['shares']
            if event=='fill' and qty>0:
                self.positions[asset][t] += qty
            elif event=='fill' and qty<0:
                need = -qty
                for born, quantity in sorted(self.positions[asset].items()):
                    if require_mature and t-born<self.holding:
                        break
                    sold = min(need,quantity)
                    self.positions[asset][born] -= sold
                    self.closed[t-born] += sold
                    need -= sold
                    if not need:
                        break
                if need:
                    raise ValueError('Sale exceeds matured lot quantities')
                self.positions[asset] = +self.positions[asset]
            elif event=='split':
                self.positions[asset] = +self.allocate(self.positions[asset],sum(self.positions[asset].values())+qty)
            elif event=='share_entitlement':
                key,_,target,quantity,_ = row['claim']
                self.entitlements[key] = (target,+self.allocate(self.positions[asset],quantity))
            elif event=='settlement' and row['remove'] in self.entitlements:
                target, additions = self.entitlements.pop(row['remove'])
                self.positions[target].update(additions)
            elif qty:
                raise ValueError(f'Unsupported lot share event {event}')
        self.cursor = len(journal)

    def eligible_to_sell(self, asset, t):
        return sum(q for born,q in self.positions[asset].items() if t+1-born>=self.holding)

    def mean_closed_days(self):
        return sum(t*q for t,q in self.closed.items())/sum(self.closed.values()) if self.closed else None


class Cohorts:
    def __init__(self, plan, mode, days, execution):
        self.plan,self.mode,self.execution = plan,mode,execution
        self.lots = Lots(days)
        self.formation = -1000
        self.budget = D(0)
        self.remaining = {}
        self.spent = Counter()

    def __call__(self, book, ordinal, day, next_day, bars, marks, last_prices):
        for e in book.log[self.lots.cursor:]:
            if e['event']=='fill' and e['side']=='BUY':
                t = e['isin']
                self.remaining[t] -= e['shares']
                self.spent[t] += D(e['shares']*e['price'])+e['fee']+e['slippage']
        self.lots.sync(book.log)
        balances = {t:sum(q.values()) for t,q in self.lots.positions.items() if q}
        if balances!=dict(book.shares):
            raise ValueError('Cohort lots do not match holdings')
        if day in self.plan and (self.mode=='staggered' or
                ordinal-self.formation>=120 and not balances and not self.lots.entitlements):
            equity = book.cash+sum(v for _,_,_,v in book.claims.values())
            marked = Counter(book.shares)
            for _,asset,qty,_ in book.claims.values():
                if qty:
                    marked[asset] += qty
            equity += sum(qty*marks.get(t,last_prices.get(t,0)) for t,qty in marked.items())
            self.budget = max(equity,D(0))/(COUNT*(6 if self.mode=='staggered' else 1))
            self.formation = ordinal
            self.remaining = {t:int(self.budget/bars[t][1]) for t in self.plan[day]
                              if t in bars and bars[t][2]==VALID}
            self.spent.clear()
            book.post(day,'cohort_targets',equity=equity,target_budget=self.budget,targets=self.remaining.copy())
        selling = set()
        for t in sorted(balances):
            quantity = self.lots.eligible_to_sell(t,ordinal)
            if quantity and t in marks:
                book.queue(day,t,'SELL',1,quantity)
                selling.add(t)
        if 0<=ordinal-self.formation<5:
            for t, qty in self.remaining.items():
                if qty<=0 or t in selling or t not in bars or bars[t][2]!=VALID:
                    continue
                limit = self.execution.limit(next_day,bars[t][1])
                possible = int(max(D(0),self.budget-self.spent[t])/(limit*(1+FEE+SLIPPAGE)))
                if possible:
                    book.queue(day,t,'BUY',limit,min(possible,qty))


def load_tape(path):
    with gzip.open(path,'rt') as stream:
        return json.load(stream)


def diagnostics(result, run, lots):
    journal = run['journal']
    orders = [e for e in journal if e['event']=='order_sized_at_close' and e['quantity']]
    fills = [e for e in journal if e['event']=='fill']
    result['closed_mean_days_share_weighted'] = lots.mean_closed_days()
    result['closed_shares'] = sum(lots.closed.values())
    result['unfilled_rate'] = 1-len(fills)/len(orders) if orders else None
    result['distinct_sell_days'] = len({e['day'] for e in fills if e['side']=='SELL'})
    result['sell_notional_to_initial_per_year'] = sum(
        -e['shares']*e['price'] for e in fills if e['side']=='SELL')/INITIAL*252/len(run['daily'])
    result['nav_issues'] = {e['key']:e for e in run.get('exceptions',[])}


def worker(task):
    phase,cap,seed,mode = task
    a, dates, plans, refs = CONTEXT
    days = dates[phase]
    key = f'{phase}-{cap}-{seed or "M4"}-{mode}'
    if mode=='monthly':
        path = a.stage6/f'{phase}-{COUNT}-{cap}-{seed or "M4"}.json.gz'
        verify(path,a.stage6/'SHA256SUMS')
        run = load_tape(path)
        lots = Lots(days)
        lots.sync(run['journal'],require_mature=False)
        # Cached tapes contain decimal strings. Use the original verified summary.
        summary = refs[phase,cap,'monthly'][seed]
    else:
        execution = Execution('E2')
        policy = Cohorts(plans[seed],mode,days,execution)
        cfg = load_config()
        cfg['execution']['cma_rate'] = 0
        with open_db(a.database) as db:
            run = replay(db,{},D(cap),cfg,mode='exploratory',end=days[-3],execution=execution,
                         additional_actions=EXTRA['B']+EXTRA['C'],start=days[0],initial=INITIAL,
                         session_days=days,rebalance=policy)
        policy.lots.sync(run['journal'])
        lots = policy.lots
        summary = report(run,refs[phase,cap,'etf'])
        with gzip.open(a.output/f'{key}.json.gz','wt') as stream:
            json.dump(run,stream,default=str,separators=(',',':'))
    diagnostics(summary,run,lots)
    return key,summary


def main():
    global CONTEXT
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','stage5','stage6','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--workers',type=int,default=8)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    formation = a.stage5/'formations.csv.gz'
    for path,root in [(formation,a.stage5),(a.stage6/'runs.jsonl',a.stage6),(a.stage6/'benchmark.json',a.stage6)]:
        verify(path,root/'SHA256SUMS')
    frame = pd.read_csv(formation,dtype={'day':str})
    if frame.day.max()>CUT or frame[['cap_cell','turn_cell']].isna().any().any():
        raise ValueError('Unexpected formation input')
    with open_db(a.database) as db:
        dates = {p:sessions(db,*limits) for p,limits in PHASES.items()}
    stored = dict(map(json.loads,(a.stage6/'runs.jsonl').open()))
    refs = {}
    for phase in PHASES:
        for cap in CAPS:
            path = a.stage6/f'{phase}-ETF-{cap}.json.gz'
            verify(path,a.stage6/'SHA256SUMS')
            refs[phase,cap,'etf'] = load_tape(path)
            refs[phase,cap,'monthly'] = {s:stored[f'{phase}-{COUNT}-{cap}-{s or "M4"}']
                                          for s in (None,*SEEDS)}
    plans = {s:targets(frame,COUNT,s) for s in (None,*SEEDS)}
    CONTEXT = a,dates,plans,refs
    tasks = [(p,c,s,m) for s in (None,*SEEDS) for m in ('monthly',*MODES) for p in PHASES for c in CAPS]
    with mp.get_context('fork').Pool(a.workers) as pool, (a.output/'holding_runs.jsonl').open('w') as stream:
        for key,result in pool.imap_unordered(worker,tasks):
            stream.write(json.dumps([key,result],default=str)+'\n')
            stream.flush()
    hashes = {p.name:digest(p) for p in (a.database,formation,a.stage6/'SHA256SUMS',
                                       Path(__file__).with_name('alpha_protocol.md'))}
    (a.output/'holding_inputs.json').write_text(json.dumps(hashes,indent=2))


if __name__=='__main__':
    main()
