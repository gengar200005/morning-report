"""Small offline behavioral checks for the full KIS history collector."""
import gzip
import json
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collect_history as history


def plan(days=None, tickers=None, chunk_size=100):
    days = days or ["20160104", "20160105", "20160106"]
    return {
        "schema_version": 1,
        "ordered_tickers": tickers or ["005930"],
        "sessions": days,
        "evaluation_start": days[0],
        "evaluation_end": days[-1],
        "chunk_size": chunk_size,
        "sources": {"calendar": "offline synthetic fixture", "universe": "offline synthetic fixture"},
    }


def raw_row(day, **overrides):
    row = dict(stck_bsop_date=day, stck_oprc="100", stck_hgpr="120",
               stck_lwpr="90", stck_clpr="110", acml_vol="1000")
    row.update(overrides)
    return row


def payload(rows, ticker="005930"):
    return {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "OK",
            "output1": {"stck_shrn_iscd": ticker}, "output2": rows}


class HistoryTests(unittest.TestCase):
    def sample(self):
        return history.make_requests(plan())[0]

    def inspect(self, rows):
        return history.inspect_response(self.sample(), 200, payload(rows))

    def test_chunks_cover_each_symbol_session_once_and_keep_leading_zero(self):
        days = [(date(2016, 1, 1) + timedelta(days=n)).strftime("%Y%m%d")
                for n in range(203)]
        requests = history.make_requests(plan(days, ["005930", "000660"]))
        self.assertEqual(len(requests), 6)
        for ticker in ["005930", "000660"]:
            chunks = [r for r in requests if r["ticker"] == ticker]
            self.assertEqual([len(r["expected"]) for r in chunks], [100, 100, 3])
            self.assertEqual([d for r in chunks for d in r["expected"]], days)
            for chunk in chunks:
                self.assertEqual(chunk["start"], chunk["expected"][0])
                self.assertEqual(chunk["end"], chunk["expected"][-1])

    def test_plan_refuses_chunks_above_endpoint_limit(self):
        with self.assertRaises(ValueError):
            history.make_requests(plan(chunk_size=101))

    def test_recent_response_cannot_fill_a_2016_request(self):
        result = self.inspect([raw_row("20261103")])
        self.assertEqual(result["rows"], [])
        self.assertEqual(set(result["missing_dates"]), set(self.sample()["expected"]))
        self.assertTrue(result["issues"])

    def test_zero_prices_or_volume_are_preserved_but_flagged(self):
        for overrides in ({"stck_oprc": "0", "stck_hgpr": "0", "stck_lwpr": "0", "stck_clpr": "0"},
                          {"acml_vol": "0"}):
            with self.subTest(overrides=overrides):
                result = self.inspect([raw_row("20160104", **overrides)])
                self.assertEqual(len(result["rows"]), 1)
                self.assertEqual(result["rows"][0]["row_status"], "zero_or_suspension_unverified")
                self.assertNotIn("20160104", result["missing_dates"])

    def test_positive_ohlcv_preserves_exact_integer_fields(self):
        result = self.inspect([raw_row("20160104")])
        row = result["rows"][0]
        self.assertEqual({k: row[k] for k in ("ticker", "date", "open", "high", "low", "close", "volume")},
                         dict(ticker="005930", date="20160104", open=100, high=120, low=90, close=110, volume=1000))
        self.assertEqual(row["row_status"], "positive_ohlcv")

    def test_conflicting_duplicate_is_removed_regardless_of_order(self):
        rows = [raw_row("20160104"), raw_row("20160104", stck_clpr="115")]
        for ordered in (rows, rows[::-1]):
            result = self.inspect(ordered)
            self.assertEqual(result["rows"], [])
            self.assertIn("20160104", result["invalid_dates"])
            self.assertTrue(result["issues"])

    def test_wrong_header_or_row_symbol_is_rejected(self):
        wrong_header = history.inspect_response(self.sample(), 200,
            payload([raw_row("20160104")], ticker="000660"))
        wrong_row = self.inspect([raw_row("20160104", stck_shrn_iscd="000660")])
        for result in (wrong_header, wrong_row):
            self.assertEqual(result["rows"], [])
            self.assertTrue(result["issues"])

    def test_malformed_prices_dates_and_impossible_ohlc_do_not_create_rows(self):
        cases = [raw_row("20160104", stck_oprc="1,000"),
                 raw_row("20160104", acml_vol="-1"),
                 raw_row("20160104", stck_clpr="121"), raw_row("20160230"),
                 {k: v for k, v in raw_row("20160104").items() if k != "stck_bsop_date"}]
        for row in cases:
            with self.subTest(row=row):
                result = self.inspect([row])
                self.assertEqual(result["rows"], [])
                self.assertTrue(result["issues"])

    def test_partial_response_reports_gap_without_fabricating_a_row(self):
        result = self.inspect([raw_row("20160104"), raw_row("20160106")])
        self.assertEqual([r["date"] for r in result["rows"]], ["20160104", "20160106"])
        self.assertEqual(result["missing_dates"], ["20160105"])

    def run_collection(self, directory, input_plan, responder, **kwargs):
        plan_path = Path(directory) / "plan.json"
        plan_path.write_text(json.dumps(input_plan), encoding="utf-8")
        calls = {"factory": 0, "auth": 0, "quote": 0}

        class FakeClient:
            def __init__(self, key, secret):
                calls["factory"] += 1
                self.key, self.secret, self.token = key, secret, None

            def authenticate(self):
                calls["auth"] += 1
                self.token = "offline-token-secret"

            def quote(self, sample):
                calls["quote"] += 1
                return responder(sample)

        with patch.dict("os.environ", {"KIS_APP_KEY": "offline-app-key-secret",
                                       "KIS_APP_SECRET": "offline-app-secret-secret"}), \
             patch.object(history.time, "sleep", return_value=None):
            result = history.collect(plan_path, Path(directory) / "out", FakeClient,
                                     workers=1, rate_per_second=5.0, **kwargs)
        return result, calls

    def test_complete_checkpoints_resume_without_client_or_authentication(self):
        p = plan(tickers=["005930", "000660"], chunk_size=2)
        def respond(sample):
            return 200, payload([raw_row(d) for d in sample["expected"]], sample["ticker"])
        with tempfile.TemporaryDirectory() as directory:
            first, calls = self.run_collection(directory, p, respond)
            self.assertEqual(calls["quote"], 4)
            self.assertTrue(first["retrieval_complete"])
            self.assertEqual(first["normalized_rows"], 6)
            second, calls = self.run_collection(directory, p, respond)
            self.assertEqual(calls, {"factory": 0, "auth": 0, "quote": 0})
            self.assertEqual(second["normalized_rows"], 6)
            self.assertTrue(second["data_ready"])

    def test_changed_plan_cannot_reuse_existing_run(self):
        def respond(sample):
            return 200, payload([raw_row(d) for d in sample["expected"]])
        with tempfile.TemporaryDirectory() as directory:
            self.run_collection(directory, plan(), respond)
            changed = plan(tickers=["000660"])
            with self.assertRaises(ValueError):
                self.run_collection(directory, changed, respond)

    def test_authentication_response_stops_remaining_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_collection(directory, plan(chunk_size=1),
                lambda sample: (401, {"rt_cd": "1", "msg1": "invalid token"}))
            self.assertEqual(calls["quote"], 1)
            self.assertFalse(result["retrieval_complete"])
            self.assertGreater(result["requests_unexecuted"], 0)

    def test_checkpoint_own_plan_identity_must_match_even_with_valid_manifest(self):
        def respond(sample):
            return 200, payload([raw_row(d) for d in sample["expected"]])
        with tempfile.TemporaryDirectory() as directory:
            self.run_collection(directory, plan(), respond)
            checkpoint = next((Path(directory) / "out" / "raw").rglob("attempt_*.json.gz"))
            saved = json.loads(gzip.decompress(checkpoint.read_bytes()))
            saved["plan_sha256"] = "0" * 64
            checkpoint.write_bytes(gzip.compress(json.dumps(saved).encode("utf-8")))
            with self.assertRaises(ValueError):
                self.run_collection(directory, plan(), respond)

    def test_symbol_error_checkpoint_requires_explicit_failed_retry(self):
        def wrong(sample):
            return 200, payload([raw_row(d) for d in sample["expected"]], "000660")
        def correct(sample):
            return 200, payload([raw_row(d) for d in sample["expected"]])
        with tempfile.TemporaryDirectory() as directory:
            failed, calls = self.run_collection(directory, plan(), wrong)
            self.assertEqual(calls["quote"], 1)
            self.assertFalse(failed["retrieval_complete"])
            self.assertEqual(failed["normalized_rows"], 0)
            reused, calls = self.run_collection(directory, plan(), correct)
            self.assertEqual(calls, {"factory": 0, "auth": 0, "quote": 0})
            self.assertFalse(reused["retrieval_complete"])
            retried, calls = self.run_collection(directory, plan(), correct, retry_failed=True)
            self.assertEqual(calls["quote"], 1)
            self.assertTrue(retried["retrieval_complete"])
            self.assertEqual(len(list((Path(directory) / "out" / "raw").rglob("attempt_*.json.gz"))), 2)

    def test_rate_limit_failure_retries_are_bounded_and_run_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.run_collection(directory, plan(chunk_size=1),
                lambda sample: (429, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"}))
            self.assertLessEqual(calls["quote"], 3)
            self.assertGreaterEqual(calls["quote"], 1)
            self.assertFalse(result["retrieval_complete"])
            self.assertGreater(result["requests_unexecuted"], 0)

    def test_saved_raw_and_reports_redact_credentials_and_token(self):
        def respond(sample):
            return 401, {"rt_cd": "1", "access_token": "offline-token-secret",
                         "authorization": "Bearer offline-token-secret",
                         "msg1": "invalid token offline-app-key-secret offline-app-secret-secret offline-token-secret"}
        with tempfile.TemporaryDirectory() as directory:
            self.run_collection(directory, plan(), respond)
            saved = []
            for path in (Path(directory) / "out").rglob("*"):
                if path.is_file():
                    content = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
                    saved.append(content.decode("utf-8"))
            self.assertTrue(saved)
            combined = "\n".join(saved)
            for secret in ("offline-app-key-secret", "offline-app-secret-secret", "offline-token-secret"):
                self.assertNotIn(secret, combined)


if __name__ == "__main__":
    unittest.main()
