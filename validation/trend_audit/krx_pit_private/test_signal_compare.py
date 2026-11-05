import unittest
import numpy as np
import pandas as pd
from validation.trend_audit.krx_pit_private.signal_features import features,ranked_signals
from validation.trend_audit.krx_pit_private.compare_signals import select_day,compare
CFG={'signal':{'minervini':{'lookback_52w':252,'trend_acceleration_days':22,'lo52_threshold':1.25,'hi52_threshold':.75,'rs_min':70},'supply':{'lookback_days':20,'ratio_min':1.2},'market_gate':{'kospi_ma':60}}}
class SignalTests(unittest.TestCase):
    def series(self):
        idx=pd.date_range('2015-01-01',periods=560,freq='B');rng=np.random.default_rng(34)
        return pd.DataFrame({'A':100*np.exp(np.cumsum(rng.normal(.001,.02,len(idx))))},index=idx),pd.DataFrame({'A':rng.integers(0,10000,len(idx))},index=idx)
    def test_scalar_formula_all_dates(self):
        c,v=self.series();ret,pre=features(c,v,CFG,c.gt(0)&c.shift(252).gt(0))
        for i in range(252,len(c)):
            x=c.A.to_numpy();y=v.A.to_numpy();ma=[x[i-n:i].mean() for n in (50,150,200)]
            uv=sum(y[j] for j in range(i-20,i) if x[j]>x[j-1]);dv=sum(y[j] for j in range(i-20,i) if x[j]<=x[j-1])
            expected=(x[i]>ma[0] and x[i]>ma[1] and x[i]>ma[2] and ma[0]>ma[1]>ma[2] and ma[2]>x[i-222:i-22].mean() and x[i]>=x[i-252:i].min()*1.25 and x[i]>=x[i-252:i].max()*.75 and (uv/dv if dv>0 else 999)>=1.2)
            self.assertEqual(bool(pre.A.iloc[i]),bool(expected));self.assertAlmostEqual(ret.A.iloc[i],x[i]/x[i-252]-1)
    def test_future_prices_do_not_change_past_features(self):
        c,v=self.series();valid=c.gt(0)&c.shift(252).gt(0);a,b=features(c,v,CFG,valid)
        c2=c.copy();v2=v.copy();c2.iloc[430:]*=100;v2.iloc[430:]*=9;x,y=features(c2,v2,CFG,valid)
        pd.testing.assert_frame_equal(a.iloc[:430],x.iloc[:430]);pd.testing.assert_frame_equal(b.iloc[:430],y.iloc[:430])
    def test_rs_max_ties_and_market_gate(self):
        ret=pd.DataFrame([[1,1,0]],columns=['A','B','C']);rs,s=ranked_signals(ret,pd.DataFrame(True,index=ret.index,columns=ret.columns),pd.Series([False]),70)
        np.testing.assert_allclose(rs.iloc[0],[100,100,100/3]);self.assertFalse(s.any().any())
    def frame(self):
        return pd.DataFrame([dict(Code=c,MarketId=m,ret252=r,precondition=True,gate=True,Volume=v,Open=10,High=11,Low=9,Close=10) for c,m,r,v in [('A','STK',1,100),('B','KSQ',10,100),('C','STK',0,0)]])
    def test_future_listing_and_kosdaq_never_ranked(self):
        ranked,s=select_day(self.frame(),{'A','C'},70);self.assertNotIn('B',ranked.Code.to_list());self.assertEqual(ranked.loc[ranked.Code.eq('A'),'rs'].iloc[0],100);self.assertEqual(s.Code.to_list(),['A'])
    def test_official_mirror_market_conflict_is_failure(self):
        with self.assertRaisesRegex(ValueError,'MARKET_CONFLICT'):select_day(self.frame(),{'B'},70)
    def test_zero_volume_is_membership_not_fill(self):
        f=self.frame();f.loc[f.Code.eq('C'),'ret252']=2;ranked,s=select_day(f,{'A','C'},70)
        self.assertEqual(len(ranked),2);self.assertEqual(s.Code.to_list(),['C']);self.assertFalse(s.execution_record_available.iloc[0])
    def test_missing_lookback_does_not_rank_or_signal(self):
        f=self.frame();f.loc[f.Code.eq('A'),'ret252']=np.nan;ranked,s=select_day(f,{'A','C'},70)
        self.assertTrue(ranked.loc[ranked.Code.eq('A'),'rs'].isna().all());self.assertNotIn('A',s.Code.to_list())
    def test_prelisting_official_membership_rejected(self):
        f=self.frame();f['date']='20260102';mem={'daily_membership':[{'date':'20260102','members':[{'code':'A','isin':'A-id','listing_date':'20260103'}]}]}
        m={'calendar':['20260102','20260105'],'ordered_fixed':['A'],'config':CFG,'sessions':['20260102']};empty=pd.DataFrame(columns=['date','code'])
        with self.assertRaisesRegex(ValueError,'PRE_LISTING'):compare(f,mem,m,empty,empty)
if __name__=='__main__':unittest.main()
