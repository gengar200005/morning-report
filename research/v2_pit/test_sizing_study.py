import unittest
from decimal import Decimal as D

import pandas as pd

from economic_account import Account, VALID
from execution_models import Execution
from sizing_study import Rebalance, benchmark, targets


class SizingStudyTest(unittest.TestCase):
    days = ['20220103','20220104','20220105','20220106','20220107','20220110','20220111','20220112']

    def test_rank_matching_is_fixed_and_excludes_selected(self):
        frame = pd.DataFrame(dict(day=[self.days[0]]*4,isin=list('DBAC'),
            M4=[0,1,1,-1],cap_cell=[2,1,1,1],turn_cell=[2,1,1,1]))
        self.assertEqual(targets(frame,1)[self.days[0]],('A',))
        self.assertEqual(targets(frame,1,1101),targets(frame,1,1101))
        self.assertIn(targets(frame,1,1101)[self.days[0]][0],('B','C'))

    def test_sale_funds_cannot_be_used_before_settlement(self):
        days = self.days
        execution = Execution('E2')
        book = Account(0,days)
        book.post(days[0],'fixture',isin='old',shares=100)
        plan = Rebalance({days[0]:('new',)},1,execution)
        bars = {x:(100,100,VALID) for x in ('old','new')}
        marks = {'old':100}
        plan(book,0,days[0],days[1],bars,marks,marks)
        self.assertEqual([x[2] for x in book.orders],['SELL'])
        book.execute(days[1],days[3],bars)
        for i in (1,2):
            plan(book,i,days[i],days[i+1],bars,{},marks)
            self.assertEqual(book.orders,[])
        book.settle(days[3])
        plan(book,3,days[3],days[4],bars,{},marks)
        self.assertEqual(book.orders[0][2],'BUY')
        self.assertLess(book.orders[0][4],100)
        book.execute(days[4],days[6],bars,volume={'new':10},participation=D('.01'))
        self.assertEqual(book.log[-1]['event'],'volume_limit_unfilled')
        plan(book,5,days[5],days[6],bars,{},marks)
        self.assertEqual(book.orders,[])

    def test_kept_position_sells_only_excess(self):
        day = self.days[0]
        book = Account(0,self.days)
        book.post(day,'fixture',isin='X',shares=100)
        plan = Rebalance({day:('X','Y')},2,Execution('E2'))
        bars = {x:(100,100,VALID) for x in ('X','Y')}
        plan(book,0,day,self.days[1],bars,{'X':100},{})
        self.assertEqual(book.orders[0][2:],('SELL',1,50))

    def test_etf_float_quote_yields_integer_ledger_and_payout(self):
        days = self.days
        quotes = {day:(10000.,10000.,10_000_000) for day in days}
        payout = {days[2]:(days[3],days[4],days[4],'100','0')}
        result = benchmark(days,quotes,payout,D('.001'))
        self.assertEqual(sum(r['event']=='fill' for r in result['journal']),1)
        self.assertGreater(result['daily'][-1]['nav'],result['daily'][1]['nav'])
