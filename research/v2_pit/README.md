# Morning Report V2 PIT foundation

Offline research only. The builder keeps official KRX observations, the vendor
snapshot, and evidence for corporate actions separate. The output is private.
Keep the database, raw archives, and logs with detailed records outside Git.
No network calls are made by the builder or replay smoke.

## Rebuild

Use Python 3.12 and install the dependencies in `requirements.txt`. Obtain
the existing monthly KRX archives and the V1 evidence from their private
locations. Extract `kospi_pit/source_panel`, `kospi_pit/code` and
`kospi_pit/inputs/v1_ca_stage` from the V1 PIT alpha evidence archive. Use the
corrected evidence ZIP as received.

```sh
python -m pip install -r research/v2_pit/requirements.txt
python research/v2_pit/foundation.py --krx /private/monthly \
  --vendor /private/kospi_pit/source_panel \
  --actions /private/kospi_pit/inputs/v1_ca_stage \
  --correction /private/V1_KRX_PIT_CA_CORRECTED_EVIDENCE_20261105.zip \
  --output /private/v2.sqlite > /private/validation.json
python -m unittest discover -s research/v2_pit
python research/v2_pit/smoke.py /private/v2.sqlite /private/kospi_pit/code
```

The build checks the pinned XKRX session calendar with the same 2026 closure
exceptions used by the V1 collector. Both KRX endpoints must report the same
daily code set. The build fails on missing months by default. Use
`--allow-partial` for explicitly labeled diagnostics. The build stages the
SQLite file and replaces the target only after integrity checks.

## Reading the database

| Object | Interpretation |
| --- | --- |
| `membership`, `securities` | Date-specific KOSPI observations, code/ISIN/name/class, observed first and last dates. First and last observations are distinct from legal admission or delisting. |
| `ohlcv`, `execution_bars` | Official integer KRX observations. The second view selects only ordinary equity (`주권` and `보통주`). Valid positive-volume bars are observations of trading that day. Auction fill, queue priority, and halt timing require separate evidence. |
| `tradability`, `data_quality` | Zero volume, malformed bars, calendar gaps, and large raw-close moves are distinct. Official halt status stays unknown. A jump is a review lead and can span missing trade observations. |
| `vendor_panel`, `vendor_comparison` | Preserved KOSPI vendor data, including 2015. OHLCV comparison is diagnostic by date and code. These archival prices have no verified historical signal vintage or ISIN mapping for 2015. |
| `corporate_actions` | V1 evidence inventory with source, terms, announcement/effective/record/payment dates where available. Event rows can overlap across evidence sources. Missing events imply unknown coverage, and rows here are not a deduplicated replay feed. |
| `signal_prices` | Publication layer for independently validated end-of-day prices. The current build leaves it empty because adjustment continuity and contemporaneous availability remain unresolved. Never use vendor prices as an automatic substitute. |
| `provenance` | Input role, SHA-256 and byte size. KRX session rows link to the input month. |

At signal time query a specific session and join on `(day, isin)`. A prior
observation is usable for an opening order only after its close. Future
membership or vendor partitions must never determine historical candidates.
An absent security remains absent for that session. Do not infer an official
delisting payout from last seen date or a missing price.

The fixed smoke uses one preselected October 2026 candidate and the preserved
V1 D1/D2 engine. It checks round-trip fills, next-session timing, observed raw
opening prices, integer shares, and existing accounting invariants. D1 uses the
realized opening to size the diagnostic order. D2 uses the previous close
for its order cap and only conditionally fills against the opening. This smoke
retains V1's fee and cash interest settings, with permissive quote bounds.
Historical taxes, additional slippage, confirmed halts, action-complete
portfolio replay, and performance certification require further validation.
