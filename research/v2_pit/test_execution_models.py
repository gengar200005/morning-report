from decimal import Decimal as D
import sqlite3
import unittest

from economic_account import Account, VALID, reconcile_journal
from execution_models import Execution, band
from full_replay import quote_tick


class ExecutionModelsTests(unittest.TestCase):
    def test_tick_and_band_by_date(self):
        self.assertEqual(Execution('E2').limit('20230125',1999),2035)
        self.assertEqual(Execution('E2').limit('20230124',1999),2035)
        self.assertEqual(quote_tick('20230124',1999),5)
        self.assertEqual(quote_tick('20230125',1999),1)
        self.assertEqual(band('20230125',9940),(6960,12920))
        self.assertEqual(Execution('E2',D('.60')).limit('20230125',9940),12920)

    def test_fixed_quantity_waiver_and_volume(self):
        days = ('20230125','20230126','20230127','20230130')
        db = sqlite3.connect(':memory:')
        db.executescript("""CREATE TABLE krx_return_checks
            (day TEXT,isin TEXT,implied_reference_krw INTEGER,rate_status TEXT);
            INSERT INTO krx_return_checks VALUES ('20230126','A',100,'PASS');""")
        for model,volume,expect in (('E1',1000,0),('E2',1000,0),('E3',1000,5),('E3',300,0)):
            a = Account(1000,days)
            exe = Execution(model)
            limit = exe.limit(days[1],100)
            a.queue(days[0],'A','BUY',limit,5)
            bars = {'A':(105,108,VALID)}
            a.execute(days[1],days[3],bars,volume={'A':volume},participation=D('.01'),
                      opening_guard=exe.guard(db,days[1],bars))
            self.assertEqual(a.shares['A'],expect)
            self.assertEqual(a.reserved,0)
            reconcile_journal(1000,a.log,[a.snapshot(days[1],{'A':108})],{days[1]:{'A':108}})

    def test_price_limit_lock_is_separate(self):
        db = sqlite3.connect(':memory:')
        db.executescript("""CREATE TABLE krx_return_checks
            (day TEXT,isin TEXT,implied_reference_krw INTEGER,rate_status TEXT);
            INSERT INTO krx_return_checks VALUES ('20230126','A',100,'PASS');""")
        guard = Execution('E3').guard(db,'20230126',{})
        self.assertEqual(guard('A','BUY',102,130),('limit_auction_unfilled',False))
        self.assertEqual(guard('A','BUY',102,131),('opening_outside_modeled_band',False))


if __name__=='__main__':
    unittest.main()
