"""
실전 기간 백테스트 추출기 — 2026-04-25 이후 거래만 출력.

사용:
    python backtest/run_recent.py

전제: backtest/data/ohlcv/*.parquet 이미 존재 (01_fetch_data.py 실행 완료)
데이터 없으면 자동으로 fetch 시도.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import pandas as pd
from strategy import load_config, load_universe_ok, load_data, run_backtest, calc_metrics

PERIOD_START = pd.Timestamp("2026-04-25")

def fetch_if_missing():
    ohlcv_dir = BASE / "data" / "ohlcv"
    index_dir = BASE / "data" / "index"
    if not ohlcv_dir.exists() or not any(ohlcv_dir.glob("*.parquet")):
        print("[데이터 없음] 01_fetch_data.py 실행 중...")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(BASE / "01_fetch_data.py")],
            capture_output=False
        )
        if result.returncode != 0:
            print("[오류] 데이터 수집 실패. 01_fetch_data.py 를 먼저 실행하세요.")
            sys.exit(1)
    else:
        n = len(list(ohlcv_dir.glob("*.parquet")))
        print(f"[데이터 확인] ohlcv {n}종목 parquet 존재")

def main():
    fetch_if_missing()

    cfg = load_config()
    universe = load_universe_ok()
    print(f"[유니버스] {len(universe)}종목")

    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}일 ({all_dates[0].date()} ~ {all_dates[-1].date()})")

    print("\n[백테 실행 중...] (수십 초 소요)")
    eq, tr = run_backtest(all_dates, stock_arr, kospi_arr, cfg)

    # ── 전체 기간 ──
    m_all = calc_metrics(eq, tr)
    print(f"\n{'='*60}")
    print(f"  전체 ({all_dates[0].date()} ~ {all_dates[-1].date()})")
    print(f"{'='*60}")
    print(f"  CAGR {m_all['cagr']:+.2f}%  MDD {m_all['mdd']:.1f}%  "
          f"거래 {m_all['trades']}건  승률 {m_all['win_rate']:.1f}%")

    # ── 실전 기간 ──
    eq_p = eq.set_index("date")["equity"]
    eq_p.index = pd.to_datetime(eq_p.index)
    eq_recent = eq_p[eq_p.index >= PERIOD_START]

    tr_recent = tr[pd.to_datetime(tr["entry_date"]) >= PERIOD_START].copy()
    # 5/26 이전 청산 or final 포함
    tr_closed = tr_recent[tr_recent["reason"] != "final"]
    tr_open   = tr_recent[tr_recent["reason"] == "final"]

    period_return = (eq_recent.iloc[-1] / eq_recent.iloc[0] - 1) * 100 if len(eq_recent) >= 2 else 0

    # KOSPI 비교
    kospi_df = pd.DataFrame({"date": all_dates, "kospi": kospi_arr})
    kospi_df["date"] = pd.to_datetime(kospi_df["date"])
    kospi_df = kospi_df.set_index("date")
    kospi_recent = kospi_df["kospi"][kospi_df.index >= PERIOD_START]
    kospi_return = (kospi_recent.iloc[-1] / kospi_recent.iloc[0] - 1) * 100 if len(kospi_recent) >= 2 else 0

    print(f"\n{'='*60}")
    print(f"  실전 기간 ({PERIOD_START.date()} ~ {all_dates[-1].date()})")
    print(f"{'='*60}")
    print(f"  전략 수익률  : {period_return:+.2f}%")
    print(f"  KOSPI 수익률 : {kospi_return:+.2f}%")
    print(f"  alpha        : {period_return - kospi_return:+.2f}%p")
    print(f"  거래 (완료)  : {len(tr_closed)}건  보유 중: {len(tr_open)}건")

    # ── 거래 로그 ──
    print(f"\n{'─'*60}")
    print(f"  거래 로그 (완료 {len(tr_closed)}건)")
    print(f"{'─'*60}")
    if len(tr_closed):
        # 종목명 매핑
        name_map = {t: n for t, n in universe}
        tr_closed = tr_closed.copy()
        tr_closed["name"] = tr_closed["ticker"].map(name_map).fillna("")
        tr_closed["entry_date"] = pd.to_datetime(tr_closed["entry_date"]).dt.date
        tr_closed["exit_date"]  = pd.to_datetime(tr_closed["exit_date"]).dt.date
        tr_sorted = tr_closed.sort_values("entry_date")
        print(f"  {'진입일':<12} {'청산일':<12} {'종목':<10} {'수익률':>7} {'보유일':>5} {'사유'}")
        print(f"  {'─'*12} {'─'*12} {'─'*10} {'─'*7} {'─'*5} {'─'*10}")
        for _, row in tr_sorted.iterrows():
            print(f"  {str(row['entry_date']):<12} {str(row['exit_date']):<12} "
                  f"{row['name'][:9]:<10} {row['ret']:>+6.2f}% {row['hold_days']:>4}일 {row['reason']}")

        wins   = tr_closed[tr_closed["ret"] > 0]
        losses = tr_closed[tr_closed["ret"] <= 0]
        print(f"\n  승: {len(wins)}건  패: {len(losses)}건  "
              f"평균수익 {wins['ret'].mean():+.1f}%  평균손실 {losses['ret'].mean():+.1f}%")

    print(f"\n{'─'*60}")
    print(f"  보유 중 (5/26 종가 기준 미실현)")
    print(f"{'─'*60}")
    if len(tr_open):
        name_map = {t: n for t, n in universe}
        tr_open = tr_open.copy()
        tr_open["name"] = tr_open["ticker"].map(name_map).fillna("")
        tr_open["entry_date"] = pd.to_datetime(tr_open["entry_date"]).dt.date
        print(f"  {'진입일':<12} {'종목':<10} {'수익률(미실현)':>14}")
        for _, row in tr_open.iterrows():
            print(f"  {str(row['entry_date']):<12} {row['name'][:9]:<10} {row['ret']:>+13.2f}%")

    # ── 에쿼티 커브 저장 ──
    out = BASE / "data" / "equity_recent.csv"
    eq_recent_df = eq_recent.reset_index()
    eq_recent_df.columns = ["date", "equity"]
    eq_recent_df["kospi"] = kospi_recent.reindex(eq_recent_df["date"]).values
    eq_recent_df.to_csv(out, index=False)
    print(f"\n[저장] equity curve → {out}")

if __name__ == "__main__":
    main()
