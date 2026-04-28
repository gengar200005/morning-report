"""
exp_f/g 결과 진단 — cash drag 가설 검증.

가설: top5_4_8 의 CAGR -9.82p 손실 원인은
  (a) 슬롯 미충원 → 시장 노출 부족 (단순 cash drag)
  (b) 매수 못 한 종목 = RS 1위 = 강세장 leader → 선택 편향

trades parquet 에서 일별 활성 포지션 수 재구성 → baseline vs top5_4_8 비교.
강세장 (2025+) 구간 분리해서 차이 부각.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"


def daily_positions(trades: pd.DataFrame, all_dates: pd.DatetimeIndex) -> pd.Series:
    """각 거래일의 활성 포지션 수."""
    counts = pd.Series(0, index=all_dates)
    for _, r in trades.iterrows():
        ed = pd.Timestamp(r['entry_date'])
        xd = pd.Timestamp(r['exit_date'])
        mask = (counts.index >= ed) & (counts.index < xd)
        counts.loc[mask] += 1
    return counts


def summarize(label, daily, period_label, mask):
    sub = daily[mask]
    if len(sub) == 0:
        return
    avg = sub.mean()
    full_days = (sub == 5).sum() / len(sub) * 100
    empty_days = (sub == 0).sum() / len(sub) * 100
    cash_ratio = (5 - sub.mean()) / 5 * 100
    print(f"  {label:<14} {period_label:<12} avg={avg:.2f}/5  "
          f"full={full_days:>5.1f}%  empty={empty_days:>5.1f}%  cash={cash_ratio:>5.1f}%")


def main():
    # 두 백테 trades 로드
    bl_path = RESULTS / "exp_f_baseline_trades.parquet"
    g48_path = RESULTS / "exp_g_top5_4_8_trades.parquet"
    bl = pd.read_parquet(bl_path)
    g48 = pd.read_parquet(g48_path)

    # 거래일 인덱스 (양쪽 trades 의 날짜 합집합)
    all_dates = pd.DatetimeIndex(sorted(set(
        list(bl['entry_date']) + list(bl['exit_date']) +
        list(g48['entry_date']) + list(g48['exit_date'])
    )))
    # 2015-01 ~ 최신까지 영업일
    start = all_dates.min()
    end = all_dates.max()
    bdays = pd.bdate_range(start, end)

    print(f"[기간] {start.date()} ~ {end.date()}  ({len(bdays)} 영업일)")
    print(f"[trades] baseline={len(bl)}  top5_4_8={len(g48)}")
    print()

    bl_daily = daily_positions(bl, bdays)
    g48_daily = daily_positions(g48, bdays)

    print("=" * 90)
    print("  일평균 활성 포지션 수 (5 슬롯 중)")
    print("=" * 90)
    print(f"  {'variant':<14} {'period':<12} {'활성':>10}  {'5슬롯Full':>10}  "
          f"{'0슬롯Empty':>10}  {'cash%':>10}")

    periods = [
        ("전체",       lambda d: pd.Series(True, index=d.index)),
        ("2015-19_박스", lambda d: (d.index >= "2015-01-01") & (d.index <= "2019-12-31")),
        ("2020-24_중립", lambda d: (d.index >= "2020-01-01") & (d.index <= "2024-12-31")),
        ("2025+_강세",  lambda d: (d.index >= "2025-01-01") & (d.index <= "2027-12-31")),
    ]

    for plabel, mfn in periods:
        bm = mfn(bl_daily)
        gm = mfn(g48_daily)
        summarize("baseline",   bl_daily,  plabel, bm)
        summarize("top5_4_8",   g48_daily, plabel, gm)
        print()

    # 강세장 cash drag 임팩트 정량
    print("=" * 90)
    print("  강세장 (2025+) cash drag 임팩트 추정")
    print("=" * 90)
    p25 = (bl_daily.index >= "2025-01-01") & (bl_daily.index <= "2027-12-31")
    bl_avg25 = bl_daily[p25].mean()
    g48_avg25 = g48_daily[p25].mean()
    delta_exposure = (bl_avg25 - g48_avg25) / 5 * 100
    print(f"  baseline 일평균 포지션 (강세) : {bl_avg25:.2f}/5  ({bl_avg25/5*100:.1f}% exposure)")
    print(f"  top5_4_8 일평균 포지션 (강세) : {g48_avg25:.2f}/5  ({g48_avg25/5*100:.1f}% exposure)")
    print(f"  포지션 노출 차이              : -{delta_exposure:.1f}%p")
    print(f"  baseline 강세 CAGR            : +160.96%")
    print(f"  top5_4_8 강세 CAGR            : +48.17%  (Δ -112.8%p)")
    print(f"  ※ 단순 노출 비례 가정 시 예상 : +160.96 × ({g48_avg25/bl_avg25:.2f}) = "
          f"{160.96 * g48_avg25 / bl_avg25:.1f}%")
    print(f"  실제 -112.8p 중 ~{(160.96 - 160.96 * g48_avg25 / bl_avg25):.0f}p 는 cash drag 추정,")
    print(f"  나머지는 종목 선택 편향 (RS 1위 = 9d+ extended 못 산 효과)")


if __name__ == "__main__":
    main()
