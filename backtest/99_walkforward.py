"""
Walk-forward 검증 + T10/CD60 민감도 분석.

목적:
  1) 2015-2020 In-Sample 에서 최적 파라미터 선정 → 2021-2026 OOS 에서 검증
     (T10/CD60 이 IS 에서도 최고인가, OOS 에서도 여전한가)
  2) T10/CD60 주변 그리드 민감도 (과적합 여부 판단)
     TRAIL: 0.08, 0.10, 0.12, 0.15
     CD   : 30, 45, 60, 75, 90

데이터: 162종목 (재검증 후)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# 99_minervini_vcp_compare 의 함수들 재사용
import importlib.util
spec = importlib.util.spec_from_file_location(
    "mvc", BASE / "99_minervini_vcp_compare.py"
)
mvc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mvc)


def calc_metrics(eq_df, tr_df, start=None, end=None):
    e = eq_df.set_index("date")["equity"]
    if start is not None:
        e = e.loc[start:end]
        if len(e) < 2:
            return None
        base = e.iloc[0]
        e = e / base
        t = tr_df[(tr_df["entry_date"] >= start)
                 & (tr_df["entry_date"] <= end)]
    else:
        t = tr_df
    years = (e.index[-1] - e.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1/years) - 1
    mdd = ((e - e.cummax()) / e.cummax() * 100).min()
    r = t["ret"] if len(t) else pd.Series([0.0])
    wins = t[t["ret"] > 0]
    losses = t[t["ret"] <= 0]
    pf = (wins["ret"].sum() / abs(losses["ret"].sum())
          if len(losses) and losses["ret"].sum() != 0 else 0)
    return {
        "cagr": cagr * 100, "mdd": mdd, "trades": len(t),
        "pf": pf, "win_rate": (r > 0).mean() * 100 if len(t) else 0,
    }


def main():
    print("=" * 68)
    print("  Walk-forward + 민감도 분석 (162종목)")
    print("=" * 68)

    universe = mvc.load_universe_ok()
    print(f"\n유니버스: {len(universe)}종목")
    all_dates, stock_arr, kospi_arr = mvc.load_data(universe)
    print(f"데이터  : {len(stock_arr)}종목, {len(all_dates)}영업일")

    # ── 1. Walk-forward: IS(2015-2020) / OOS(2021-2026) ──
    print(f"\n{'='*68}")
    print("  [1] Walk-forward: 2015-2020 IS → 2021-2026 OOS")
    print(f"{'='*68}")

    IS_START = pd.Timestamp("2015-01-02")
    IS_END   = pd.Timestamp("2020-12-31")
    OOS_START = pd.Timestamp("2021-01-02")
    OOS_END   = pd.Timestamp("2026-12-31")

    trails = [0.10, 0.15, 0.20, 0.25]
    cooldowns = [0, 60, 120]

    results = {}
    for ts in trails:
        for cd in cooldowns:
            eq, tr = mvc.run_portfolio(
                all_dates, stock_arr, kospi_arr,
                mvc.check_minervini_supply,
                cooldown=cd, trail_stop=ts,
            )
            m_is  = calc_metrics(eq, tr, IS_START, IS_END)
            m_oos = calc_metrics(eq, tr, OOS_START, OOS_END)
            results[(ts, cd)] = (m_is, m_oos)

    # IS 랭킹
    print("\n[IS 2015-2020 CAGR 랭킹]")
    is_rank = sorted(
        [(k, v[0]) for k, v in results.items() if v[0]],
        key=lambda x: -x[1]["cagr"]
    )
    print(f"  {'파라미터':<12} {'IS CAGR':>10} {'IS MDD':>10} {'IS PF':>6} "
          f"{'OOS CAGR':>10} {'OOS MDD':>10} {'OOS PF':>6}")
    print("  " + "─" * 70)
    for (ts, cd), m_is in is_rank:
        m_oos = results[(ts, cd)][1]
        lab = f"T{int(ts*100)}/CD{cd}"
        oos_c = f"{m_oos['cagr']:+8.2f}%" if m_oos else "   --"
        oos_m = f"{m_oos['mdd']:7.1f}%" if m_oos else "   --"
        oos_p = f"{m_oos['pf']:5.2f}" if m_oos else "--"
        print(f"  {lab:<12} {m_is['cagr']:+8.2f}% {m_is['mdd']:7.1f}%  "
              f"{m_is['pf']:5.2f}  {oos_c:>10} {oos_m:>10} {oos_p:>6}")

    # OOS 랭킹
    print("\n[OOS 2021-2026 CAGR 랭킹]")
    oos_rank = sorted(
        [(k, v[1]) for k, v in results.items() if v[1]],
        key=lambda x: -x[1]["cagr"]
    )
    print(f"  {'파라미터':<12} {'OOS CAGR':>10} {'OOS MDD':>10} {'OOS PF':>6}  "
          f"IS 랭크")
    print("  " + "─" * 65)
    for rank, ((ts, cd), m_oos) in enumerate(oos_rank, 1):
        is_pos = next(i for i, (k, _) in enumerate(is_rank, 1) if k == (ts, cd))
        lab = f"T{int(ts*100)}/CD{cd}"
        print(f"  {lab:<12} {m_oos['cagr']:+8.2f}% {m_oos['mdd']:7.1f}%  "
              f"{m_oos['pf']:5.2f}  #{is_pos}")

    # IS 최적 선정 → OOS 검증
    best_is = is_rank[0]
    print(f"\n[IS 최적 파라미터] T{int(best_is[0][0]*100)}/CD{best_is[0][1]}  "
          f"(IS CAGR {best_is[1]['cagr']:+.2f}%)")
    m_oos_best = results[best_is[0]][1]
    print(f"   → OOS 성과: CAGR {m_oos_best['cagr']:+.2f}%, "
          f"MDD {m_oos_best['mdd']:.1f}%, PF {m_oos_best['pf']:.2f}")

    best_oos = oos_rank[0]
    print(f"[OOS 최적 파라미터] T{int(best_oos[0][0]*100)}/CD{best_oos[0][1]}  "
          f"(OOS CAGR {best_oos[1]['cagr']:+.2f}%)")

    # ── 2. T10/CD60 민감도: TRAIL 8/10/12/15 × CD 30/45/60/75/90 ──
    print(f"\n{'='*68}")
    print("  [2] T10/CD60 주변 민감도 그리드")
    print(f"{'='*68}")

    trails_s = [0.08, 0.10, 0.12, 0.15]
    cds_s = [30, 45, 60, 75, 90]

    sens_cagr = {}
    sens_mdd  = {}
    for ts in trails_s:
        for cd in cds_s:
            eq, tr = mvc.run_portfolio(
                all_dates, stock_arr, kospi_arr,
                mvc.check_minervini_supply,
                cooldown=cd, trail_stop=ts,
            )
            m = calc_metrics(eq, tr)
            sens_cagr[(ts, cd)] = m["cagr"] if m else None
            sens_mdd[(ts, cd)]  = m["mdd"]  if m else None

    print(f"\n[전체 CAGR]")
    header = f"  {'TRAIL':<6} │ " + " │ ".join(f"CD={cd:<3}" for cd in cds_s)
    print(header)
    print("  " + "─" * (len(header) - 2))
    for ts in trails_s:
        row = f"  {int(ts*100)}%    "
        for cd in cds_s:
            v = sens_cagr.get((ts, cd))
            row += f" │ {v:+6.2f}%" if v is not None else " │   --   "
        print(row)

    print(f"\n[전체 MDD]")
    print(header)
    print("  " + "─" * (len(header) - 2))
    for ts in trails_s:
        row = f"  {int(ts*100)}%    "
        for cd in cds_s:
            v = sens_mdd.get((ts, cd))
            row += f" │ {v:+6.1f}%" if v is not None else " │   --   "
        print(row)

    # 민감도 요약
    vals = [v for v in sens_cagr.values() if v is not None]
    print(f"\n  민감도 범위 CAGR: {min(vals):+.2f}% ~ {max(vals):+.2f}%  "
          f"(spread {max(vals)-min(vals):.2f}%p)")
    print(f"  T10/CD60 값     : {sens_cagr[(0.10, 60)]:+.2f}%")


if __name__ == "__main__":
    main()
