"""Offline checks for 2017-2026 PIT collection. Never calls KRX or Drive."""
import importlib.util
from pathlib import Path
import unittest

SRC=Path(__file__).resolve().with_name("drive_collect_history.py")
spec=importlib.util.spec_from_file_location("krx_history_collector",SRC)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CalendarTests(unittest.TestCase):
    def test_year_2017(self):
        dates=[x for mon in range(1,13) for x in m.sessions(2017,mon)]
        self.assertEqual(len(dates),243)
        self.assertEqual(dates[0],"20170102")
        self.assertEqual(dates[-1],"20171228")
        self.assertEqual(len(dates),len(set(dates)))

    def test_year_2026_cutoff(self):
        dates=[x for mon in range(1,11) for x in m.sessions(2026,mon)]
        self.assertEqual(len(dates),202)
        self.assertEqual(dates[-1],"20261030")
        self.assertTrue(all(x<="20261030" for x in dates))

    def test_announced_closures_and_neighbors(self):
        june = m.sessions(2026,6)
        july = m.sessions(2026,7)
        self.assertNotIn("20260603", june)
        self.assertNotIn("20260717", july)
        self.assertTrue({"20260601","20260602","20260604","20260605"}.issubset(june))
        self.assertIn("20260716", july)
        self.assertIn("20260720", july)
        self.assertEqual(len(june),21)
        self.assertEqual(len(july),22)
        self.assertEqual([len(m.sessions(2026,n)) for n in range(1,6)],[21,17,21,22,18])

    def test_sanitized_validation_diagnostic(self):
        m.context("krx_validate_daily", "20260603", 2026, 6)
        detail = m.failure_details(ValueError("Invalid KRX row count"))
        self.assertEqual(detail["rule"], "KRX_ROW_COUNT")
        self.assertEqual(detail["date"], "20260603")
        detail = m.failure_details(ValueError("SECRET URL"))
        self.assertNotIn("SECRET", str(detail))

    def test_private_inventory_rejects_missing_duplicate_and_shared(self):
        from unittest.mock import Mock, patch
        from validation.trend_audit.krx_pit_private import audit_history as audit
        rows=[{"name":f"KRX_PIT_{year}_{month:02d}_v1.json.gz","shared":False,"size":"1000"}
              for year in range(2017,2027) for month in range(1,11 if year==2026 else 13)]
        drive=Mock()
        with patch("builtins.print"), patch.object(audit,"_build_service",return_value=drive), patch.object(audit,"folder",return_value="1f_FAl_IL31nhw69gSgU5UCfW8P9LBbKY"), patch.dict(audit.os.environ,dict.fromkeys(("GDRIVE_OAUTH_CLIENT_ID","GDRIVE_OAUTH_CLIENT_SECRET","GDRIVE_OAUTH_REFRESH_TOKEN"),"test")):
            drive.files.return_value.list.return_value.execute.return_value={"files":rows}
            audit.inventory()
            for invalid in (rows[:-1],rows+[rows[0]],[dict(x,shared=True) for x in rows]):
                drive.files.return_value.list.return_value.execute.return_value={"files":invalid}
                with self.assertRaises(RuntimeError):
                    audit.inventory()

    def test_outside_range_rejected(self):
        for year,month in ((2016,1),(2027,1),(2026,11),(2026,12),(2017,0),(2017,13)):
            with self.assertRaises(ValueError):
                m.sessions(year,month)

    def test_mixed_alphanumeric_ticker(self):
        rows=[{
            "ISU_SRT_CD":"0120G0" if i==0 else f"{i:06d}",
            "MKT_TP_NM":"KOSPI",
            "ISU_CD":f"KR7{i:09d}",
            "LIST_DD":"20260101"
        } for i in range(600)]
        result=m.validate("basic","20261030",rows)
        self.assertIn("0120G0",result)
        with self.assertRaises(ValueError):
            m.validate("basic","20261030",rows+[rows[0]])

if __name__=="__main__":
    unittest.main()
