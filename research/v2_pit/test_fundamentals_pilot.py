import json
import unittest
from unittest.mock import patch

from dart_receipts import listing
from fundamentals_pilot import entry_window, metrics


class EarningsPilotTest(unittest.TestCase):
    def test_positive_margin_with_negative_profit_base(self):
        x = metrics([100,-5,90,-10])
        self.assertGreater(x['margin_change'],0)
        self.assertIsNone(x['operating_growth'])
        with self.assertRaises(ValueError):
            metrics([100,1,0,1])

    def test_date_only_publication_waits_and_phase_does_not_cross(self):
        days = ['20211229','20211230','20220103','20220104','20220105']
        self.assertEqual(entry_window(days,'20211229',1),(1,1))
        self.assertIsNone(entry_window(days,'20211229',2))
        self.assertEqual(entry_window(days,'20220101',2),(2,3))

    @patch('dart_receipts.fetch')
    def test_listing_retains_original_and_correction(self, fetch):
        rows = [
            dict(corp_code='00126380',rcept_dt='20230427',rcept_no='20230427000001',report_nm='원본'),
            dict(corp_code='00126380',rcept_dt='20230501',rcept_no='20230501000001',report_nm='[기재정정] 원본')]
        fetch.side_effect = [json.dumps(dict(status='000',page_no=i,total_page=2,total_count=2,
                          list=[row])).encode() for i,row in enumerate(rows,1)]
        pages = listing('secret','00126380','20230401','20230601')
        self.assertEqual(len(pages),2)
        self.assertTrue(all(c.kwargs['last_reprt_at']=='N' for c in fetch.call_args_list))

    @patch('dart_receipts.fetch')
    def test_listing_rejects_wrong_issuer(self, fetch):
        row = dict(corp_code='00000000',rcept_dt='20230427',rcept_no='20230427000001')
        fetch.return_value = json.dumps(dict(status='000',page_no=1,total_page=1,total_count=1,list=[row])).encode()
        with self.assertRaisesRegex(ValueError,'identity'):
            listing('secret','00126380','20230401','20230601')
