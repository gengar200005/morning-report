"""Compare execution policies on the frozen Stage 4 candidates through 2023."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal as D
from functools import lru_cache
import json
import multiprocessing as mp
from pathlib import Path
from statistics import median

from candidate_features import NAMES, Policy, build_features
from candidate_study import CUT, open_db, summarize_one
from execution_models import Execution
from foundation import digest
from full_replay import calendar, load_config, replay

MODELS = {'E1':('E1','.00'), 'E2':('E2','.02'), 'E2-1':('E2','.01'),
          'E2-3':('E2','.03'), 'E3':('E3','.02')}
CONTEXT = None


def execution_details(run, db, days):
    counts, forward = Counter(), defaultdict(list)
    orders = {(e['day'],e['isin']):e for e in run['journal']
              if e['event']=='order_sized_at_close' and e['side']=='BUY' and e['quantity']}
    days_by_index = {day:i for i,day in enumerate(days)}

    @lru_cache(maxsize=16000)
    def path(isin,start,end):
        return db.execute("""SELECT day,price_index,link_status FROM economic_momentum
            WHERE isin=? AND day BETWEEN ? AND ? ORDER BY day""",(isin,start,end)).fetchall()

    def add_forward(isin,day,op,close,reason):
        i = days_by_index[day]
        for horizon in (1,5,20):
            if i+horizon>=len(days) or days[i+horizon]>CUT:
                continue
            rows = path(isin,day,days[i+horizon])
            if (len(rows)!=horizon+1 or not rows[0][1] or
                    any(x[2]!='CONTIGUOUS_RAW_RETURN' for x in rows[1:])):
                continue
            forward[reason,horizon].append(rows[-1][1]/rows[0][1]*close/op-1)

    matched = set()
    for event in run['journal']:
        kind = event['event']
        if kind=='unit_change_order_cancelled':
            key = (event['decision'],event['isin'])
            if key in orders:
                matched.add(key)
                counts[kind] += 1
            continue
        if event.get('side')!='BUY' or not event.get('decision'):
            continue
        isin,day = event['isin'],event['day']
        key = (event['decision'],isin)
        matched.add(key)
        if kind=='fill':
            counts['filled'] += 1
            continue
        bar = db.execute('SELECT open,close,state FROM execution_bars WHERE day=? AND isin=?',
                         (day,isin)).fetchone()
        reason = kind
        if kind=='conditional_order_unfilled':
            reason = 'limit_miss' if bar and bar[0]>orders[key]['limit'] and (
                not run['execution'].startswith('E3')) else 'cash_at_fill'
        if kind=='opening_unavailable':
            reason = bar[2] if bar else 'absent_bar'
        counts[reason] += 1
        if bar and bar[0] and bar[1] and bar[2]=='POSITIVE_VOLUME_VALID_BAR':
            add_forward(isin,day,bar[0],bar[1],reason)
    counts['submitted'] = len(orders)
    counts['end_censored'] = len(orders.keys()-matched)
    return dict(order_counts=dict(counts),opportunities=run['opportunities'],
                fill_rate=counts['filled']/(len(orders)-counts['end_censored'])
                if len(orders)>counts['end_censored'] else None,
                missed_forward={f'{k[0]}:{k[1]}':dict(n=len(v),median=median(v),
                    mean=sum(v)/len(v)) for k,v in sorted(forward.items())})


class Exclusion(Policy):
    def entries(self, day):
        return [r for r in super().entries(day) if r[1]!='001570']


def run_one(job):
    name, model, size = job
    db_path, market, benchmark, features, out, legacy = CONTEXT
    base, premium = MODELS[model]
    policy = Exclusion('D',features) if name=='D-exclude' else Policy(name,features)
    with open_db(db_path) as db:
        run = replay(db,market,D(size),load_config(),mode='exploratory',policy=policy,end=CUT,
                     execution=Execution(base,D(premium)))
        run['execution'] = model
        result = summarize_one(run,benchmark)
        result.update(execution_details(run,db,calendar(db)))
    slug = f'{name}-{model}-{size}'
    if model=='E1' and name in NAMES:
        old = json.loads((legacy/f"{name}-{'base' if size=='.01' else 'liquidity'}.json").read_text())
        if any(json.dumps(run[k],default=str,sort_keys=True)!=json.dumps(old[k],sort_keys=True)
               for k in ('daily','journal','selections','counts')):
            raise ValueError(f'E1 replay mismatch: {slug}')
        result['e1_exact_replay'] = True
    if name.startswith('D'):
        result['through_2022'] = result['annual'].get('2022')
        if result['through_2022'] and all(r['research_nav'] is not None for r in run['daily'] if r['day']<'20230101'):
            from replay_summary import statistics
            result['exclude_2023'] = statistics([dict(r,nav=r['research_nav'])
                                  for r in run['daily'] if r['day']<'20230101'])
    result['exception_inventory'] = run['exceptions']
    result['mean_annual_turnover'] = annual_turnover(run)
    (out/f'{slug}.json').write_text(json.dumps(run,default=str))
    return slug,result


def annual_turnover(run):
    gross, nav = defaultdict(list),defaultdict(list)
    for e in run['journal']:
        if e['event']=='fill':
            gross[e['day'][:4]].append(abs(e['shares'])*e['price'])
    for row in run['daily']:
        nav[row['day'][:4]].append(row['research_nav'])
    return {y:sum(gross[y])/2/(sum(map(float,values))/len(values))
            if all(v is not None for v in values) else None for y,values in nav.items()}


def main():
    global CONTEXT
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','market','benchmark','legacy','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--workers',type=int,default=4)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    market = {r[0]:r[4] for r in json.loads(args.market.read_text())[1:] if r[0]<=CUT}
    benchmark = [r for r in json.loads(args.benchmark.read_text())['gross']['daily'] if r['day']<=CUT]
    with open_db(args.database) as db:
        features = build_features(db,calendar(db),market,CUT)
    CONTEXT = args.database,market,benchmark,features,args.output,args.legacy
    jobs = [(name,model,size) for name in NAMES for model in MODELS for size in ('.01','.001')]
    jobs += [('D-exclude',model,size) for model in ('E1','E2','E3') for size in ('.01','.001')]
    with mp.get_context('fork').Pool(args.workers) as pool:
        results = dict(pool.map(run_one,jobs))
    metadata = {name:digest(getattr(args,name)) for name in ('database','market','benchmark')}
    metadata['protocol'] = digest(Path(__file__).with_name('execution_protocol.md'))
    metadata['stage4_summary'] = digest(args.legacy/'summary.json')
    (args.output/'summary.json').write_text(json.dumps(dict(inputs=metadata,results=results),indent=2))


if __name__=='__main__':
    main()
