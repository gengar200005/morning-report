"""모든 실험 결과를 experiments_compare.csv 로 통합."""
from __future__ import annotations
import sys
import json
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"


def load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    rows = []
    # 실험 A (= B0 baseline)
    a = load("exp_a_summary.json")
    if a:
        rows.append({
            "experiment": "A_baseline",
            "filter": "check_signal (core+rs+supply)",
            "entry_mode": "open_next_day",
            "cagr": a["cagr"], "mdd": a["mdd"], "pf": a["pf"],
            "win_rate": a["win_rate"], "trades": a["trades"],
            "avg_hold_days": a["avg_hold_days"],
            "signal_age_mean": a["signal_age"]["mean"],
            "signal_age_median": a["signal_age"]["median"],
            "note": "baseline T10/CD60 재현 + signal_age 계측",
        })
    # 실험 B split (4 variants)
    bs = load("exp_b_split.json") or []
    for b in bs:
        if b["variant"] == "B0_baseline":
            continue
        rows.append({
            "experiment": b["variant"],
            "filter": b["filter"],
            "entry_mode": b["entry_mode"],
            "cagr": b["cagr"], "mdd": b["mdd"], "pf": b["pf"],
            "win_rate": b["win_rate"], "trades": b["trades"],
            "avg_hold_days": b["avg_hold_days"],
            "signal_age_mean": b["signal_age_mean"],
            "signal_age_median": b["signal_age_median"],
            "note": {
                "B1_close_sameday_only": "체결 타이밍만 변경 (당일 종가)",
                "B2_core_only_filter": "필터만 완화 (core_only)",
                "B3_both_relaxed": "필터+체결 둘 다",
            }.get(b["variant"], ""),
        })
    # 실험 C (sensitivity)
    cs = load("exp_c_summary.json") or []
    for c in cs:
        rows.append({
            "experiment": f"C_fresh_le{c['max_streak']}",
            "filter": "check_signal + streak<=N",
            "entry_mode": "open_next_day",
            "cagr": c["cagr"], "mdd": c["mdd"], "pf": c["pf"],
            "win_rate": c["win_rate"], "trades": c["trades"],
            "avg_hold_days": c["avg_hold_days"],
            "signal_age_mean": c["signal_age_mean"],
            "signal_age_median": c["signal_age_median"],
            "note": f"fresh-only max_streak={c['max_streak']}",
        })

    df = pd.DataFrame(rows)
    out = RESULTS / "experiments_compare.csv"
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    print(f"\n[저장] {out}")


if __name__ == "__main__":
    main()
