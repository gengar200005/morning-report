"""Full-period PIT application of the frozen V1 T10/CD60 backtest rules."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from datetime import date
from decimal import Decimal as D
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np

from economic_account import Account, VALID, FEE, SLIPPAGE, reconcile_journal
from foundation import digest

INITIAL = 100_000_000
START = '20170110'
END = '20261030'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backtest'))
from strategy import check_signal, check_market_gate, load_config


def calendar(db):
    from exchange_calendars import get_calendar
    upcoming = get_calendar('XKRX',start='2026-10-29',end='2026-11-05').sessions.strftime('%Y%m%d')
    return [r[0] for r in db.execute('SELECT day FROM sessions WHERE day<=? ORDER BY day',(END,))]+[
        d for d in upcoming if d>END][:2]


def interest(book, day, previous, annual):
    elapsed = (date.fromisoformat(day)-date.fromisoformat(previous)).days
    amount = (max(D(0),book.buying_power)*((1+annual)**(D(elapsed)/365)-1)).quantize(D('.000001'))
    if amount:
        book.post(day,'cash_interest',cash=amount)


def buy_limit(day, close):
    bands = ((0,1),(1000,5),(5000,10),(10000,50),(50000,100),(100000,500),(500000,1000))
    if day >= '20230125':
        bands = ((0,1),(2000,5),(5000,10),(20000,50),(50000,100),(200000,500),(500000,1000))
    tick = next(tick for floor,tick in reversed(bands) if close>=floor)
    return close//tick*tick


def action_inventory(db, days):
    actions = defaultdict(list)
    for key,isin,kind,status,day,payment,terms in db.execute("""
        SELECT event_id,isin,kind,status,effective_date,payment_or_delivery,terms
        FROM corporate_actions WHERE isin IS NOT NULL"""):
        payload = json.loads(terms)
        day = day or payload.get('inventory_date')
        if not day or day>END:
            continue
        # Legal non-session dates take effect before the next opening.
        from bisect import bisect_left
        idx = bisect_left(days,day)
        if idx==len(days):
            continue
        actions[days[idx]].append((key,isin,kind,status,payment,payload))
    return actions


def replay(db, market, participation, cfg, *, scheduled_bonus=False):
    days = calendar(db)
    book = Account(INITIAL,days)
    actions = action_inventory(db,days)
    exits = {(d,t):category for d,t,category in db.execute('SELECT delisted,isin,category FROM exit_audit WHERE isin IS NOT NULL')}
    holdings, cool, histories, last_prices = {},{},{},{}
    doubtful, daily, market_window = [],[],deque(maxlen=61)
    marks_log, dividends = {},defaultdict(list)
    counts = Counter()
    known_split = set()
    risk = cfg['risk']
    annual = D(str(cfg['execution']['cma_rate']))

    def flag(day,isin,key,category):
        if key not in book.unknown:
            exposure = book.shares[isin]*last_prices.get(isin,0)
            book.post(day,'valuation_exception',isin=isin,block=key,category=category)
            doubtful.append(dict(day=day,isin=isin,key=key,category=category,
                                 shares=book.shares[isin],last_mark_exposure=exposure))

    for i,day in enumerate(days[:-2]):
        if day not in market:
            raise ValueError(f'Missing KOSPI gate close {day}')
        market_window.append(market[day])
        bars, volume, signal = {},{},[]
        for isin,code,op,cl,v,state,index,momentum,link in db.execute("""
            SELECT p.isin,p.code,p.open,p.close,p.volume,p.state,m.price_index,m.momentum_252,m.link_status
            FROM execution_bars p LEFT JOIN economic_momentum m USING(day,isin) WHERE p.day=?""",(day,)):
            bars[isin] = (op,cl,state)
            volume[isin] = v
            if index is not None:
                h = histories.setdefault(isin,deque(maxlen=253))
                if link!='CONTIGUOUS_RAW_RETURN':
                    h.clear()
                h.append((index,v))
            if momentum is not None:
                signal.append((isin,code,momentum,cl))
        if day<START:
            continue
        counts['eligible_observations'] += len(signal)
        counts['excluded_or_unready_observations'] += len(bars)-len(signal)
        if day!=START:
            interest(book,day,days[i-1],annual)
        for key,isin,amount in dividends.pop(day,[]):
            book.post(day,'archived_gross_dividend_paid',isin=isin,cash=amount,unblock=key)
        book.settle(day)
        for key,isin,kind,status,payment,terms in actions.get(day,[]):
            if kind=='split' and status=='V1_ACCOUNT_TERMS':
                known_split.add(isin)
                ratio = Fraction(terms['verified']['ratio_numerator'],terms['verified']['ratio_denominator'])
                book.cancel_unit_change_orders(day,isin)
                if book.shares[isin]:
                    book.split(day,key,isin,ratio)
                    if isin in holdings:
                        p = holdings[isin]
                        factor = D(ratio.numerator)/ratio.denominator
                        p[1] /= factor
                        p[2] /= factor
                    if isin in last_prices:
                        last_prices[isin] = int(D(last_prices[isin])*ratio.denominator/ratio.numerator)
                continue
            if not book.shares[isin] or kind=='third_party_allotment':
                continue
            if kind=='cash_dividend' and payment and payment>day:
                marker = 'dividend:'+key
                flag(day,isin,marker,'DIVIDEND_AMOUNT_PENDING_ON_EX_DATE')
                dividends[payment].append((marker,isin,D(terms['per_share_krw'])*book.shares[isin]))
            else:
                flag(day,isin,'action:'+key,'UNVERIFIED_'+kind.upper())
                book.cancel_unit_change_orders(day,isin)
                if scheduled_bonus and key=='20190228000002':
                    ratio = Fraction(terms['ratio'])
                    book.award(day,key,isin,isin,ratio,terms['planned_delivery'])
                    factor = 1+D(ratio.numerator)/ratio.denominator
                    holdings[isin][1] /= factor
                    holdings[isin][2] /= factor
                    known_split.add(isin)
        for isin in tuple(book.shares):
            if (day,isin) in exits:
                flag(day,isin,'exit:'+isin,'UNVERIFIED_DELISTING_'+exits[day,isin])
        before = len(book.log)
        book.execute(day,days[i+2],bars,volume=volume,participation=participation)
        for event in book.log[before:]:
            if event['event']!='fill':
                continue
            isin = event['isin']
            if event['side']=='BUY':
                entry = D(event['price'])*(1+FEE+SLIPPAGE)
                holdings[isin] = [i,entry,entry]
            else:
                if not any(asset==isin and n for _,asset,n,_ in book.claims.values()):
                    holdings.pop(isin)
                cool[isin] = i
        marks = {}
        for isin in book.shares:
            bar = bars.get(isin)
            if bar and bar[2]==VALID:
                close = bar[1]
                prior = last_prices.get(isin)
                if (prior and abs(close-prior)*100>35*prior and isin not in known_split
                        and holdings[isin][0]!=i):
                    flag(day,isin,'jump:'+day+':'+isin,'UNVERIFIED_HELD_PRICE_DISCONTINUITY')
                known_split.discard(isin)
                last_prices[isin] = close
                marks[isin] = close
            elif isin in last_prices:
                flag(day,isin,'missing:'+isin,'UNVERIFIED_HELD_MARK_OR_HALT')
                # No stale marks are used for NAV; positions and orders are retained.
        if day!=END:
            for isin,qty in book.shares.items():
                if isin not in marks:
                    continue
                opened,entry,peak = holdings[isin]
                peak = holdings[isin][2] = max(peak,marks[isin])
                if (marks[isin]<=max(entry*(1-D(str(risk['stop_loss']))),peak*(1-D(str(risk['trail_stop']))))
                        or i-opened>=risk['max_hold_days']):
                    book.queue(day,isin,'SELL',1,qty)
            pending_assets = {asset for _,asset,n,_ in book.claims.values() if n}
            slots = risk['max_positions']-len(book.shares.keys() | pending_assets)
            # Orders reserve cash already settled; no contingent slots or sale proceeds.
            if slots>0 and len(market_window)==61 and check_market_gate(np.array(market_window),60,cfg):
                rank = sorted(s[2] for s in signal)
                budget = (book.buying_power-book.reserved)/slots
                for isin,code,momentum,close in sorted(signal,key=lambda s:(-s[2],s[1])):
                    rs = 100*bisect_right(rank,momentum)/len(rank)
                    if rs<cfg['signal']['minervini']['rs_min']:
                        break
                    if isin in book.shares or isin in pending_assets or i-cool.get(isin,-1000)<cfg['cooldown_days']:
                        continue
                    h = np.asarray(histories[isin])
                    if len(h)!=253:
                        raise ValueError('Signal eligible without aligned prices and volume')
                    if check_signal(h[:,0],h[:,1],252,rs,cfg):
                        limit = buy_limit(days[i+1],close)
                        requested = int(budget/(D(limit)*(1+FEE+SLIPPAGE)))
                        if requested:
                            book.queue(day,isin,'BUY',limit,requested)
                            counts['buy_signals_queued'] += 1
                            slots -= 1
                        if not slots:
                            break
        marks_log[day] = marks
        daily.append(book.snapshot(day,marks))
    reconcile_journal(INITIAL,book.log,daily,marks_log)
    return dict(daily=daily,journal=book.log,exceptions=doubtful,counts=dict(counts))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path)
    p.add_argument('market',type=Path)
    p.add_argument('--participation',type=D,default=D('.01'))
    p.add_argument('--scheduled-bonus',action='store_true')
    a = p.parse_args()
    market = {r[0]:r[4] for r in json.loads(a.market.read_text())[1:]}
    cfg = load_config()
    with sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        out = replay(db,market,a.participation,cfg,scheduled_bonus=a.scheduled_bonus)
    out['inputs'] = dict(database_sha256=digest(a.database),market_sha256=digest(a.market),
                         config_sha256=digest(ROOT/'backtest/strategy_config.yaml'),
                         participation=str(a.participation),scheduled_bonus=a.scheduled_bonus,strategy_sha256=digest(ROOT/'backtest/strategy.py'))
    print(json.dumps(out,default=str))


if __name__=='__main__':
    main()
