"""Frozen execution controls for Stage 4.1. E1 uses the unchanged account branch."""
from decimal import Decimal as D

from full_replay import buy_limit, quote_tick


def band(day, reference):
    tick = quote_tick(day,reference)
    width = (reference*3//10)//tick*tick
    bottom = reference-width
    unit = quote_tick(day,bottom)
    return (bottom+unit-1)//unit*unit, buy_limit(day,reference+width)


class Execution:
    def __init__(self, name, premium=D('.02')):
        self.name = name
        self.premium = premium

    def limit(self, day, previous_close):
        if self.name=='E1':
            return buy_limit(day,previous_close)
        _,upper = band(day,previous_close)
        return min(upper,buy_limit(day,int(D(previous_close)*(1+self.premium))))

    def guard(self, db, day, bars):
        if self.name=='E1':
            return None

        def opening(isin,side,limit,price):
            row = db.execute("""SELECT implied_reference_krw FROM krx_return_checks
                WHERE day=? AND isin=? AND rate_status='PASS'""",(day,isin)).fetchone()
            if row is None:
                return 'exchange_reference_unverified',False
            lower,upper = band(day,row[0])
            if not lower<=price<=upper or price%quote_tick(day,price):
                return 'opening_outside_modeled_band',False
            if (side=='BUY' and price==upper) or (side=='SELL' and price==lower):
                return 'limit_auction_unfilled',False
            if side=='BUY' and not lower<=limit<=upper:
                return 'submitted_limit_outside_band',False
            return None,self.name=='E3' and side=='BUY'

        return opening
