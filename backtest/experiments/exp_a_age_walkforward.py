"""
실험 A 사후 분석 #2 — signal_age sweet-spot stability 검증.

exp_a_age_returns 가 발견: baseline 333 trades 중 signal_age 4-7일 버킷이
모든 지표 (mean/median/win/PF) 최고. 사용자 결정으로 (B) walkforward 진입.

본 스크립트:
1) 기간 × 버킷 cross-tab (2015-19 박스 / 2020-24 중립 / 2025+ 강세).
   4-7d 우위가 모든 시기 일관이면 robust, 한두 시기에만 몰리면 cherry-pick.
2) 버킷 경계 sensitivity — best bucket 정의를 흔들어 본다.
   3-7d / 4-7d / 4-8d / 5-7d / 3-8d 가 모두 비슷한 우위면 robust,
   특정 정의에서만 우위면 data dredging.

ADR-010 robustness 요건: 시기 stability + 정의 sensitivity 둘 다 통과해야
ADR 후보 진입.

산출:
- 콘솔: 두 표
- results/exp_a_age_walkforward.csv
- results/exp_a_age_sensitivity.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
TRADES = RESULTS / "exp_a_trades.parquet"


def bucket(age: int) -> str:
    if age <= 1:    return "01_1d"
    if age <= 3:    return "02_2-3d"
    if age <= 7:    return "03_4-7d"
    if age <= 14:   return "04_8-14d"
    if age <= 30:   return "05_15-30d"
    if age <= 60:   return "06_31-60d"
    return "07_61+d"


def stats(rets: pd.Series) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan,
                "win": np.nan, "pf": np.nan}
    gain = rets[rets > 0].sum()
    loss = -rets[rets < 0].sum()
    pf = float(gain / loss) if loss > 0 else float("inf")
    return {
        "n": n,
        "mean": float(rets.mean()),
        "median": float(rets.median()),
        "win": float((rets > 0).mean() * 100),
        "pf": pf,
    }


def main():
    if not TRADES.exists():
        print(f"[ERROR] {TRADES} 없음.")
        sys.exit(1)

    tr = pd.read_parquet(TRADES)
    tr = tr.dropna(subset=["signal_age_at_sel", "ret"]).copy()
    tr["age"] = tr["signal_age_at_sel"].astype(int)
    tr["bucket"] = tr["age"].map(bucket)
    tr["entry_date"] = pd.to_datetime(tr["entry_date"])

    # ── (1) 기간 × 버킷 walkforward stability ──
    periods = [
        ("2015-19_박스", "2015-01-01", "2019-12-31"),
        ("2020-24_중립", "2020-01-01", "2024-12-31"),
        ("2025+_강세",  "2025-01-01", "2027-12-31"),
    ]

    print("=" * 100)
    print("  (1) 기간 × signal_age 버킷 — walkforward stability")
    print("=" * 100)
    print("  4-7d 우위가 3 시기 모두 유지되면 ROBUST. 한 시기에만 몰리면 cherry-pick.")
    print()

    rows = []
    for plabel, ps, pe in periods:
        mask = (tr["entry_date"] >= ps) & (tr["entry_date"] <= pe)
        sub = tr[mask]
        if len(sub) == 0:
            continue
        print(f"  ── {plabel}  (n_total={len(sub)}, "
              f"전체 mean={sub['ret'].mean():+.2f}%) ──")
        hdr = f"    {'bucket':<14} {'n':>3} {'mean%':>7} {'med%':>7} {'win%':>6} {'pf':>5}"
        print(hdr)
        for bk in sorted(sub["bucket"].unique()):
            ssub = sub[sub["bucket"] == bk]
            s = stats(ssub["ret"])
            pf_str = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
            highlight = " ★" if bk == "03_4-7d" else ""
            print(f"    {bk:<14} {s['n']:>3} {s['mean']:>+7.2f} {s['median']:>+7.2f} "
                  f"{s['win']:>6.1f} {pf_str:>5}{highlight}")
            rows.append({"period": plabel, "bucket": bk, **s})
        print()

    pd.DataFrame(rows).round(2).to_csv(
        RESULTS / "exp_a_age_walkforward.csv", index=False)

    # ── (2) 버킷 경계 sensitivity ──
    print("=" * 100)
    print("  (2) sweet-spot 정의 sensitivity — 정의를 흔들어도 우위 유지되나")
    print("=" * 100)
    print("  baseline 외 trades vs sweet-spot trades 비교. 모든 정의에서 우위면 ROBUST.")
    print()

    defs = [
        ("3-7d",  3, 7),
        ("4-7d",  4, 7),
        ("4-8d",  4, 8),
        ("5-7d",  5, 7),
        ("3-8d",  3, 8),
        ("4-10d", 4, 10),
    ]
    overall_mean = float(tr["ret"].mean())
    overall_med = float(tr["ret"].median())
    overall_win = float((tr["ret"] > 0).mean() * 100)

    hdr = f"  {'def':<8} {'n_in':>5} {'n_out':>5}  "
    hdr += f"{'mean_in':>8} {'mean_out':>9} {'D_mean':>7}  "
    hdr += f"{'med_in':>7} {'med_out':>8} {'D_med':>7}  "
    hdr += f"{'win_in':>7} {'win_out':>8} {'D_win':>7}"
    print(hdr)
    print(f"  {'-'*98}")
    rows2 = []
    for label, lo, hi in defs:
        in_mask = (tr["age"] >= lo) & (tr["age"] <= hi)
        s_in = stats(tr.loc[in_mask, "ret"])
        s_out = stats(tr.loc[~in_mask, "ret"])
        d_mean = s_in["mean"] - s_out["mean"]
        d_med = s_in["median"] - s_out["median"]
        d_win = s_in["win"] - s_out["win"]
        print(f"  {label:<8} {s_in['n']:>5} {s_out['n']:>5}  "
              f"{s_in['mean']:>+8.2f} {s_out['mean']:>+9.2f} {d_mean:>+7.2f}  "
              f"{s_in['median']:>+7.2f} {s_out['median']:>+8.2f} {d_med:>+7.2f}  "
              f"{s_in['win']:>7.1f} {s_out['win']:>8.1f} {d_win:>+7.1f}")
        rows2.append({
            "definition": label,
            "n_in": s_in["n"], "n_out": s_out["n"],
            "mean_in": round(s_in["mean"], 2),
            "mean_out": round(s_out["mean"], 2),
            "delta_mean": round(d_mean, 2),
            "median_in": round(s_in["median"], 2),
            "median_out": round(s_out["median"], 2),
            "delta_median": round(d_med, 2),
            "win_in": round(s_in["win"], 1),
            "win_out": round(s_out["win"], 1),
            "delta_win": round(d_win, 1),
        })

    pd.DataFrame(rows2).to_csv(
        RESULTS / "exp_a_age_sensitivity.csv", index=False)

    # ── 자동 진단 ──
    print()
    print("=" * 100)
    print("  자동 진단")
    print("=" * 100)

    # 시기 stability: 각 시기의 4-7d 가 같은 시기 다른 버킷 평균보다 우위인가?
    print("\n  [stability] 각 시기에서 4-7d 가 그 시기 평균보다 위인가?")
    wf = pd.DataFrame(rows)
    for plabel, _, _ in periods:
        period_df = wf[wf["period"] == plabel]
        if period_df.empty:
            continue
        sweet = period_df[period_df["bucket"] == "03_4-7d"]
        if sweet.empty:
            print(f"    {plabel}: 4-7d 표본 없음")
            continue
        sweet_mean = float(sweet["mean"].iloc[0])
        sweet_med = float(sweet["median"].iloc[0])
        sweet_win = float(sweet["win"].iloc[0])
        # 시기 내 다른 버킷 가중 평균
        other = period_df[period_df["bucket"] != "03_4-7d"]
        other_n = float(other["n"].sum())
        if other_n > 0:
            other_mean = float((other["mean"] * other["n"]).sum() / other_n)
            other_win = float((other["win"] * other["n"]).sum() / other_n)
        else:
            other_mean = float("nan")
            other_win = float("nan")
        verdict_mean = "✓" if sweet_mean > other_mean else "✗"
        verdict_win = "✓" if sweet_win > other_win else "✗"
        print(f"    {plabel}: 4-7d mean={sweet_mean:+.2f}% vs others {other_mean:+.2f}%  {verdict_mean}  "
              f"|  win 4-7d={sweet_win:.1f}% vs others {other_win:.1f}%  {verdict_win}")

    # 정의 sensitivity: 모든 정의에서 in_mean > out_mean ?
    sens = pd.DataFrame(rows2)
    n_pos_mean = int((sens["delta_mean"] > 0).sum())
    n_pos_med = int((sens["delta_median"] > 0).sum())
    n_pos_win = int((sens["delta_win"] > 0).sum())
    print(f"\n  [sensitivity] 6 정의 중 in > out 인 횟수")
    print(f"    Δ mean > 0   : {n_pos_mean}/6")
    print(f"    Δ median > 0 : {n_pos_med}/6")
    print(f"    Δ win > 0    : {n_pos_win}/6")
    print(f"    (6/6 ROBUST, 4-5/6 약하게 robust, ≤3/6 cherry-pick 의심)")

    print(f"\n[저장] {RESULTS}/exp_a_age_walkforward.csv, exp_a_age_sensitivity.csv")


if __name__ == "__main__":
    main()
