"""
ADR-004 실험: 섹터 게이트 on/off A/B 비교.

baseline        : sector_gate.enabled=False (기존 T10/CD60)
sector_gate     : sector_gate.enabled=True, tiers=[주도, 강세]

출력:
    backtest/data/adr004_ab.json   — 지표 비교 (CAGR / MDD / 거래 / PF / 승률)
    콘솔                          — 표 형식 요약
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

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "adr004_ab.json"

PERIODS = [
    ("전체",            None,         None),
    ("2015-19 박스권", "2015-01-01", "2019-12-31"),
    ("2020-24 중립",   "2020-01-01", "2024-12-31"),
    ("2025+ 강세",     "2025-01-01", "2026-12-31"),
]


def _run(cfg, all_dates, stock_arr, kospi_arr, tier_cache):
    t0 = time.time()
    eq, tr = run_backtest(all_dates, stock_arr, kospi_arr, cfg,
                          sector_tier_cache=tier_cache)
    dt = time.time() - t0
    m_full = calc_metrics(eq, tr)
    periods = {}
    for label, s, e in PERIODS:
        if s is None:
            periods[label] = m_full
        else:
            m = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
            periods[label] = m
    return {"metrics_full": m_full, "periods": periods,
            "trades": len(tr), "elapsed_sec": round(dt, 1)}, tr


def _fmt_metric(m: dict | None, key: str, fmt: str) -> str:
    if m is None or key not in m or m[key] is None:
        return "     -"
    return format(m[key], fmt)


def main() -> int:
    print("="*74)
    print("  ADR-004 실험: 섹터 게이트 on/off A/B")
    print("="*74)

    # ── 공통 데이터 로드 (1회) ──
    cfg_base = load_config()
    universe = load_universe_ok()
    print(f"\n[유니버스] {len(universe)}종목")
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터]   {len(stock_arr)}종목 × {len(all_dates)}영업일")

    # ── cfg 변형 ──
    cfg_off = deepcopy(cfg_base)
    cfg_off["signal"]["sector_gate"]["enabled"] = False

    cfg_on = deepcopy(cfg_base)
    cfg_on["signal"]["sector_gate"]["enabled"] = True
    cfg_on["signal"]["sector_gate"]["tiers"] = ["주도", "강세"]
    cfg_on["signal"]["sector_gate"]["fallback_on_na"] = "pass"
    cfg_on["signal"]["sector_gate"]["recompute_every"] = 5

    # ── 섹터 티어 사전계산 (on 에서만) ──
    print("\n[섹터 티어] 사전계산 중 (recompute_every=5, 약 2-5분)...")
    t0 = time.time()
    tier_cache = precompute_sector_tiers(all_dates, stock_arr, cfg_on)
    print(f"[섹터 티어] 완료 ({time.time()-t0:.1f}s, cache {len(tier_cache)}일)")

    # ── 백테 실행 ──
    print("\n[A] baseline (gate off) 실행...")
    res_off, tr_off = _run(cfg_off, all_dates, stock_arr, kospi_arr, None)
    print(f"    완료 {res_off['elapsed_sec']}s / 거래 {res_off['trades']}건")

    print("\n[B] sector_gate on (주도+강세) 실행...")
    res_on, tr_on = _run(cfg_on, all_dates, stock_arr, kospi_arr, tier_cache)
    print(f"    완료 {res_on['elapsed_sec']}s / 거래 {res_on['trades']}건")

    # ── 비교 표 ──
    print("\n" + "="*74)
    print(f"  {'기간':<15} {'CAGR A':>9} {'CAGR B':>9} {'Δ':>7} | "
          f"{'MDD A':>7} {'MDD B':>7} | {'거래 A':>6} {'거래 B':>6}")
    print("="*74)
    for label, _s, _e in PERIODS:
        ma = res_off["periods"][label]
        mb = res_on["periods"][label]
        if ma and mb:
            d = mb["cagr"] - ma["cagr"]
            print(f"  {label:<13} {ma['cagr']:>+8.2f}% {mb['cagr']:>+8.2f}% "
                  f"{d:>+6.2f}% | {ma['mdd']:>6.1f}% {mb['mdd']:>6.1f}% | "
                  f"{ma['trades']:>6} {mb['trades']:>6}")
        else:
            print(f"  {label:<13} {_fmt_metric(ma,'cagr','+8.2f')}  "
                  f"{_fmt_metric(mb,'cagr','+8.2f')}")
    print("="*74)

    # PF / 승률 상세
    print("\n[상세 지표]")
    print(f"  {'':19} {'PF':>8}  {'승률':>8}  {'거래':>6}")
    for label in ["A baseline", "B gate-on"]:
        m = (res_off if "A" in label else res_on)["metrics_full"]
        print(f"  {label:<19} {m['pf']:>8.2f}  {m['win_rate']:>7.1f}%  {m['trades']:>6}")

    # ── 저장 ──
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"baseline": res_off, "sector_gate_on": res_on}, f,
                  ensure_ascii=False, indent=2, default=str)
    print(f"\n저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
