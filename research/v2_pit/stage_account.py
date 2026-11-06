"""Fixed account regressions with preserved V1 Book and actual KRX opening bars."""
import argparse
from decimal import Decimal as D
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import sys

from foundation import digest
from smoke import ENGINE_HASH

# The fixed 2017/2018 cases precede the May 2019 reduction.
SELL_TAX_2017_2018 = D('.003')
SLIPPAGE = D('.0005')


def run(path, engine):
    for name, sha in ENGINE_HASH.items():
        if digest(engine/name)!=sha:
            raise ValueError('Preserved engine hash mismatch')
    sys.path.insert(0,str(engine.resolve()))
    from execution import Book, FEE, QuoteRule, reconcile

    rule = QuoteRule(1,10**9,((0,1),))
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        def trade(book, isin, side, decision, fill, quantity, limit=None):
            days = db.execute('SELECT day FROM sessions WHERE day>=? ORDER BY day LIMIT 2',
                              (decision,)).fetchall()
            if days!=[(decision,),(fill,)]:
                raise ValueError('Only next-session orders are supported')
            book.time = f'{decision} after close'
            key = book.submit(isin,side,quantity,limit)
            book.time = f'{fill} open'
            row = db.execute('SELECT open,state FROM execution_bars WHERE day=? AND isin=?',
                             (fill,isin)).fetchone()
            if row is None or row[1]!='POSITIVE_VOLUME_VALID_BAR':
                book.close_order(key,rejected=True)
                book.event('opening_unavailable',isin)
                return False
            opening = row[0]
            book.accepted(key)
            gross = D(opening)*quantity
            slippage = gross*SLIPPAGE
            if side=='BUY' and D(opening)*(1+SLIPPAGE)>limit:
                book.cancel_request(key)
                book.close_order(key)
                return False
            cash_before = book.cash
            book.fill(key,f'case-{key}',quantity,opening,rule)
            tax = gross*SELL_TAX_2017_2018 if side=='SELL' else D(0)
            book.cash -= slippage+tax
            book.event('modeled_execution_cost',isin,slippage=slippage,sell_tax=tax,
                       cash_delta=-slippage-tax)
            expected = cash_before + (-gross if side=='BUY' else gross)-gross*FEE-slippage-tax
            reconcile(book.cash,expected)
            return True

        samsung = 'KR7005930003'
        split = Book(10_000_000,slots=1)
        if not trade(split,samsung,'BUY','20180425','20180426',2,3_000_000):
            raise ValueError('Split fixture buy did not fill')
        for day in ('20180430','20180502','20180503'):
            if db.execute('SELECT state FROM execution_bars WHERE day=? AND isin=?',
                          (day,samsung)).fetchone()!=('ZERO_VOLUME',):
                raise ValueError('Split fixture suspension disagrees with source')
        split.time = '20180503 legal conversion'
        split.apply_action('samsung-split',samsung,'split',ratio=Fraction(50))
        if split.positions[samsung].shares!=100:
            raise ValueError('Split did not reconcile shares')
        if not trade(split,samsung,'SELL','20180504','20180508',100) or split.positions:
            raise ValueError('Split fixture sell did not close position')

        dividend = Book(1_000_000,slots=1)
        if not trade(dividend,samsung,'BUY','20180626','20180627',10,60_000):
            raise ValueError('Dividend fixture buy did not fill')
        terms, = db.execute("""SELECT terms FROM corporate_actions
            WHERE isin=? AND kind='cash_dividend' AND effective_date='20180628'""",
            (samsung,)).fetchone()
        terms = json.loads(terms)
        payment, amount = terms['payment_date'], D(terms['per_share_krw'])
        if (payment,amount)!=('20180820',D(354)):
            raise ValueError('Dividend terms changed')
        # The amount was confirmed after the ex-date. This fixed holder remains
        # invested and recognizes the gross receivable only after announcement.
        dividend.time = '20180628 ex-date'
        eligible = dividend.positions[samsung].shares
        dividend.event('entitlement_quantity_recorded',samsung,quantity=eligible)
        dividend.time = '20180801 after July 31 board decision'
        dividend.apply_action(terms['event_id'],samsung,'cash_dividend',due=1,per_share=amount)
        before = dividend.cash
        dividend.settle(0)
        reconcile(dividend.cash,before)
        dividend.time = f'{payment} payment'
        dividend.settle(1)
        reconcile(dividend.cash,before+eligible*amount)
        if dividend.rights:
            raise ValueError('Dividend receivable did not clear')

        code = '117930'
        isin, = db.execute("SELECT isin FROM execution_bars WHERE day='20170303' AND code=?",
                           (code,)).fetchone()
        actual = Book(100_000,slots=1)
        if not trade(actual,isin,'BUY','20170302','20170303',100,100):
            raise ValueError('Delisting fixture buy did not fill')
        if trade(actual,isin,'SELL','20170306','20170307',100):
            raise ValueError('Post-delisting fill must be impossible')
        if actual.positions[isin].shares!=100:
            raise ValueError('Unresolved delisted holding disappeared')
        actual.event('valuation_unresolved_after_delisting',isin,nav=None)
        return {'split':split.log,'dividend':dividend.log,'delisting':actual.log}


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('engine',type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.database,args.engine),default=str,indent=2))
