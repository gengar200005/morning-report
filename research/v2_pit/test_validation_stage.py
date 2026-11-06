from pathlib import Path
import sqlite3
import unittest

from validate_stage import pit_candidates
from validate_stage import bridge


class ValidationStageTests(unittest.TestCase):
    def test_future_membership_and_end_state_do_not_change_past_candidates(self):
        with sqlite3.connect(':memory:') as db:
            root = Path(__file__).parent
            for name in ('schema.sql','views.sql','validation_schema.sql'):
                db.executescript((root/name).read_text())
            db.execute("INSERT INTO provenance VALUES ('fixture','test','hash',0)")
            db.executemany("INSERT INTO sessions VALUES (?,'fixture')",
                           [('20180102',),('20180103',)])
            rows = [('20180102','ISIN_A','000001',1),('20180102','ISIN_B','000002',0)]
            insert = "INSERT INTO membership SELECT ?,?,?, 'name','20180102','group','kind',?"
            db.executemany(insert,rows)
            db.executemany("INSERT INTO signal_segments VALUES ('20180102',?,100,253,'RAW_PRICE_RETURN',100)",
                           [('ISIN_A',),('ISIN_B',)])
            expected = [('ISIN_A','000001',100,253)]
            self.assertEqual(pit_candidates(db,'20180102'),expected)
            db.executemany(insert,[('20180103','ISIN_B','000002',1),
                                   ('20180103','ISIN_C','000003',1)])
            db.executemany("INSERT INTO signal_segments VALUES ('20180103',?,101,254,'RAW_PRICE_RETURN',100)",
                           [('ISIN_B',),('ISIN_C',)])
            self.assertEqual(pit_candidates(db,'20180102'),expected)
            db.execute("UPDATE signal_segments SET observations=252 WHERE day='20180102'")
            self.assertEqual(pit_candidates(db,'20180102'),[])

    def test_split_rebases_only_on_observed_effective_price(self):
        isin = 'KR7005930003'
        prior = (1,2650000,100,252)
        self.assertEqual(bridge(isin,'20180430',2,51900,53000,prior,False)[1:],(1,'RESET_UNVERIFIED_REFERENCE_OR_GAP'))
        value,n,status = bridge(isin,'20180504',5,51900,53000,prior,False)
        self.assertAlmostEqual(value,51900/530)
        self.assertEqual((n,status),(253,'VERIFIED_50_FOR_1'))
        self.assertEqual(bridge(isin,'20180504',5,51900,52000,prior,False)[1],1)

    def test_unverified_gap_breaks_chain_and_spac_is_excluded(self):
        prior = (1,100,100,252)
        self.assertEqual(bridge('A','20180102',3,102,100,prior,False)[1],1)
        self.assertEqual(bridge('A','20180102',2,64,100,prior,False)[1],1)
        self.assertEqual(bridge('A','20180102',2,102,100,prior,True)[2],'SPAC_EXCLUDED')


if __name__=='__main__':
    unittest.main()
