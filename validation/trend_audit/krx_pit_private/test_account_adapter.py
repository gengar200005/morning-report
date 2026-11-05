import unittest
from types import SimpleNamespace
from collections import namedtuple
import numpy as np
import pandas as pd
from validation.trend_audit.krx_pit_private.pit_account_replay import make_quotes,valid_row
class Rule:
    def __init__(self,lower,upper,bands):self.bands=bands
Quote=namedtuple('Quote','rule reference opening close tradable')
EX=SimpleNamespace(QuoteRule=Rule);REP=SimpleNamespace(Quote=Quote)
class AdapterTests(unittest.TestCase):
    def rows(self,opening=100,volume=100):return pd.DataFrame([dict(Code='A',Open=opening,High=max(100,opening),Low=min(100,opening),Close=100,Volume=volume)])
    def quotes(self,rows,prior=None,mode='D2'):return make_quotes(rows,{'A':100} if prior is None else prior,{'A'},mode,'20200102',EX,REP)[0]
    def test_future_open_does_not_change_d2_reference_or_cap(self):
        a=self.quotes(self.rows(90))['A'];b=self.quotes(self.rows(110))['A'];self.assertEqual(a.reference,b.reference);self.assertEqual(a.rule.cap(a.reference),b.rule.cap(b.reference));self.assertNotEqual(a.opening,b.opening)
    def test_unknown_future_zero_volume_does_not_release_preopen_slot(self):
        a=self.quotes(self.rows())['A'];b=self.quotes(self.rows(volume=0))['A'];self.assertEqual(a.reference,b.reference);self.assertEqual(a.rule.cap(a.reference),b.rule.cap(b.reference));self.assertFalse(b.tradable);self.assertIsNone(b.opening)
    def test_no_prior_reference_never_uses_future_open(self):self.assertEqual(self.quotes(self.rows(),prior={}),{})
    def test_missing_bar_retains_known_d2_submission_reference(self):
        q=self.quotes(self.rows().iloc[:0])['A'];self.assertEqual(q.reference,100);self.assertIsNone(q.opening);self.assertFalse(q.tradable)
    def test_d1_is_explicit_observed_open_diagnostic(self):
        q=self.quotes(self.rows(110),mode='D1')['A'];self.assertEqual(q.opening,110);self.assertEqual(self.quotes(self.rows(volume=0),mode='D1'),{})
    def test_bad_prices_and_ohlc_cannot_produce_fill(self):
        for key,val in [('Open',0),('Open',np.nan),('High',90),('Volume',0),('Open',100.5)]:
            f=self.rows();f.loc[0,key]=val;self.assertFalse(valid_row(next(f.itertuples(index=False))));self.assertFalse(self.quotes(f)['A'].tradable)
if __name__=='__main__':unittest.main()
