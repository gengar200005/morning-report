#!/usr/bin/env python3
"""Bounded read-only KRX KOSPI historical-universe smoke test.

No trading/orders, no automatic full-history collection, and no secret persistence.
"""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

import requests

BASE = "https://data-dbg.krx.co.kr/svc/apis/sto/"
ENDPOINTS = {
    "basic": "stk_isu_base_info",
    "daily": "stk_bydd_trd",
}
DATES = (
    "20160601",  # Hanjin Shipping before delisting
    "20170306",  # Hanjin Shipping last trading day
    "20170307",  # Hanjin Shipping delisted
    "20180208",  # Celltrion before KOSPI transfer
    "20180209",  # Celltrion KOSPI transfer
    "20200414",  # KRX sample contract date
    "20261030",  # last known complete evaluation day
)
ANCHORS = (
    ("20160601", "117930", "present", "Hanjin Shipping pre-delisting"),
    ("20170307", "117930", "absent", "Hanjin Shipping delisting date"),
    ("20180208", "068270", "absent", "Celltrion KOSDAQ pre-transfer"),
    ("20180209", "068270", "present", "Celltrion KOSPI transfer date"),
)
USER_AGENT = "morning-report-validation-krx-readonly/1"
EXPECTED_FIELDS = {"basic": "ISU_SRT_CD", "daily": "ISU_CD"}


def scrub(value, secret):
    """Remove secrets even if a provider reflects them in a JSON error."""
    if isinstance(value, dict):
        return {
            k: scrub(v, secret)
            for k, v in value.items()
            if not any(term in k.lower() for term in ("auth_key", "authorization", "token", "secret", "apikey"))
        }
    if isinstance(value, list):
        return [scrub(x, secret) for x in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def classify(status, body, kind, day):
    """Strict schema check. Empty success is NOT proof of no listing."""
    if kind not in ENDPOINTS or day not in DATES:
        raise ValueError("Date or API outside read-only allowlist")
    if status != 200:
        return {"ok": False, "status": "http_error", "http_status": status, "n": 0}
    if not isinstance(body, dict) or not isinstance(body.get("OutBlock_1"), list):
        return {"ok": False, "status": "unexpected_response_schema", "http_status": status, "n": 0}
    rows = body["OutBlock_1"]
    if len(rows) > 10000:
        return {"ok": False, "status": "oversized_response_rows", "http_status": status, "n": len(rows)}
    field = EXPECTED_FIELDS[kind]
    if any(not isinstance(r, dict) or not isinstance(r.get(field), str) or not r[field] for r in rows):
        return {"ok": False, "status": "invalid_row_code", "http_status": status, "n": len(rows)}
    if kind == "daily" and any(r.get("BAS_DD") not in (None, "", day) for r in rows):
        return {"ok": False, "status": "wrong_day_in_response", "http_status": status, "n": len(rows)}
    return {
        "ok": True,
        "status": "empty_success_not_absence_proof" if not rows else "rows_returned",
        "http_status": status,
        "n": len(rows),
        "unique_codes": len({r[field] for r in rows}),
        "fields": sorted({k for r in rows[:3] for k in r}),
    }


def codes(rows, kind):
    field = EXPECTED_FIELDS[kind]
    out = set()
    for item in rows:
        raw = str(item.get(field, "")).strip()
        code = raw[1:] if raw.startswith("A") else raw
        if re.fullmatch(r"\d{6}", code):
            out.add(code)
    return out


def request_once(session, kind, day, secret):
    if kind not in ENDPOINTS or day not in DATES:
        raise ValueError("Unsupported URL input")
    url = BASE + ENDPOINTS[kind]
    response = session.get(
        url,
        headers={"AUTH_KEY": secret, "Accept": "application/json", "User-Agent": USER_AGENT},
        params={"basDd": day},
        timeout=(8, 20),
        allow_redirects=False,  # Never forward the auth header to redirects.
    )
    status = response.status_code
    # Read only JSON; do not preserve HTML errors or raw HTTP headers.
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    return status, scrub(body, secret)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python collect.py OUTPUT_DIRECTORY")
    secret = os.environ.get("KRX_API_KEY", "")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if not secret or len(secret) < 8:
        print("KRX_API_KEY is unavailable or invalid. No API calls made.")
        return 2

    result = {
        "schema": 1,
        "purpose": "seven-day KOSPI PIT official data smoke; not a complete universe",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": ENDPOINTS, "dates": list(DATES),
        "requests": [], "anchors": [], "date_comparisons": [],
        "coverage_complete": False, "production_strategy_modified": False,
    }
    all_rows = {}
    with requests.Session() as session:
        for kind in ENDPOINTS:
            unauthorized = False
            for day in DATES:
                if unauthorized:
                    result["requests"].append({
                        "kind": kind, "date": day, "status": "skipped_after_auth_failure",
                        "ok": False,
                    })
                    continue
                status = None
                body = {"non_json_response": True}
                for attempt in range(3):
                    # Limit traffic to 1 request/second, including retries.
                    time.sleep(1)
                    try:
                        status, body = request_once(session, kind, day, secret)
                    except requests.RequestException:
                        status, body = None, {"network_failure": True}
                    if status not in (None, 429, 500, 502, 503, 504) or attempt == 2:
                        break
                    time.sleep(2)

                classified = classify(status, body, kind, day)
                if status in (401, 403):
                    unauthorized = True
                    classified["status"] = "service_auth_or_approval_required"
                file_name = f"{kind}_{day}.json.gz"
                raw = json.dumps(
                    {"kind": kind, "date": day, "http_status": status, "body": body},
                    sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
                compressed = gzip.compress(raw, mtime=0)
                path = out / file_name
                path.write_bytes(compressed)
                classified.update({
                    "kind": kind, "date": day,
                    "raw_file": file_name,
                    "raw_sha256": hashlib.sha256(compressed).hexdigest(),
                })
                result["requests"].append(classified)
                all_rows[(kind, day)] = body.get("OutBlock_1", []) if classified["ok"] else []
                print(f"{kind} {day}: {classified['status']} rows={classified['n']} HTTP={status}", flush=True)

    for day, code, desired, rationale in ANCHORS:
        item = {"date": day, "ticker": code, "expected": desired, "reason": rationale}
        for kind in ENDPOINTS:
            record = next(x for x in result["requests"] if x["kind"] == kind and x["date"] == day)
            if record.get("ok") and record.get("n", 0) > 0:
                item[kind] = "present" if code in codes(all_rows[(kind, day)], kind) else "absent"
            else:
                item[kind] = "unverified"
        result["anchors"].append(item)

    for day in DATES:
        a = all_rows.get(("basic", day), [])
        b = all_rows.get(("daily", day), [])
        status_a = next(x for x in result["requests"] if x["kind"] == "basic" and x["date"] == day)
        status_b = next(x for x in result["requests"] if x["kind"] == "daily" and x["date"] == day)
        if status_a.get("ok") and status_b.get("ok") and a and b:
            base_codes = codes(a, "basic")
            trade_codes = codes(b, "daily")
            result["date_comparisons"].append({
                "date": day,
                "basic_codes": len(base_codes),
                "traded_codes": len(trade_codes),
                "traded_without_basic_count": len(trade_codes - base_codes),
                "basic_without_trade_count": len(base_codes - trade_codes),
                "traded_without_basic_sample": sorted(trade_codes - base_codes)[:10],
                "basic_without_trade_sample": sorted(base_codes - trade_codes)[:10],
                "basic_security_classes": dict(Counter(
                    str(x.get("KIND_STKCERT_TP_NM", "UNKNOWN")) for x in a
                )),
            })
    result["checks"] = {
        "any_valid_basic": any(x["kind"] == "basic" and x["status"] == "rows_returned" for x in result["requests"]),
        "any_valid_daily": any(x["kind"] == "daily" and x["status"] == "rows_returned" for x in result["requests"]),
        "auth_issue": any(x["status"] == "service_auth_or_approval_required" for x in result["requests"]),
        "all_requested_success": all(x.get("ok") for x in result["requests"]),
    }
    p = out / "summary.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUMMARY " + json.dumps(result["checks"], sort_keys=True))
    return 0 if result["checks"]["all_requested_success"] and all([
        result["checks"]["any_valid_basic"], result["checks"]["any_valid_daily"]
    ]) else 2


if __name__ == "__main__":
    sys.exit(main())
