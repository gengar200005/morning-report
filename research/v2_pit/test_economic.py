from collections import deque
from decimal import Decimal as D
from fractions import Fraction
import unittest

from economic_account import Account, VALID, metrics, reconcile_journal, sale_tax
from economic_prices import advance, reference_check, signed


class EconomicTests(unittest.TestCase):
    def test_signed_krx_arithmetic_and_rounding(self):
        self.assertEqual(signed('+1,100'),1100)
        self.assertEqual(reference_check(51900,-1100,'-2.08'),(53000,'PASS'))
        self.assertNotEqual(reference_check(51900,1100,'-2.08')[1],'PASS')
        self.assertEqual(reference_check(51900,-1100,'NaN')[1],'MISSING_INPUT')
        self.assertEqual(reference_check(201,1,'0.50'),(200,'PASS'))

    def test_252_session_window_resets_on_gap_or_bad_reference(self):
        history = deque(maxlen=253)
        for i in range(253):
            out = advance(history,i,str(i),'A',100,100,'PASS')
            self.assertEqual(out[2],0 if i==252 else None)
        self.assertEqual(out[1],'0')
        self.assertIsNone(advance(history,254,'254','A',100,100,'PASS')[2])
        self.assertIsNone(advance(history,255,'255','A',100,100,'RATE_DISAGREES')[0])

    def test_tax_schedule_boundaries(self):
        self.assertEqual([sale_tax(day) for day in ('20190602','20190603','20210101','20230101',
                                                     '20240101','20250101','20260101')],
                         list(map(D,('.003','.0025','.0023','.002','.0018','.0015','.002'))))

    def test_no_opening_sizing_or_unsettled_proceeds_spending(self):
        a = Account(1000)
        a.queue('20180102','A','BUY',200,100)
        self.assertEqual(a.orders[0][-1],4)
        a.execute('20180103','20180105',{'A':(100,100,VALID)})
        self.assertEqual(a.cash,D(1000))
        self.assertEqual(a.buying_power,D('599.2'))
        self.assertEqual(a.snapshot('20180103',{'A':100})['payables'],D('400.8'))
        a.settle('20180105')
        self.assertEqual(a.cash,D('599.2'))
        a.queue('20180105','A','SELL',1,4)
        a.execute('20180108','20180110',{'A':(100,100,VALID)})
        self.assertEqual(a.buying_power,D('599.2'))
        a.settle('20180110')
        self.assertEqual(a.cash,D('997.2'))

    def test_bonus_spinoff_merger_and_unknown_fraction(self):
        a = Account(1000)
        a.post('20180102','fixture_position',isin='A',shares=3)
        a.award('20180102','bonus','A','A',Fraction(1), '20180103')
        self.assertEqual(a.snapshot('20180102',{'A':10})['receivables'],30)
        a.settle('20180103')
        self.assertEqual(a.shares['A'],6)
        a.award('20180103','spinoff','A','B',Fraction(1,4),'20180104')
        a.settle('20180104')
        self.assertIsNone(a.snapshot('20180104',{'A':10,'B':20})['nav'])
        self.assertEqual(a.shares['B'],1)
        a.award('20180104','merger','A','C',Fraction(1,4),'20180105',replace=True,
                fraction_cash=5,fraction_due='20180106')
        a.settle('20180105')
        a.settle('20180106')
        self.assertEqual(dict(a.shares),{'B':1,'C':1})
        self.assertEqual(a.cash,1005)
        self.assertIsNone(a.snapshot('20180106',{'B':20,'C':10})['nav'])

    def test_reconciliation_detects_tampered_nav_and_metrics_fail_closed(self):
        a = Account(100)
        a.post('20180102','unknown',block='unresolved')
        row = a.snapshot('20180102',{})
        reconcile_journal(100,a.log,[row],{'20180102':{}})
        with self.assertRaises(ValueError):
            reconcile_journal(100,a.log,[dict(row,nav=100)],{'20180102':{}})
        self.assertIsNone(metrics([row,dict(row,day='20180103',nav=100)]))
        complete = [dict(day='20180101',nav=D(100)),dict(day='20180102',nav=D(90)),
                    dict(day='20190101',nav=D(110))]
        self.assertAlmostEqual(metrics(complete)['mdd'],-.10)
        self.assertAlmostEqual(metrics(complete)['cagr'],.10,places=3)


if __name__=='__main__':
    unittest.main()
