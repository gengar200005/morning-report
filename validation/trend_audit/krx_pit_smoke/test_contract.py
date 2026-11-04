import unittest

from collect import ANCHORS, DATES, ENDPOINTS, classify, codes, scrub


class OfflineContractTests(unittest.TestCase):
    def test_readonly_endpoint_allowlist(self):
        self.assertEqual(set(ENDPOINTS), {"basic", "daily"})
        self.assertTrue(all(x in ENDPOINTS.values() for x in ("stk_bydd_trd", "stk_isu_base_info")))

    def test_bounded_historical_dates(self):
        self.assertEqual(len(DATES), 7)
        self.assertEqual(len(set(DATES)), len(DATES))
        self.assertEqual(len(ANCHORS), 4)

    def test_valid_basic(self):
        x = classify(200, {"OutBlock_1": [
            {"ISU_SRT_CD": "117930", "KIND_STKCERT_TP_NM": "보통주"}
        ]}, "basic", "20160601")
        self.assertTrue(x["ok"])
        self.assertEqual(x["n"], 1)

    def test_valid_daily(self):
        x = classify(200, {"OutBlock_1": [
            {"ISU_CD": "117930", "BAS_DD": "20160601"}
        ]}, "daily", "20160601")
        self.assertTrue(x["ok"])

    def test_empty_is_not_absence_proof(self):
        self.assertEqual(classify(200, {"OutBlock_1": []}, "basic", "20170307")["status"],
                         "empty_success_not_absence_proof")

    def test_wrong_day_and_missing_field_fail_closed(self):
        self.assertFalse(classify(200, {"OutBlock_1": [
            {"ISU_CD": "005930", "BAS_DD": "20200413"}
        ]}, "daily", "20200414")["ok"])
        self.assertFalse(classify(200, {"OutBlock_1": [
            {"ISU_CD": "005930"}
        ]}, "basic", "20200414")["ok"])
        self.assertFalse(classify(200, {}, "basic", "20200414")["ok"])

    def test_unauthorized(self):
        self.assertFalse(classify(401, {"message": "Unauthorized"}, "basic", "20200414")["ok"])

    def test_scrub_nested_and_reflected_key(self):
        original = {"AUTH_KEY": "MY_KRX_SECRET",
                    "OutBlock_1": [{"ISU_SRT_CD": "005930", "note": "MY_KRX_SECRET"}]}
        clean = scrub(original, "MY_KRX_SECRET")
        self.assertNotIn("AUTH_KEY", clean)
        self.assertEqual(clean["OutBlock_1"][0]["note"], "[REDACTED]")

    def test_ticker_code_extract(self):
        self.assertEqual(codes([{"ISU_CD": "A117930"}, {"ISU_CD": "005930"}], "daily"),
                         {"117930", "005930"})


if __name__ == "__main__":
    unittest.main()
