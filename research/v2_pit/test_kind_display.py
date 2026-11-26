import unittest

from stage82b.kind_display import ROOT, contents_url, document_number, full_report


class KindDisplayTest(unittest.TestCase):
    receipt = '20210517000487'
    doc = '20210517001079'
    url = ROOT + '/external/2021/05/17/000487/20210517001079/11013.htm'

    def test_original_only_and_checks_exact_date(self):
        body = (f'<select id="mainDoc"><option value="{self.doc}|N">분기보고서 (2021.05.17)</option>'
                '<option value="20210702000456|Y" selected>[정정]분기보고서 (2021.07.02)</option></select>').encode()
        self.assertEqual(document_number(body, self.receipt), self.doc)
        with self.assertRaises(ValueError):
            document_number(body, '20210514000001')
        wrong = b'<header><h1>Issuer (000100)</h1></header>' + body
        with self.assertRaisesRegex(ValueError, 'another security'):
            document_number(wrong, self.receipt, '001000')

    def test_pointer_bound_to_exact_receipt_document_and_origin(self):
        def pointer(url):
            return f"parent.setPath('toc','{url}','path');".encode()
        self.assertEqual(contents_url(pointer(self.url), self.receipt, self.doc), self.url)
        for wrong in [self.url.replace('000487/', '000488/'), self.url.replace('20210517001079/', '20210517001080/'),
                      self.url.replace('kind.krx.co.kr', 'example.org')]:
            with self.assertRaises(ValueError):
                contents_url(pointer(wrong), self.receipt, self.doc)

    def test_identity_is_required_before_fetch(self):
        row = dict(kind_receipt=self.receipt, receipt_candidate='20210517001800', filing_date='20210517',
                   identity_status='BLOCKED')
        with self.assertRaises(ValueError):
            full_report('never_created', row)
