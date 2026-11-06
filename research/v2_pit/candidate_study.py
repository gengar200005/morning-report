"""Run the frozen Stage 4 candidate study in pre-selection and final phases."""
import argparse
from collections import defaultdict
from decimal import Decimal as D
import json
import multiprocessing as mp
from pathlib import Path
import sqlite3
from statistics import mean

from candidate_features import NAMES, Policy, build_features
from foundation import digest
from full_replay import START, END, calendar, load_config, replay
from replay_summary import statistics, summarize

CUT = '20231231'
DEV = '20211231'
SCENARIOS = {'base':('exploratory',D('.01')), 'liquidity':('exploratory',D('.001')),
             'action_stress':('stress',D('.01'))}
PROTOCOL = Path(__file__).with_name('candidate_protocol.md')
CONTEXT = None


def open_db(path):
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)


def window(rows, start, end):
    chosen = [i for i,r in enumerate(rows) if start<=r['day']<=end]
    return rows[max(0,chosen[0]-1):chosen[-1]+1] if chosen else []


def phase(path, benchmark, start, end):
    rows = window(path['daily'],start,end)
    ref = window(benchmark,start,end)
    if [r['day'] for r in rows]!=[r['day'] for r in ref]:
        raise ValueError('Mismatched benchmark dates')
    result = statistics(rows)
    relative = statistics(ref)
    return dict(metrics=result,benchmark=relative,
                cagr_spread=result['cagr']-relative['cagr'] if result and relative else None,
                unresolved_days=sum(r['nav'] is None for r in rows))


def run_one(task):
    name, scenario = task
    path, market, features, end, output = CONTEXT
    mode, participation = SCENARIOS[scenario]
    with open_db(path) as db:
        run = replay(db,market,participation,load_config(),mode=mode,policy=Policy(name,features),end=end)
    (output/f'{name}-{scenario}.json').write_text(json.dumps(run,default=str))
    return name,scenario


def summarize_one(run, benchmark):
    path = dict(run,daily=[dict(r,nav=r['research_nav']) for r in run['daily']])
    result = summarize(path)
    result['development'] = phase(path,benchmark,START,DEV)
    result['selection'] = phase(path,benchmark,'20220101',CUT)
    if path['daily'][-1]['day']>CUT:
        result['final'] = phase(path,benchmark,'20240101',END)
    annual = {year:row['total_return'] if row else None for year,row in result['annual'].items()}
    result['worst_year'] = min((r,year) for year,r in annual.items() if r is not None) if any(
        r is not None for r in annual.values()) else None
    weights = []
    for row in path['daily']:
        positions = row['marked_positions']
        if positions and row['nav']:
            weights.append(max(positions.values())/float(row['nav']))
    result['concentration'] = dict(mean_largest_marked_position_weight=mean(weights) if weights else None,
                                   max_largest_marked_position_weight=max(weights,default=None))
    unresolved = defaultdict(list)
    for row in path['daily']:
        for issue in row['research_unresolved']:
            unresolved[issue].append(row['day'])
    result['unexplained'] = {key:[len(days),days[0],days[-1]] for key,days in unresolved.items()}
    return result


def select(results):
    eligible = {}
    for name,cases in results.items():
        scores = [v['selection']['cagr_spread'] for v in cases.values()]
        dev = cases['base']['development']['cagr_spread']
        if dev is not None and dev>0 and all(s is not None and s>0 for s in scores):
            eligible[name] = min(scores)
    return min(eligible,key=lambda n:(-eligible[n],n)) if eligible else None


def main():
    global CONTEXT
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','market','benchmark','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--selection',type=Path)
    p.add_argument('--workers',type=int,default=4)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    hashes = {name:digest(getattr(args,name)) for name in ('database','market','benchmark')}
    hashes['protocol'] = digest(PROTOCOL)
    if args.selection:
        sealed = json.loads(args.selection.read_text())
        if sealed['hashes']!=hashes or select(sealed['results'])!=sealed['finalist']:
            raise ValueError('Frozen selection or inputs changed')
        if sealed['finalist'] is None:
            raise ValueError('No eligible finalist; final period remains sealed')
        names,end = (sealed['finalist'],),END
    else:
        names,end = NAMES,CUT
    market = {r[0]:r[4] for r in json.loads(args.market.read_text())[1:] if r[0]<=end}
    benchmark = [r for r in json.loads(args.benchmark.read_text())['gross']['daily'] if r['day']<=end]
    with open_db(args.database) as db:
        features = build_features(db,calendar(db),market,end,names)
    CONTEXT = args.database,market,features,end,args.output
    with mp.get_context('fork').Pool(args.workers) as pool:
        completed = pool.map(run_one,[(name,scenario) for name in names for scenario in SCENARIOS])
    results = {name:{} for name in names}
    for name,scenario in completed:
        run = json.loads((args.output/f'{name}-{scenario}.json').read_text())
        results[name][scenario] = summarize_one(run,benchmark)
    finalist = names[0] if args.selection else select(results)
    if args.selection:
        for scenario in SCENARIOS:
            for phase_name in ('development','selection'):
                if results[finalist][scenario][phase_name]!=sealed['results'][finalist][scenario][phase_name]:
                    raise ValueError('Pre-selection NAV changed during final replay')
    manifest = dict(hashes=hashes,finalist=finalist,results=results,through=end,
                    selection_manifest_sha256=digest(args.selection) if args.selection else None)
    (args.output/'summary.json').write_text(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
