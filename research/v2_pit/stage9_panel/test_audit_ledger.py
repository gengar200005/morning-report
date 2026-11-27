"""Regression tests for the independent as-of chronology audit. No market returns are read."""
import unittest

from audit_ledger import latest_body_candidates


class AttachmentChronologyTests(unittest.TestCase):
    def setUp(self):
        self.original={'receipt':'20210330000123','period':'20201231','published':'20210330','version':'original',
                       'corp_code':'00123456','report_type':'11011','identity_status':'PASS'}
        self.annex=dict(self.original, receipt='20210401000321', published='20210401', version='amendment',
                        amendment_scope='nonfinancial_attachment_only', attachment_name='정관',
                        original_receipt=self.original['receipt'], main_receipts_at_event=self.original['receipt'],
                        source_fss_viewer_sha256='2'*64)

    def test_proven_nonfinancial_attachment_preserves_latest_financial_body(self):
        corrected=dict(self.annex, receipt='20210331000234', published='20210331',
                       amendment_scope='periodic_main_body', attachment_name='')
        history=[self.original,corrected,self.annex]
        self.assertEqual(latest_body_candidates(history,'20210331'),[self.original])
        self.assertEqual(latest_body_candidates(history,'20210401'),[corrected])
        self.assertEqual(latest_body_candidates(history,'20210402'),[corrected])
        same_day=dict(corrected,published=self.annex['published'])
        self.assertEqual(latest_body_candidates([self.original,self.annex,same_day],'20210402'),[same_day])

    def test_unproven_and_financial_attachments_stay_candidates(self):
        for change in ({'amendment_scope':'financial_attachment_only'}, {'version':'unknown'},
                       {'attachment_name':'감사보고서'}, {'identity_status':'BLOCKED'},
                       {'source_fss_viewer_sha256':'z'*64}, {'main_receipts_at_event':'20301111000999'},
                       {'original_receipt':''},{'corp_code':'00000000'},{'report_type':'11012'}):
            with self.subTest(change=change):
                annex=dict(self.annex,**change)
                self.assertEqual(latest_body_candidates([self.original,annex],'20210402'),[annex])

    def test_attachment_needs_unambiguous_contemporaneous_original_in_same_period(self):
        for variant in ({'period':'20200930'}, {'published':'20210402'}, {'identity_status':'BLOCKED'}):
            with self.subTest(variant=variant):
                self.assertEqual(latest_body_candidates([dict(self.original,**variant),self.annex],'20210402'),
                                 [self.annex])
        duplicate=dict(self.original,receipt='20210330000456')
        self.assertEqual(latest_body_candidates([self.original,duplicate,self.annex],'20210402'),[self.annex])
        next_q=dict(self.original,receipt='20210517000123',period='20210331',published='20210517')
        self.assertEqual(latest_body_candidates([self.original,self.annex,next_q],'20210518'),[next_q])
