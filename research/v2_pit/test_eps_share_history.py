import unittest
from copy import deepcopy
from hashlib import sha256

from stage82b.eps_review import common_only_history, fallback, shares_in_index


def table(raw_rows):
    return {"rows":[[{"text":c} for c in row] for row in raw_rows]}


class ShareHistoryTests(unittest.TestCase):
    def setUp(self):
        self.date = "2021-03-31"
        self.tables = [
            table([["(기준일 :", "2021년 03월 31일", ")", "(단위 : 주)"]]),
            table([["구 분","주식의 종류","비고"],["보통주","종류주식","합계"],
                   ["Ⅱ. 현재까지 발행한 주식의 총수","3,000","-","3,000","-"],
                   ["Ⅲ. 현재까지 감소한 주식의 총수","200","0","200","-"],
                   ["Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)","2,800","-","2,800","-"]]),
        ]
        self.original = {"status":"BLOCKED","reason":"no_eligible_quarterly_statement_and_common_share_note_pair",
                         "statement_evidence":[{"values":["1734","1404"]}]}
        self.facts = {"periods":{"current":["2021-01-01",self.date]},"fields":{
            period:{"basic_common_eps":{"candidates":[{"raw":val}]}}
            for period,val in (("current","1734"),("prior_as_reported","1404"))}}

    def test_lifetime_reconciles(self):
        self.assertEqual(common_only_history(self.tables,self.date)["common_share_counts"],
                         {"issued":3000,"reduced":200,"balance":2800})

    def test_past_preferred_stale_date_and_bad_balance(self):
        for table_num,row,col,value in [(1,2,2,"100"),(1,3,2,"100"),(1,4,1,"2,799"),
                (1,2,1,""),(1,2,3,"3,001"),(0,0,1,"2020.03.31"),(1,1,0,"기타주식")]:
            with self.subTest(value=value,row=row):
                tables = deepcopy(self.tables)
                tables[table_num]["rows"][row][col]["text"]=value
                self.assertIsNone(common_only_history(tables,self.date))

    def test_duplicate_and_current_only_rejected(self):
        self.assertIsNone(common_only_history(self.tables*2,self.date))
        del self.tables[1]["rows"][2]
        self.assertIsNone(common_only_history(self.tables,self.date))

    def test_unreconciled_per_share_note_blocks_table_fallback(self):
        for text in ["기본주당 계속영업손익 및 중단영업손익", "EPS", "가중평균유통보통주식수"]:
            row=fallback(self.facts,self.original,("<p>"+text+"</p>").encode(),b"",None,None)
            self.assertEqual(row["status"],"BLOCKED")
            self.assertEqual(row["reason"],"per_share_note_present_requires_explicit_reconciliation")

    def test_only_retains_consistent_xbrl_and_statement(self):
        from unittest.mock import patch
        with patch("stage82b.eps_review.table_rows",return_value=self.tables):
            share=b"shares"
            original=fallback(self.facts,self.original,b"<p>financial note</p>",share,"u","s")
            self.assertEqual(original["status"],"PASS")
            self.assertEqual(original["share_evidence"]["sha256"],sha256(share).hexdigest())
            self.original["statement_evidence"][0]["values"][1]="1410"
            wrong=fallback(self.facts,self.original,b"<p>financial note</p>",share,"u","s")
            self.assertEqual(wrong["reason"],"statement_differs_from_xbrl")

    def test_other_receipt_or_document_cannot_match(self):
        node='''var node1 = {}; node1['text'] = "4. 주식의 총수 등"; node1['rcpNo'] = "11";
                node1['dcmNo'] = "22"; node1['eleId'] = "5"; node1['offset'] = "123";
                node1['length'] = "25"; node1['dtd'] = "dart3.xsd";'''.encode()
        self.assertIn("dcmNo=22",shares_in_index(node,"11","22")[1])
        for doc,rcp in (("21","11"),("22","12")):
            with self.assertRaises(ValueError):
                shares_in_index(node,rcp,doc)
