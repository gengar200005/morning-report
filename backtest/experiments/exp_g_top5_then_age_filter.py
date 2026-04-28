"""
실험 G — "Top5 안에 든 종목 중 signal_age sweet-spot 만 매수" 룰 백테.

마스터 제안 (2026-04-28 세션 #2):
> Top5 에 들어온 종목이 4-8d 구간에만 매수하면서 포트를 총 5개까지 채우면?

ss_4_8 (실험 F, candidate pool 자체를 4-8d 로 좁힘) 와 다른 룰:
- ss_4_8: 매일 4-8d 종목 풀 전체 → RS 순 → top5 (≈ "RS 6위였던 4d" 도 매수)
- 본 실험 G: 매일 baseline 전체 162종목 RS 순 → top5 추출 → 그 5명 중 4-8d 만
  매수, 빈 슬롯은 다음 날 다시 시도

운영 의미: 마스터가 실제로 보는 "리포트 Top5" 화면 안에서만 매수, signal_age
조건 추가. cash drag 더 심할 가능성 있으나 운영 일관성 있는 룰.

variants: top5 + 4 sweet-spot 정의 (3-7 / 4-7 / 4-8 / 4-10)

산출:
- 콘솔: variant × CAGR/MDD/Trades + 기간별
- results/exp_g_top5_then_age.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
sys.path.insert(0, str(REPO / "backtest"))
sys.path.insert(0, str(BASE))

from strategy import (load_config, load_universe_ok, load_data, calc_metrics,  # noqa: E402
                      check_signal, check_sector_gate)
from engine import run_backtest_hooked, select_baseline  # noqa: E402

RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)


def make_select_top5_then_age(lo: int, hi: int, top_n: int = 5):
    """Top N RS 후보 중 signal_streak ∈ [lo, hi] 만 반환.

    엔진은 반환 리스트를 open_slots 만큼 자르므로, top5 중 4-8d 인 종목만
    빈 슬롯에 매수, 슬롯 못 채우면 다음 거래일에 다시 평가.
    """
    def _sel(ctx):
        cfg = ctx["cfg"]
        i = ctx["i"]
        rs_map = ctx["rs_map"]
        cd = ctx["cd"]
        positions = ctx["positions"]
        last_exit_i = ctx["last_exit_i"]
        streak = ctx["signal_streak"]
        sector_tier_cache = ctx["sector_tier_cache"]

        # 1) baseline 전체 후보 RS 순
        cand = []
        for tk, (c, _o, v) in ctx["stock_arr"].items():
            if tk in positions or i >= len(c) or c[i] <= 0:
                continue
            if cd > 0 and tk in last_exit_i and (i - last_exit_i[tk]) < cd:
                continue
            if check_signal(c, v, i, rs_map.get(tk), cfg):
                if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                    continue
                cand.append((tk, rs_map.get(tk, 0)))
        cand.sort(key=lambda x: -x[1])

        # 2) Top N 추출 (RS 1-5위)
        top = cand[:top_n]

        # 3) sweet-spot 필터 (Top N 안에서만)
        filtered = [(tk, rs) for tk, rs in top
                    if lo <= streak.get(tk, 0) <= hi]
        return filtered
    return _sel


def period_cagrs(eq: pd.DataFrame) -> dict:
    eq = eq.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    periods = [
        ("p_2015_19", "2015-01-01", "2019-12-31"),
        ("p_2020_24", "2020-01-01", "2024-12-31"),
        ("p_2025plus", "2025-01-01", "2027-12-31"),
    ]
    out = {}
    for label, s, e in periods:
        sub = eq[(eq["date"] >= s) & (eq["date"] <= e)]
        if len(sub) < 2:
            out[label] = float("nan"); continue
        v0 = sub["equity"].iloc[0]
        v1 = sub["equity"].iloc[-1]
        years = (sub["date"].iloc[-1] - sub["date"].iloc[0]).days / 365.25
        if years <= 0 or v0 <= 0:
            out[label] = float("nan"); continue
        out[label] = ((v1 / v0) ** (1/years) - 1) * 100
    return out


def main():
    cfg = load_config()
    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    variants = [
        ("baseline",     None),
        ("top5_3_7",     (3, 7)),
        ("top5_4_7",     (4, 7)),
        ("top5_4_8",     (4, 8)),
        ("top5_4_10",    (4, 10)),
        ("top5_3_10",    (3, 10)),
    ]

    results = []
    for label, rng in variants:
        print(f"\n[백테] {label} {rng if rng else '(no filter)'}...", flush=True)
        sel = (select_baseline if rng is None
               else make_select_top5_then_age(*rng, top_n=5))
        eq, tr = run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                                     select_fn=sel, entry_mode='open_next_day')
        m = calc_metrics(eq, tr)
        pcs = period_cagrs(eq)
        row = {
            "variant": label,
            "lo": rng[0] if rng else 0,
            "hi": rng[1] if rng else 999,
            "cagr": round(m["cagr"], 2),
            "mdd": round(m["mdd"], 2),
            "trades": int(m["trades"]),
            "win_rate": round(m["win_rate"], 1),
            "pf": round(m["pf"], 2),
            "avg_hold": round(float(tr["hold_days"].mean()) if len(tr) else 0, 1),
            **{k: round(v, 2) for k, v in pcs.items()},
        }
        results.append(row)
        print(f"  CAGR {row['cagr']:+.2f}%  MDD {row['mdd']:.2f}%  "
              f"Trades {row['trades']}  Win {row['win_rate']}%  PF {row['pf']}",
              flush=True)
        eq.to_parquet(RESULTS / f"exp_g_{label}_equity.parquet")
        tr.to_parquet(RESULTS / f"exp_g_{label}_trades.parquet")

    df = pd.DataFrame(results)
    df.to_csv(RESULTS / "exp_g_top5_then_age.csv", index=False)
    print(f"\n[저장] {RESULTS}/exp_g_top5_then_age.csv")

    base = df.iloc[0]
    print(f"\n{'='*102}")
    print(f"  variant 비교 (baseline = {base['cagr']:+.2f}% / MDD {base['mdd']:.2f}%)")
    print(f"{'='*102}")
    print(f"  {'variant':<14} {'CAGR':>8} {'dCAGR':>8} {'MDD':>8} {'dMDD':>8} "
          f"{'Trades':>7} {'dT':>5} {'Win%':>6} {'PF':>5}")
    print("  " + "-"*100)
    for _, r in df.iterrows():
        d_cagr = r['cagr'] - base['cagr']
        d_mdd = r['mdd'] - base['mdd']
        d_t = int(r['trades'] - base['trades'])
        if r['variant'] == 'baseline':
            marker = "  "
        elif d_cagr > 0:
            marker = "* "
        else:
            marker = "  "
        print(f"{marker}{r['variant']:<12} {r['cagr']:>+7.2f}% {d_cagr:>+7.2f}p "
              f"{r['mdd']:>+7.2f}% {d_mdd:>+7.2f}p "
              f"{r['trades']:>7} {d_t:>+5} "
              f"{r['win_rate']:>6.1f} {r['pf']:>5.2f}")

    print(f"\n{'-'*102}")
    print(f"  기간별 CAGR — baseline 대비 d (박/중/강)")
    print(f"{'-'*102}")
    for _, r in df.iterrows():
        d1 = r['p_2015_19'] - base['p_2015_19']
        d2 = r['p_2020_24'] - base['p_2020_24']
        d3 = r['p_2025plus'] - base['p_2025plus']
        print(f"  {r['variant']:<14} {r['p_2015_19']:>+9.2f}% {r['p_2020_24']:>+9.2f}% "
              f"{r['p_2025plus']:>+9.2f}%   ({d1:>+6.1f} / {d2:>+6.1f} / {d3:>+6.1f})")


if __name__ == "__main__":
    main()
