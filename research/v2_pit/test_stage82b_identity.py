import unittest
from unittest.mock import patch

from stage82b.identity import build


class HistoricalIdentityTest(unittest.TestCase):
    def joined(self, *, dart_names=("법인명",), kind_title="분기보고서(일반법인)(2021.03)", day_isin="KR7005930003"):
        sec = {"stock_code":"005930", "isin":"KR7005930003", "issuer_as_of":"옛이름"}
        kind = {"stock_code":"005930", "kind_receipt":"20210517000001", "timestamp":"2021-05-17 13:04",
                "kind_name":"새상호", "submitter":"법인명", "title":kind_title, "page":1}
        reports = [
            {"receipt":f"202105170000{index:02}", "corp_code":f"{index:08}", "filed":"20210517",
             "title":"분기보고서 (2021.03)", "dart_display_name":name, "type":"original"}
            for index,name in enumerate(dart_names,2)
        ]
        dates = {"20210331":{"005930":sec["isin"]}, "20210517":{"005930":day_isin}}
        with patch("stage82b.identity.official_securities",return_value=dates):
            row, = build([sec],reports,[kind],None)
        return row

    def test_submission_alias_and_distinct_ids(self):
        row=self.joined()
        self.assertEqual(row["identity_status"],"PASS")
        self.assertNotEqual(row["kind_receipt"],row["receipt_candidate"])

    def test_duplicate_dart_issuer_or_conflicting_aliases(self):
        for names in (("법인명","법인명"),("법인명","새상호")):
            with self.subTest(names=names):
                self.assertEqual(self.joined(dart_names=names)["identity_status"],"BLOCKED")

    def test_changed_isin_or_correction_or_different_period(self):
        self.assertEqual(self.joined(day_isin="KR7000000000")["identity_status"],"BLOCKED")
        for title in ("[정정]분기보고서(일반법인)(2021.03)","분기보고서(일반법인)(2021.02)"):
            self.assertEqual(self.joined(kind_title=title)["identity_status"],"BLOCKED")
