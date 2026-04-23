"""
ADR-004 실험 확장: 섹터 게이트 티어 조합 변형.

baseline      : gate off
leading_only  : ["주도"]
leading_strong: ["주도", "강세"]          ← 기본 추천 (기각됨: -8.12%p)
three_tier    : ["주도", "강세", "중립"]   ← 약세만 차단
block_na_hard : ["주도", "강세"] + fallback=block

tier_cache 는 1회만 계산하고 재사용.
"""
from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy import (  # noqa: E402
    load_config, load_universe_ok, load_data,
    precompute_sector_tiers, run_backtest, calc_metrics,
)

PERIODS = [
    ("전체",          None,         None),
    ("2015-19",      "2015-01-01", "2019-12-31"),
    ("2020-24",      "2020-01-01", "2024-12-31"),
    ("2025+",        "2025-01-01", "2026-12-31"),
]

VARIANTS = [
    ("A baseline",      {"enabled": False}),
    ("B 주도 only",      {"enabled": True, "tiers": ["주도"],
                          "fallback_on_na": "pass", "recompute_every": 5}),
    ("C 주도+강세",      {"enabled": True, "tiers": ["주도", "강세"],
                          "fallback_on_na": "pass", "recompute_every": 5}),
    ("D 주도+강세+중립", {"enabled": True, "tiers": ["주도", "강세", "중립"],
                          "fallback_on_na": "pass", "recompute_every": 5}),
    ("E 주도+강세 strict", {"enabled": True, "tiers": ["주도", "강세"],
                          "fallback_on_na": "block", "recompute_every": 5}),
]


def main() -> int:
    cfg_base = load_config()
    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[유니버스] {len(universe)} × {len(all_dates)}일")

    # tier cache 1회 계산 (enabled=True 사본으로 호출)
    cfg_for_cache = deepcopy(cfg_base)
    cfg_for_cache["signal"]["sector_gate"]["enabled"] = True
    cfg_for_cache["signal"]["sector_gate"]["recompute_every"] = 5
    t0 = time.time()
    print("\n[tier cache] 계산 중...")
    tier_cache = precompute_sector_tiers(all_dates, stock_arr, cfg_for_cache)
    print(f"[tier cache] 완료 ({time.time()-t0:.1f}s)")

    results = {}
    for label, override in VARIANTS:
        cfg = deepcopy(cfg_base)
        cfg["signal"]["sector_gate"].update(override)
        t0 = time.time()
        eq, tr = run_backtest(all_dates, stock_arr, kospi_arr, cfg,
                              sector_tier_cache=tier_cache)
        dt = time.time() - t0
        m_full = calc_metrics(eq, tr)
        periods = {}
        for lbl, s, e in PERIODS:
            if s is None:
                periods[lbl] = m_full
            else:
                periods[lbl] = calc_metrics(eq, tr, pd.Timestamp(s),
                                             pd.Timestamp(e))
        results[label] = {"full": m_full, "periods": periods,
                          "trades": len(tr), "elapsed": round(dt, 1)}
        print(f"  {label:<22} CAGR {m_full['cagr']:+6.2f}% "
              f"MDD {m_full['mdd']:+6.2f}% 거래 {len(tr):>3} "
              f"PF {m_full['pf']:4.2f} 승률 {m_full['win_rate']:4.1f}% "
              f"({dt:.1f}s)")

    # 표
    print("\n" + "="*92)
    hdr = f"  {'variant':<20} " + " ".join(f"{lbl:>10}" for lbl, _, _ in PERIODS)
    print(hdr)
    print("="*92)
    for label, _ in VARIANTS:
        r = results[label]
        row = f"  {label:<20}"
        for lbl, _, _ in PERIODS:
            m = r["periods"][lbl]
            row += f"  {m['cagr']:>+9.2f}%" if m else f"  {'-':>10}"
        print(row)
    print("="*92)

    out = Path(__file__).resolve().parent / "data" / "adr004_variants.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
