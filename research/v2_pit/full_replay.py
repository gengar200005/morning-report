"""Full-period PIT application of the frozen V1 T10/CD60 backtest rules."""
import argparse
from bisect import bisect_left, bisect_right
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


def quote_tick(day, price):
    bands = ((0,1),(1000,5),(5000,10),(10000,50),(50000,100),(100000,500),(500000,1000))
    if day >= '20230125':
        bands = ((0,1),(2000,5),(5000,10),(20000,50),(50000,100),(200000,500),(500000,1000))
    return next(tick for floor,tick in reversed(bands) if price>=floor)


def buy_limit(day, close):
    tick = quote_tick(day,close)
    return close//tick*tick


def action_inventory(db, days, end=END):
    actions = defaultdict(list)
    for key,isin,kind,status,day,payment,terms,announced in db.execute("""
        SELECT event_id,isin,kind,status,effective_date,payment_or_delivery,terms,announcement_date
        FROM corporate_actions WHERE isin IS NOT NULL
        AND coalesce(effective_date,json_extract(terms,'$.inventory_date'))<=?""",(end,)):
        payload = json.loads(terms)
        day = day or payload.get('inventory_date')
        if not day or day>end:
            continue
        # Legal non-session dates take effect before the next opening.
        idx = bisect_left(days,day)
        if idx==len(days):
            continue
        actions[days[idx]].append((key,isin,kind,status,payment,payload,announced))
    return actions


def replay(db, market, participation, cfg, *, mode="verified", policy=None, end=END,
           execution=None, additional_actions=(), rebalance=None, session_days=None,
           start=START, initial=INITIAL):
    days = calendar(db) if session_days is None else session_days
    book = Account(initial,days)
    actions = action_inventory(db,days,end)
    for day,action in additional_actions:
        actions[day].append(action)
    exits = {(d,t):category for d,t,category in db.execute('SELECT delisted,isin,category FROM exit_audit WHERE isin IS NOT NULL AND delisted<=?',(end,))}
    holdings, cool, histories, last_prices = {},{},{},{}
    doubtful, daily, market_window = [],[],deque(maxlen=61)
    marks_log, dividends = {},defaultdict(list)
    counts = Counter()
    known_split = set()
    research = mode!='verified'
    stress = mode in ('stress','valuation-stress')
    fractional = {}
    modeled_issues = set()
    selections = defaultdict(list)
    opportunities = Counter()
    risk = cfg['risk']
    annual = D(str(cfg['execution']['cma_rate']))

    def flag(day,isin,key,category):
        if key not in book.unknown:
            exposure = book.shares[isin]*last_prices.get(isin,0)
            book.post(day,'valuation_exception',isin=isin,block=key,category=category)
            doubtful.append(dict(day=day,isin=isin,key=key,category=category,
                                 shares=book.shares[isin],last_mark_exposure=exposure))

    for i,day in enumerate(days[:-2]):
        if day>end:
            break
        if rebalance is not None and day<start:
            continue
        if rebalance is None and day not in market:
            raise ValueError(f'Missing KOSPI gate close {day}')
        if rebalance is None:
            market_window.append(market[day])
        bars, volume, signal = {},{},[]
        for isin,code,op,cl,v,state,index,momentum,link in db.execute("""
            SELECT p.isin,p.code,p.open,p.close,p.volume,p.state,m.price_index,m.momentum_252,m.link_status
            FROM execution_bars p LEFT JOIN economic_momentum m USING(day,isin) WHERE p.day=?""",(day,)):
            bars[isin] = (op,cl,state)
            volume[isin] = v
            if index is not None and policy is None and rebalance is None:
                h = histories.setdefault(isin,deque(maxlen=253))
                if link!='CONTIGUOUS_RAW_RETURN':
                    h.clear()
                h.append((index,v))
            if momentum is not None:
                signal.append((isin,code,momentum,cl))
        if day<start:
            continue
        counts['eligible_observations'] += len(signal)
        counts['excluded_or_unready_observations'] += len(bars)-len(signal)
        if day!=START:
            interest(book,day,days[i-1],annual)
        for key,isin,amount in dividends.pop(day,[]):
            book.resolve_issue(day,key,'Archived payment date and per-share cash terms',
                               isin=isin,cash=amount)
        book.settle(day)
        for key,isin,kind,status,payment,terms,announced in actions.get(day,[]):
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
                pay_idx = bisect_left(days,payment)
                amount = D(terms['per_share_krw'])*book.shares[isin]
                if pay_idx<len(days):
                    dividends[days[pay_idx]].append((marker,isin,amount))
                else:
                    dividends[payment].append((marker,isin,amount))
            else:
                flag(day,isin,'action:'+key,'UNVERIFIED_'+kind.upper())
                book.cancel_unit_change_orders(day,isin)
                if (kind=='bonus' and status=='TERMS_CONFIRMED_SETTLEMENT_UNVERIFIED'
                        and announced and announced<day
                        and terms.get('planned_delivery') and terms.get('ratio')):
                    ratio = Fraction(terms['ratio'])
                    due_idx = bisect_left(days,terms['planned_delivery'])+(5 if mode=='stress' else 0)
                    amount = book.shares[isin]*ratio
                    if due_idx>=len(days):
                        continue
                    due = days[due_idx]
                    book.post(day,'public_bonus_terms',isin=isin,event_id=key,
                              estimated_whole=int(amount),fraction=str(amount-int(amount)),
                              stated_schedule=terms['planned_delivery'])
                    factor = 1+D(ratio.numerator)/ratio.denominator
                    holdings[isin][1] /= factor
                    holdings[isin][2] /= factor
                    known_split.add(isin)
                    if research:
                        book.award(day,key,isin,isin,ratio,due)
                        modeled_issues.add('action:'+key)
                        if amount.denominator!=1:
                            fraction = amount-int(amount)
                            fractional[key+':fraction'] = [isin,fraction,terms['planned_delivery'],None]
        for isin in tuple(book.shares):
            if (day,isin) in exits:
                flag(day,isin,'exit:'+isin,'UNVERIFIED_DELISTING_'+exits[day,isin])
        # Resolve mark gaps before matching orders so a sale on the
        # resumption opening does not leave a stale valuation block.
        for marker in sorted(book.unknown):
            if marker.startswith('missing:'):
                isin = marker.removeprefix('missing:')
                if isin in bars and bars[isin][2]==VALID:
                    book.resolve_issue(day,marker,'Positive-volume KRX mark returned',isin=isin)
        before = len(book.log)
        guard = execution.guard(db,day,bars) if execution is not None else None
        book.execute(day,days[i+2],bars,volume=volume,participation=participation,
                     opening_guard=guard)
        for event in book.log[before:]:
            if event['event']!='fill':
                continue
            isin = event['isin']
            if event['side']=='BUY':
                entry = D(event['price'])*(1+FEE+SLIPPAGE)
                holdings[isin] = [i,entry,entry]
            else:
                if not book.shares.get(isin) and not any(asset==isin and n for _,asset,n,_ in book.claims.values()):
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
        # A delivered sale does not erase unsettled entitlements. Pending
        # stock rights can have their own raw mark even after the old lot sold.
        for _,asset,quantity,_ in book.claims.values():
            bar = bars.get(asset)
            if quantity and bar and bar[2]==VALID:
                marks[asset] = bar[1]
        if day!=end and rebalance is not None:
            rebalance(book, i, day, days[i+1], bars, marks, last_prices)
        if day!=end and rebalance is None:
            if policy is not None:
                policy.prepare(day)
            for isin,qty in book.shares.items():
                if isin not in marks:
                    continue
                opened,entry,peak = holdings[isin]
                peak = holdings[isin][2] = max(peak,marks[isin])
                should_exit = (marks[isin]<=max(entry*(1-D(str(risk['stop_loss']))),
                                                    peak*(1-D(str(risk['trail_stop']))))
                               or i-opened>=risk['max_hold_days']) if policy is None else (
                                   policy.exit(day,isin,marks[isin],entry))
                if should_exit:
                    book.queue(day,isin,'SELL',1,qty)
            pending_assets = {asset for _,asset,n,_ in book.claims.values() if n}
            slots = risk['max_positions']-len(book.shares.keys() | pending_assets)
            # Orders reserve cash already settled; no contingent slots or sale proceeds.
            if policy is not None:
                budget = (book.buying_power-book.reserved)/slots if slots>0 else D(0)
                eligible_isins = {row[0] for row in signal}
                for isin,code in policy.entries(day):
                    opportunities['ranked_signal_occurrences'] += 1
                    if isin not in eligible_isins:
                        opportunities['not_currently_eligible'] += 1
                        continue
                    if isin in book.shares or isin in pending_assets:
                        opportunities['already_held_or_pending'] += 1
                        continue
                    if slots<=0:
                        opportunities['slots_unavailable'] += 1
                        continue
                    limit = (execution.limit(days[i+1],bars[isin][1]) if execution is not None
                             else buy_limit(days[i+1],bars[isin][1]))
                    requested = int(budget/(D(limit)*(1+FEE+SLIPPAGE)))
                    if requested:
                        book.queue(day,isin,'BUY',limit,requested)
                        selections[day].append(code)
                        counts['buy_signals_queued'] += 1
                        slots -= 1
                    else:
                        opportunities['cash_too_small_for_one_share'] += 1
            elif policy is None and slots>0 and len(market_window)==61 and check_market_gate(np.array(market_window),60,cfg):
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
                            selections[day].append(code)
                            counts['buy_signals_queued'] += 1
                            slots -= 1
                        if not slots:
                            break
        marks_log[day] = marks
        row = book.snapshot(day,marks)
        if policy is not None or rebalance is not None:
            row['marked_positions'] = {isin:qty*marks[isin] for isin,qty in book.shares.items()
                                       if isin in marks}
        if research:
            # Post-close analytical values never enter Account.cash, claims,
            # position sizing, stop decisions, or the PIT rank universe.
            overlays = {}
            handled = set(modeled_issues)
            for key,isin,amount in (event for events in dividends.values() for event in events):
                handled.add(key)
                overlays[key] = amount
            for key,(isin,fraction,listing,fixed) in fractional.items():
                raw = bars.get(isin)
                close = raw[1] if raw and raw[2]==VALID else None
                if fixed is None and day>=listing and close is not None:
                    fixed = fractional[key][3] = close
                value = fixed if fixed is not None else close
                if value is not None:
                    handled.add(key)
                    overlays[key] = D(value)*D(fraction.numerator)/fraction.denominator*(0 if stress else 1)
            for isin in set(book.shares)-marks.keys():
                raw = bars.get(isin)
                marker = 'missing:'+isin
                if raw and raw[2]=='ZERO_VOLUME' and last_prices.get(isin) and marker in book.unknown:
                    handled.update((isin,marker))
                    overlays[marker] = D(book.shares[isin]*last_prices[isin])*(D('.5') if stress else 1)
            unexplained = sorted(set(row['unresolved'])-handled)
            row.update(research_nav=None if unexplained else row['cash']+row['stock']+
                       row['receivables']-row['payables']+sum(overlays.values(),D(0)),
                       valuation_overlays=overlays,research_unresolved=unexplained)
        daily.append(row)
    reconcile_journal(initial,book.log,daily,marks_log)
    return dict(daily=daily,journal=book.log,exceptions=doubtful,counts=dict(counts),
                selections=dict(selections),mode=mode,opportunities=dict(opportunities))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path)
    p.add_argument('market',type=Path)
    p.add_argument('--participation',type=D,default=D('.01'))
    p.add_argument('--mode',choices=('verified','exploratory','stress','valuation-stress'),default='verified')
    p.add_argument('--scheduled-bonus',action='store_const',dest='mode',const='exploratory',
                   help='Compatibility alias for --mode exploratory')
    a = p.parse_args()
    market = {r[0]:r[4] for r in json.loads(a.market.read_text())[1:]}
    cfg = load_config()
    with sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        out = replay(db,market,a.participation,cfg,mode=a.mode)
    out['inputs'] = dict(database_sha256=digest(a.database),market_sha256=digest(a.market),
                         config_sha256=digest(ROOT/'backtest/strategy_config.yaml'),
                         participation=str(a.participation),mode=a.mode,strategy_sha256=digest(ROOT/'backtest/strategy.py'))
    print(json.dumps(out,default=str))


if __name__=='__main__':
    main()
