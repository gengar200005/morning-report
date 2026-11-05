import unittest
from validation.trend_audit.krx_pit_private.compare_universe import classification, compare_day

class CompareTests(unittest.TestCase):
    def test_classes_and_uncertainty(self):
        base=dict(KIND_STKCERT_TP_NM="보통주",SECUGRP_NM="주권",ISU_NM="회사")
        self.assertEqual(classification(base),"common")
        self.assertEqual(classification(dict(base,KIND_STKCERT_TP_NM="구형우선주")),"excluded_share_class")
        self.assertEqual(classification(dict(base,SECUGRP_NM="부동산투자회사")),"excluded_security_group")
        self.assertEqual(classification(dict(base,ISU_NM="제1호스팩")),"uncertain_spac_name")

    def test_zero_volume_missing_and_future_fixed_members(self):
        day="20260102"
        codes=[f"{i:06d}" for i in range(600)]
        codes[0]="0120G0"
        b=[dict(ISU_SRT_CD=c,ISU_CD=f"KR7{i:09d}",MKT_TP_NM="KOSPI",
                LIST_DD="20200101",KIND_STKCERT_TP_NM="보통주",SECUGRP_NM="주권",ISU_NM="회사")
           for i,c in enumerate(codes)]
        d=[dict(ISU_CD=c,BAS_DD=day,MKT_NM="KOSPI",ACC_TRDVOL="0") for c in codes]
        summary, common, missing, outside, _, _=compare_day(day,b,d,{"0120G0","999999"})
        self.assertEqual(summary["overlap"],1)
        self.assertEqual(summary["missing_fixed"],599)
        self.assertEqual(outside,{"999999"})
        self.assertEqual(summary["zero_volume_common"],600)
        self.assertIn("0120G0",common)
        with self.assertRaises(ValueError):
            compare_day(day,b+b[:1],d,{"0120G0"})
