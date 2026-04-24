"""
실험 B 분리: 필터 완화 vs 체결 타이밍 각각의 기여도.

B0: baseline (check_signal + open_next_day) ← 실험 A 와 동일
B1: check_signal + close_same_day         (체결만 변경)
B2: core_only    + open_next_day          (필터만 변경)
B3: core_only    + close_same_day         (실험 B 원본 = 둘 다 변경)
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
from engine import run_backtest_hooked, select_baseline, select_live_equivalent  # noqa: E402

RESULTS = BASE / "results"


def main():
    cfg = load_config()
    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    variants = [
        ("B0_baseline",           select_baseline,         "open_next_day"),
        ("B1_close_sameday_only", select_baseline,         "close_same_day"),
        ("B2_core_only_filter",   select_live_equivalent,  "open_next_day"),
        ("B3_both_relaxed",       select_live_equivalent,  "close_same_day"),
    ]

    rows = []
    for label, sel_fn, mode in variants:
        print(f"\n[{label}] {mode} ...")
        eq, tr = run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                                      select_fn=sel_fn, entry_mode=mode)
        m = calc_metrics(eq, tr)
        ages = tr["signal_age_at_sel"].dropna().astype(int) if len(tr) else pd.Series([0])
        r = {
            "variant": label,
            "filter": "check_signal" if sel_fn is select_baseline else "core_only",
            "entry_mode": mode,
            "cagr": round(m["cagr"], 2),
            "mdd": round(m["mdd"], 2),
            "pf": round(m["pf"], 2),
            "win_rate": round(m["win_rate"], 1),
            "trades": m["trades"],
            "avg_hold_days": round(float(tr["hold_days"].mean()), 1) if len(tr) else 0,
            "signal_age_mean": round(float(ages.mean()), 2),
            "signal_age_median": float(ages.median()),
        }
        for plabel, s, e in [
            ("2015_19", "2015-01-01", "2019-12-31"),
            ("2020_24", "2020-01-01", "2024-12-31"),
            ("2025p",   "2025-01-01", "2026-12-31"),
        ]:
            mm = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
            r[f"cagr_{plabel}"] = round(mm["cagr"], 2) if mm else None
        rows.append(r)
        print(f"  CAGR {r['cagr']:+7.2f}%  MDD {r['mdd']:6.1f}%  "
              f"거래 {r['trades']:4d}  승률 {r['win_rate']:4.1f}%  "
              f"PF {r['pf']:.2f}")

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "exp_b_split.csv", index=False)
    (RESULTS / "exp_b_split.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {RESULTS}/exp_b_split.*")
    print("\n결과 요약:")
    print(df[["variant","cagr","mdd","win_rate","pf","trades"]].to_string(index=False))


if __name__ == "__main__":
    main()
