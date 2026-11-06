"""Replay fixed research paths against actual bars and documented event terms."""
import argparse
from decimal import Decimal as D
from fractions import Fraction
import json
from pathlib import Path
import sqlite3

from economic_account import Account, VALID, metrics, reconcile_journal

SAMSUNG = 'KR7005930003'
HANJIN = 'KR7117930008'
HYUNDAI = 'KR7005380001'
INITIAL = 10_000_000

ORDERS = {
    '20170302': (HANJIN,'BUY',100,10_000),
    '20170303': (HANJIN,'SELL',1,10_000),
    '20180425': (SAMSUNG,'BUY',3_000_000,10_000),
    '20180427': (SAMSUNG,'SELL',1,10_000),  # no opening during the split halt
    '20180504': (SAMSUNG,'SELL',1,10_000),
    '20180510': (HYUNDAI,'BUY',200_000,10_000),
    '20180515': (HYUNDAI,'SELL',1,10_000),
    '20180626': (SAMSUNG,'BUY',60_000,10_000),
    '20180629': (SAMSUNG,'SELL',1,10_000),  # retain dividend entitlement
}


def replay(db, miss_last_sale=False):
    dates = [r[0] for r in db.execute("SELECT day FROM sessions WHERE day BETWEEN '20170302' AND '20180824' ORDER BY day")]
    book = Account(INITIAL,dates)
    days = dates[:-2]  # keep the final two calendar dates for settlement lookup
    rows, marks_by_day = [], {}
    payment, per_share = db.execute("""
        SELECT payment_or_delivery,json_extract(terms,'$.per_share_krw') FROM corporate_actions
        WHERE isin=? AND kind='cash_dividend' AND effective_date='20180628'""",(SAMSUNG,)).fetchone()
    if (payment,D(per_share))!=('20180820',D(354)):
        raise ValueError('Unexpected dividend source terms')
    scheduled = ORDERS.copy()
    if miss_last_sale:
        scheduled['20170306'] = scheduled.pop('20170303')
    entitlement = 0
    for i,day in enumerate(days):
        bars = dict((isin,(op,cl,state)) for isin,op,cl,state in db.execute("""
            SELECT isin,open,close,state FROM execution_bars
            WHERE day=? AND isin IN (?,?,?)""",(day,SAMSUNG,HANJIN,HYUNDAI)))
        if day=='20180503' and book.shares[SAMSUNG]:
            book.split(day,'samsung-split',SAMSUNG,Fraction(50))
            book.last_marks[SAMSUNG] = D(book.last_marks[SAMSUNG])/50
        if day=='20170307' and book.shares[HANJIN]:
            book.post(day,'delisting_recovery_unknown',isin=HANJIN,block='hanjin-delisting')
        if day=='20180628' and book.shares[SAMSUNG]:
            entitlement = book.shares[SAMSUNG]
            book.post(day,'dividend_amount_unknown',isin=SAMSUNG,block='samsung-q2',
                      eligible_shares=entitlement)
        if day=='20180801' and entitlement:
            book.post(day,'dividend_receivable',isin=SAMSUNG,unblock='samsung-q2',
                      claim=('samsung-q2',payment,'',0,D(per_share)*entitlement))
        book.settle(day)
        book.execute(day,dates[i+2],bars)
        marks = {t:b[1] for t,b in bars.items() if b[2]==VALID}
        if day in ('20180430','20180502','20180503') and book.shares[SAMSUNG]:
            if bars[SAMSUNG][2]!='ZERO_VOLUME':
                raise ValueError('Documented halt disagrees with bar')
            marks[SAMSUNG] = book.last_marks[SAMSUNG]
        book.last_marks.update(marks)
        if day in scheduled:
            book.queue(day,*scheduled[day])
        marks_by_day[day] = marks
        rows.append(book.snapshot(day,marks))
    reconcile_journal(INITIAL,book.log,rows,marks_by_day)
    approved = []
    for idx,row in enumerate(rows):
        if row['nav'] is not None:
            if not idx or rows[idx-1]['nav'] is None:
                approved.append([row['day'],row['day'],1])
            else:
                approved[-1][1] = row['day']
                approved[-1][2] += 1
    return dict(daily=rows,journal=book.log,metrics_computable=metrics(rows) is not None,
                confirmed_nav_windows=approved,
                unresolved_days=sum(r['nav'] is None for r in rows),
                end_nav=rows[-1]['nav'])


def miwon_terms(db):
    terms, = db.execute("""SELECT terms FROM corporate_actions
        WHERE event_id='20170310000026' AND kind='spin_off_and_conversion'""").fetchone()
    data = json.loads(terms)
    original = 8
    parent = original*Fraction(data['parent_ratio'])
    child = original*Fraction(data['child_ratio'])
    values = {}
    for code,amount in [('107590',parent),(data['child_code'],child)]:
        close, = db.execute("""SELECT close FROM execution_bars WHERE day=? AND code=?""",
                            (data['first_relisting_session'],code)).fetchone()
        values[code] = dict(whole_shares=int(amount),fraction=str(amount-int(amount)),
                            provisional_gross_cash=D(close)*(D((amount-int(amount)).numerator)/
                                                            (amount-int(amount)).denominator))
    if [r['whole_shares'] for r in values.values()]!=[21,58]:
        raise ValueError('Spin-off units disagree with preserved V1 case')
    return dict(original_shares=original,valuation_day=data['first_relisting_session'],
                delivery='UNVERIFIED',cash_payment='UNVERIFIED',terms=values)


def run(path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        regular, missed = replay(db), replay(db,True)
        spin = miwon_terms(db)
    fills = [e for e in regular['journal'] if e['event']=='fill']
    splits = [e for e in regular['journal'] if e['event']=='split']
    if len(fills)!=8 or len(splits)!=1 or fills[2]['shares']!=3 or splits[0]['shares']!=147:
        raise ValueError('Fixed round trips or split quantities changed')
    if fills[0]['price']!=63 or fills[1]['price']!=29:
        raise ValueError('Liquidation-window opening changed')
    first = {r['day']:r for r in regular['daily']}
    if first['20170303']['payables']!=D('631260') or first['20170306']['receivables']!=D('288550'):
        raise ValueError('Independent first-buy or first-sale settlement amount disagrees')
    if first['20170307']['cash']!=D('9368740') or first['20170308']['cash']!=D('9657290'):
        raise ValueError('Independent cash settlement disagrees')
    if not any(e['remove']=='samsung-q2' and e['cash']>0 for e in regular['journal']):
        raise ValueError('Dividend payment missing')
    if missed['end_nav'] is not None or missed['daily'][-1]['positions'].get(HANJIN)!=10_000:
        raise ValueError('Unknown delisting recovery was lost')
    if not regular['unresolved_days'] or regular['metrics_computable']:
        raise ValueError('Unknown dividend period must block whole-path metrics')
    return dict(fixed=regular,missed_delisting=missed,miwon_terms=spin)


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path)
    print(json.dumps(run(p.parse_args().database),default=str,indent=2))
