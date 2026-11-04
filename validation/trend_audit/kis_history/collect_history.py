"""Bounded, resumable KIS original-price collection; independent of production code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("kis_sample_helper", ROOT.parent / "kis_v1" / "collect.py")
_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helper)
KIS, params, auth_error, redact, number, FIELDS, BASE, PATH, TR = (
    getattr(_helper, name) for name in ("KIS", "params", "auth_error", "redact", "number", "FIELDS", "BASE", "PATH", "TR"))
VERSION = "1.0.0"
CREDENTIALS = ("KIS_APP_KEY", "KIS_APP_SECRET")
OPTIONAL_FIELDS = ("mod_yn", "prtt_rate", "revl_issu_reas", "flng_cls_code")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, value, compressed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    temp.write_bytes(gzip.compress(body, mtime=0) if compressed else body)
    temp.replace(path)


def valid_day(day):
    if not isinstance(day, str) or not re.fullmatch(r"\d{8}", day):
        raise ValueError("Invalid calendar date")
    datetime.strptime(day, "%Y%m%d")
    return day


def make_requests(plan):
    if plan.get("schema_version") != 1:
        raise ValueError("Unsupported plan schema")
    tickers, sessions = plan["ordered_tickers"], plan["sessions"]
    if not tickers or len(set(tickers)) != len(tickers) or any(
            not isinstance(t, str) or not re.fullmatch(r"\d{6}", t) for t in tickers):
        raise ValueError("Tickers must be unique six-character strings")
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError("Sessions must be sorted and unique")
    for day in sessions:
        valid_day(day)
    start, end = valid_day(plan["evaluation_start"]), valid_day(plan["evaluation_end"])
    if start > end or sessions[0] < start or sessions[-1] > end:
        raise ValueError("Sessions outside evaluation range")
    size = plan.get("chunk_size", 100)
    if type(size) is not int or not 1 <= size <= 100:
        raise ValueError("Chunk size must be between 1 and 100")
    return [dict(ticker=ticker, start=chunk[0], end=chunk[-1], expected=chunk)
            for ticker in tickers for chunk in (sessions[i:i+size] for i in range(0, len(sessions), size))]


def inspect_response(sample, status, payload):
    expected = set(sample["expected"])
    result = dict(rows=[], missing_dates=sorted(expected), issues=[], application_ok=False, request_valid=False,
                  returned_dates=[], invalid_dates=[])
    issues, invalid, returned, rows, seen, conflicts = result["issues"], set(), set(), {}, {}, set()

    def issue(code, day=None):
        entry = {"code": code}
        if day is not None:
            entry["date"] = day
        issues.append(entry)

    if status != 200 or not isinstance(payload, dict) or payload.get("rt_cd") not in (0, "0"):
        issue("http_or_application_error")
        return result
    result["application_ok"] = True
    result["request_valid"] = True
    header = payload.get("output1") or {}
    if not isinstance(header, dict) or any(header.get(key) and header[key] != sample["ticker"]
                                          for key in ("stck_shrn_iscd", "mksc_shrn_iscd")):
        issue("response_symbol_mismatch")
        result["request_valid"] = False
        invalid.update(expected)
    data = payload.get("output2")
    if not isinstance(data, list):
        issue("malformed_daily_rows")
        result["request_valid"] = False
        invalid.update(expected)
        data = []
    for raw in data:
        if raw == {}:
            continue
        if not isinstance(raw, dict):
            issue("malformed_daily_row")
            continue
        try:
            day = valid_day(raw.get("stck_bsop_date"))
        except (ValueError, TypeError):
            issue("invalid_date")
            continue
        if not sample["start"] <= day <= sample["end"]:
            issue("outside_request_range", day)
            continue
        if day not in expected:
            issue("outside_frozen_calendar", day)
            continue
        returned.add(day)
        if any(raw.get(key) and raw[key] != sample["ticker"]
               for key in ("stck_shrn_iscd", "mksc_shrn_iscd")):
            invalid.add(day)
            issue("row_symbol_mismatch", day)
            result["request_valid"] = False
            continue
        try:
            values = {name: number(raw[field]) for name, field in FIELDS.items()}
        except (ValueError, KeyError, TypeError):
            invalid.add(day)
            issue("missing_or_malformed_ohlcv", day)
            continue
        if day in seen:
            if seen[day] != values:
                conflicts.add(day)
                issue("conflicting_duplicate", day)
            else:
                issue("identical_duplicate", day)
        seen[day] = values
        positive = all(value > 0 for value in values.values())
        if positive and not values["low"] <= min(values["open"], values["close"]) <= max(
                values["open"], values["close"]) <= values["high"]:
            invalid.add(day)
            issue("invalid_ohlc_order", day)
            continue
        row_status = "positive_ohlcv" if positive else "zero_or_suspension_unverified"
        if not positive:
            issue(row_status, day)
        rows[day] = dict(ticker=sample["ticker"], date=day, **values, row_status=row_status,
                         grade="KIS original-price response")
        rows[day].update({key: raw[key] for key in OPTIONAL_FIELDS if key in raw
                         and isinstance(raw[key], (str, int, float, bool))})
    invalid.update(conflicts)
    for day in invalid:
        rows.pop(day, None)
    result.update(rows=[rows[day] for day in sorted(rows)], returned_dates=sorted(returned),
                  invalid_dates=sorted(invalid), missing_dates=sorted(expected - rows.keys() - invalid))
    return result


class RateLimiter:
    def __init__(self, rate):
        self.interval, self.next_start, self.lock = 1.0 / rate, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            delay = max(0, self.next_start - time.monotonic())
            if delay:
                time.sleep(delay)
            self.next_start = time.monotonic() + self.interval


def write_csv(path, fields, rows):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def request_key(sample):
    return "{ticker}_{start}_{end}".format(**sample)


def load_attempts(out, sample, fingerprint=None):
    attempts = []
    for path in sorted((out / "raw" / request_key(sample)).glob("attempt_*.json.gz")):
        saved = json.loads(gzip.decompress(path.read_bytes()))
        if saved.get("params") != params(sample) or saved.get("endpoint") != BASE + PATH or saved.get("tr_id") != TR:
            raise ValueError("Checkpoint request identity mismatch")
        if fingerprint is not None and saved.get("plan_sha256") != fingerprint:
            raise ValueError("Checkpoint plan fingerprint mismatch")
        attempts.append((path, saved))
    return attempts


def collect(plan_path, out, client_factory=KIS, workers=4, rate_per_second=5.0, retry_failed=False):
    plan_path, out = Path(plan_path), Path(out)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    samples = make_requests(plan)
    if not 1 <= workers <= 16 or not 0 < rate_per_second < float("inf"):
        raise ValueError("Workers must be 1..16 and rate finite and >0")
    rate_per_second = min(rate_per_second, 5.0)
    out.mkdir(parents=True, exist_ok=True)
    fingerprint = sha(plan_path)
    manifest_path = out / "run_manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["plan_sha256"] != fingerprint:
        raise ValueError("Resume plan fingerprint mismatch")
    identity_path = out / "checkpoint_identity.json"
    identity = dict(plan_sha256=fingerprint, endpoint=BASE+PATH, tr_id=TR)
    if not identity_path.exists() and any((out / "raw").glob("**/attempt_*.json.gz")):
        raise ValueError("Raw checkpoints exist without checkpoint identity")
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("Checkpoint plan fingerprint mismatch")
    atomic_json(identity_path, identity)
    credentials = tuple(os.getenv(name) for name in CREDENTIALS)
    manifest = dict(collector_version=VERSION, collector_sha256=sha(Path(__file__)),
                    helper_sha256=sha(Path(_helper.__file__)), plan_sha256=fingerprint, plan=plan,
                    started_at=now(), endpoint=BASE+PATH, tr_id=TR,
                    credential_present=dict(zip(CREDENTIALS, map(bool, credentials))),
                    workers=workers, rate_per_second=rate_per_second, retry_failed=retry_failed)
    lock, stop, limiter = threading.Lock(), threading.Event(), RateLimiter(rate_per_second)
    pending, selected = [], {}
    progress = {"requests_total": len(samples), "requests_finished": 0, "live_attempts": 0}
    secrets = list(credentials)

    def advance():
        with lock:
            progress["requests_finished"] += 1
            count = progress["requests_finished"]
            if count % 25 == 0:
                atomic_json(out / "progress.json", dict(progress, updated_at=now()))
            if count % 100 == 0:
                print(f"KIS history: {count}/{len(samples)} windows processed", flush=True)

    def run_one(client, sample, rate_wrapped):
        key = request_key(sample)
        previous = load_attempts(out, sample, fingerprint)
        for attempt in range(3):
            if stop.is_set():
                return
            if not rate_wrapped:
                limiter.wait()
            if stop.is_set():
                return
            try:
                status, payload = client.quote(sample)
            except Exception as exc:
                status, payload = None, {"collector_error_type": type(exc).__name__}
            payload = redact(payload, secrets)
            saved = dict(params=params(sample), http_status=status, body=payload,
                         collected_at=now(), endpoint=BASE+PATH, tr_id=TR,
                         plan_sha256=fingerprint, attempt=len(previous)+attempt+1)
            path = out / "raw" / key / f"attempt_{saved['attempt']:04d}.json.gz"
            if path.exists():
                raise ValueError("Refusing to overwrite raw attempt")
            atomic_json(path, saved, compressed=True)
            with lock:
                selected[key] = (path, saved)
                progress["live_attempts"] += 1
            if auth_error(status, payload):
                stop.set()
                manifest["blocked_reason"] = "authentication_or_permission_error"
                break
            transient = status is None or status == 429 or (isinstance(status, int) and 500 <= status < 600)
            transient = transient or (isinstance(payload, dict) and payload.get("msg_cd") == "EGW00201")
            if not transient:
                break
            if attempt < 2:
                stop.wait(min(2 ** attempt, 4))
            else:
                stop.set()
                manifest["blocked_reason"] = "transient_retry_budget_exhausted"
        advance()

    def worker(token):
        client = client_factory(*credentials)
        client.token = token
        wrapped = isinstance(client, KIS)
        if wrapped:
            original_get = client.session.get

            def limited_get(*args, **kwargs):
                limiter.wait()
                if stop.is_set():
                    raise client.requests.RequestException("Collection stopped")
                return original_get(*args, **kwargs)
            client.session.get = limited_get
        try:
            while not stop.is_set():
                with lock:
                    sample = pending.pop(0) if pending else None
                if sample is None:
                    break
                run_one(client, sample, wrapped)
        finally:
            if hasattr(client, "session"):
                client.session.close()

    try:
        for sample in samples:
            attempts = load_attempts(out, sample, fingerprint)
            successes = [(path, saved) for path, saved in attempts
                         if inspect_response(sample, saved["http_status"], saved["body"])["request_valid"]]
            if successes or (attempts and not retry_failed):
                selected[request_key(sample)] = (successes or attempts)[-1]
                advance()
            else:
                pending.append(sample)
        if pending and not all(credentials):
            manifest["blocked_reason"] = "credentials_unavailable"
        elif pending:
            auth_client = None
            try:
                auth_client = client_factory(*credentials)
                auth_client.authenticate()
                token = auth_client.token
                if not token:
                    raise ValueError("Authentication returned no token")
                secrets.append(token)
            except Exception as exc:
                manifest["blocked_reason"] = "authentication_unavailable"
                manifest["authentication_error_type"] = type(exc).__name__
                stop.set()
            finally:
                if auth_client is not None and hasattr(auth_client, "session"):
                    auth_client.session.close()
            if not stop.is_set():
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(worker, token) for _ in range(workers)]
                    for future in futures:
                        future.result()
    except BaseException as exc:
        stop.set()
        manifest["collector_error_type"] = type(exc).__name__
        raise
    finally:
        finalize(out, samples, selected, manifest)
        atomic_json(out / "progress.json", dict(progress, updated_at=now(), finished=True))
    return manifest


def finalize(out, samples, selected, manifest):
    rows, gaps, requests, coverage = [], [], [], {}
    successful = failed = unexecuted = 0
    for sample in samples:
        ticker = sample["ticker"]
        counts = coverage.setdefault(ticker, dict(ticker=ticker, expected_rows=0, normalized_rows=0,
            positive_rows=0, zero_rows=0, invalid_rows=0, missing_rows=0, requests_successful=0,
            requests_failed=0, requests_unexecuted=0))
        counts["expected_rows"] += len(sample["expected"])
        record = selected.get(request_key(sample))
        entry = dict(ticker=ticker, start=sample["start"], end=sample["end"], expected_rows=len(sample["expected"]))
        if record:
            path, saved = record
            result = inspect_response(sample, saved["http_status"], saved["body"])
            ok = result["request_valid"]
            successful += int(ok)
            failed += int(not ok)
            counts["requests_successful" if ok else "requests_failed"] += 1
            body = saved["body"] if isinstance(saved["body"], dict) else {}
            entry.update(http_status=saved["http_status"], rt_cd=body.get("rt_cd"), msg_cd=body.get("msg_cd"),
                application_ok=result["application_ok"], request_valid=ok, raw_file=str(path.relative_to(out)), raw_sha256=sha(path),
                attempts=len(load_attempts(out, sample, manifest["plan_sha256"])), collected_at=saved["collected_at"],
                issues=result["issues"], returned_dates=result["returned_dates"])
            for row in result["rows"]:
                rows.append(dict(row, source_file=str(path.relative_to(out))))
                counts["normalized_rows"] += 1
                counts["positive_rows" if row["row_status"] == "positive_ohlcv" else "zero_rows"] += 1
        else:
            unexecuted += 1
            counts["requests_unexecuted"] += 1
            result = dict(missing_dates=sample["expected"], invalid_dates=[])
            entry.update(application_ok=False, reason=manifest.get("blocked_reason", "unexecuted"), issues=[])
        for kind in ("missing", "invalid"):
            for day in result[kind+"_dates"]:
                counts[kind+"_rows"] += 1
                gaps.append(dict(ticker=ticker, date=day, gap_status=kind,
                                 reason=";".join(i["code"] for i in entry["issues"] if i.get("date") in (None, day))
                                 or entry.get("reason", "no_returned_row")))
        requests.append(entry)
    write_csv(out / "normalized.csv", ["ticker", "date", *FIELDS, *OPTIONAL_FIELDS, "row_status", "grade", "source_file"], rows)
    write_csv(out / "gaps.csv", ["ticker", "date", "gap_status", "reason"], gaps)
    write_csv(out / "coverage.csv", list(next(iter(coverage.values()))), coverage.values())
    temp = out / "requests.jsonl.tmp"
    temp.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True)+"\n" for r in requests), encoding="utf-8")
    temp.replace(out / "requests.jsonl")
    totals = {key: sum(c[key] for c in coverage.values()) for key in (
        "expected_rows", "normalized_rows", "positive_rows", "zero_rows", "invalid_rows", "missing_rows")}
    complete = successful == len(samples) and not manifest.get("collector_error_type")
    manifest.update(totals, requests_total=len(samples), requests_successful=successful,
        requests_failed=failed, requests_unexecuted=unexecuted, retrieval_complete=complete,
        price_grid_complete=totals["normalized_rows"] == totals["expected_rows"],
        positive_grid_complete=totals["positive_rows"] == totals["expected_rows"],
        data_ready=False, backtest_ready=False,
        exit_code=0 if complete else 2, finished_at=now(),
        output_sha256={name: sha(out/name) for name in ("normalized.csv", "gaps.csv", "coverage.csv", "requests.jsonl")},
        historical_reference_or_limits_verified=False)
    for field in ("http_status", "rt_cd", "msg_cd"):
        counts = {}
        for entry in requests:
            value = str(entry.get(field, "unexecuted"))
            counts[value] = counts.get(value, 0) + 1
        manifest[field+"_counts"] = counts
    atomic_json(out / "run_manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "plan.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate", type=float, default=5.0)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    try:
        result = collect(args.plan, args.out, workers=args.workers,
                         rate_per_second=args.rate, retry_failed=args.retry_failed)
    except Exception as exc:
        print("KIS history stopped:", type(exc).__name__)
        raise SystemExit(2)
    print("KIS history:", result["requests_successful"], "/", result["requests_total"], "successful windows")
    raise SystemExit(result["exit_code"])
