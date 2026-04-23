"""
Sector strength scoring — ADR-003 Amendment 2026-04-23 implementation.

ADR-003 산식 (임시):
    섹터 점수 = ((A) IBD 6M 백분위 50 + (C) Breadth 25) × 100/75
              = (IBD + Breadth) × 1.333 → 0-100 스케일

    (B) Weinstein Stage 25점은 pykrx 인덱스 API 복구 후 재도입.

등급:
    ≥ 75  → 주도 (Leading)
    60-74 → 강세 (Strong)
    40-59 → 중립 (Neutral)
    < 40  → 약세 (Weak)

사용:
    import sector_breadth as sb
    scores = sb.compute_sector_scores(
        sector_map_path='...sector_map.parquet',
        stocks_daily_path='...stocks_daily.parquet',
        end_date='2026-04-22',
    )
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════
#  Constants (ADR-003 Amendment)
# ═══════════════════════════════════════════════════════════════════
IBD_LOOKBACK_DAYS = 126           # 6 months ≈ 126 trading days
MA_WINDOW = 50                    # Breadth: % above 50-day MA
SINGLE_STOCK_CAP = 0.25           # 시총 가중 단일 종목 25% cap (ADR §시총 가중)
SAMPLE_MIN_FULL = 5               # 종목 ≥5 → 정상 점수
SAMPLE_MIN_PARTIAL = 3            # 종목 3-4 → breadth 무시, IBD만
# <3 은 섹터 점수 N/A

IBD_WEIGHT = 50                   # (A) 50점
BREADTH_WEIGHT = 25               # (C) 25점
SCORE_SCALE = 100 / (IBD_WEIGHT + BREADTH_WEIGHT)  # rescale ×1.333 (Stage 복구 시 1.0)

THRESHOLDS = {
    "주도": 75.0,
    "강세": 60.0,
    "중립": 40.0,
}


# ═══════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════
@dataclass
class SectorScore:
    sector: str
    n_stocks: int                 # 섹터 내 매핑된 종목 수
    n_priced: int                 # 가격 데이터 있는 종목 수 (6M 수익률 계산 가능)
    ibd_return: float | None      # 시총가중+cap 6M 수익률 (0.15 = +15%)
    ibd_percentile: float | None  # 22업종 중 백분위 (0-1)
    ibd_points: float             # IBD 점수 (0-50)
    breadth_pct: float | None     # MA50 돌파 비율 (0-1)
    breadth_points: float         # Breadth 점수 (0-25), 샘플 부족 시 0
    raw_score: float              # IBD + Breadth (0-75)
    score: float                  # rescale ×1.333 (0-100)
    grade: str                    # 주도 / 강세 / 중립 / 약세 / N/A


# ═══════════════════════════════════════════════════════════════════
#  Loaders
# ═══════════════════════════════════════════════════════════════════
def load_sector_map(path: str | Path) -> pd.DataFrame:
    """sector_map.parquet 로드 + 유효 컬럼 검증.

    Returns:
        DataFrame with: ticker, name, market, ksic, sector, marcap
    """
    df = pd.read_parquet(path)
    required = {"ticker", "name", "sector", "marcap"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"sector_map missing columns: {missing}")
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    return df


def load_stocks_daily(path: str | Path) -> pd.DataFrame:
    """stocks_daily.parquet 로드 + 날짜 정렬.

    Returns:
        DataFrame with: 날짜, ticker, 시가/고가/저가/종가, ...
        날짜 오름차순, ticker 별 group 정렬.
    """
    df = pd.read_parquet(path)
    df["날짜"] = pd.to_datetime(df["날짜"])
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    return df.sort_values(["ticker", "날짜"]).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════
#  (A) IBD 6M 백분위 (시총 가중 + 25% cap)
# ═══════════════════════════════════════════════════════════════════
def compute_stock_6m_returns(
    stocks_daily: pd.DataFrame,
    end_date: pd.Timestamp,
) -> pd.Series:
    """종목별 6개월(126 거래일) 수익률 계산.

    Args:
        stocks_daily: load_stocks_daily 산출물
        end_date: 기준일 (이 날 또는 이전 마지막 거래일의 종가 vs 126일 전)

    Returns:
        Series indexed by ticker, value = (종가_end / 종가_126일전) - 1
        데이터 부족 종목은 누락 (NaN 아닌 키 자체 없음).
    """
    end_date = pd.Timestamp(end_date)
    out = {}
    for ticker, g in stocks_daily.groupby("ticker"):
        g = g[g["날짜"] <= end_date]
        if len(g) < IBD_LOOKBACK_DAYS + 1:
            continue
        # 마지막 IBD_LOOKBACK_DAYS+1 개 중 첫째와 마지막
        recent = g.tail(IBD_LOOKBACK_DAYS + 1)
        start_price = recent.iloc[0]["종가"]
        end_price = recent.iloc[-1]["종가"]
        if start_price <= 0:
            continue
        out[ticker] = end_price / start_price - 1
    return pd.Series(out, name="ret_6m")


def _cap_weights(marcaps: np.ndarray, cap: float = SINGLE_STOCK_CAP) -> np.ndarray:
    """시총 배열 → 비중 배열. 최대 `cap`(25%)으로 제한하고 초과분은 나머지에 재분배.

    반복 적용: cap 이상인 종목 고정 → 나머지 정규화 → 또 cap 넘는 종목 있으면 반복.
    """
    if len(marcaps) == 0:
        return np.array([], dtype=float)
    w = marcaps.astype(float) / marcaps.sum()
    # 단일 종목일 때: 100% 자동 = cap 무의미 (섹터 내 1종목이면 그 종목이 섹터)
    if len(w) == 1:
        return w
    for _ in range(len(w)):
        over = w > cap
        if not over.any():
            break
        fixed_sum = cap * over.sum()
        remaining = 1 - fixed_sum
        if remaining <= 0:
            # 극단 케이스: cap × 종목수 ≥ 1 → 동등 가중
            return np.full_like(w, 1 / len(w))
        rest_mask = ~over
        rest_sum = w[rest_mask].sum()
        if rest_sum <= 0:
            return np.full_like(w, 1 / len(w))
        w = np.where(over, cap, w * remaining / rest_sum)
    return w


def compute_sector_ibd_return(
    sector_map: pd.DataFrame,
    returns_6m: pd.Series,
) -> pd.DataFrame:
    """섹터별 시총가중+cap 6M 수익률.

    Returns:
        DataFrame indexed by sector with:
          - n_stocks: 매핑된 종목 수
          - n_priced: 6M 수익률 계산 가능 종목 수
          - ibd_return: 가중 평균 수익률 (NaN 가능)
    """
    rows = []
    for sector, grp in sector_map.groupby("sector"):
        n_stocks = len(grp)
        valid = grp[
            grp["ticker"].isin(returns_6m.index)
            & grp["marcap"].notna()
            & (grp["marcap"] > 0)
        ]
        n_priced = len(valid)
        if n_priced == 0:
            rows.append({"sector": sector, "n_stocks": n_stocks, "n_priced": 0, "ibd_return": np.nan})
            continue
        weights = _cap_weights(valid["marcap"].to_numpy())
        rets = valid["ticker"].map(returns_6m).to_numpy()
        wret = float(np.sum(weights * rets))
        rows.append({"sector": sector, "n_stocks": n_stocks, "n_priced": n_priced, "ibd_return": wret})
    return pd.DataFrame(rows).set_index("sector")


def compute_ibd_points(sector_returns: pd.DataFrame) -> pd.Series:
    """백분위 순위 → IBD 점수 (0-50).

    점수 = IBD_WEIGHT × percentile_rank  (동점은 평균 순위)
    n_priced=0 섹터는 순위 대상 제외 → 점수 NaN.
    """
    r = sector_returns["ibd_return"].dropna()
    if len(r) == 0:
        return pd.Series(dtype=float, name="ibd_points")
    # pandas rank pct=True: (rank / count) ∈ (0, 1]
    pct = r.rank(pct=True, method="average")
    points = (pct * IBD_WEIGHT).reindex(sector_returns.index)  # 빠진 섹터는 NaN
    points.name = "ibd_points"
    return points


# ═══════════════════════════════════════════════════════════════════
#  (C) Breadth (% above MA50)
# ═══════════════════════════════════════════════════════════════════
def compute_breadth(
    sector_map: pd.DataFrame,
    stocks_daily: pd.DataFrame,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """섹터별 % above MA50 breadth.

    Returns:
        DataFrame indexed by sector with:
          - n_above: MA50 상회 종목 수
          - n_ma50_eligible: MA50 계산 가능 종목 수 (거래일 50+)
          - breadth_pct: n_above / n_ma50_eligible (NaN 가능)
    """
    end_date = pd.Timestamp(end_date)
    above_flags = {}
    for ticker, g in stocks_daily.groupby("ticker"):
        g = g[g["날짜"] <= end_date]
        if len(g) < MA_WINDOW:
            continue
        recent = g.tail(MA_WINDOW)
        ma = recent["종가"].mean()
        last = recent.iloc[-1]["종가"]
        above_flags[ticker] = bool(last > ma)

    rows = []
    for sector, grp in sector_map.groupby("sector"):
        eligible = grp[grp["ticker"].isin(above_flags)]
        n_elig = len(eligible)
        n_above = int(sum(above_flags[t] for t in eligible["ticker"]))
        pct = n_above / n_elig if n_elig > 0 else np.nan
        rows.append({
            "sector": sector,
            "n_above": n_above,
            "n_ma50_eligible": n_elig,
            "breadth_pct": pct,
        })
    return pd.DataFrame(rows).set_index("sector")


def compute_breadth_points(breadth: pd.DataFrame, sector_sizes: pd.Series) -> pd.Series:
    """Breadth 점수 (0-25).

    표본 단계화 (ADR-003):
      - 종목 수 ≥ 5  → 정상: BREADTH_WEIGHT × breadth_pct
      - 3-4        → 0점 (IBD만 반영)
      - < 3        → 이 함수는 호출되지 않음 (상위에서 N/A 처리)
    """
    out = {}
    for sector in sector_sizes.index:
        n = sector_sizes[sector]
        if n >= SAMPLE_MIN_FULL and sector in breadth.index:
            pct = breadth.at[sector, "breadth_pct"]
            out[sector] = BREADTH_WEIGHT * pct if pd.notna(pct) else np.nan
        else:
            out[sector] = 0.0
    return pd.Series(out, name="breadth_points")


# ═══════════════════════════════════════════════════════════════════
#  합산 + 등급
# ═══════════════════════════════════════════════════════════════════
def classify_grade(score: float) -> str:
    if not np.isfinite(score):
        return "N/A"
    if score >= THRESHOLDS["주도"]:
        return "주도"
    if score >= THRESHOLDS["강세"]:
        return "강세"
    if score >= THRESHOLDS["중립"]:
        return "중립"
    return "약세"


def compute_sector_scores(
    sector_map_path: str | Path | None = None,
    stocks_daily_path: str | Path | None = None,
    end_date: str | pd.Timestamp | None = None,
    sector_map: pd.DataFrame | None = None,
    stocks_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """섹터 점수 일괄 산출 — ADR-003 Amendment 산식.

    Args:
        sector_map_path / stocks_daily_path: parquet 경로. 또는 이미 로드된
            DataFrame 을 직접 넘겨도 됨 (회귀 검증에서 end_date 루프 시 유용).
        end_date: 기준일. None 이면 stocks_daily 의 마지막 날짜.

    Returns:
        DataFrame indexed by sector with columns:
          n_stocks, n_priced, ibd_return, ibd_percentile, ibd_points,
          breadth_pct, breadth_points, raw_score, score, grade
        점수 내림차순 정렬.
    """
    if sector_map is None:
        if sector_map_path is None:
            raise ValueError("sector_map or sector_map_path required")
        sector_map = load_sector_map(sector_map_path)
    if stocks_daily is None:
        if stocks_daily_path is None:
            raise ValueError("stocks_daily or stocks_daily_path required")
        stocks_daily = load_stocks_daily(stocks_daily_path)

    if end_date is None:
        end_date = stocks_daily["날짜"].max()
    end_date = pd.Timestamp(end_date)

    # 섹터 매핑 있는 종목만 (NaN 섹터 제외)
    sm = sector_map[sector_map["sector"].notna()].copy()
    sector_sizes = sm.groupby("sector").size()

    # (A) IBD
    returns_6m = compute_stock_6m_returns(stocks_daily, end_date)
    sector_returns = compute_sector_ibd_return(sm, returns_6m)
    ibd_points = compute_ibd_points(sector_returns)

    # percentile 별도 계산 (출력용)
    r = sector_returns["ibd_return"]
    percentile = r.rank(pct=True, method="average")

    # (C) Breadth
    breadth = compute_breadth(sm, stocks_daily, end_date)
    breadth_points = compute_breadth_points(breadth, sector_sizes)

    # 합산
    df = sector_returns.join(breadth, how="outer")
    df["ibd_percentile"] = percentile
    df["ibd_points"] = ibd_points
    df["breadth_points"] = breadth_points
    df["raw_score"] = df["ibd_points"].fillna(0) + df["breadth_points"].fillna(0)
    df["score"] = df["raw_score"] * SCORE_SCALE

    # 표본 부족 섹터 (< 3) → N/A
    too_small = sector_sizes[sector_sizes < SAMPLE_MIN_PARTIAL].index
    df.loc[df.index.isin(too_small), ["score", "raw_score"]] = np.nan
    # IBD 계산 실패(n_priced=0) 시 점수 N/A
    df.loc[df["n_priced"] == 0, ["score", "raw_score"]] = np.nan

    df["grade"] = df["score"].apply(classify_grade)

    # 정렬 + 컬럼 순서
    cols = [
        "n_stocks", "n_priced",
        "ibd_return", "ibd_percentile", "ibd_points",
        "n_above", "n_ma50_eligible", "breadth_pct", "breadth_points",
        "raw_score", "score", "grade",
    ]
    cols = [c for c in cols if c in df.columns]
    df = df[cols].sort_values("score", ascending=False, na_position="last")
    return df


# ═══════════════════════════════════════════════════════════════════
#  CLI (간단 실행)
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="섹터 강도 점수 산출")
    parser.add_argument("--sector-map", required=True, help="sector_map.parquet 경로")
    parser.add_argument("--stocks-daily", required=True, help="stocks_daily.parquet 경로")
    parser.add_argument("--end-date", default=None, help="기준일 YYYY-MM-DD (기본: 최신)")
    args = parser.parse_args()

    scores = compute_sector_scores(
        sector_map_path=args.sector_map,
        stocks_daily_path=args.stocks_daily,
        end_date=args.end_date,
    )
    with pd.option_context("display.max_rows", None, "display.width", 200):
        print(scores.round(2))
