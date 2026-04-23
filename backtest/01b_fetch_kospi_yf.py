"""
KOSPI 지수 수집 (yfinance) — pykrx 인덱스 API 장애 우회.

pykrx `get_index_ohlcv_by_date` 가 다운된 상태에서 kospi.parquet 을 yfinance
`^KS11` 로 확보한다. 백테 엔진 (`backtest/strategy.py::load_data`) 은 close
컬럼만 사용하므로 최소 스키마면 충분하다.

사용:
    python backtest/01b_fetch_kospi_yf.py                 # 2015-01-01 ~ 오늘
    python backtest/01b_fetch_kospi_yf.py --start 2020-01-01

출력:
    backtest/data/index/kospi.parquet   — index=DatetimeIndex, columns=[open,high,low,close,volume]
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent
INDEX_DIR = BASE_DIR / "data" / "index"


def fetch_kospi(start: str, end: str) -> pd.DataFrame:
    df = yf.download("^KS11", start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError("yfinance ^KS11 returned empty DataFrame")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    end = args.end or date.today().isoformat()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[yfinance] ^KS11  {args.start} ~ {end}")
    df = fetch_kospi(args.start, end)
    out = INDEX_DIR / "kospi.parquet"
    df.to_parquet(out, engine="pyarrow", compression="snappy")
    print(f"완료: {len(df)} rows  ({df.index.min().date()} ~ {df.index.max().date()})")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
