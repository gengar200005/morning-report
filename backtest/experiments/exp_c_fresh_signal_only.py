"""
실험 C: fresh signal 만 — baseline candidate AND signal_streak ∈ [1, 3].

baseline 과의 차이:
- candidate: check_signal=True (동일) AND streak ≤ 3 (신규 필터)
- 체결: 익일 시가 (baseline 동일)
- 그 외 동일

목적: "신호 3일 이내 종목만 진입" 강제 시 baseline 대비 성과 변화 측정.
    → 백테와 실전의 extended-진입 패턴을 강제로 fresh 로 밀어넣었을 때
      오히려 좋아지는지 나빠지는지 실증.

기본 max_streak=3 (프롬프트 지정). 민감도 체크용으로 1·2·5 도 돌려봄.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
sys.path.insert(0, str(REPO / "backtest"))
sys.path.insert(0, str(BASE))

from strategy import load_config, load_universe_ok, load_data, calc_metrics  # noqa: E402
from engine import run_backtest_hooked, make_select_fresh_only  # noqa: E402

RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)


def run_one(cfg, all_dates, stock_arr, kospi_arr, max_streak):
    sel = make_select_fresh_only(max_streak)
    eq, tr = run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                                  select_fn=sel, entry_mode='open_next_day')
    m = calc_metrics(eq, tr)
    ages = tr["signal_age_at_sel"].dropna().astype(int) if len(tr) else pd.Series([0])
    result = {
        "max_streak": max_streak,
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "pf": round(m["pf"], 2),
        "win_rate": round(m["win_rate"], 1),
        "trades": m["trades"],
        "avg_hold_days": round(float(tr["hold_days"].mean()), 1) if len(tr) else 0,
        "signal_age_mean": round(float(ages.mean()), 2),
        "signal_age_median": float(ages.median()),
    }
    # 기간별
    period = {}
    for label, s, e in [
        ("2015_19", "2015-01-01", "2019-12-31"),
        ("2020_24", "2020-01-01", "2024-12-31"),
        ("2025p",   "2025-01-01", "2026-12-31"),
    ]:
        mm = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
        period[label] = round(mm["cagr"], 2) if mm else None
    result["period_cagr"] = period
    return result, eq, tr


def main():
    cfg = load_config()
    print(f"[실험 C] fresh-signal only (streak ≤ N)")

    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    all_results = []
    main_eq, main_tr = None, None
    for k in [1, 2, 3, 5, 10]:
        print(f"\n[백테] max_streak ≤ {k} ...")
        r, eq, tr = run_one(cfg, all_dates, stock_arr, kospi_arr, k)
        all_results.append(r)
        print(f"  CAGR {r['cagr']:+7.2f}%  MDD {r['mdd']:6.1f}%  "
              f"거래 {r['trades']:4d}  승률 {r['win_rate']:4.1f}%  "
              f"PF {r['pf']:.2f}  avg_age {r['signal_age_mean']:.1f}")
        print(f"  기간 CAGR: 2015-19 {r['period_cagr']['2015_19']:+7.2f}%  "
              f"2020-24 {r['period_cagr']['2020_24']:+7.2f}%  "
              f"2025+ {r['period_cagr']['2025p']:+7.2f}%")
        if k == 3:
            main_eq, main_tr = eq, tr

    # 메인(3일) 저장
    if main_tr is not None:
        main_tr.to_parquet(RESULTS / "exp_c_trades.parquet")
        main_eq.to_parquet(RESULTS / "exp_c_equity.parquet")

    df = pd.DataFrame(all_results)
    df.to_csv(RESULTS / "exp_c_sensitivity.csv", index=False)

    (RESULTS / "exp_c_summary.json").write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {RESULTS}/exp_c_*")


if __name__ == "__main__":
    main()
