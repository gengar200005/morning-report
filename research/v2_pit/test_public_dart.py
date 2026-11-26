import sqlite3
import unittest
from unittest.mock import patch

from public_dart import cache_init, collect, main_index, table_rows, validate_receipt


ORIGINAL = '20210407800092'
CORRECTION = '20210429800242'


def index(receipt):
    return (f'<title>LG전자/연결재무제표기준영업(잠정)실적(공정공시)</title>'
            f'<select><option value="rcpNo={receipt}" selected>report</option></select>'
            f'<script>viewDoc("{receipt}", "123", "0", "0", "0", "HTML", "");</script>').encode()


def body(value):
    return (f'<p>연결 잠정 실적</p><table><tr><th colspan="2">매출액</th></tr>'
            f'<tr><td>당해실적</td><td>{value}</td></tr></table>').encode('cp949')


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        cache_init(self.db)

    @patch('public_dart.download')
    def test_correction_is_separate_and_archive_is_reusable(self, download):
        download.side_effect = [index(ORIGINAL), body('188,057'), index(CORRECTION), body('188,095')]
        original = collect(self.db, ORIGINAL)
        corrected = collect(self.db, CORRECTION)
        for result, expected in [(original, '188,057'), (corrected, '188,095')]:
            section, = result['sections']
            rows = section['tables'][0]['rows']
            self.assertEqual(rows[0][0]['colspan'], '2')
            self.assertEqual(rows[1][1]['text'], expected)
            self.assertIn(result['receipt'], section['url'])
        self.assertEqual(collect(self.db, ORIGINAL), original)
        self.assertEqual(download.call_count, 4)

    @patch('public_dart.download')
    def test_resume_after_error_page_then_detect_local_corruption(self, download):
        download.side_effect = [index(ORIGINAL), b'<html>maintenance</html>', body('0')]
        with self.assertRaises(ValueError):
            collect(self.db, ORIGINAL)
        collect(self.db, ORIGINAL)
        self.assertEqual(download.call_count, 3)
        self.db.execute("UPDATE page SET body=X'00'")
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            collect(self.db, ORIGINAL)

    def test_mismatched_selected_receipt_or_toc_coordinates_rejected(self):
        with self.assertRaises(ValueError):
            main_index(index(CORRECTION), ORIGINAL)
        wrong = index(ORIGINAL).replace(b'viewDoc("' + ORIGINAL.encode(), b'viewDoc("' + CORRECTION.encode())
        with self.assertRaises(ValueError):
            main_index(wrong, ORIGINAL)

    def test_reject_invalid_cutoff_and_wrong_viewer(self):
        for bad in ['abc', '20241101000001', '20210230000001']:
            with self.assertRaises(ValueError):
                validate_receipt(bad)
        with self.assertRaisesRegex(ValueError, 'heading'):
            table_rows(body('5'), '2. 연결재무제표')


if __name__ == '__main__':
    unittest.main()
