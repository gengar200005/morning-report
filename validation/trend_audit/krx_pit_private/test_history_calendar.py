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
        self.assertEqual(len(dates),204)
        self.assertEqual(dates[-1],"20261030")
        self.assertTrue(all(x<="20261030" for x in dates))

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
