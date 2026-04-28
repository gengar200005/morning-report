"""
실험 F — signal_streak sweet-spot 룰 hard 백테.

trade-level 분포 (exp_a_age_returns.csv) 가 4-7d sweet-spot 을 robustness
양면으로 지지 (시기 3/3, 정의 6/6). 본 실험은 진짜 검증: signal_streak ∈
[lo, hi] 필터를 룰로 추가했을 때 포트폴리오 CAGR 이 baseline (+29.55%)
을 넘는지.

가설:
- (H1) sweet-spot 강제 → trade-mean 우위가 CAGR 우위로 전이 (룰 후보 ADR).
- (H2) 후보 수 감소 → 슬롯 미충원 → cash drag → CAGR 하락 (실험 C 와 같은
  패턴, ADR-005 fail 재현).

6 variant + baseline 비교. 6/6 일관 우위면 ADR 후보, 일부만 우위면 cherry-
pick, 전부 하회면 H2 (cash drag) 확정.

산출:
- 콘솔: variant × CAGR/MDD/Win/PF + 기간별 CAGR
- results/exp_f_sweet_spot.csv
- 각 variant equity/trades parquet
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


def make_select_sweet_spot(lo: int, hi: int):
    def _sel(ctx):
        cfg = ctx["cfg"]
        i = ctx["i"]
        rs_map = ctx["rs_map"]
        cd = ctx["cd"]
        positions = ctx["positions"]
        last_exit_i = ctx["last_exit_i"]
        streak = ctx["signal_streak"]
        sector_tier_cache = ctx["sector_tier_cache"]

        cand = []
        for tk, (c, _o, v) in ctx["stock_arr"].items():
            if tk in positions or i >= len(c) or c[i] <= 0:
                continue
            if cd > 0 and tk in last_exit_i and (i - last_exit_i[tk]) < cd:
                continue
            s = streak.get(tk, 0)
            if s < lo or s > hi:
                continue
            if check_signal(c, v, i, rs_map.get(tk), cfg):
                if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                    continue
                cand.append((tk, rs_map.get(tk, 0)))
        cand.sort(key=lambda x: -x[1])
        return cand
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
        ("baseline",  None),
        ("ss_3_7",    (3, 7)),
        ("ss_4_7",    (4, 7)),
        ("ss_4_8",    (4, 8)),
        ("ss_5_7",    (5, 7)),
        ("ss_3_8",    (3, 8)),
        ("ss_4_10",   (4, 10)),
    ]

    results = []
    for label, rng in variants:
        print(f"\n[백테] {label} {rng if rng else '(no filter)'}...", flush=True)
        sel = select_baseline if rng is None else make_select_sweet_spot(*rng)
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
        eq.to_parquet(RESULTS / f"exp_f_{label}_equity.parquet")
        tr.to_parquet(RESULTS / f"exp_f_{label}_trades.parquet")

    df = pd.DataFrame(results)
    df.to_csv(RESULTS / "exp_f_sweet_spot.csv", index=False)
    print(f"\n[저장] {RESULTS}/exp_f_sweet_spot.csv")

    base = df.iloc[0]
    print(f"\n{'='*102}")
    print(f"  variant 비교 (baseline CAGR = {base['cagr']:+.2f}%, MDD = {base['mdd']:.2f}%)")
    print(f"{'='*102}")
    print(f"  {'variant':<12} {'CAGR':>8} {'dCAGR':>8} {'MDD':>8} {'dMDD':>8} "
          f"{'Trades':>7} {'dT':>5} {'Win%':>6} {'PF':>5}")
    print("  " + "-"*100)
    for _, r in df.iterrows():
        d_cagr = r['cagr'] - base['cagr']
        d_mdd = r['mdd'] - base['mdd']
        d_t = int(r['trades'] - base['trades'])
        if r['variant'] == 'baseline':
            marker = "  "
        elif d_cagr > 0:
            marker = "★ "
        else:
            marker = "  "
        print(f"{marker}{r['variant']:<12} {r['cagr']:>+7.2f}% {d_cagr:>+7.2f}p "
              f"{r['mdd']:>+7.2f}% {d_mdd:>+7.2f}p "
              f"{r['trades']:>7} {d_t:>+5} "
              f"{r['win_rate']:>6.1f} {r['pf']:>5.2f}")

    print(f"\n{'-'*102}")
    print(f"  기간별 CAGR")
    print(f"{'-'*102}")
    print(f"  {'variant':<12} {'2015-19':>10} {'2020-24':>10} {'2025+':>10}   baseline 대비 d (박/중/강)")
    for _, r in df.iterrows():
        d1 = r['p_2015_19'] - base['p_2015_19']
        d2 = r['p_2020_24'] - base['p_2020_24']
        d3 = r['p_2025plus'] - base['p_2025plus']
        print(f"  {r['variant']:<12} {r['p_2015_19']:>+9.2f}% {r['p_2020_24']:>+9.2f}% "
              f"{r['p_2025plus']:>+9.2f}%   ({d1:>+6.1f} / {d2:>+6.1f} / {d3:>+6.1f})")


if __name__ == "__main__":
    main()
