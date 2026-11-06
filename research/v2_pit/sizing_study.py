"""Replay Stage 5 M4 ranks in settlement-aware accounts."""
import argparse
from collections import Counter
from decimal import Decimal as D
import gzip
import json
import multiprocessing as mp
from pathlib import Path
import random
from statistics import mean

import pandas as pd

from candidate_study import open_db
from economic_account import Account, FEE, SLIPPAGE, VALID, reconcile_journal
from execution_models import Execution
from execution_rights_diagnostic import EXTRA
from foundation import digest
from full_replay import load_config, replay
from momentum_study import CUT, benchmark_quotes
from replay_summary import statistics, summarize

INITIAL = 10_000_000
SIZES = (1,5,10)
SEEDS = (1101,1102,1103,1104,1105)
CAPS = ('.01','.001')
PHASES = {'development':('20170201','20211230'), 'validation':('20220103','20231228'),
          'continuous':('20170201','20231228')}
CONTEXT = None


def targets(frame, count, seed=None):
    rng = random.Random(seed)
    chosen = {}
    for day, group in frame.groupby('day', sort=True):
        ranked = group.sort_values(['M4','isin'],ascending=[False,True])
        top = list(ranked[['isin','cap_cell','turn_cell']].itertuples(index=False,name=None))[:count]
        if seed is None:
            chosen[day] = tuple(row[0] for row in top)
            continue
        remaining = list(ranked[['isin','cap_cell','turn_cell']].itertuples(index=False,name=None))[count:]
        matched = []
        for _, cap, turn in top:
            if not remaining:
                break
            distances = [abs(cap-c)+abs(turn-t) for _,c,t in remaining]
            nearest = min(distances)
            j = rng.choice([i for i,d in enumerate(distances) if d==nearest])
            matched.append(remaining.pop(j)[0])
        chosen[day] = tuple(matched)
    return chosen


class Rebalance:
    def __init__(self, plan, count, execution):
        self.plan, self.count, self.execution = plan,count,execution
        self.desired = {}
        self.formation = -100
        self.budget = D(0)

    def __call__(self, book, ordinal, day, next_day, bars, marks, last_prices):
        pending = Counter()
        for _,asset,quantity,_ in book.claims.values():
            if quantity:
                pending[asset] += quantity
        if day in self.plan:
            self.formation = ordinal
            sizing_equity = book.cash+sum(v for _,_,_,v in book.claims.values())
            sizing_equity += sum(qty*marks.get(isin,last_prices.get(isin,0))
                                 for isin,qty in (Counter(book.shares)+pending).items())
            self.budget = max(D(0),sizing_equity)/self.count
            self.desired = {isin:int(self.budget/bars[isin][1]) for isin in self.plan[day]
                            if isin in bars and bars[isin][2]==VALID}
            book.post(day,'rebalance_targets',sizing_equity=sizing_equity,target_budget=self.budget,
                      targets=self.desired)
        if not 0<=ordinal-self.formation<5:
            return
        for isin,qty in sorted(book.shares.items()):
            excess = min(qty,qty+pending[isin]-self.desired.get(isin,0))
            if excess>0 and isin in marks and bars.get(isin,(None,None,None))[2]==VALID:
                book.queue(day,isin,'SELL',1,excess)
        for isin,desired in self.desired.items():
            existing = book.shares.get(isin,0)+pending[isin]
            _,close,state = bars.get(isin,(None,None,None))
            if desired<=existing or state!=VALID:
                continue
            limit = self.execution.limit(next_day,close)
            affordable = int(max(D(0),self.budget-existing*close)/(limit*(1+FEE+SLIPPAGE)))
            requested = min(desired-existing,affordable)
            if requested:
                book.queue(day,isin,'BUY',limit,requested)


def sessions(db, start, end):
    from exchange_calendars import get_calendar
    dates = [d for d, in db.execute('SELECT day FROM sessions WHERE day BETWEEN ? AND ? ORDER BY day',
                                   (start,end))]
    schedule = get_calendar('XKRX').sessions_in_range(pd.Timestamp(end),
                pd.Timestamp(end)+pd.Timedelta(days=14)).strftime('%Y%m%d')
    return dates+[d for d in schedule if d>end][:2]


def benchmark(days, quotes, payouts, cap):
    book = Account(INITIAL,days,etf=True)
    daily, marks_log = [], {}
    for i,day in enumerate(days[:-2]):
        book.settle(day)
        if day in payouts and book.shares.get('ETF'):
            record,pay,settlement,gross,_ = payouts[day]
            book.post(day,'issuer_distribution_receivable',isin='ETF',
                      claim=(f'distribution:{record}',settlement,'',0,D(gross)*book.shares['ETF']))
        op,close,volume = quotes.get(day,(None,None,None))
        bars = {'ETF':(int(op),int(close),VALID)} if op and close and volume else {}
        book.execute(day,days[i+2],bars,volume={'ETF':volume or 0},participation=cap)
        if i<5 and close and not book.shares.get('ETF'):
            limit = int(D(str(close))*D('1.02'))//5*5
            book.queue(day,'ETF','BUY',limit,INITIAL)
        marks = {'ETF':int(close)} if close else {}
        marks_log[day] = marks
        daily.append(book.snapshot(day,marks))
    reconcile_journal(INITIAL,book.log,daily,marks_log)
    if not any(r['positions'] for r in daily):
        raise ValueError('ETF failed to enter during the fixed window')
    return dict(daily=daily,journal=book.log)


def report(run, ref=None):
    rows = [dict(r,nav=r.get('research_nav',r['nav'])) for r in run['daily']]
    summary = summarize(dict(run,daily=rows))
    fill = [x for x in run['journal'] if x['event']=='fill']
    orders = [x for x in run['journal'] if x['event']=='order_sized_at_close']
    gross = lambda x: abs(x['shares'])*x['price']
    flow = Counter()
    for x in fill:
        flow[x['isin']] += gross(x)*(1 if x['side']=='SELL' else -1)
    for isin,value in rows[-1].get('marked_positions',{}).items():
        flow[isin] += value
    summary.update(confirmed_missing_days=sum(r['nav'] is None for r in run['daily']),
                   mean_buy_krw=mean([gross(x) for x in fill if x['side']=='BUY']) if
                       any(x['side']=='BUY' for x in fill) else None,
                   total_fill_krw=sum(map(gross,fill)),
                   order_attempts=dict(Counter(x['side'] for x in orders)),
                   positive_orders=dict(Counter(x['side'] for x in orders if x['quantity'])),
                   blocked_reasons=dict(Counter(k for r in rows for k in r.get('research_unresolved',[]))),
                   terminal_ledger={k:rows[-1][k] for k in ('cash','stock','receivables','payables','unresolved')},
                   observed_name_cashflows_plus_terminal_marks=dict(flow),
                   mean_observed_cash_weight=mean([float(r['cash']/r['nav']) for r in rows if r['nav']]),
                   first_exception=next(iter(run.get('exceptions',[])),None))
    if ref:
        first_gap = next((i for i,(a,b) in enumerate(zip(rows,ref['daily'],strict=True))
                          if a['nav'] is None or b['nav'] is None),len(rows))
        summary.update(prefix_end=rows[first_gap-1]['day'] if first_gap else None,
                       prefix=statistics(rows[:first_gap]),prefix_etf=statistics(ref['daily'][:first_gap]))
    return summary


def worker(task):
    phase,count,rate,seed = task
    db_path, days_by_phase, plans, refs, output = CONTEXT
    days = days_by_phase[phase]
    cfg = load_config()
    cfg['execution']['cma_rate'] = 0
    execution = Execution('E2')
    with open_db(db_path) as db:
        run = replay(db,{},D(rate),cfg,mode='exploratory',end=days[-3],execution=execution,
                     additional_actions=EXTRA['B']+EXTRA['C'],start=days[0],initial=INITIAL,
                     session_days=days,rebalance=Rebalance(plans[count,seed],count,execution))
    key = f'{phase}-{count}-{rate}-{seed or "M4"}'
    with gzip.open(output/f'{key}.json.gz','wt') as stream:
        json.dump(run,stream,default=str,separators=(',',':'))
    return key,report(run,refs[phase,rate])


def main():
    global CONTEXT
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','formation','etf','secondary','distributions','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--workers',type=int,default=8)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    frame = pd.read_csv(a.formation,dtype={'day':str})
    if frame.day.max()>CUT or frame[['cap_cell','turn_cell']].isna().any().any():
        raise ValueError('Unexpected formation date or missing matching keys')
    plans = {(n,seed):targets(frame,n,seed) for n in SIZES for seed in (None,*SEEDS)}
    with open_db(a.database) as db:
        days = {p:sessions(db,*limits) for p,limits in PHASES.items()}
    quotes = benchmark_quotes(a.etf,a.secondary)
    payouts = {d:r for d,r in json.loads(a.distributions.read_text())['issuer_events'].items() if d<=CUT}
    refs = {(phase,rate):benchmark(calendar,quotes,payouts,D(rate))
            for phase,calendar in days.items() for rate in CAPS}
    for (phase,rate),run in refs.items():
        with gzip.open(a.output/f'{phase}-ETF-{rate}.json.gz','wt') as stream:
            json.dump(run,stream,default=str)
    CONTEXT = a.database,days,plans,refs,a.output
    tasks = [(p,n,r,s) for s in (None,*SEEDS) for p in PHASES for r in CAPS for n in SIZES]
    with mp.get_context('fork').Pool(a.workers) as pool, (a.output/'runs.jsonl').open('w') as stream:
        for key,result in pool.imap_unordered(worker,tasks):
            stream.write(json.dumps([key,result],default=str)+'\n')
            stream.flush()
    benchmark_results = {f'{p}-{r}':report(run) for (p,r),run in refs.items()}
    (a.output/'benchmark.json').write_text(json.dumps(benchmark_results,default=str,indent=2))
    hashes = {n:digest(getattr(a,n)) for n in ('database','formation','etf','secondary','distributions')}
    hashes['protocol'] = digest(Path(__file__).with_name('sizing_protocol.md'))
    (a.output/'inputs.json').write_text(json.dumps(hashes,indent=2))


if __name__=='__main__':
    main()
