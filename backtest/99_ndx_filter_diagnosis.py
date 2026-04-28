"""
사전 진단: 전일 NDX -2% 필터 base rate 확인.

질문: 전일 나스닥이 -2% 이상 하락한 날 신규 매수를 차단하면 백테가 어떻게 변할까.
1단계 (본 스크립트): 백테 trades 와 무관하게 시장 데이터만으로 빈도/조건부 분포 확인.
  - 11년간 NDX 전일 종가 수익률 ≤ -2% 날 = 몇 일?
  - 그날들의 KOSPI 다음날 시가→시가 수익률 평균/분포는?
  - 전체 KOSPI 시가→시가 수익률 분포와 비교 → 실제 차단 효과 추정.

2단계 (필요 시): 백테 데이터 fetch 후 실제 trades 와 join.
"""
from __future__ import annotations
import sys
import yfinance as yf
import numpy as np
import pandas as pd

START = "2015-01-01"
END = "2026-04-28"
THRESHOLD = -0.02  # -2%


def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"empty: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[["Open", "Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def main() -> int:
    print(f"[fetch] ^IXIC, ^KS11  ({START} ~ {END})")
    ndx = fetch("^IXIC")
    kospi = fetch("^KS11")
    print(f"  NDX   {ndx.index.min().date()} ~ {ndx.index.max().date()}  {len(ndx)}일")
    print(f"  KOSPI {kospi.index.min().date()} ~ {kospi.index.max().date()}  {len(kospi)}일")

    # NDX 일간 종가 수익률
    ndx["ret"] = ndx["Close"].pct_change()
    # KOSPI 시가→시가 (다음날) 수익률 — 백테 entry 모델과 동일
    kospi["open_next"] = kospi["Open"].shift(-1)
    kospi["ret_oo"] = kospi["open_next"] / kospi["Open"] - 1

    # NDX -2% 발생 날 → 그 다음 KOSPI 거래일 매핑
    # 방법: NDX 날짜 D 의 ret 이 -2% 이하 → KOSPI 에서 D 이후 첫 거래일 이 "차단 대상"
    ndx_bad = ndx[ndx["ret"] <= THRESHOLD].index

    # KOSPI 인덱스에서 각 ndx_bad 날짜 이후 첫 거래일 찾기
    kospi_idx = kospi.index
    blocked_dates = []
    for d in ndx_bad:
        # NDX 가 D 에 폭락 → KOSPI 다음날 (D+1 이후 첫 KOSPI 거래일) 의 시가 매수 차단
        loc = kospi_idx.searchsorted(d, side="right")
        if loc < len(kospi_idx):
            blocked_dates.append(kospi_idx[loc])
    blocked_dates = pd.DatetimeIndex(sorted(set(blocked_dates)))

    print(f"\n[base rate]")
    print(f"  NDX 일간 -2% 이하 날 수: {len(ndx_bad)}")
    print(f"  KOSPI 차단 후보 거래일 수: {len(blocked_dates)}")
    yrs = (kospi.index.max() - kospi.index.min()).days / 365.25
    print(f"  연평균 차단일: {len(blocked_dates) / yrs:.1f}일/년 ({yrs:.1f}년 기준)")

    # 조건부 KOSPI 시가→시가 수익률
    blocked_ret = kospi.loc[kospi.index.intersection(blocked_dates), "ret_oo"].dropna()
    all_ret = kospi["ret_oo"].dropna()

    def stats(s: pd.Series, label: str):
        print(f"  {label:<22} n={len(s):>5}  "
              f"mean={s.mean()*100:+.3f}%  "
              f"median={s.median()*100:+.3f}%  "
              f"std={s.std()*100:.2f}%  "
              f"win%={(s > 0).mean()*100:.1f}%")

    print(f"\n[KOSPI 시가→시가 수익률 분포]")
    stats(all_ret, "전체 거래일")
    stats(blocked_ret, "NDX -2% 다음날")

    # 더 극단 케이스: NDX -3% 이하
    ndx_very_bad = ndx[ndx["ret"] <= -0.03].index
    blocked_v = []
    for d in ndx_very_bad:
        loc = kospi_idx.searchsorted(d, side="right")
        if loc < len(kospi_idx):
            blocked_v.append(kospi_idx[loc])
    blocked_v = pd.DatetimeIndex(sorted(set(blocked_v)))
    blocked_v_ret = kospi.loc[kospi.index.intersection(blocked_v), "ret_oo"].dropna()
    print(f"\n[참고: NDX -3% 이하]")
    print(f"  KOSPI 차단 후보 {len(blocked_v)}일 ({len(blocked_v) / yrs:.1f}일/년)")
    stats(blocked_v_ret, "NDX -3% 다음날")

    # 차단된 날에 KOSPI 가 평균적으로 손해인지 — 차단 효과의 상한
    diff_mean = (blocked_ret.mean() - all_ret.mean()) * 100
    print(f"\n[해석]")
    print(f"  NDX -2% 다음날 KOSPI 평균 - 전체 평균 = {diff_mean:+.3f}%p")
    if blocked_ret.mean() < 0:
        print(f"  → 차단일 평균 음수: 필터의 잠재 효과 있음 (단, 진입 신호 동시 발생 빈도 별도 확인 필요)")
    else:
        print(f"  → 차단일 평균 양수 또는 0 근처: 시가에 이미 갭다운 반영, 필터 효과 의심")

    return 0


if __name__ == "__main__":
    sys.exit(main())
