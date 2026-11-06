import unittest

import numpy as np

from alpha_conditions import block_stats
from alpha_holding import Lots


class AlphaConditionsTest(unittest.TestCase):
    def test_calendar_month_contrast_ignores_unknown_state(self):
        x = [1.,0.,100.]*10
        state = [True,False,None]*10
        result = block_stats(x,state)
        self.assertEqual((result['n'],result['other_n'],result['effect']),(10,10,1.))
        self.assertEqual(result['low'],1.)

    def test_thin_regime_is_descriptive(self):
        result = block_stats(np.arange(19),[True]+[False]*18)
        self.assertIsNone(result['p'])
        self.assertEqual(result['n'],1)

    def test_staggered_lots_keep_distinct_expiry(self):
        days = [f'{i:03}' for i in range(140)]
        def entry(i,event,qty,**extra):
            return dict(day=days[i],event=event,isin='X',shares=qty,**extra)
        ledger = [entry(0,'fill',10),entry(20,'fill',20),entry(100,'split',30)]
        lots = Lots(days)
        lots.sync(ledger)
        self.assertEqual(lots.eligible_to_sell('X',118),0)
        self.assertEqual(lots.eligible_to_sell('X',119),20)
        ledger.append(entry(120,'fill',-20))
        lots.sync(ledger)
        self.assertEqual(lots.positions['X'],{20:40})
        self.assertEqual(lots.mean_closed_days(),120)
        with self.assertRaises(ValueError):
            lots.sync(ledger+[entry(121,'fill',-1)])

    def test_award_delivery_inherits_origin_age(self):
        days = [f'{i:03}' for i in range(140)]
        lots = Lots(days)
        ledger = [
            dict(day='000',event='fill',isin='X',shares=10),
            dict(day='050',event='share_entitlement',isin='X',shares=0,claim=('a','070','X',5,0)),
            dict(day='070',event='settlement',isin='X',shares=5,remove='a')]
        lots.sync(ledger)
        self.assertEqual(lots.eligible_to_sell('X',119),15)
