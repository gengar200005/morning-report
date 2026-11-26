import hashlib
import sqlite3
import unittest
from unittest.mock import patch

from public_dart_xbrl import attachment_path, package


class PublicAttachmentTest(unittest.TestCase):
    def test_only_selected_menu_pair(self):
        menu = b'<a href="/pdf/download/ifrs.do?rcp_no=20210517001185&amp;dcm_no=8073522&amp;lang=ko">XBRL</a>'
        self.assertIn('8073522', attachment_path(menu, '20210517001185', '8073522'))
        with self.assertRaises(ValueError):
            attachment_path(menu, '20210517001185', '8073523')

    def test_cached_bytes_reused_and_checked(self):
        receipt = '20210517001185'
        payload = b'checked by downloader'
        meta = {'receipt': receipt, 'sha256': hashlib.sha256(payload).hexdigest()}
        with sqlite3.connect(':memory:') as db, patch('public_dart_xbrl.download_package', return_value=(meta, payload)) as fetch:
            self.assertEqual(package(db, receipt), (meta, payload))
            self.assertEqual(package(db, receipt), (meta, payload))
            fetch.assert_called_once()
            db.execute("UPDATE packages SET body=X'00'")
            with self.assertRaisesRegex(ValueError, 'integrity'):
                package(db, receipt)
