"""
잔존 OHLC 위반 원인 파악. 거래정지일 아닌데 왜 위반?
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parent / "data" / "ohlcv"

TARGETS = ["005930", "247540", "068270", "003690", "128940"]

for tk in TARGETS:
    df = pd.read_parquet(DATA / f"{tk}.parquet")
    df.index = pd.to_datetime(df.index)

    # 거래정지 제외
    halt = (df["volume"] == 0) & (df["open"] == 0)
    dft = df[~halt]
    oc_min = dft[["open", "close"]].min(axis=1)
    oc_max = dft[["open", "close"]].max(axis=1)
    viol = dft[(dft["low"] > oc_min) | (dft["high"] < oc_max)
               | (dft["low"] > dft["high"])]
    print(f"\n=== {tk}: {len(viol)} violations ===")
    for d in viol.index[:5]:
        row = df.loc[d]
        print(f"  {d.date()} o={row['open']:.0f} h={row['high']:.0f} "
              f"l={row['low']:.0f} c={row['close']:.0f} v={row['volume']:.0f}")
