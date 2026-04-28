"""
사전 진단 2단계: 백테 실제 진입 거래의 시가 갭 분포.

질문: 우리 전략이 매수 추천하는 종목들이 다음날 시가에 갭상하는 경향이 있나?
  - "시그널 = 어제 종가 강세" → 다음날 시가 갭상으로 이어질 가능성?
  - 갭상 빈도/평균이 높으면 백테 "시가 100% 체결" 가정의 부풀림 효과 큼
  - 갭다운 빈도가 높으면 마스터 인지 갭("핫 종목은 항상 갭상") 과 다름

측정:
  각 trade 의 gap = entry_date 시가 / 직전 거래일 종가 - 1
  분포 + 갭 버킷별 trade 수익률 + 연도별 분해
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from strategy import (
    load_config, load_universe_ok, load_data, run_backtest,
)


def main() -> int:
    cfg = load_config()
    universe = load_universe_ok()
    print(f"[load] universe {len(universe)}종목")
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[load] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    print("\n[backtest] 실행 중...")
    eq, trades = run_backtest(all_dates, stock_arr, kospi_arr, cfg)
    print(f"[backtest] 거래 {len(trades)}건")

    # 날짜 → index 매핑
    date_to_i = {pd.Timestamp(d): i for i, d in enumerate(all_dates)}

    rows = []
    for _, t in trades.iterrows():
        tk = t["ticker"]
        ed = pd.Timestamp(t["entry_date"])
        i = date_to_i.get(ed)
        if i is None or i == 0:
            continue
        c_arr, o_arr, _v = stock_arr[tk]
        # entry_date 직전 거래일 종가 = c_arr[i-1] (이미 ffill 처리)
        prev_close = c_arr[i - 1]
        today_open = o_arr[i]
        if prev_close <= 0 or today_open <= 0:
            continue
        gap = today_open / prev_close - 1
        rows.append({
            "ticker": tk,
            "entry_date": ed,
            "gap_pct": gap * 100,
            "ret_pct": float(t["ret"]),  # strategy.py 가 이미 % 단위로 저장
            "reason": t["reason"],
            "hold_days": int(t["hold_days"]),
        })

    g = pd.DataFrame(rows)
    print(f"\n[analysis] 분석 가능 거래 {len(g)}건 (전체 {len(trades)} 중)")

    print(f"\n[갭 분포]")
    print(f"  평균 gap        : {g['gap_pct'].mean():+.3f}%")
    print(f"  중앙 gap        : {g['gap_pct'].median():+.3f}%")
    print(f"  std             : {g['gap_pct'].std():.3f}%")
    print(f"  갭상 (>0)       : {(g['gap_pct'] > 0).mean() * 100:.1f}%")
    print(f"  갭상 ≥ +1%      : {(g['gap_pct'] >= 1).mean() * 100:.1f}%")
    print(f"  갭상 ≥ +3%      : {(g['gap_pct'] >= 3).mean() * 100:.1f}%")
    print(f"  갭상 ≥ +5%      : {(g['gap_pct'] >= 5).mean() * 100:.1f}%")
    print(f"  갭다운 ≤ -1%    : {(g['gap_pct'] <= -1).mean() * 100:.1f}%")
    print(f"  갭다운 ≤ -3%    : {(g['gap_pct'] <= -3).mean() * 100:.1f}%")

    # 갭 버킷별 trade 수익률
    print(f"\n[갭 버킷 × 백테 수익률 (entry → exit, 1 거래 단위)]")
    bins = [-np.inf, -3, -1, 0, 1, 3, 5, 10, np.inf]
    labels = ["≤-3%", "-3~-1", "-1~0", "0~1", "1~3", "3~5", "5~10", ">10%"]
    g["bucket"] = pd.cut(g["gap_pct"], bins=bins, labels=labels)
    bucket_stats = g.groupby("bucket", observed=True).agg(
        n=("ret_pct", "count"),
        share=("ret_pct", lambda x: len(x) / len(g) * 100),
        mean_ret=("ret_pct", "mean"),
        median_ret=("ret_pct", "median"),
        win_pct=("ret_pct", lambda x: (x > 0).mean() * 100),
    )
    print(bucket_stats.to_string(float_format=lambda x: f"{x:+.2f}"))

    # 연도별 분해
    print(f"\n[연도별 분해]")
    g["year"] = g["entry_date"].dt.year
    yr_stats = g.groupby("year").agg(
        n=("gap_pct", "count"),
        mean_gap=("gap_pct", "mean"),
        gap_up_pct=("gap_pct", lambda x: (x > 0).mean() * 100),
        mean_ret=("ret_pct", "mean"),
    )
    print(yr_stats.to_string(float_format=lambda x: f"{x:+.2f}"))

    # 시장 환경별 (CLAUDE.md 분류)
    print(f"\n[시장 환경별]")
    regimes = [
        ("박스권 2015-19", 2015, 2019),
        ("중립 2020-24",   2020, 2024),
        ("강세 2025+",     2025, 2026),
    ]
    for label, ys, ye in regimes:
        sub = g[(g["year"] >= ys) & (g["year"] <= ye)]
        if len(sub) == 0:
            continue
        print(f"  {label:<14}  n={len(sub):>4}  "
              f"mean_gap={sub['gap_pct'].mean():+.3f}%  "
              f"갭상%={(sub['gap_pct'] > 0).mean() * 100:.1f}%  "
              f"mean_ret={sub['ret_pct'].mean():+.2f}%")

    # 해석 가이드
    print(f"\n[해석]")
    avg_gap = g["gap_pct"].mean()
    up_pct = (g["gap_pct"] > 0).mean() * 100
    if up_pct >= 60 and avg_gap >= 1.0:
        msg = "강한 갭상 편향: 시그널 종목이 평균적으로 시가에 1%+ 점프. 백테 시가 체결 가정이 알파를 부풀릴 위험 큼."
    elif up_pct >= 55 and avg_gap >= 0.3:
        msg = "약한 갭상 편향: 시그널 종목이 살짝 비싸게 시작. 백테 가정은 어느 정도 살아있지만 슬리피지 보정 필요."
    elif up_pct < 50:
        msg = "갭다운 편향: 시그널 종목이 오히려 시가에 약간 떨어져서 시작 (의외). mean reversion 패턴이 인덱스만이 아닐 수 있음."
    else:
        msg = "거의 균등: 갭상/갭다운 절반씩, 백테 시가 가정은 통계적으로 합리."
    print(f"  → {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
