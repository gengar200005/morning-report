import unittest
from identity_ledger import event,following,previous,valid_name
class HistoricalReceiptTest(unittest.TestCase):
    def test_search_returns_extensions_and_amended_attachments(self):
        self.assertIsNone(event('사업보고서제출기한연장신고서 (2020.12)'))
        self.assertEqual(event('[첨부정정] 반기보고서 (2020.02)'),('20200229','11012','amendment'))
        self.assertEqual(event('[연결포함]사업보고서(일반법인)(2016.12)'),('20161231','11011','original'))
    def test_outside_verified_sessions_has_no_next_session(self):
        days=['20160104','20160105','20160106']
        self.assertEqual(following(days,'20150331'),'')
        self.assertEqual(following(days,'20160104'),'20160105')
        self.assertEqual(following(days,'20160106'),'')
        self.assertEqual(previous(days,'20160103'),'')
    def test_empty_alias_cannot_prove_identity(self):
        self.assertFalse(valid_name({'name':'','submitter':''},{'name':'','submitter':''},''))
        self.assertTrue(valid_name({'name':'A','submitter':'(주) 예시'},{'name':'예시','submitter':'A'},'옛 사명'))
if __name__=='__main__':unittest.main()
