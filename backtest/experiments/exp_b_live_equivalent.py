"""
실험 B: 실전 동형 — Minervini core 만 필터 + 당일 종가 진입.

baseline 과의 차이:
- candidate: check_signal (core+수급+RS) → check_minervini_core (core only)
- 체결: 익일 시가 → 당일 종가
- 트레일링/손절/쿨다운/시장게이트 동일

목적: 백테 ↔ 실전 운용 괴리가 (1) candidate 필터 (2) 체결 타이밍 중
어느 쪽에서 오는지 격리 측정.
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
from engine import run_backtest_hooked, select_live_equivalent  # noqa: E402

RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)


def main():
    cfg = load_config()
    print(f"[실험 B] live-equivalent: core-only + close_same_day entry")

    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    print("\n[백테] 실행 중...")
    eq, tr = run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                                  select_fn=select_live_equivalent,
                                  entry_mode='close_same_day')
    m = calc_metrics(eq, tr)
    print(f"\n{'='*60}")
    print(f"  실험 B — live-equivalent")
    print(f"{'='*60}")
    print(f"  CAGR      : {m['cagr']:+.2f}%")
    print(f"  MDD       : {m['mdd']:.2f}%")
    print(f"  거래      : {m['trades']}건")
    print(f"  승률      : {m['win_rate']:.1f}%")
    print(f"  PF        : {m['pf']:.2f}")
    print(f"  평균 보유일: {tr['hold_days'].mean():.1f}")

    ages = tr["signal_age_at_sel"].dropna().astype(int)
    print(f"\n  signal_age  median={ages.median():.0f} "
          f"mean={ages.mean():.1f} p75={ages.quantile(0.75):.0f} "
          f"p90={ages.quantile(0.90):.0f}")

    # 기간별
    print(f"\n{'─'*60}")
    print(f"  기간 분해")
    print(f"{'─'*60}")
    for label, s, e in [
        ("2015-2019 박스권", "2015-01-01", "2019-12-31"),
        ("2020-2024",        "2020-01-01", "2024-12-31"),
        ("2025+ 강세",       "2025-01-01", "2026-12-31"),
    ]:
        mm = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
        if mm:
            print(f"  {label:<14} CAGR {mm['cagr']:+7.2f}% "
                  f"MDD {mm['mdd']:6.1f}%  거래 {mm['trades']}")

    tr.to_parquet(RESULTS / "exp_b_trades.parquet")
    eq.to_parquet(RESULTS / "exp_b_equity.parquet")

    summary = {
        "experiment": "B_live_equivalent",
        "cagr": round(m["cagr"], 2),
        "mdd": round(m["mdd"], 2),
        "pf": round(m["pf"], 2),
        "win_rate": round(m["win_rate"], 1),
        "trades": m["trades"],
        "avg_hold_days": round(float(tr["hold_days"].mean()), 1),
        "signal_age": {
            "mean": round(float(ages.mean()), 2),
            "median": float(ages.median()),
            "p75": float(ages.quantile(0.75)),
            "p90": float(ages.quantile(0.90)),
        },
    }
    (RESULTS / "exp_b_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {RESULTS}/exp_b_*")


if __name__ == "__main__":
    main()
