"""
Step 1: UNIVERSE OHLCV + 지수 데이터 수집 → Parquet.

사용:
    python backtest/01_fetch_data.py                 # 이미 있는 파일은 스킵
    python backtest/01_fetch_data.py --force         # 전부 다시 받음
    python backtest/01_fetch_data.py --start 2020-01-01
    python backtest/01_fetch_data.py --only 005930,000660

출력:
    backtest/data/ohlcv/{ticker}.parquet     — 종목별
    backtest/data/index/{kospi,kosdaq}.parquet
    backtest/data/meta.json                  — 수집 이력·실패 기록
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd
from pykrx import stock
from tqdm import tqdm

# backtest/ 를 import path 에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe import UNIVERSE, INDICES  # noqa: E402

# ── 경로 상수 ────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OHLCV_DIR = DATA_DIR / "ohlcv"
INDEX_DIR = DATA_DIR / "index"
META_PATH = DATA_DIR / "meta.json"

# ── 수집 파라미터 ────────────────────────────────
DEFAULT_START = "2015-01-01"
SLEEP_SEC = 0.4          # pykrx rate-limit 회피
MAX_RETRY = 3            # 종목별 재시도
RETRY_SLEEP = 2.0        # 재시도 간 대기


def load_universe() -> list[tuple[str, str]]:
    """universe.py 의 UNIVERSE 스냅샷 반환."""
    return list(UNIVERSE)


def _fmt(d: str | date) -> str:
    """'2015-01-01' 또는 date → 'YYYYMMDD' (pykrx 포맷)."""
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    return d.replace("-", "")


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """단일 종목 OHLCV. 재시도 포함. 빈 DF 가능 (신규 상장 등)."""
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRY):
        try:
            df = stock.get_market_ohlcv_by_date(_fmt(start), _fmt(end), ticker)
            # pykrx 컬럼: 시가/고가/저가/종가/거래량/거래대금/등락률
            df = df.rename(columns={
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "value",
                "등락률": "change_pct",
            })
            df.index.name = "date"
            return df
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRY - 1:
                time.sleep(RETRY_SLEEP * (attempt + 1))
    raise RuntimeError(f"fetch_ohlcv failed for {ticker}: {last_err}")


def fetch_index(index_code: str, start: str, end: str) -> pd.DataFrame:
    """지수 OHLCV (KOSPI/KOSDAQ). 재시도 포함."""
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRY):
        try:
            df = stock.get_index_ohlcv_by_date(_fmt(start), _fmt(end), index_code)
            df = df.rename(columns={
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "value",
                "상장시가총액": "market_cap",
            })
            df.index.name = "date"
            return df
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRY - 1:
                time.sleep(RETRY_SLEEP * (attempt + 1))
    raise RuntimeError(f"fetch_index failed for {index_code}: {last_err}")


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", compression="snappy")


def _row_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"rows": 0, "first": None, "last": None}
    return {
        "rows": int(len(df)),
        "first": str(df.index.min().date()),
        "last": str(df.index.max().date()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="종료일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--force", action="store_true", help="기존 parquet 덮어쓰기")
    ap.add_argument("--only", default=None,
                    help="쉼표구분 티커만 처리 (예: 005930,000660)")
    ap.add_argument("--skip-index", action="store_true", help="지수 수집 생략")
    args = ap.parse_args()

    start = args.start
    end = args.end or date.today().isoformat()

    universe = load_universe()
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        universe = [(t, n) for t, n in universe if t in wanted]
        if not universe:
            print(f"[error] --only 필터 {wanted} 와 매칭되는 티커 없음")
            return 1

    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    meta: dict = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "start": start,
        "end": end,
        "universe_size": len(load_universe()),
        "processed": len(universe),
        "tickers": {},
        "indices": {},
        "failures": [],
    }

    # ── 1) 종목 OHLCV ─────────────────────────────
    print(f"[1/2] OHLCV 수집  ({len(universe)} 종목, {start} ~ {end})")
    for ticker, name in tqdm(universe, desc="ohlcv"):
        out = OHLCV_DIR / f"{ticker}.parquet"
        if out.exists() and not args.force:
            try:
                existing = pd.read_parquet(out)
                meta["tickers"][ticker] = {
                    "name": name, "skipped": True, **_row_summary(existing),
                }
            except Exception as e:
                meta["tickers"][ticker] = {
                    "name": name, "skipped": True, "read_error": str(e),
                }
            continue

        try:
            df = fetch_ohlcv(ticker, start, end)
            save_parquet(df, out)
            meta["tickers"][ticker] = {"name": name, **_row_summary(df)}
        except Exception as e:
            meta["tickers"][ticker] = {"name": name, "error": str(e)}
            meta["failures"].append({"ticker": ticker, "name": name, "error": str(e)})
            tqdm.write(f"  [fail] {ticker} {name}: {e}")

        time.sleep(SLEEP_SEC)

    # ── 2) 지수 ──────────────────────────────────
    if not args.skip_index:
        print(f"[2/2] 지수 수집  ({list(INDICES)})")
        for name, code in INDICES.items():
            out = INDEX_DIR / f"{name}.parquet"
            if out.exists() and not args.force:
                try:
                    existing = pd.read_parquet(out)
                    meta["indices"][name] = {
                        "code": code, "skipped": True, **_row_summary(existing),
                    }
                except Exception as e:
                    meta["indices"][name] = {
                        "code": code, "skipped": True, "read_error": str(e),
                    }
                continue
            try:
                df = fetch_index(code, start, end)
                save_parquet(df, out)
                meta["indices"][name] = {"code": code, **_row_summary(df)}
            except Exception as e:
                meta["indices"][name] = {"code": code, "error": str(e)}
                meta["failures"].append({"index": name, "code": code, "error": str(e)})
                print(f"  [fail] {name} {code}: {e}")
            time.sleep(SLEEP_SEC)

    # ── 3) meta.json ─────────────────────────────
    # 이전 meta 가 있으면 병합 (이번 실행에서 건드리지 않은 종목 정보 유지)
    if META_PATH.exists():
        try:
            prev = json.loads(META_PATH.read_text(encoding="utf-8"))
            for t, info in prev.get("tickers", {}).items():
                meta["tickers"].setdefault(t, info)
            for k, info in prev.get("indices", {}).items():
                meta["indices"].setdefault(k, info)
        except Exception as e:
            print(f"  [warn] 이전 meta.json 병합 실패: {e}")

    META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── 요약 ────────────────────────────────────
    ok = sum(1 for v in meta["tickers"].values() if "error" not in v)
    fail = len(meta["failures"])
    print()
    print(f"완료: {ok}/{len(meta['tickers'])} 종목 · 실패 {fail}건")
    print(f"메타: {META_PATH}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
