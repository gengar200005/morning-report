"""Event-driven, conservative KOSPI account research ledger."""
from collections import Counter
from datetime import date
from decimal import Decimal as D
from fractions import Fraction
import math

# Legal effective dates, applied to modeled T+2 settlement dates.
TAX_BP = (('20160101',30),('20190603',25),('20210101',23),('20230101',20),
          ('20240101',18),('20250101',15),('20260101',20))
FEE = D('.0015')
SLIPPAGE = D('.0005')
VALID = 'POSITIVE_VOLUME_VALID_BAR'


def sale_tax(day):
    if not '20160101'<=day<='20261231':
        raise ValueError('Tax date outside supported years')
    return D(next(bp for start,bp in reversed(TAX_BP) if start<=day))/10000


class Account:
    def __init__(self, cash):
        self.cash = D(cash)
        self.shares = Counter()
        self.claims = {}
        self.unknown = set()
        self.orders = []
        self.log = []
        self.last_marks = {}

    def post(self, day, event, *, isin='', shares=0, cash=D(0), claim=None,
             remove=None, block=None, unblock=None, **details):
        if type(shares) is not int:
            raise ValueError('Positions require integer shares')
        if self.shares[isin]+shares<0 or self.cash+cash<0:
            raise ValueError('Insufficient holdings or cash')
        if claim and claim[0] in self.claims:
            raise ValueError('Duplicate claim')
        if remove and remove not in self.claims:
            raise ValueError('Unknown claim')
        self.cash += cash
        if shares:
            self.shares[isin] += shares
            if not self.shares[isin]:
                del self.shares[isin]
        if claim:
            self.claims[claim[0]] = claim[1:]
        if remove:
            del self.claims[remove]
        if block:
            self.unknown.add(block)
        if unblock:
            self.unknown.remove(unblock)
        self.log.append(dict(day=day,event=event,isin=isin,shares=shares,cash=cash,
                             claim=claim,remove=remove,block=block,unblock=unblock,**details))

    @property
    def buying_power(self):
        return self.cash+sum((min(v,D(0)) for _,_,_,v in self.claims.values()),D(0))

    def queue(self, day, isin, side, limit, requested):
        if (side not in ('BUY','SELL') or type(requested) is not int or requested<1
                or type(limit) is not int or limit<1):
            raise ValueError('Invalid order terms')
        if side=='BUY':
            shares = min(requested,int(self.buying_power/(limit*(1+FEE+SLIPPAGE))))
        else:
            shares = min(requested,self.shares[isin])
        self.post(day,'order_sized_at_close',isin=isin,side=side,quantity=shares,
                  requested=requested,limit=limit)
        if shares:
            self.orders.append((day,isin,side,limit,shares))

    def execute(self, day, settlement, bars):
        for decision,isin,side,limit,shares in self.orders:
            bar = bars.get(isin)
            if day<=decision:
                raise ValueError('Order cannot fill before the following session')
            if not bar or bar[2]!=VALID:
                self.post(day,'opening_unavailable',isin=isin,side=side,decision=decision)
                continue
            price = bar[0]
            gross = D(price)*shares
            costs = gross*(FEE+SLIPPAGE)
            if ((side=='BUY' and (price>limit or gross+costs>self.buying_power))
                    or (side=='SELL' and (price<limit or self.shares[isin]<shares))):
                self.post(day,'conditional_order_unfilled',isin=isin,side=side,decision=decision)
                continue
            tax = gross*sale_tax(settlement) if side=='SELL' else D(0)
            amount = gross-costs-tax if side=='SELL' else -(gross+costs)
            receivable = (f'fill:{day}:{isin}:{len(self.log)}',settlement,'',0,amount)
            self.post(day,'fill',isin=isin,shares=shares if side=='BUY' else -shares,
                      claim=receivable,
                      decision=decision,side=side,price=price,fee=gross*FEE,
                      slippage=gross*SLIPPAGE,sell_tax=tax,settlement=settlement)
        self.orders.clear()

    def settle(self, day):
        for event,(due,asset,quantity,value) in list(self.claims.items()):
            if due==day:
                self.post(day,'settlement',isin=asset,shares=quantity,cash=value,remove=event)
            elif due<day:
                raise ValueError('Settlement date missing from replay')

    def cancel_unit_change_orders(self, day, isin):
        for order in tuple(self.orders):
            if order[1]==isin:
                self.orders.remove(order)
                self.post(day,'unit_change_order_cancelled',isin=isin,decision=order[0])

    def split(self, day, key, isin, ratio, *, fraction_cash=None, fraction_due=None):
        self.cancel_unit_change_orders(day,isin)
        before = self.shares[isin]
        if not before:
            return
        if type(ratio) is not Fraction or ratio<=0:
            raise ValueError('Invalid split ratio')
        total = before*ratio
        if total.denominator==1:
            self.post(day,'split',isin=isin,shares=int(total)-before)
        else:
            self.award(day,key,isin,isin,ratio,day,replace=True,
                       fraction_cash=fraction_cash,fraction_due=fraction_due)

    def award(self, day, key, origin, asset, ratio, due, *,
              replace=False, fraction_cash=None, fraction_due=None):
        if not self.shares[origin]:
            return
        if ((fraction_cash is None)!=(fraction_due is None)
                or fraction_due is not None and (fraction_due<day or D(fraction_cash)<0)):
            raise ValueError('Invalid fractional settlement')
        if not day<=due or type(ratio) is not Fraction or ratio<=0:
            raise ValueError('Invalid verified corporate action terms')
        amount = self.shares[origin]*ratio
        whole = int(amount)
        if replace:
            self.cancel_unit_change_orders(day,origin)
            self.post(day,'conversion_surrender',isin=origin,shares=-self.shares[origin])
        if whole:
            self.post(day,'share_entitlement',isin=origin,claim=(key,due,asset,whole,D(0)))
        if whole!=amount:
            if fraction_cash is None or fraction_due is None:
                self.post(day,'fraction_value_unknown',isin=origin,block=key+':fraction',
                          fractional_shares=str(amount-whole))
            else:
                self.post(day,'fraction_receivable',isin=origin,
                          claim=(key+':fraction',fraction_due,'',0,D(fraction_cash)))

    def snapshot(self, day, marks):
        missing = sorted((set(self.shares) | {a for _,a,n,_ in self.claims.values() if n})-marks.keys())
        stock = sum(n*marks[t] for t,n in self.shares.items() if t in marks)
        rights = sum((v+(n*marks[a] if n and a in marks else 0)
                      for _,a,n,v in self.claims.values()),D(0))
        reasons = sorted(self.unknown | set(missing))
        nav = None if reasons else self.cash+stock+rights
        return dict(day=day,cash=self.cash,positions=dict(self.shares),stock=stock,
                    receivables=sum((v+(n*marks.get(a,0)) for _,a,n,v in self.claims.values() if v>=0),D(0)),
                    payables=-sum((v for _,_,_,v in self.claims.values() if v<0),D(0)),
                    nav=nav,unresolved=reasons)


def reconcile_journal(initial, journal, snapshots, daily_marks):
    """Rebuild cash, quantities, receivables and NAV from emitted postings."""
    cash, positions, claims, pending = D(initial), Counter(), {}, set()
    pos = 0
    for row in snapshots:
        day = row['day']
        while pos<len(journal) and journal[pos]['day']<=day:
            event = journal[pos]
            cash += event['cash']
            positions[event['isin']] += event['shares']
            if event['claim']:
                key,due,isin,quantity,value = event['claim']
                claims[key] = (isin,quantity,value)
            if event['remove']:
                del claims[event['remove']]
            if event['block']:
                pending.add(event['block'])
            if event['unblock']:
                pending.remove(event['unblock'])
            pos += 1
        held = dict(+positions)
        marks = daily_marks[day]
        stock = sum(marks.get(t,0)*n for t,n in held.items())
        rights = sum(v+n*marks.get(t,0) for t,n,v in claims.values() if v>=0)
        payable = -sum(v for _,_,v in claims.values() if v<0)
        missing = set(held).union(t for t,n,v in claims.values() if n).difference(marks)
        nav = cash+stock+rights-payable if not pending and not missing else None
        if (cash,held,stock,rights,payable,nav)!=(row['cash'],row['positions'],row['stock'],
                                         row['receivables'],row['payables'],row['nav']):
            raise ValueError(f'Independent daily reconciliation failed: {day}')
    if pos!=len(journal):
        raise ValueError('Unreconciled postings')


def metrics(rows):
    if len(rows)<2 or any(r['nav'] is None or r['nav']<=0 for r in rows):
        return None
    elapsed = (date.fromisoformat(rows[-1]['day'])-date.fromisoformat(rows[0]['day'])).days
    if not elapsed:
        return None
    high, drawdown = rows[0]['nav'],0.0
    for row in rows:
        high = max(high,row['nav'])
        drawdown = min(drawdown,float(row['nav']/high)-1)
    return dict(cagr=math.expm1(math.log(float(rows[-1]['nav']/rows[0]['nav']))*365.25/elapsed),
                mdd=drawdown)
