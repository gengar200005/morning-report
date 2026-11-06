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

## Stage 1.5 validation

Use the foundation SQLite file and the same 130 archived KRX inputs. Extract
`kospi_pit/metadata/{delisting,desc,krx}_2026-10-30.csv` from the V1 PIT
alpha evidence ZIP. They are the preserved delisting-history, listing master
and endpoint security snapshots, separate from the daily OPEN API endpoints.

```sh
python research/v2_pit/validate_stage.py --base /private/v2.sqlite \
  --krx /private/monthly --metadata /private/kospi_pit/metadata \
  --output /private/stage15.sqlite > /private/stage15_validation.json
python -m unittest discover -s research/v2_pit
python research/v2_pit/smoke.py /private/stage15.sqlite /private/kospi_pit/code
python research/v2_pit/stage_account.py /private/stage15.sqlite /private/kospi_pit/code
```

`pit_candidates(db, signal_day)` returns diagnostic price-only inputs for that
session's close, from its own membership and 252 preceding price observations.
The forward return chain restarts at unresolved reference changes, anomalous
moves, and missing sessions. One evidenced 50:1 Samsung Electronics conversion
bridges the changed trading unit after its known suspension. The chain excludes
cash dividends and does not populate the production-quality `signal_prices`
table. Spot checks for bonus issuances compare the theoretical unrounded
reference against that session's reported reference. Terms from later filings,
uncertain cash or share deliveries, and the ex-date reports stay separate from
tradable signal inputs. Listing and action identity audits are retrospective
and must not be used as candidate inputs.

The fixed account cases exercise the preserved V1 Book. Historical sell cost
in the 2017–2018 fixtures includes 30 bps combined transaction and rural tax.
Each fill also charges modeled slippage of 5 bps as a cash cost. This fixed
test uses conditional next-opening fills, no auction allocation model, and
gross dividend accounting. An unverified delisting entitlement leaves the
position open and NAV undefined. A whole-period tax schedule and account
certification are separate requirements.

## Stage 2 economic replay

Build from the stage 1.5 SQLite and the same preserved monthly KRX archives.

```sh
python research/v2_pit/economic_prices.py --base /private/stage15.sqlite \
  --krx /private/monthly --output /private/economic.sqlite > /private/price_audit.json
python research/v2_pit/economic_fixture.py /private/economic.sqlite > /private/replay.json
python -m unittest discover -s research/v2_pit
```

Use `economic_prices.candidates(db, signal_day)` for the dated price momentum
input. `economic_momentum.price_index` is a forward index, `ohlcv.close` is
raw KRW, and confirmed unit conversions are recorded separately. The legacy
`signal_segments.close` is retained for reproduction of Stage 1.5 and is a
forward index. No execution or Stage 2 signal reads that column. The new
signal needs 252 contiguous validated returns. Even a confirmed split
with a trading halt restarts the signal window. Rates use the published
two-decimal rounding interval and are cross-checked within the same KRX feed.

The fixed ledger uses prior-close order decisions, conditional next-opening
fills, integer shares, T+2 settlement, modeled 15 bps commissions and 5 bps
slippage, and a dated KOSPI sale-tax schedule. Sale proceeds are not available
to reinvest before settlement. Taxes use the effective settlement date as the
schedule key and exact decimal charges; broker rounding and auction allocation
are unmodeled. A halt carries a mark only for the documented fixture and share
unit conversion. Unknown cash or equity rights block path-level metrics.
The fixed actual cases cover trades, Samsung split and gross dividend, and
Hanjin delisting. Share awards and conversions also have synthetic accounting
tests. Miwon filing terms are audited separately from actual delivery and payment.

## Stage 3 full replay

Use the Stage 2 SQLite, the preserved V1 `KOSPI.json` and Yahoo
`yahoo_069500.json` archives, the six Samsung fund distribution pages
(`stkTicker=069500`, all history), and the Daum raw-price archive.

```sh
python research/v2_pit/full_replay.py economic.sqlite KOSPI.json > base.json
python research/v2_pit/full_replay.py economic.sqlite KOSPI.json --participation .001 > strict.json
python research/v2_pit/full_replay.py economic.sqlite KOSPI.json --scheduled-bonus > scheduled_bonus.json
python research/v2_pit/kodex_benchmark.py economic.sqlite yahoo_069500.json issuer[1-6].json \
  --secondary daum.json > benchmark.json
python research/v2_pit/replay_summary.py base.json strict.json scheduled_bonus.json benchmark.json
python -m unittest discover -s research/v2_pit
```

Frozen V1 research configuration is read from `backtest/strategy_config.yaml`
and the same Minervini, supply and market-gate helpers are reused. Live report
VIX and broker supply inputs have no equivalent historical PIT series here.
The replay uses 252 contiguous returns with a PIT rank universe, prior-close
buy limits, settled cash only, open slots without anticipating sales, one
session expiry, and no forced endpoint liquidation. The fixed baseline uses
a daily participation rejection threshold of 1%; the strict path uses 0.1%.
Execution-day volume is used only to reject modeled fills. Neither threshold
certifies opening-auction depth. Sequential queue order is rank descending,
then ticker ascending. The bonus sensitivity uses only the archived planned
Miwon delivery date; the fractional cash and whole-path NAV remain unresolved.

ETF prices are unadjusted Yahoo bars supplemented by overlapping, cross-checked
Daum bars. Distributions use the issuer's payment/record-date table; entitlement
is dated by the exchange calendar. Historical distribution amounts are used
for economic accrual only, and reinvestment can use cash after the official
payment date. Distribution withholding is also modeled separately for the
benchmark; the primary comparison uses gross distributions on both sides.
Results assume modeled commissions, slippage, cash interest and quote rules.
The account leaves unresolved NAV unset and never splices around missing days.
