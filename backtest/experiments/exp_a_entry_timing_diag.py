"""
실험 A: baseline (T10/CD60) 의 진입 타이밍 실증.

- 현 strategy.run_backtest 와 동일 candidate 필터·ranking·체결 시점 (익일 시가)
- 각 trade 에 signal_age_at_sel (선정일 기준 연속 신호 streak) 기록
- signal_age 분포 히스토그램 + 기간별 요약

산출:
- results/exp_a_trades.parquet
- results/exp_a_equity.parquet
- results/exp_a_signal_age_hist.csv
- 표준출력: 요약 지표 + signal_age 분포
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
sys.path.insert(0, str(REPO / "backtest"))
sys.path.insert(0, str(BASE))

from strategy import load_config, load_universe_ok, load_data, calc_metrics  # noqa: E402
from engine import run_backtest_hooked, select_baseline  # noqa: E402

RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)


def main():
    cfg = load_config()
    print(f"[실험 A] baseline {cfg['name']} entry-timing diagnostic")

    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    print("\n[백테] 실행 중...")
    eq, tr = run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                                  select_fn=select_baseline,
                                  entry_mode='open_next_day')
    m = calc_metrics(eq, tr)
    print(f"\n{'='*60}")
    print(f"  실험 A — baseline 재현")
    print(f"{'='*60}")
    print(f"  CAGR      : {m['cagr']:+.2f}%")
    print(f"  MDD       : {m['mdd']:.2f}%")
    print(f"  거래      : {m['trades']}건")
    print(f"  승률      : {m['win_rate']:.1f}%")
    print(f"  PF        : {m['pf']:.2f}")
    print(f"  평균 보유일: {tr['hold_days'].mean():.1f}")

    # signal_age 분포 분석
    ages = tr["signal_age_at_sel"].dropna().astype(int)
    print(f"\n{'─'*60}")
    print(f"  signal_age_at_sel 분포 (선정일 기준 연속 신호 streak)")
    print(f"{'─'*60}")
    print(f"  count       : {len(ages)}")
    print(f"  min / max   : {ages.min()} / {ages.max()}")
    print(f"  mean        : {ages.mean():.2f}")
    print(f"  median      : {ages.median():.0f}")
    print(f"  p25 / p75   : {ages.quantile(0.25):.0f} / {ages.quantile(0.75):.0f}")
    print(f"  p90 / p99   : {ages.quantile(0.90):.0f} / {ages.quantile(0.99):.0f}")

    print(f"\n{'─'*60}")
    print(f"  구간별 비율")
    print(f"{'─'*60}")
    bins = [(1, 1), (2, 3), (4, 7), (8, 14), (15, 30), (31, 60), (61, 999)]
    n = len(ages)
    dist_rows = []
    for lo, hi in bins:
        c = int(((ages >= lo) & (ages <= hi)).sum())
        pct = c / n * 100 if n else 0
        label = f"{lo}일" if lo == hi else (f"{lo}-{hi}일" if hi < 999 else f"{lo}+일")
        print(f"  {label:<12} {c:>4}건  {pct:>5.1f}%  " + "█" * int(pct / 2))
        dist_rows.append({"bin": label, "count": c, "pct": round(pct, 2)})

    # 기간별 entry age
    print(f"\n{'─'*60}")
    print(f"  기간별 평균 signal_age (진입일 기준)")
    print(f"{'─'*60}")
    periods = [
        ("2015-2019 박스권", "2015-01-01", "2019-12-31"),
        ("2020-2024",        "2020-01-01", "2024-12-31"),
        ("2025+ 강세",       "2025-01-01", "2026-12-31"),
    ]
    period_rows = []
    for label, s, e in periods:
        mask = ((tr["entry_date"] >= pd.Timestamp(s))
                & (tr["entry_date"] <= pd.Timestamp(e)))
        sub = tr[mask]["signal_age_at_sel"].dropna()
        if len(sub) > 0:
            print(f"  {label:<14} n={len(sub):<4} mean={sub.mean():5.1f}  "
                  f"median={sub.median():4.0f}  p75={sub.quantile(0.75):4.0f}")
            period_rows.append({
                "period": label, "n": int(len(sub)),
                "mean_age": round(float(sub.mean()), 2),
                "median_age": float(sub.median()),
                "p75_age": float(sub.quantile(0.75)),
            })

    # 저장
    tr.to_parquet(RESULTS / "exp_a_trades.parquet")
    eq.to_parquet(RESULTS / "exp_a_equity.parquet")
    pd.DataFrame(dist_rows).to_csv(RESULTS / "exp_a_signal_age_hist.csv", index=False)
    pd.DataFrame(period_rows).to_csv(RESULTS / "exp_a_signal_age_by_period.csv", index=False)

    summary = {
        "experiment": "A_baseline_diagnostic",
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
    (RESULTS / "exp_a_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {RESULTS}/exp_a_*")


if __name__ == "__main__":
    main()
