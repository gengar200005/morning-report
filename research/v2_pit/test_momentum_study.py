import unittest

import numpy as np
import pandas as pd

from momentum_statistics import holm, inference, summarize
from momentum_study import VALID, eligible, outcome, scores, window


def bar(op=100, close=100, ref=100, state=VALID):
    return (op,close,'000001',state,ref,'PASS',100,'CONTIGUOUS_RAW_RETURN',1)


class MomentumStudyTest(unittest.TestCase):
    def test_exact_lags_and_average(self):
        close = np.arange(100.,353.)
        m1,m2,m3,m4,distance,slope = scores(close)
        self.assertAlmostEqual(m1,331/100-1)
        self.assertAlmostEqual(m2,226/100-1)
        self.assertAlmostEqual(m3,331/226-1)
        self.assertAlmostEqual(m4,352/351-1)
        self.assertAlmostEqual(distance,352/251.5-1)
        self.assertAlmostEqual(slope,251.5/229.5-1)

    def test_future_change_does_not_change_signal(self):
        panel = {'X':{i:bar() for i in range(253)}}
        before = eligible(panel,252,{})
        panel['X'][253] = bar(close=1000)
        self.assertEqual(before,eligible(panel,252,{}))
        panel['X'][80] = bar()[:7]+('ANCHOR',1)
        self.assertEqual(eligible(panel,252,{}),([],1))

    def test_end_inclusive_and_phase_boundary(self):
        days = ['20211229','20211230','20220103','20220104','20231228','20240102']
        self.assertEqual(window(0,1,days),(1,1))
        self.assertIsNone(window(0,2,days))
        self.assertEqual(window(2,2,days),(3,4))
        self.assertIsNone(window(2,3,days))

    def test_split_cash_and_open_entry_rights(self):
        bars = {1:bar(),2:bar(50,50,50),3:bar(51,51,50)}
        events = {1:[('cash',99)],2:[('split',2)],3:[('cash',2)]}
        price,economic,status,count = outcome(bars,events,set(),1,[3])[3]
        self.assertAlmostEqual(price,.02)
        self.assertAlmostEqual(economic,.06)
        self.assertEqual((status,count),('observed',1))

    def test_exit_halt_unknown_rights_and_bad_reference(self):
        halted = bar(state='ZERO_VOLUME')
        self.assertEqual(outcome({1:halted},{},set(),1,[2])[2][2],'entry_unavailable')
        results = outcome({1:bar(),2:halted,3:bar(),4:bar(ref=87)},
                          {4:[('unknown',0)]},{5},1,[2,3,4,5])
        self.assertIn('suspended',results[2][2])
        self.assertEqual(results[3][2],'observed')
        self.assertIn('unverified_reference',results[4][2])
        self.assertIn('corporate_action',results[4][2])
        self.assertIn('pit_exit',results[5][2])
        self.assertIsNone(results[5][0])

    def test_matching_keeps_preformed_top_group(self):
        frame = pd.DataFrame(dict(isin=list('ABCDE'),M1=[5,4,3,2,1],
            price=[.2,.1,.5,.3,np.nan],economic=[.2,.1,.5,.3,np.nan],
            cap_cell=[0,0,1,1,0],turn_cell=[0]*5,etf_price=[0]*5,etf_economic=[0]*5,
            status=['observed']*4+['entry_unavailable']))
        result,_ = summarize(frame,'M1')
        self.assertAlmostEqual(result['matched'],.1)
        self.assertEqual(result['top_count'],1)
        frame.loc[0,'price'] = np.nan
        result,_ = summarize(frame,'M1')
        self.assertEqual(result['top_observed'],0)
        self.assertEqual(result['top_count'],1)

    def test_block_inference_and_multiplicity(self):
        self.assertIsNone(inference(pd.Series(np.ones(11)))['p'])
        stat = inference(pd.Series(np.ones(24)))
        self.assertEqual(stat['low'],1)
        self.assertLess(stat['p'],.001)
        rows = [{'p':.01},{'p':.02},{'p':.9},{'p':None}]
        holm(rows)
        self.assertAlmostEqual(rows[0]['holm_p'],.04)
        self.assertAlmostEqual(rows[1]['holm_p'],.06)
