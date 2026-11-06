"""KODEX 200 integer-share benchmark with issuer distributions and raw marks."""
import argparse
from bisect import bisect_left, bisect_right
from datetime import datetime
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from economic_account import Account, VALID, reconcile_journal
from foundation import digest
from full_replay import START, END, INITIAL, calendar, interest

ETF = '069500'
SEOUL = ZoneInfo('Asia/Seoul')


def day(timestamp):
    return datetime.fromtimestamp(timestamp,SEOUL).strftime('%Y%m%d')


def market_data(path):
    chart = json.loads(path.read_text())['result']
    if chart['meta']['symbol']!='069500.KS' or chart.get('events',{}).get('splits'):
        raise ValueError('Unexpected instrument or split')
    quote = chart['indicators']['quote'][0]
    bars = {day(ts):(op,cl,v) for ts,op,cl,v in zip(chart['timestamp'],quote['open'],
            quote['close'],quote['volume'],strict=True)}
    dividends = {day(r['date']):D(str(r['amount'])) for r in chart['events']['dividends'].values()}
    return bars,dividends


def bridge_raw_quotes(prices, path):
    data = json.loads(path.read_text())
    if data['code']!=200 or any(r['symbolCode']!='A069500' for r in data['data']):
        raise ValueError('Unexpected secondary instrument')
    fallback = {r['date'][:10].replace('-',''):(r['openingPrice'],r['tradePrice'],r['accTradeVolume'])
                for r in data['data']}
    checked = 0
    repaired = []
    for d,(op,close,volume) in fallback.items():
        before = prices.get(d)
        if before and all(before):
            if before[:2]!=(op,close):
                raise ValueError(f'Raw source open/close disagreement: {d}')
            checked += 1
        elif START<=d<=END and op and close and volume:
            prices[d] = (op,close,volume)
            repaired.append(d)
    return dict(overlap_checked=checked,filled_dates=sorted(repaired))


def official_distributions(paths, days):
    pages = [json.loads(p.read_text()) for p in paths]
    rows = [r for p in pages for r in p['dividList']]
    if len({r['basicD'] for r in rows})!=len(rows) or any(p['totalCnt']!=len(rows) for p in pages):
        raise ValueError('Incomplete or duplicate issuer pagination')
    result = {}
    for row in rows:
        record,payment = row['basicD'],row['payD']
        if row['stkTicker']!=ETF:
            raise ValueError('Unexpected issuer ticker')
        if not START<=record<=END:
            continue
        ex = days[bisect_right(days,record)-2]
        settlement = days[bisect_left(days,payment)]
        if not ex<record<payment:
            raise ValueError('Invalid distribution chronology')
        result[ex] = (record,payment,settlement,D(row['dividA']),D(row['taxDividA']))
    return result


def replay(days, quotes, payouts, *, withhold=False):
    book = Account(INITIAL,days,etf=True)
    rows, mark_log, gaps = [],{},[]
    for i,session in enumerate(days[:-2]):
        if session<START:
            continue
        if session!=START:
            interest(book,session,days[i-1],D('.03'))
        book.settle(session)
        if session in payouts and book.shares[ETF]:
            record,payment,settlement,gross,tax_basis = payouts[session]
            tax = min(gross,tax_basis)*D('.154') if withhold else D(0)
            amount = (gross-tax)*book.shares[ETF]
            book.post(session,'issuer_distribution_receivable',isin=ETF,
                      claim=('distribution:'+record,settlement,'',0,amount),
                      payment=payment,unit_tax=tax)
        opening,close,volume = quotes.get(session,(None,None,None))
        bars = {ETF:(int(opening),int(close),VALID)} if opening and close and volume else {}
        if not bars:
            gaps.append(session)
            if book.orders and not opening:
                book.post(session,'benchmark_fill_price_unverified',isin=ETF,
                          block='missing_etf_open:'+session)
        book.execute(session,days[i+2],bars,volume={ETF:volume or 0},participation=D('.01'))
        if session!=END and close:
            # Previous close limit, integer sizing, and available cash after payment.
            limit = int(close)//5*5
            book.queue(session,ETF,'BUY',limit,10**8)
        marks = {ETF:int(close)} if close else {}
        mark_log[session] = marks
        rows.append(book.snapshot(session,marks))
    reconcile_journal(INITIAL,book.log,rows,mark_log)
    return dict(daily=rows,journal=book.log,raw_bar_gaps=gaps)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path)
    p.add_argument('quotes',type=Path)
    p.add_argument('issuer',type=Path,nargs='+')
    p.add_argument('--secondary',type=Path,required=True)
    a = p.parse_args()
    with sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        days = calendar(db)
    prices,vendor_dividends = market_data(a.quotes)
    price_crosscheck = bridge_raw_quotes(prices,a.secondary)
    payouts = official_distributions(a.issuer,days)
    differences = {d:[str(payouts[d][3]) if d in payouts else None,str(vendor_dividends[d]) if d in vendor_dividends else None]
                   for d in set(payouts)|set(vendor_dividends)
                   if START<=d<=END and (d not in payouts or d not in vendor_dividends or payouts[d][3]!=vendor_dividends[d])}
    print(json.dumps(dict(gross=replay(days,prices,payouts),retail_withholding=replay(days,prices,payouts,withhold=True),
                          issuer_events=payouts,vendor_differences=differences,price_crosscheck=price_crosscheck,
                          inputs={p.name:digest(p) for p in [a.database,a.quotes,a.secondary,*a.issuer]}),default=str))


if __name__=='__main__':
    main()
