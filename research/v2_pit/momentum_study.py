"""Stage 5 PIT signal formation and forward outcome audit."""
import argparse
from bisect import bisect_left
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from candidate_features import ma200_pair
from candidate_study import open_db
from foundation import digest
from kodex_benchmark import ETF, day as etf_day

CUT = '20231231'
HORIZONS = (5, 20, 60, 120)
SIGNALS = ('M1', 'M2', 'M3', 'M4', 'M5')
VALID = 'POSITIVE_VOLUME_VALID_BAR'


def scores(closes):
    now, lag = ma200_pair(closes, 252)
    return (closes[-22]/closes[0]-1, closes[126]/closes[0]-1,
            closes[-22]/closes[126]-1, closes[-1]/max(closes[:-1])-1,
            closes[-1]/now-1, now/lag-1)


def window(i, horizon, days):
    end = i+horizon
    cutoff = '20211231' if days[i]<'20220101' else CUT
    if end>=len(days) or days[end]>cutoff:
        return None
    return i+1, end


def outcome(bars, actions, exits, entry, ends):
    opening = bars.get(entry)
    if not opening or opening[3]!=VALID or not opening[0]:
        return {end:(None, None, 'entry_unavailable', 0) for end in ends}
    denominator = opening[0]
    prev = opening[1]
    shares, cash, dividend_count = 1, 0, 0
    issues = set()
    results = {}
    for i in range(entry, max(ends)+1):
        row = bars.get(i)
        if i>entry:
            if i in exits or not row:
                issues.add('pit_exit_or_missing_membership')
            for kind, amount in actions.get(i, ()):
                if kind=='split':
                    shares *= amount
                    prev /= amount
                elif kind=='cash':
                    cash += shares*amount
                    dividend_count += 1
                else:
                    issues.add('corporate_action')
            if row and row[3]==VALID:
                if row[5]!='PASS' or row[4]!=prev or abs(row[1]/prev-1)>.35:
                    issues.add('unverified_reference')
                prev = row[1]
            elif row and row[3]!='ZERO_VOLUME':
                issues.add('invalid_bar')
        if i in ends:
            reasons = issues.copy()
            if row and row[3]=='ZERO_VOLUME':
                reasons.add('suspended_or_zero_volume_end')
            if not row or row[3]!=VALID:
                reasons.add('end_unavailable')
            if reasons:
                results[i] = (None, None, '|'.join(sorted(reasons)), dividend_count)
            else:
                value = shares*row[1]
                results[i] = (value/denominator-1, (value+cash)/denominator-1, 'observed', dividend_count)
    return results


def load_panel(db, days):
    ordinal = {d:i for i,d in enumerate(days)}
    panel = defaultdict(dict)
    for d, isin, code, common, op, cl, state, ref, check, price, link in db.execute("""
        SELECT m.day,m.isin,m.code,m.common,p.open,p.close,p.state,k.implied_reference_krw,
               k.rate_status,e.price_index,e.link_status
        FROM membership m LEFT JOIN execution_bars p USING(day,isin)
        LEFT JOIN krx_return_checks k USING(day,isin)
        LEFT JOIN economic_momentum e USING(day,isin) WHERE m.day<=?
        ORDER BY m.day,m.isin""", (CUT,)):
        panel[isin][ordinal[d]] = (op,cl,code,state,ref,check,price,link,common)
    return panel


def load_actions(db, days):
    actions = defaultdict(lambda: defaultdict(list))
    for isin, kind, status, day, pay, terms in db.execute("""
        SELECT isin,kind,status,effective_date,payment_or_delivery,terms
        FROM corporate_actions WHERE isin IS NOT NULL AND effective_date<=?""", (CUT,)):
        p = json.loads(terms)
        if kind=='split' and status=='V1_ACCOUNT_TERMS':
            info = p['verified']
            ratio = info['ratio_numerator']/info['ratio_denominator']
            event = ('split',ratio) if ratio.is_integer() and ratio>=1 else ('unknown',0)
        elif kind=='cash_dividend' and status=='V1_ACCOUNT_TERMS' and pay and day<pay:
            event = ('cash',float(p['per_share_krw']))
        else:
            event = ('unknown',0)
        idx = bisect_left(days, day)
        if idx<len(days):
            actions[isin][idx].append(event)
    exits = defaultdict(set)
    for isin, day in db.execute("SELECT isin,delisted FROM exit_audit WHERE delisted<=?", (CUT,)):
        exits[isin].add(bisect_left(days, day))
    return actions, exits


def formation_liquidity(db, root, day):
    path = root/f'KRX_PIT_{day[:4]}_{day[4:6]}_v1.json.gz'
    expected, = db.execute('SELECT sha256 FROM provenance WHERE source=?',(path.name,)).fetchone()
    if digest(path)!=expected:
        raise ValueError(f'Unverified KRX archive {path.name}')
    with gzip.open(path,'rt',encoding='utf-8') as handle:
        records = json.load(handle)['records']
    rows = next(r['daily'] for r in records if r['date']==day)
    return {r['ISU_CD']:(int(r['MKTCAP'].replace(',','')),int(r['ACC_TRDVAL'].replace(',','')))
            for r in rows if r['MKTCAP'].replace(',','').isdigit() and r['ACC_TRDVAL'].replace(',','').isdigit()}


def eligible(panel, i, liquidity):
    result = []
    common = 0
    for isin, bars in panel.items():
        current = bars.get(i)
        if not current or not current[8]:
            continue
        common += 1
        if i<252 or not current[6]:
            continue
        history = [bars.get(j) for j in range(i-252,i+1)]
        if not history[0] or history[0][6] is None or any(
                not bar or bar[7]!='CONTIGUOUS_RAW_RETURN' for bar in history[1:]):
            continue
        code = current[2]
        result.append((isin,code,*liquidity.get(code,(None,None)),*scores([bar[6] for bar in history])))
    return result, common


def build(db, archives, quotes, dividends, output):
    days = [d for d, in db.execute('SELECT day FROM sessions WHERE day<=? ORDER BY day',(CUT,))]
    panel = load_panel(db, days)
    actions, exits = load_actions(db, days)
    audit, label_records = [], []
    formed = []
    for i, day in enumerate(days):
        if day<'20170101' or day[:6]==days[i-1][:6]:
            continue
        universe, common = eligible(panel, i, formation_liquidity(db,archives,day))
        windows = {h:window(i,h,days) for h in HORIZONS}
        audit.append(dict(day=day,common=common,ranked=len(universe),
                          windows={h:[days[j] for j in w] if w else None for h,w in windows.items()}))
        if not universe:
            continue
        u = pd.DataFrame(universe,columns=['isin','code','cap','turnover',*SIGNALS[:4],'ma_distance','ma_slope'])
        u['day'] = day
        u['M5'] = (rankdata(u.ma_distance)+rankdata(u.ma_slope))/(2*len(u))
        u['cap_cell'] = (u.cap.rank(pct=True,method='first')*3).apply(np.ceil)-1
        u['turn_cell'] = (u.turnover.rank(pct=True,method='first')*3).apply(np.ceil)-1
        formed.append(u)
        ends = {w[1]:h for h,w in windows.items() if w}
        if not ends:
            continue
        previous = quotes.get(days[i-60],(None,None))[1] if i>=60 else None
        current = quotes.get(day,(None,None))[1]
        regime = ('up' if current>=previous else 'down') if current and previous else 'unknown'
        etf_open = quotes.get(days[i+1],(None,None))[0]
        refs = {}
        for end in ends:
            close = quotes.get(days[end],(None,None))[1]
            cash = sum(dividends.get(days[j],0) for j in range(i+2,end+1))
            refs[end] = (close/etf_open-1,(close+cash)/etf_open-1) if close and etf_open else (None,None)
        for isin in u['isin']:
            values = outcome(panel[isin],actions[isin],exits[isin],i+1,ends)
            for end,(price,economic,status,count) in values.items():
                label_records.append((day,isin,ends[end],days[i+1],days[end],regime,
                                      price,economic,status,count,*refs[end]))
    cohort = pd.concat(formed,ignore_index=True)
    labels = pd.DataFrame(label_records,columns=['day','isin','horizon','entry','exit','regime','price',
                                                'economic','status','dividends','etf_price','etf_economic'])
    cohort.to_csv(output/'formations.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    labels.to_csv(output/'outcomes.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    (output/'calendar.json').write_text(json.dumps(audit,indent=2))
    return cohort, labels


def benchmark_quotes(primary, secondary):
    chart = json.loads(primary.read_text())['result']
    if chart['meta']['symbol']!=f'{ETF}.KS':
        raise ValueError('Unexpected ETF instrument')
    if any(etf_day(row['date'])<=CUT for row in chart.get('events',{}).get('splits',{}).values()):
        raise ValueError('ETF split requires separate valuation')
    quote = chart['indicators']['quote'][0]
    prices = {}
    for ts, op, cl, volume in zip(chart['timestamp'],quote['open'],quote['close'],quote['volume'],strict=True):
        day = etf_day(ts)
        if day<=CUT and op and cl and volume:
            prices[day] = (op,cl,volume)
    fallback = json.loads(secondary.read_text())
    if fallback['code']!=200:
        raise ValueError('Secondary ETF quote source unavailable')
    for row in fallback['data']:
        day = row['date'][:10].replace('-','')
        if day>CUT:
            continue
        if row['symbolCode']!=f'A{ETF}':
            raise ValueError('Unexpected secondary ETF instrument')
        op,cl,volume = row['openingPrice'],row['tradePrice'],row['accTradeVolume']
        if day in prices and prices[day][:2]!=(op,cl):
            raise ValueError(f'Raw ETF sources disagree on {day}')
        if op and cl and volume:
            prices.setdefault(day,(op,cl,volume))
    return prices


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','archives','etf','secondary','benchmark','output'):
        p.add_argument(name,type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    quotes = benchmark_quotes(a.etf,a.secondary)
    archived = json.loads(a.benchmark.read_text())['issuer_events']
    dividends = {d:float(r[3]) for d,r in archived.items() if d<=CUT}
    with open_db(a.database) as db:
        cohort, labels = build(db,a.archives,quotes,dividends,a.output)
    hashes = {n:digest(getattr(a,n)) for n in ('database','etf','secondary','benchmark')}
    hashes['protocol'] = digest(Path(__file__).with_name('momentum_protocol.md'))
    (a.output/'inputs.json').write_text(json.dumps(hashes,indent=2))
    print(len(cohort),len(labels))


if __name__=='__main__':
    main()
