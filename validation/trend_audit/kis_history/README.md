# KIS full-history collection

This standalone collector imports only the immutable `../kis_v1/collect.py` KIS
helper, never the production report. It preserves the plan's ticker strings,
frozen session calendar, order, and source provenance. It does not edit signals,
selection rules, or the frozen universe.

Run from the repository with the two KIS credential environment variables already
present. Credentials and the one issued token are retained only in memory.

```bash
python validation/trend_audit/kis_history/collect_history.py \
  --plan validation/trend_audit/kis_history/plan.json \
  --out /path/to/history-results --workers 4 --rate 5
```

The schema-version-1 plan contains `ordered_tickers`, `sessions` (sorted unique
YYYYMMDD strings), `evaluation_start`, `evaluation_end`, and `chunk_size` (1–100).
Additional source hashes are copied into the run manifest. The full frozen plan
has 162 tickers, 2,650 sessions, 4,374 request windows, and 429,300 expected
ticker/session observations. Each window has at most 100 expected sessions.

Authentication occurs once per run requiring new responses. Each worker has its
own client and requests Session; the token is copied in memory. All actual quote
GET starts, including the immutable helper's internal retries, share one start
limiter capped at five per second. A requested higher rate is capped at five.
There are at most three outer attempts per window; each helper call can itself
make at most two network attempts. Transport errors, HTTP 429/5xx, and EGW00201
receive bounded retries. Exhausting this budget stops new work. Authentication
and permission errors also stop new work without requesting another token.
Already in-flight requests can finish. Ordinary application errors are recorded
without retry; an empty successful response is a coverage gap and is not retried.

Every returned attempt is an atomic gzip JSON checkpoint under
`raw/TICKER_START_END/attempt_NNNN.json.gz`. It records sanitized response body,
request parameters, HTTP status, timestamp, endpoint, transaction ID, and plan
fingerprint. Attempts are immutable, including failed attempts. Raw response
hashes and the selected attempt appear in `requests.jsonl`. No authorization
headers are persisted. Helper network retries are internal to one returned
attempt; their discarded responses are not exposed by the immutable helper.

Resume using the same output directory and byte-identical plan. Successful KIS
application responses with valid structure and symbol identity are reused even
when they contain gaps or zeros. Failed
windows are reused by default; `--retry-failed` retries them with new attempt
numbers. A different plan is rejected. A separate checkpoint identity file
protects resume even if a run stops before its final manifest is written.

Outputs are generated even when credentials are absent or collection stops:

* `normalized.csv`: every accepted nonnegative integer OHLCV row, with no
  rounding or forward fill. `positive_ohlcv` requires positive coherent OHLC and
  positive volume. Zeros are retained as `zero_or_suspension_unverified`; they
  are not valid execution observations. Every row references its source attempt.
  Optional `mod_yn`, `prtt_rate`, `revl_issu_reas`, and `flng_cls_code` values
  are preserved as returned; their presence does not certify corporate actions.
* `coverage.csv`: per-ticker expected, accepted, positive, zero, invalid, and
  missing counts, plus successful/failed/unexecuted request counts.
* `gaps.csv`: one row per missing or invalid expected observation. Missing and
  invalid counts are disjoint. Listing, delisting, and suspension dates are not
  inferred from absent observations or zeros.
* `requests.jsonl`: one record per planned window with HTTP/KIS status,
  validation issues, returned dates, checkpoint path/hash, and attempt count.
* `run_manifest.json`: plan/source provenance, collector/helper hashes, output
  hashes, counts, credential-presence booleans, and completion/readiness flags.
* `progress.json`: updated every 25 processed windows and on finalization.
  Standard output reports only aggregate progress every 100 windows.

Validation checks supplied response symbols, real dates, requested bounds,
frozen calendar membership, integer OHLCV fields, positive OHLC ordering, and
duplicate consistency. Identical duplicates are flagged and deduplicated;
conflicting duplicates remove that date. Missing fields and symbol conflicts
are invalid observations rather than ordinary absent rows. Empty padding
objects are ignored. Unexpected dates are flagged without extending the plan.

Exit status **0** means every planned window produced HTTP 200 and KIS success;
**2** means authentication, transport/application failure, malformed response
structure, symbol identity failure, or unexecuted windows.
Successful responses can still have incomplete/invalid/zero data, so consumers
must inspect `price_grid_complete` and `positive_grid_complete` separately.
The first requires every expected row to be accepted (including zero rows);
the second requires every expected row to be positive and accepted. Both
`data_ready` and `backtest_ready` remain false at this collection stage.
Neither original-price responses nor current `output1`
metadata verify historical reference prices or historical price limits. No
exchange-raw verification claim is made.

Pure validation interfaces are `make_requests(plan)` and
`inspect_response(sample, status, payload)`. Offline tests can inject a
`client_factory(key, secret)` whose clients expose `authenticate()`, `token`,
and `quote(sample) -> (status, payload)`. No live API call is needed for tests.
