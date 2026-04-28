"""
실험 A 사후 분석 — signal_age_at_sel 버킷별 trade return 분포.

ADR-005 실험 A 가 만든 exp_a_trades.parquet (333 trades, baseline T10/CD60) 를
재사용. signal_age 별로 trade 수익률을 group by 하여 "어느 신호일에 진입한
trade 가 평균/median/승률 면에서 가장 좋았나" 를 측정.

⚠️ 주의 (ADR-005/010 메타 원칙):
- 이 분석은 사후 진단이지 알파 룰이 아님.
- 결과가 "X일차가 best" 로 나와도 그 버킷만 고르는 룰을 만들면 ADR-005
  실험 C 와 동형 (cherry-pick = overfitting). 4번 연속 fail 패턴 재진입.

산출:
- 콘솔: 버킷별 n / mean / median / win / pf / std
- results/exp_a_age_returns.csv
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
    if age <= 1:
        return "01_fresh(1)"
    if age <= 3:
        return "02_2-3d"
    if age <= 7:
        return "03_4-7d"
    if age <= 14:
        return "04_8-14d"
    if age <= 30:
        return "05_15-30d"
    if age <= 60:
        return "06_31-60d"
    return "07_61+d"


def main():
    if not TRADES.exists():
        print(f"[ERROR] {TRADES} 없음. 먼저 exp_a_entry_timing_diag.py 를 실행하거나")
        print(f"        main checkout 의 results/ 를 worktree 로 복사하세요.")
        sys.exit(1)

    tr = pd.read_parquet(TRADES)
    print(f"[로드] {len(tr)} trades from {TRADES.name}")
    print(f"  컬럼: {list(tr.columns)}")
    print(f"  ret 단위: % (이미 *100 처리됨, engine.py 참조)")

    tr = tr.dropna(subset=["signal_age_at_sel", "ret"]).copy()
    tr["age"] = tr["signal_age_at_sel"].astype(int)
    tr["bucket"] = tr["age"].map(bucket)
    tr["win"] = (tr["ret"] > 0).astype(int)

    # Profit factor 계산용
    def pf(rets: pd.Series) -> float:
        gain = rets[rets > 0].sum()
        loss = -rets[rets < 0].sum()
        return float(gain / loss) if loss > 0 else float("inf")

    print(f"\n{'='*88}")
    print(f"  signal_age 버킷별 trade return 분포 (baseline T10/CD60, n={len(tr)})")
    print(f"{'='*88}")
    hdr = f"  {'bucket':<14} {'n':>4} {'mean%':>7} {'med%':>7} {'std%':>7} "
    hdr += f"{'win%':>6} {'pf':>5} {'p25%':>7} {'p75%':>7} {'best%':>8} {'worst%':>8}"
    print(hdr)
    print(f"  {'-'*86}")

    rows = []
    for bk, sub in tr.groupby("bucket"):
        rets = sub["ret"]
        n = len(sub)
        row = {
            "bucket": bk,
            "n": n,
            "mean": float(rets.mean()),
            "median": float(rets.median()),
            "std": float(rets.std()),
            "win_rate": float(sub["win"].mean() * 100),
            "pf": pf(rets),
            "p25": float(rets.quantile(0.25)),
            "p75": float(rets.quantile(0.75)),
            "best": float(rets.max()),
            "worst": float(rets.min()),
        }
        rows.append(row)
        pf_str = f"{row['pf']:.2f}" if row['pf'] != float("inf") else "inf"
        print(f"  {bk:<14} {n:>4} {row['mean']:>+7.2f} {row['median']:>+7.2f} "
              f"{row['std']:>7.2f} {row['win_rate']:>6.1f} {pf_str:>5} "
              f"{row['p25']:>+7.2f} {row['p75']:>+7.2f} "
              f"{row['best']:>+8.2f} {row['worst']:>+8.2f}")

    # 전체
    all_rets = tr["ret"]
    print(f"  {'-'*86}")
    print(f"  {'TOTAL':<14} {len(tr):>4} {all_rets.mean():>+7.2f} {all_rets.median():>+7.2f} "
          f"{all_rets.std():>7.2f} {tr['win'].mean()*100:>6.1f} {pf(all_rets):>5.2f} "
          f"{all_rets.quantile(0.25):>+7.2f} {all_rets.quantile(0.75):>+7.2f} "
          f"{all_rets.max():>+8.2f} {all_rets.min():>+8.2f}")

    # 청산 사유별 (참고)
    print(f"\n{'─'*88}")
    print(f"  버킷 × 청산 사유 (count)")
    print(f"{'─'*88}")
    pivot = tr.pivot_table(index="bucket", columns="reason",
                           values="ret", aggfunc="count", fill_value=0)
    print(pivot.to_string())

    # CSV 저장
    out_df = pd.DataFrame(rows).round(2)
    out_csv = RESULTS / "exp_a_age_returns.csv"
    out_df.to_csv(out_csv, index=False)
    print(f"\n[저장] {out_csv}")

    # 사후 sanity — 단순 가중 평균 vs baseline CAGR 환산은 의미 없음
    # (포트폴리오 5종목 균등가중 + cooldown 상호작용 때문에 trade-mean 으로
    # 곧장 CAGR 재현 안 됨. 이 분석은 trade-level 분포만 본다.)
    print(f"\n  ※ trade mean 은 포트폴리오 CAGR 과 직접 비교 불가.")
    print(f"    이 표는 '신호 N일차에 진입한 trade 의 평균 손익률' 분포만 측정.")


if __name__ == "__main__":
    main()
