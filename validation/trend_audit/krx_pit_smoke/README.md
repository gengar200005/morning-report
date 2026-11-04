# KRX KOSPI PIT seven-day read-only smoke

Purpose: Validate service entitlements and historical point-in-time KOSPI membership **before** downloading the full history. This is NOT a backtest and does not change trading code.

- Fixed services: KRX `/svc/apis/sto/stk_isu_base_info` and `/svc/apis/sto/stk_bydd_trd`
- Fixed dates: 2016-06-01, 2017-03-06, 2017-03-07, 2018-02-08, 2018-02-09, 2020-04-14, 2026-10-30
- Historical sentinels: Hanjin Shipping 117930 before/after 2017-03-07 delisting; Celltrion 068270 before/after 2018-02-09 KOSPI transfer.
- Secret `KRX_API_KEY` read exclusively from GitHub Actions repository secrets. Never commit or log the key.
- Each service/date request uses only one GET, 1/sec throttle, no redirects, bounded retries, redacted JSON-only artifacts.
- Service-level HTTP 401/403 stops that service's remaining dates; other service is still tested so approval can be diagnosed.
- KRX `OutBlock_1` records are preserved in private workflow artifacts, never in the public git tree. Artifact retention 7 days.
- A returned empty `OutBlock_1` or absent ticker is **not alone** proof of delisting; trading suspension and service coverage require independent confirmation.
- `coverage_complete` remains false; full historical collection needs explicit review of entitlement and results.

Official documentation: https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd

Run offline tests: `cd validation/trend_audit/krx_pit_smoke && python -m unittest discover -v`
