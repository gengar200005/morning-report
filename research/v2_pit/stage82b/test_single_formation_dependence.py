import unittest
from single_formation_dependence import contrast


class ConcentrationTest(unittest.TestCase):
    def test_contributions_capture_both_groups_and_reweight_remaining(self):
        left=set('abc');right=set('defghijk')
        raw=dict(a=.63,b=.12,c=.03,d=1.4,e=.84,f=.07,g=.035,h=-.42,i=0.,j=.014,k=None)
        records={k:(v,v,'observed' if v is not None else 'entry_unavailable',0) for k,v in raw.items()}
        out=contrast(left,right,records)
        omitted=[i['isin'] for i in out['removed_by_primary_price_contribution']]
        self.assertEqual(omitted,list('adehb'))
        self.assertAlmostEqual(out['price']['after']['difference'],.03-(.07+.035+.014)/4)
        self.assertEqual(out['price']['after']['comparison']['assigned'],5)
        self.assertEqual(out['price']['after']['comparison']['observed'],4)
        self.assertEqual(out['price']['after'],out['partial_economic_same_exclusions']['after'])

    def test_zero_ties_sort_by_isin_and_empty_remaining_is_undefined(self):
        names=set('abcdef')
        data={k:(0.,0.,'observed',0) for k in names}
        result=contrast({'a'},names-{'a'},data)
        self.assertEqual([r['isin'] for r in result['removed_by_primary_price_contribution']],list('abcde'))
        self.assertIsNone(result['price']['after']['difference'])
        data['a']=(None,None,'entry_unavailable',0)
        self.assertEqual(contrast({'a'},names-{'a'},data)['removed_by_primary_price_contribution'],[])
