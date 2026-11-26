"""One pre-registered descriptive cross-section. Requires a verified as-of ledger and gate."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import sqlite3
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean, median, correlation
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
DAY = '20210601'
HORIZONS = (20, 60, 120)
FIELDS = ('F2','F3')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gate_signals(gate, asof):
    signals = gate.get('passed_signals')
    if (gate.get('formation') != DAY or any(gate.get(k) is not True for k in
            ('q1_quality_pass','quarter_forms_checked','asof_complete'))
            or not isinstance(signals, list) or not signals or len(set(signals)) != len(signals)
            or not set(signals) <= set(FIELDS) or gate.get('asof_sha256') != digest(asof)):
        raise ValueError('Missing Q1, forms, signal, or as-of verification')
    return signals


def read_ledger(path, members, signals, sessions):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(members) or {r['isin'] for r in rows} != set(members):
        raise ValueError('Missing, duplicate or extra formation ISIN')
    values = {f:{} for f in signals}
    if not sessions or sessions != sorted(set(sessions)) or sessions[-1] != DAY:
        raise ValueError('Missing official availability calendar')
    for r in rows:
        if r['industry_group'] not in ('nonfinancial','financial','unknown') or not r['status'].strip():
            raise ValueError('Missing sector classification or status')
        active = [s for s in signals if r[s].strip()]
        if not active:
            continue
        filed = r.get('published_date') or r.get('filing_date') or ''
        next_i = bisect_right(sessions, filed)
        if (not re.fullmatch(r'\d{8}',filed) or not sessions[0] <= filed < DAY
                or next_i == len(sessions) or sessions[next_i] != r['available_session']
                or r['receipt'][:8] > filed):
            raise ValueError('Publication date and first eligible session disagree')
        if (r['status'] != 'PASS' or r['industry_group'] != 'nonfinancial'
                or not re.fullmatch(r'\d{14}', r['receipt']) or not re.fullmatch(r'\d{8}', r['available_session'])
                or not (r['receipt'][:8] < r['available_session'] <= DAY)
                or not re.fullmatch(r'[0-9a-f]{64}',r['source_sha256'])):
            raise ValueError('Financial observation violates eligibility, timing or provenance')
        for s in active:
            x=Decimal(r[s])
            if not x.is_finite():
                raise ValueError('Nonfinite formation signal')
            values[s][r['isin']]=x
    return rows,values


def top(scores):
    order=sorted(scores, key=lambda k: (-scores[k],k))
    return set(order[:len(order)//5])


def groups(signal, m4):
    strong=top(signal)
    joint=set(m4) & set(signal)
    m=top({k:m4[k] for k in joint})
    f=top({k:signal[k] for k in joint})
    return {'eligible':set(signal),'top':strong,'remainder':set(signal)-strong,'joint':joint,
            'A':m-f,'B':f-m,'C':m&f,'D':joint-(m|f)}


def cells(names, liquidity):
    eligible=[k for k in names if k in liquidity and all(x is not None for x in liquidity[k])]
    ranks=[]
    for col in (0,1):
        order=sorted(eligible,key=lambda k:(liquidity[k][col],k))
        ranks.append({k:math.ceil(3*i/len(order))-1 for i,k in enumerate(order,1)})
    return {k:(ranks[0][k],ranks[1][k]) for k in eligible}


def average(names, returns):
    vals=[returns[k] for k in sorted(names) if returns.get(k) is not None]
    return mean(vals) if vals else None


def diff(a,b):
    return a-b if a is not None and b is not None else None


def matched(left, right, values, bins):
    matched_left=set()
    matched_right=set()
    cell_effects=[]
    for cell in sorted(set(bins.values())):
        a={i for i in left if bins.get(i)==cell}
        b={i for i in right if bins.get(i)==cell}
        if a and b:
            matched_left.update(a)
            matched_right.update(b)
            delta=diff(average(a,values),average(b,values))
            if delta is not None:
                cell_effects.append((len(a),delta))
    weight=sum(n for n,_ in cell_effects)
    return {'effect':sum(n*d for n,d in cell_effects)/weight if weight else None,
            'structurally_matched_target':len(matched_left),'structurally_matched_peer':len(matched_right),
            'target_in_cells_with_both_observed':weight,'target_total':len(left)}


def read_formation_bundle(path):
    """Use only the June cohort and its identical benchmark references; stop at next date."""
    with ZipFile(path) as z:
        def select(filename):
            with z.open(filename) as raw, gzip.GzipFile(fileobj=raw) as gz, io.TextIOWrapper(gz) as text:
                for row in csv.DictReader(text):
                    if row['day'] > DAY:
                        break
                    if row['day']==DAY:
                        yield row
        scores={row['isin']:Decimal(row['M4']) for row in select('formations.csv.gz')}
        benchmark=defaultdict(set)
        reference_outcomes={}
        for row in select('outcomes.csv.gz'):
            h=int(row['horizon'])
            if h in HORIZONS:
                benchmark[h].add((row['entry'],row['exit'],float(row['etf_price']),float(row['etf_economic'])))
                key=(row['isin'],h)
                if key in reference_outcomes:
                    raise ValueError('Duplicate June Stage 5 reference')
                reference_outcomes[key]=(float(row['price']) if row['price'] else None,
                                         float(row['economic']) if row['economic'] else None,
                                         row['status'],int(row['dividends']))
    if not scores or set(benchmark)!=set(HORIZONS) or any(len(v)!=1 for v in benchmark.values()):
        raise ValueError('Missing cohort or ambiguous archived benchmark')
    return scores,{h:v.pop() for h,v in benchmark.items()},reference_outcomes


def stress(names, records, ix, scenario):
    # Never impute an unfillable entry. Post-entry unresolved holdings receive
    # the adverse scenario solely for this sensitivity, not as a recovery estimate.
    items=[records[k][ix] if records[k][ix] is not None else scenario for k in sorted(names)
           if records[k][2]!='entry_unavailable']
    return mean(items) if items and all(x is not None for x in items) else None


def rank_ic(score, vals):
    ids=sorted(k for k in score if vals.get(k) is not None)
    if len(ids)<3:
        return None
    x=[score[k] for k in ids]
    y=[vals[k] for k in ids]
    if len(set(x))<2 or len(set(y))<2:
        return None
    return correlation(x,y,method='ranked')


def audit_replayed_outcomes(replayed, windows, in_stage5, reference):
    checked=0
    for isin in set(replayed) & set(in_stage5):
        for h,(_,end) in windows.items():
            actual=replayed[isin][end]
            old=reference.get((isin,h))
            if old is None or old[2:]!=actual[2:]:
                raise ValueError('June archived Stage 5 outcome status/count mismatch')
            for a,b in zip(actual[:2],old[:2]):
                if (a is None)!=(b is None) or (a is not None and not math.isclose(a,b,abs_tol=1e-10,rel_tol=1e-10)):
                    raise ValueError('June archived Stage 5 return mismatch')
            checked+=1
    return checked


def summaries(group, hrows, liquidity, sector, score):
    output={}
    ranked=sorted(score,key=lambda k:(-score[k],k))
    quintiles=[ranked[q*len(ranked)//5:(q+1)*len(ranked)//5] for q in range(5)]
    for h,(records,reference) in hrows.items():
        all_groups={}
        contrasts={}
        diagnostics={}
        for ix,metric in [(0,'price'),(1,'partial_economic')]:
            vals={k:r[ix] for k,r in records.items()}
            means={label:average(items,vals) for label,items in group.items()}
            diagnostics[metric]={'spearman_ic':rank_ic(score,vals),'quintiles_high_to_low':[
                {'n':len(bucket),'observed':sum(vals.get(k) is not None for k in bucket),
                 'mean':average(bucket,vals)} for bucket in quintiles]}
            for label,items in group.items():
                status=Counter(records[k][2] for k in items)
                peer='joint' if label in ('A','B','C','D','joint') else 'eligible'
                row=all_groups.setdefault(label,{'n':len(items),'statuses':dict(sorted(status.items()))})
                observed=[vals[k] for k in items if vals.get(k) is not None]
                row[metric]={'mean':means[label],'median':median(observed) if observed else None,
                             'observed':len(observed),'minus_etf':diff(means[label],reference[2+ix]),
                             'minus_universe':diff(means[label],means[peer])}
            for left,right,base in [('top','remainder','eligible'),('C','A','joint'),('C','B','joint')]:
                center=means[base]
                low=max(-1.,center-.20) if center is not None else None
                high=center+.20 if center is not None else None
                contrasts.setdefault(f'{left}-{right}',{})[metric]={
                    'difference':diff(means[left],means[right]),
                    'matched_cap_turnover':matched(group[left],group[right],vals,cells(group[base],liquidity)),
                    'matched_sector':matched(group[left],group[right],vals,sector),
                    'adverse_unresolved_stress':diff(stress(group[left],records,ix,low),
                                                    stress(group[right],records,ix,high))}
        output[h]={'entry':reference[0],'exit':reference[1],'etf_price':reference[2],
                   'etf_partial_economic':reference[3],'groups':all_groups,'contrasts':contrasts,
                   'diagnostics':diagnostics}
    return output


def run(a, diagnostic=None):
    signals=gate_signals(json.loads(a.gate.read_text()),a.asof)
    # The ledger is run only on explicit release after the upstream data gates.
    if not a.release_outcomes:
        raise ValueError('Explicit release of this single formation is required')
    from momentum_study import formation_liquidity, load_actions, outcome, window

    inv=json.loads(Path(__file__).with_name('stage5_input_inventory.json').read_text())
    if digest(a.database)!=inv['stage5']['expected_input_hashes']['database']:
        raise ValueError('Stage 5 database input hash mismatch')
    # Match the persisted bundle members by size and central-directory CRC to the stored inventory.
    with ZipFile(a.stage5) as z:
        for m in inv['stage5']['members']:
            info=z.getinfo(m['member'])
            if (info.file_size,f'{info.CRC:08x}')!=(m['size'],m['crc32']):
                raise ValueError('Unrecognized Stage 5 archive member')
    with sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        members=dict(db.execute('SELECT isin, code FROM membership WHERE day=? AND common=1',(DAY,)))
        march={i for i, in db.execute("SELECT isin FROM membership WHERE day='20210331' AND common=1")}
        eligibility_days=[d for d, in db.execute("SELECT day FROM sessions WHERE day BETWEEN '20210101' AND ? ORDER BY day",(DAY,))]
        ledger,values=read_ledger(a.asof,members,signals,eligibility_days)
        sector={r['isin']:r['sector_code'] for r in ledger if r['industry_group']=='nonfinancial' and r['sector_code']}
        days=[d for d, in db.execute("SELECT day FROM sessions WHERE day BETWEEN ? AND ? ORDER BY day",(DAY,'20211231'))]
        if not days or days[0]!=DAY:
            raise ValueError('Unrecognized formation session')
        windows={h:window(0,h,days) for h in HORIZONS}
        if any(v is None for v in windows.values()):
            raise ValueError('Unavailable endpoint')
        scores,etf,references=read_formation_bundle(a.stage5)
        if not scores.keys() <= members.keys():
            raise ValueError('Stage 5 M4 includes ISIN outside official same-day universe')
        for h,(start,end) in windows.items():
            if etf[h][:2]!=(days[start],days[end]):
                raise ValueError('Benchmark timing differs from eligible horizon')
        end_date=days[windows[120][1]]
        # Confine even the shared action loader to the single pilot interval.
        for t,c in [('corporate_actions','effective_date'),('exit_audit','delisted')]:
            db.execute(f"CREATE TEMP VIEW {t} AS SELECT * FROM main.{t} WHERE {c} BETWEEN '{DAY}' AND '{end_date}'")
        actions,exits=load_actions(db,days)
        liquidity_code=formation_liquidity(db,a.archives,DAY)
        liq={i:liquidity_code[c] for i,c in members.items() if c in liquidity_code}
        ordinal={d:i for i,d in enumerate(days)}
        bars=defaultdict(dict)
        for d,i,op,cl,state,ref,check in db.execute("""
            SELECT m.day,m.isin,p.open,p.close,p.state,k.implied_reference_krw,k.rate_status
            FROM membership m LEFT JOIN execution_bars p USING(day,isin)
            LEFT JOIN krx_return_checks k USING(day,isin) WHERE m.day BETWEEN ? AND ?
            """,(days[1],end_date)):
            if i in members:
                bars[i][ordinal[d]]=(op,cl,None,state,ref,check)
        ends={v[1] for v in windows.values()}
        evaluations={i:outcome(bars[i],actions[i],exits[i],1,ends) for i in set().union(*values.values())}
        hrows={h:({i:r[windows[h][1]] for i,r in evaluations.items()},etf[h]) for h in HORIZONS}
        overlap=audit_replayed_outcomes(evaluations,windows,scores,references)
        if diagnostic is not None:
            return {'formation':DAY,'horizon':120,'entry':etf[120][0],'exit':etf[120][1],
                    'asof_sha256':digest(a.asof),'gate_sha256':digest(a.gate),
                    'matched_stage5_isin_horizon_checks':overlap,
                    'signals':{s:diagnostic(groups(values[s],scores),hrows[120][0]) for s in signals}}
        fresh=set(members)-march
        return {'formation':DAY,'scope':'single descriptive formation only','universe':len(members),
                'matched_stage5_isin_horizon_checks':overlap,
                'new_since_march31':[{k:r[k] for k in ('isin','industry_group','status',*signals)} for r in ledger if r['isin'] in fresh],
                'coverage':dict(Counter(r['industry_group']+'/'+r['status'] for r in ledger)),
                'sources':{'asof_sha256':digest(a.asof),'gate_sha256':digest(a.gate),'stage5_bundle_sha256':digest(a.stage5)},
                'signals':{s:summaries(groups(values[s],scores),hrows,liq,sector,values[s]) for s in signals}}


def arguments(description):
    p=argparse.ArgumentParser(description=description)
    for arg in ('gate','asof','database','archives','stage5'):
        p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--release-outcomes',action='store_true')
    return p.parse_args()


if __name__=='__main__':
    print(json.dumps(run(arguments(__doc__)),indent=2,ensure_ascii=False,allow_nan=False))
