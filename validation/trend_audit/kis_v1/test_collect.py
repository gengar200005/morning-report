import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from collect import BASE, PATH, TR, KIS, collect, normalize, params, redact

SAMPLE = dict(ticker="000370",start="20160302",end="20160303",expected=["20160302","20160303"])


def row(day="20160303", **changes):
    return dict(stck_bsop_date=day,stck_oprc="100",stck_hgpr="120",
                stck_lwpr="90",stck_clpr="110",acml_vol="1234",**changes)


def response(*rows):
    return dict(rt_cd="0",output1={"stck_shrn_iscd":"000370"},output2=list(rows))


class SampleTests(unittest.TestCase):
    def test_original_query_and_auth_transport(self):
        transport = Mock()
        transport.post.return_value.status_code = 200
        transport.post.return_value.json.return_value = {"access_token":"test-token"}
        transport.get.return_value.status_code = 200
        transport.get.return_value.json.return_value = response(row())
        with patch.dict(sys.modules,{"requests":Mock(Session=Mock(return_value=transport))}):
            client = KIS("test-key","test-secret")
            client.authenticate()
            client.quote(SAMPLE)
        self.assertEqual(transport.post.call_args.args,(BASE+"/oauth2/tokenP",))
        self.assertEqual(transport.get.call_args.args,(BASE+PATH,))
        self.assertEqual(transport.get.call_args.kwargs["headers"]["tr_id"],TR)
        self.assertEqual(transport.get.call_args.kwargs["params"],{
            "FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":"000370",
            "FID_INPUT_DATE_1":"20160302","FID_INPUT_DATE_2":"20160303",
            "FID_PERIOD_DIV_CODE":"D","FID_ORG_ADJ_PRC":"1"})

    def test_rows_preserve_symbol_dates_and_ohlcv(self):
        rows,issues = normalize(SAMPLE,200,response(row(),row("20160302"),{}))
        self.assertEqual(issues,[])
        self.assertEqual(rows[0],dict(ticker="000370",date="20160302",open=100,high=120,low=90,
                                      close=110,volume=1234,grade="KIS original-price response"))

    def test_reject_http_or_kis_error_or_empty(self):
        for status,body in [(403,response(row())),(200,dict(rt_cd="1",output2=[row()])),
                            (200,response()),(200,response({}))]:
            rows,issues = normalize(SAMPLE,status,body)
            self.assertEqual(rows,[])
            self.assertTrue(issues)

    def test_recent_rows_duplicate_conflict_and_missing_field(self):
        bad = row()
        del bad["acml_vol"]
        conflict = {**row(),"stck_oprc":"101"}
        rows,issues = normalize(SAMPLE,200,response(row("20261103"),row(),row(),conflict,bad))
        self.assertEqual(rows,[])
        for issue in ("outside request","duplicate","conflicting duplicate","missing/malformed","Missing expected"):
            self.assertTrue(any(issue in line for line in issues),issue)

    def test_invalid_price_zero_volume_and_symbol(self):
        for bad in ({**row(),"stck_hgpr":"89"},{**row(),"acml_vol":"0"},
                    row(stck_shrn_iscd="999999"),{**row(),"stck_oprc":"100.5"}):
            self.assertEqual(normalize(SAMPLE,200,response(bad))[0],[])

    def test_permission_failure_not_repeated_and_cache_reused(self):
        client = Mock()
        client.quote.return_value = (403,{"rt_cd":"1","msg1":"권한 없음"})
        factory = Mock(return_value=client)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{"KIS_APP_KEY":"key","KIS_APP_SECRET":"secret"}):
            out = Path(d)
            manifest = collect(out,factory)
            self.assertEqual(client.quote.call_count,1)
            self.assertIn("stopped",manifest["requests"][1]["reason"])
            self.assertFalse((out/"kis_normalized.csv").exists())
            again = collect(out,factory)
            self.assertTrue(again["requests"][0]["reused_response"])
            self.assertEqual(client.quote.call_count,1)

    def test_missing_credentials_do_not_invoke_transport(self):
        factory = Mock()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{},clear=True):
            out = Path(d)
            result = collect(out,factory)
            self.assertTrue(all(row["reason"]=="KIS credentials unavailable" for row in result["requests"]))
            self.assertFalse(any(out.glob("*raw.json")))
            factory.assert_not_called()

    def test_redaction(self):
        self.assertEqual(redact({"access_token":"token","nested":[{"Authorization":"secret","msg":"x secret"}]},
                                ("secret","token")),{"nested":[{"msg":"x [redacted]"}]})
