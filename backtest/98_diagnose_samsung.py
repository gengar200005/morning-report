"""
1단계 진단: 삼성전자 parquet 의 zero/negative price + OHLC 위반 원인 파악.

출력:
  - 문제 날짜 리스트
  - 주변 몇일 가격 (액면분할 흔적 확인)
  - 검증 실패 원인 분류 (pykrx 버그 / 수정주가 불완전 / validation 과엄격)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "ohlcv"

# 진단 대상: validation fail 중 대표 종목 5개
TARGETS = [
    ("005930", "삼성전자"),
    ("247540", "에코프로"),
    ("012450", "한화에어로스페이스"),
    ("011200", "HMM"),
    ("003670", "포스코홀딩스"),
]


def diagnose(ticker: str, name: str) -> dict:
    path = DATA / f"{ticker}.parquet"
    if not path.exists():
        return {"ticker": ticker, "name": name, "error": "file missing"}

    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)

    cols = ["open", "high", "low", "close", "volume"]
    n = len(df)

    # 1) zero / negative price
    bad_rows = df[(df[cols[:-1]] <= 0).any(axis=1)]
    # 2) OHLC integrity: high < max(o,c,l) or low > min(o,c,h)
    ohlc_bad = df[
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    ]
    # 3) 극단적 가격 점프 (전일 대비 -50% 이하)
    jumps = df["close"].pct_change()
    big_drops = df[jumps < -0.3]

    return {
        "ticker": ticker,
        "name": name,
        "rows": n,
        "first": str(df.index.min().date()),
        "last": str(df.index.max().date()),
        "bad_price_count": len(bad_rows),
        "ohlc_violation_count": len(ohlc_bad),
        "big_drop_count": len(big_drops),
        "bad_price_dates": [str(d.date()) for d in bad_rows.index[:10]],
        "ohlc_violation_dates": [str(d.date()) for d in ohlc_bad.index[:10]],
        "big_drop_samples": [
            (str(d.date()), float(df.loc[d, "close"]), float(jumps.loc[d]))
            for d in big_drops.index[:5]
        ],
    }


def show_context(ticker: str, name: str, dates: list[str], days: int = 3):
    """특정 날짜 전후 시세 출력."""
    path = DATA / f"{ticker}.parquet"
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    print(f"\n--- {ticker} {name}: 문제 날짜 전후 시세 ---")
    for d_str in dates[:3]:
        d = pd.to_datetime(d_str)
        try:
            pos = df.index.get_loc(d)
        except KeyError:
            continue
        lo = max(0, pos - days)
        hi = min(len(df), pos + days + 1)
        sub = df.iloc[lo:hi][["open", "high", "low", "close", "volume"]].copy()
        print(f"\n  문제일: {d_str}")
        print(sub.to_string())


def main() -> int:
    print("=" * 60)
    print("  1단계 진단: validation fail 대표 5종목")
    print("=" * 60)

    results = []
    for ticker, name in TARGETS:
        r = diagnose(ticker, name)
        results.append(r)
        print(f"\n[{ticker} {name}]")
        if "error" in r:
            print(f"  {r['error']}")
            continue
        print(f"  rows={r['rows']} period={r['first']} ~ {r['last']}")
        print(f"  zero/neg price: {r['bad_price_count']}건 → {r['bad_price_dates']}")
        print(f"  OHLC 위반    : {r['ohlc_violation_count']}건 → {r['ohlc_violation_dates']}")
        print(f"  -30% 이상 급락: {r['big_drop_count']}건")
        for d, c, p in r["big_drop_samples"]:
            print(f"    {d}  close={c:,.0f}  change={p:+.1%}")

    # 삼성전자 + 에코프로는 문제 날짜 전후 시세도 표시
    for ticker, name in [("005930", "삼성전자"), ("247540", "에코프로")]:
        r = next((x for x in results if x["ticker"] == ticker), None)
        if r and r.get("bad_price_dates"):
            show_context(ticker, name, r["bad_price_dates"])

    # 판정
    print("\n" + "=" * 60)
    print("  판정")
    print("=" * 60)
    for r in results:
        if "error" in r:
            continue
        total_bad = r["bad_price_count"] + r["ohlc_violation_count"]
        pct = total_bad / r["rows"] * 100
        verdict = "치명적" if pct > 5 else ("경미" if pct > 0 else "정상")
        print(f"  {r['ticker']} {r['name']:20s} "
              f"위반 {total_bad}건 / {r['rows']}행 = {pct:.2f}% [{verdict}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
