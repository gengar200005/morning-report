"""ADR-003 섹터 강도 산식 회귀 검증.

가설: 매 월말 기준 "주도" 등급 섹터의 다음 1개월 평균 수익률이 벤치마크(KOSPI)
      보다 일관되게 높다면 산식이 실전에 쓸모 있음.

성공 기준 (ADR-003):
    - 평균 초과수익 > 0
    - 월 단위 hit ratio ≥ 60%

사용:
    python scripts/validate_sector_breadth.py \\
        --sector-map backtest/data/sector/sector_map.parquet \\
        --stocks-daily backtest/data/sector/stocks_daily.parquet \\
        --months 12 \\
        --grades 주도

벤치마크는 yfinance ^KS11 종가. 호출 실패 시 "유니버스 전체 평균"으로 폴백.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 레포 루트에서 import 하기 위한 path 보정 (scripts/ 하위 실행 가정)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sector_breadth as sb  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
#  월말 거래일 추출
# ═══════════════════════════════════════════════════════════════════
def get_month_end_trading_days(stocks_daily: pd.DataFrame) -> list[pd.Timestamp]:
    """stocks_daily 의 실제 거래일 중 각 월 마지막 거래일 리스트. 오름차순."""
    dates = pd.to_datetime(stocks_daily["날짜"].unique())
    dates = pd.Series(sorted(dates))
    by_month = dates.groupby(dates.dt.to_period("M")).max()
    return list(by_month.sort_values())


# ═══════════════════════════════════════════════════════════════════
#  벤치마크 (KOSPI)
# ═══════════════════════════════════════════════════════════════════
def fetch_kospi_monthly(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series | None:
    """yfinance ^KS11 일봉 → 월말 종가. 실패 시 None."""
    try:
        import yfinance as yf
    except ImportError:
        print("[warn] yfinance 없음 → KOSPI 벤치마크 생략")
        return None
    try:
        df = yf.download(
            "^KS11",
            start=(start - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        print(f"[warn] yfinance KOSPI 호출 실패: {e}")
        return None
    if df is None or df.empty:
        print("[warn] KOSPI 데이터 비어있음")
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.sort_index()


def kospi_return_between(series: pd.Series, t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    """t0 이전 가장 가까운 날 vs t1 이전 가장 가까운 날. 못 찾으면 NaN."""
    if series is None or series.empty:
        return float("nan")
    before_t0 = series.loc[series.index <= t0]
    before_t1 = series.loc[series.index <= t1]
    if before_t0.empty or before_t1.empty:
        return float("nan")
    p0 = float(before_t0.iloc[-1])
    p1 = float(before_t1.iloc[-1])
    if p0 <= 0:
        return float("nan")
    return p1 / p0 - 1


# ═══════════════════════════════════════════════════════════════════
#  월별 루프
# ═══════════════════════════════════════════════════════════════════
def forward_return(
    prices_wide: pd.DataFrame,
    tickers: list[str],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
) -> tuple[float, int]:
    """선택 종목들의 t0→t1 동등 가중 평균 수익률. (평균, 계산 가능 종목수)."""
    if not tickers:
        return float("nan"), 0
    valid = [t for t in tickers if t in prices_wide.columns]
    if not valid:
        return float("nan"), 0
    sub = prices_wide.loc[:, valid]
    p0 = sub.loc[t0] if t0 in sub.index else None
    p1 = sub.loc[t1] if t1 in sub.index else None
    if p0 is None or p1 is None:
        return float("nan"), 0
    rets = (p1 / p0 - 1).dropna()
    rets = rets[np.isfinite(rets)]
    if rets.empty:
        return float("nan"), 0
    return float(rets.mean()), int(len(rets))


def run_validation(
    sector_map: pd.DataFrame,
    stocks_daily: pd.DataFrame,
    months: int = 12,
    grades: tuple[str, ...] = ("주도",),
    benchmark: str = "universe",
) -> pd.DataFrame:
    """매 월말 기준 선정 섹터의 다음 1개월 수익률 vs benchmark.

    benchmark:
        - "universe": 같은 stocks_daily 유니버스의 동등가중 평균 (ADR-003 의도:
          universe 내 섹터 선택의 순 알파)
        - "kospi": yfinance ^KS11. universe 대비 대형주 편입 차이로 장기 drag
          가능하므로 참고용."""
    month_ends = get_month_end_trading_days(stocks_daily)
    if len(month_ends) < 2:
        raise ValueError("월말 거래일이 2개 이상 필요")

    # 최근 months+1 개 사용 (N개 구간 검증 ⇒ N+1 개 월말 필요)
    month_ends = month_ends[-(months + 1):]

    prices_wide = (
        stocks_daily.pivot_table(index="날짜", columns="ticker", values="종가", aggfunc="last")
        .sort_index()
    )

    kospi = fetch_kospi_monthly(month_ends[0], month_ends[-1]) if benchmark == "kospi" else None

    rows = []
    for i in range(len(month_ends) - 1):
        t0 = month_ends[i]
        t1 = month_ends[i + 1]

        scores = sb.compute_sector_scores(
            sector_map=sector_map, stocks_daily=stocks_daily, end_date=t0,
        )
        selected = scores[scores["grade"].isin(grades)].index.tolist()
        selected_tickers = sector_map.loc[
            sector_map["sector"].isin(selected), "ticker"
        ].tolist()
        universe_tickers = sector_map["ticker"].tolist()

        sector_ret, n_sec = forward_return(prices_wide, selected_tickers, t0, t1)
        universe_ret, n_uni = forward_return(prices_wide, universe_tickers, t0, t1)
        kospi_ret = kospi_return_between(kospi, t0, t1) if kospi is not None else float("nan")

        if benchmark == "kospi":
            bench = kospi_ret if np.isfinite(kospi_ret) else universe_ret
        else:
            bench = universe_ret

        rows.append({
            "month_end": t0.strftime("%Y-%m-%d"),
            "next_end": t1.strftime("%Y-%m-%d"),
            "leading_sectors": ", ".join(selected) if selected else "(none)",
            "n_leading_stocks": n_sec,
            "sector_ret": sector_ret,
            "universe_ret": universe_ret,
            "kospi_ret": kospi_ret,
            "benchmark": bench,
            "excess": sector_ret - bench if np.isfinite(sector_ret) and np.isfinite(bench) else float("nan"),
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════
#  요약
# ═══════════════════════════════════════════════════════════════════
def summarize(results: pd.DataFrame) -> dict:
    valid = results.dropna(subset=["excess"])
    if valid.empty:
        return {
            "n_months": 0, "n_signal_months": 0,
            "mean_excess": float("nan"), "hit_ratio": float("nan"),
        }
    signal = valid[valid["n_leading_stocks"] > 0]
    return {
        "n_months": int(len(valid)),
        "n_signal_months": int(len(signal)),
        "mean_excess": float(valid["excess"].mean()),
        "mean_sector_ret": float(valid["sector_ret"].mean()),
        "mean_benchmark_ret": float(valid["benchmark"].mean()),
        "hit_ratio": float((valid["excess"] > 0).mean()),
    }


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser(description="섹터 강도 산식 회귀 검증 (월별)")
    p.add_argument("--sector-map", required=True)
    p.add_argument("--stocks-daily", required=True)
    p.add_argument("--overrides", default="reports/sector_overrides.yaml")
    p.add_argument("--months", type=int, default=12, help="검증 월 수 (기본 12)")
    p.add_argument(
        "--grades",
        default="주도",
        help="콤마 구분 대상 등급. 예: '주도' 또는 '주도,강세'",
    )
    p.add_argument(
        "--benchmark",
        choices=["universe", "kospi"],
        default="universe",
        help=(
            "판정 벤치마크. universe(기본): stocks_daily 유니버스 동등가중 평균 "
            "— ADR-003 의도인 'universe 내 섹터 선택 알파' 측정. "
            "kospi: yfinance ^KS11 — universe 구성에 따른 drag 있을 수 있음 (참고용)"
        ),
    )
    args = p.parse_args()

    sector_map = sb.load_sector_map(args.sector_map)
    stocks_daily = sb.load_stocks_daily(args.stocks_daily)

    overrides = sb.load_overrides(args.overrides)
    if overrides:
        print(f"[info] ticker_overrides {len(overrides)} applied")
        sector_map = sb.apply_ticker_overrides(sector_map, overrides)

    grades = tuple(g.strip() for g in args.grades.split(",") if g.strip())
    print(f"[info] target grades = {grades}, months = {args.months}, benchmark = {args.benchmark}")

    results = run_validation(
        sector_map, stocks_daily,
        months=args.months, grades=grades, benchmark=args.benchmark,
    )
    with pd.option_context("display.max_rows", None, "display.width", 200, "display.float_format", "{:.4f}".format):
        print("\n=== 월별 결과 ===")
        print(results.to_string(index=False))

    summary = summarize(results)
    print("\n=== 요약 ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:20s}: {v:+.4f}" if "ratio" not in k and "mean" in k else f"  {k:20s}: {v:.4f}")
        else:
            print(f"  {k:20s}: {v}")

    hit = summary.get("hit_ratio", float("nan"))
    exc = summary.get("mean_excess", float("nan"))
    print("\n=== 판정 ===")
    if np.isfinite(exc) and np.isfinite(hit):
        ok_excess = exc > 0
        ok_hit = hit >= 0.60
        print(f"  평균 초과수익 > 0:  {'PASS' if ok_excess else 'FAIL'}  ({exc:+.4f})")
        print(f"  hit ratio ≥ 60%:   {'PASS' if ok_hit else 'FAIL'}  ({hit:.2%})")
        print(f"  종합:              {'PASS' if ok_excess and ok_hit else 'FAIL'}")
    else:
        print("  데이터 부족으로 판정 보류")


if __name__ == "__main__":
    main()
