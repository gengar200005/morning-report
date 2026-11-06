import sqlite3
import unittest

import numpy as np

from candidate_features import Policy, build_features, ma200_pair


class CandidateFeaturesTests(unittest.TestCase):
    def test_ma200_uses_exact_lagged_200_window(self):
        closes = np.arange(1,301)
        self.assertEqual(ma200_pair(closes,252),(152.5,130.5))
        # Shift old observations which lie outside both correct windows.
        closes[:30] = 100000
        self.assertEqual(ma200_pair(closes,252),(152.5,130.5))

    def test_feature_cache_prefix_unchanged_by_future_row(self):
        from datetime import date,timedelta
        days = [(date(2017,1,10)+timedelta(days=i)).strftime('%Y%m%d') for i in range(254)]
        market = {d:i+100 for i,d in enumerate(days)}
        db = sqlite3.connect(':memory:')
        db.executescript("""
            CREATE TABLE execution_bars(day,isin,code,volume);
            CREATE TABLE economic_momentum(day,isin,price_index,momentum_252,link_status);
        """)
        db.executemany("INSERT INTO execution_bars VALUES (?,'X','000001',100)",
                       [(day,) for day in days])
        db.executemany("INSERT INTO economic_momentum VALUES (?,'X',?,?,'CONTIGUOUS_RAW_RETURN')",
                       [(day,i+1000,.252 if i>=252 else None) for i,day in enumerate(days)])
        early = build_features(db,days,market,days[-2])
        db.execute('UPDATE economic_momentum SET price_index=100000000 WHERE day=?',(days[-1],))
        full = build_features(db,days,market,days[-1])
        self.assertEqual(early[days[-2]],full[days[-2]])
        self.assertEqual(early[days[-2]]['C'][0],[('X','000001')])

    def test_monthly_rotation_uses_only_current_review_targets(self):
        f = {'20200102':{'A':([('X','1')],set())},
             '20200103':{'A':([('Y','2')],set())},
             '20200203':{'A':([('Y','2')],set())}}
        p = Policy('A',f)
        self.assertEqual(p.entries('20200102'),[('X','1')])
        self.assertFalse(p.exit('20200103','X',100,100))
        self.assertEqual(p.entries('20200103'),[('X','1')])
        self.assertTrue(p.exit('20200203','X',100,100))


if __name__=='__main__':
    unittest.main()
