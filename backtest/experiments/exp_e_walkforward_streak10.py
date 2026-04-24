"""
실험 E: Walkforward IS/OOS — max_streak ≤ 10 재현성 검증.

ADR-006 §2.1.

baseline 과 K=10 variant 를 전체 기간 한 번씩 백테 후, 4개 기간에서
metrics 분해:
  - IS1: 2015-01-01 ~ 2019-12-31 (Train 1)
  - OOS1: 2020-01-01 ~ 2022-12-31 (Test 1)
  - IS2: 2015-01-01 ~ 2022-12-31 (Train 2, rolling)
  - OOS2: 2023-01-01 ~ 2026-04-23 (Test 2)

수용 기준 (K=10 채택 조건):
  1) 모든 OOS window 에서 ΔCAGR = CAGR_K10 - CAGR_baseline ≥ -3%p
  2) 모든 OOS window 에서 ΔMDD = MDD_K10 - MDD_baseline ≥ -2%p
  3) 최소 1개 OOS window 에서 K=10 이 baseline 유의 개선

세 기준 모두 충족 → Accepted. 하나라도 미달 → Rejected.
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
from engine import run_backtest_hooked, select_baseline, make_select_fresh_only  # noqa: E402

RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)

WINDOWS = [
    ("IS1_2015_19",  "2015-01-01", "2019-12-31", "IS"),
    ("OOS1_2020_22", "2020-01-01", "2022-12-31", "OOS"),
    ("IS2_2015_22",  "2015-01-01", "2022-12-31", "IS"),
    ("OOS2_2023_25", "2023-01-01", "2026-12-31", "OOS"),
]


def run_variant(cfg, all_dates, stock_arr, kospi_arr, select_fn, label):
    eq, tr = run_backtest_hooked(
        all_dates, stock_arr, kospi_arr, cfg,
        select_fn=select_fn, entry_mode='open_next_day',
    )
    overall = calc_metrics(eq, tr)
    window_metrics = {}
    for name, s, e, kind in WINDOWS:
        mm = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
        window_metrics[name] = {
            "kind": kind,
            "cagr": round(mm["cagr"], 2) if mm else None,
            "mdd": round(mm["mdd"], 2) if mm else None,
            "trades": mm["trades"] if mm else 0,
            "win_rate": round(mm["win_rate"], 1) if mm else None,
            "pf": round(mm["pf"], 2) if mm else None,
        }
    return {
        "label": label,
        "overall": {
            "cagr": round(overall["cagr"], 2),
            "mdd": round(overall["mdd"], 2),
            "trades": overall["trades"],
            "win_rate": round(overall["win_rate"], 1),
            "pf": round(overall["pf"], 2),
        },
        "windows": window_metrics,
    }, eq, tr


def evaluate_acceptance(baseline, k10):
    """수용 기준 평가.

    Return: dict with:
      - oos_delta: [{window, d_cagr, d_mdd, passes}]
      - criterion_1: all OOS ΔCAGR ≥ -3%p
      - criterion_2: all OOS ΔMDD ≥ -2%p
      - criterion_3: >=1 OOS where K10 CAGR > baseline CAGR and ΔMDD ≥ -2%p
      - decision: Accepted / Rejected
      - reason: short string
    """
    oos_rows = []
    for name, _s, _e, kind in WINDOWS:
        if kind != "OOS":
            continue
        b = baseline["windows"][name]
        k = k10["windows"][name]
        d_cagr = round(k["cagr"] - b["cagr"], 2) if (b["cagr"] is not None and k["cagr"] is not None) else None
        d_mdd = round(k["mdd"] - b["mdd"], 2) if (b["mdd"] is not None and k["mdd"] is not None) else None
        oos_rows.append({
            "window": name,
            "baseline_cagr": b["cagr"], "k10_cagr": k["cagr"], "d_cagr": d_cagr,
            "baseline_mdd": b["mdd"], "k10_mdd": k["mdd"], "d_mdd": d_mdd,
        })

    c1 = all(r["d_cagr"] is not None and r["d_cagr"] >= -3.0 for r in oos_rows)
    c2 = all(r["d_mdd"] is not None and r["d_mdd"] >= -2.0 for r in oos_rows)
    c3 = any(r["d_cagr"] is not None and r["d_cagr"] > 0 and r["d_mdd"] >= -2.0
             for r in oos_rows)

    decision = "Accepted" if (c1 and c2 and c3) else "Rejected"
    reasons = []
    if not c1:
        bad = [r["window"] for r in oos_rows if r["d_cagr"] < -3.0]
        reasons.append(f"CAGR 악화 >3%p: {bad}")
    if not c2:
        bad = [r["window"] for r in oos_rows if r["d_mdd"] < -2.0]
        reasons.append(f"MDD 악화 >2%p: {bad}")
    if not c3:
        reasons.append("OOS 유의 개선 없음")
    return {
        "oos_rows": oos_rows,
        "criterion_1_cagr_within_3pp": c1,
        "criterion_2_mdd_within_2pp": c2,
        "criterion_3_any_oos_improved": c3,
        "decision": decision,
        "reason": "; ".join(reasons) if reasons else "모든 기준 충족",
    }


def main():
    cfg = load_config()
    print(f"[실험 E] Walkforward IS/OOS — max_streak ≤ 10 재현성")
    print(f"[{cfg['name']}]")

    universe = load_universe_ok()
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일\n")

    print("[백테 1/2] baseline (무필터) ...")
    baseline_res, b_eq, b_tr = run_variant(
        cfg, all_dates, stock_arr, kospi_arr, select_baseline, "baseline")
    ov = baseline_res["overall"]
    print(f"  전체: CAGR {ov['cagr']:+.2f}% / MDD {ov['mdd']:.2f}% / "
          f"trades {ov['trades']}")

    print("\n[백테 2/2] K=10 variant (streak ≤ 10) ...")
    k10_res, k_eq, k_tr = run_variant(
        cfg, all_dates, stock_arr, kospi_arr,
        make_select_fresh_only(10), "k10")
    ov = k10_res["overall"]
    print(f"  전체: CAGR {ov['cagr']:+.2f}% / MDD {ov['mdd']:.2f}% / "
          f"trades {ov['trades']}")

    rows_csv = []
    print("\n[요약 테이블]")
    for name, _s, _e, kind in WINDOWS:
        b = baseline_res["windows"][name]
        k = k10_res["windows"][name]
        d_c = round(k["cagr"] - b["cagr"], 2)
        d_m = round(k["mdd"] - b["mdd"], 2)
        print(f"  {name:<18} [{kind}]  baseline CAGR {b['cagr']:+7.2f}% MDD {b['mdd']:+7.2f}%  |  "
              f"K10 CAGR {k['cagr']:+7.2f}% MDD {k['mdd']:+7.2f}%  |  "
              f"Δ CAGR {d_c:+6.2f}p MDD {d_m:+6.2f}p")
        rows_csv.append({
            "window": name, "kind": kind,
            "baseline_cagr": b["cagr"], "baseline_mdd": b["mdd"],
            "baseline_trades": b["trades"], "baseline_win_rate": b["win_rate"],
            "k10_cagr": k["cagr"], "k10_mdd": k["mdd"],
            "k10_trades": k["trades"], "k10_win_rate": k["win_rate"],
            "d_cagr": d_c, "d_mdd": d_m,
        })

    pd.DataFrame(rows_csv).to_csv(RESULTS / "exp_e_windows.csv", index=False)

    # 수용 기준
    eval_res = evaluate_acceptance(baseline_res, k10_res)
    print("\n" + "=" * 60)
    print(f"  수용 기준 평가 (OOS 윈도우 기준)")
    print("=" * 60)
    print(f"  C1 (모든 OOS ΔCAGR ≥ -3%p): {'✅' if eval_res['criterion_1_cagr_within_3pp'] else '❌'}")
    print(f"  C2 (모든 OOS ΔMDD ≥ -2%p): {'✅' if eval_res['criterion_2_mdd_within_2pp'] else '❌'}")
    print(f"  C3 (≥1 OOS 유의 개선):      {'✅' if eval_res['criterion_3_any_oos_improved'] else '❌'}")
    print(f"\n  판정: **{eval_res['decision']}**")
    print(f"  사유: {eval_res['reason']}")

    # 저장
    summary = {
        "baseline": baseline_res,
        "k10": k10_res,
        "evaluation": eval_res,
    }
    (RESULTS / "exp_e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    b_tr.to_parquet(RESULTS / "exp_e_baseline_trades.parquet")
    k_tr.to_parquet(RESULTS / "exp_e_k10_trades.parquet")
    b_eq.to_parquet(RESULTS / "exp_e_baseline_equity.parquet")
    k_eq.to_parquet(RESULTS / "exp_e_k10_equity.parquet")
    print(f"\n[저장] {RESULTS}/exp_e_*")


if __name__ == "__main__":
    main()
