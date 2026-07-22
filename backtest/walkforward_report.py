#!/usr/bin/env python3
"""
walkforward_report.py — v6 Phase 3 워크포워드 검증 리포트

전체 백테스트가 뱉은 트레이드 로그(CSV)를 입력으로 받아 3가지를 계산한다:

  [1] 연도별 분할 성과   : 연도별 승률·손익비·기대값·MDD (성과의 흔들림 = 추정 오차의 크기)
  [2] 앵커드 워크포워드  : 매년 T에 대해 "T 이전 데이터만으로 추정한 승률" vs "T년 실제 승률"
                          → (추정 − 실현) 오차 분포가 곧 '백테스트 승률에서 깎아야 할 폭'
  [3] 홀드아웃 비교      : 규칙 설계에 참고하지 않은 구간을 별도 채점 (설계 편향 방어)

v6는 파라미터 고정 시스템이므로 창별 재최적화 없는 앵커드(누적) 방식을 쓴다.

사용법:
  python backtest/strategy.py            # → backtest/results/trades.csv 생성
  python backtest/walkforward_report.py --trades backtest/results/trades.csv \
      --holdout-start 2014-01-01 --holdout-end 2017-12-31

입력 CSV 필수 컬럼 (컬럼명이 다르면 --col-* 옵션으로 매핑):
  entry_date, exit_date, ticker, ret
  * 수익률은 소수(0.18) 또는 퍼센트(18.0) 모두 자동 인식
  * strategy.py 트레이드 로그(ret, 퍼센트)가 기본값과 일치. 외부 CSV가
    return_pct 등 다른 이름을 쓰면 --col-ret return_pct 로 매핑.

출력:
  콘솔 리포트 + backtest/results/wf_yearly.csv, wf_anchored.csv, wf_holdout.csv
  (backtest/data/ 및 기존 파이프라인 파일은 건드리지 않음)
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────

def load_trades(path: str, col_entry: str, col_exit: str, col_ret: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in (col_entry, col_exit, col_ret) if c not in df.columns]
    if missing:
        sys.exit(f"[에러] 컬럼 없음: {missing} / 실제 컬럼: {list(df.columns)}\n"
                 f"      --col-entry / --col-exit / --col-ret 옵션으로 매핑하세요.")

    df = df.rename(columns={col_entry: "entry_date", col_exit: "exit_date", col_ret: "ret"})
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])

    # 퍼센트/소수 자동 인식: 절대값 중앙값이 1.5 초과면 퍼센트로 간주
    if df["ret"].abs().median() > 1.5:
        df["ret"] = df["ret"] / 100.0

    df = df.sort_values("exit_date").reset_index(drop=True)
    df["exit_year"] = df["exit_date"].dt.year
    return df


def max_drawdown(returns: pd.Series) -> float:
    """트레이드 순차 복리 기준 근사 MDD (자본 100% 단일 포지션 가정)."""
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    return float(dd.min()) if len(dd) else np.nan


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return dict(n=0, win_rate=np.nan, avg_win=np.nan, avg_loss=np.nan,
                    payoff=np.nan, expectancy=np.nan, mdd=np.nan)
    wins = df[df["ret"] > 0]["ret"]
    losses = df[df["ret"] <= 0]["ret"]
    win_rate = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else np.nan
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    return dict(n=n, win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
                payoff=payoff, expectancy=expectancy, mdd=max_drawdown(df["ret"]))


def kelly(win_rate: float, payoff: float) -> float:
    """켈리 비중 f* = p − (1−p)/b. 음수면 0."""
    if not np.isfinite(payoff) or payoff <= 0:
        return np.nan
    f = win_rate - (1 - win_rate) / payoff
    return max(f, 0.0)


def fmt_row(d: dict) -> dict:
    return {
        "N": d["n"],
        "승률": f"{d['win_rate']*100:.1f}%" if np.isfinite(d["win_rate"]) else "-",
        "평균수익": f"{d['avg_win']*100:+.2f}%" if np.isfinite(d["avg_win"]) else "-",
        "평균손실": f"{d['avg_loss']*100:+.2f}%" if np.isfinite(d["avg_loss"]) else "-",
        "손익비": f"{d['payoff']:.2f}" if np.isfinite(d["payoff"]) else "-",
        "기대값": f"{d['expectancy']*100:+.2f}%" if np.isfinite(d["expectancy"]) else "-",
        "MDD": f"{d['mdd']*100:.1f}%" if np.isfinite(d["mdd"]) else "-",
    }


# ──────────────────────────────────────────────────────────────
# [1] 연도별 분할
# ──────────────────────────────────────────────────────────────

def yearly_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in df.groupby("exit_year"):
        rows.append({"연도": year, **fmt_row(stats(g))})
    rows.append({"연도": "전체", **fmt_row(stats(df))})
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# [2] 앵커드 워크포워드: T 이전 누적으로 추정 → T년 실현과 비교
# ──────────────────────────────────────────────────────────────

def anchored_walkforward(df: pd.DataFrame, min_train_years: int, min_train_trades: int) -> pd.DataFrame:
    years = sorted(df["exit_year"].unique())
    rows = []
    for year in years:
        train = df[df["exit_year"] < year]
        test = df[df["exit_year"] == year]
        if train["exit_year"].nunique() < min_train_years or len(train) < min_train_trades:
            continue  # 훈련 표본 부족 → 스킵
        s_tr, s_te = stats(train), stats(test)
        rows.append({
            "검증연도": year,
            "훈련N": s_tr["n"],
            "추정승률": s_tr["win_rate"],
            "실현승률": s_te["win_rate"],
            "승률오차(추정-실현)": s_tr["win_rate"] - s_te["win_rate"],
            "추정손익비": s_tr["payoff"],
            "실현손익비": s_te["payoff"],
            "검증N": s_te["n"],
            "훈련기준_켈리": kelly(s_tr["win_rate"], s_tr["payoff"]),
            "실현기대값": s_te["expectancy"],
        })
    return pd.DataFrame(rows)


def summarize_wf(wf: pd.DataFrame) -> str:
    if wf.empty:
        return "워크포워드 계산 불가 (훈련 표본 부족). --min-train-years / --min-train-trades 를 낮춰보세요."
    err = wf["승률오차(추정-실현)"]
    lines = [
        f"검증 구간 수          : {len(wf)}개 연도",
        f"승률 오차 평균         : {err.mean()*100:+.1f}%p  (양수 = 백테스트가 실전보다 후하게 나옴)",
        f"승률 오차 표준편차      : {err.std()*100:.1f}%p",
        f"승률 오차 최악(과대추정) : {err.max()*100:+.1f}%p",
        "",
        f"→ 실전용 보수적 승률 제안: [전체 백테스트 승률] − {max(err.mean() + err.std(), 0)*100:.1f}%p (평균오차+1σ 차감)",
        f"→ 비중 산정 시 위 보수 승률로 켈리 계산 후 1/2 이하 적용 권장",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# [3] 홀드아웃 비교
# ──────────────────────────────────────────────────────────────

def holdout_report(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    start, end = pd.to_datetime(start), pd.to_datetime(end)
    mask = (df["exit_date"] >= start) & (df["exit_date"] <= end)
    rows = [
        {"구간": f"홀드아웃 ({start.date()}~{end.date()})", **fmt_row(stats(df[mask]))},
        {"구간": "나머지 전체", **fmt_row(stats(df[~mask]))},
    ]
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="v6 Phase 3 워크포워드 검증 리포트")
    ap.add_argument("--trades", default="backtest/results/trades.csv", help="트레이드 로그 CSV 경로")
    ap.add_argument("--col-entry", default="entry_date")
    ap.add_argument("--col-exit", default="exit_date")
    ap.add_argument("--col-ret", default="ret")
    ap.add_argument("--holdout-start", default=None, help="홀드아웃 시작일 (예: 2014-01-01)")
    ap.add_argument("--holdout-end", default=None, help="홀드아웃 종료일 (예: 2017-12-31)")
    ap.add_argument("--min-train-years", type=int, default=3, help="워크포워드 최소 훈련 연수")
    ap.add_argument("--min-train-trades", type=int, default=30, help="워크포워드 최소 훈련 트레이드 수")
    ap.add_argument("--outdir", default=None, help="결과 CSV 저장 폴더 (기본: 입력 CSV와 같은 폴더)")
    args = ap.parse_args()

    df = load_trades(args.trades, args.col_entry, args.col_exit, args.col_ret)
    outdir = Path(args.outdir) if args.outdir else Path(args.trades).parent
    outdir.mkdir(parents=True, exist_ok=True)

    pd.set_option("display.unicode.east_asian_width", True)

    print("=" * 70)
    print("[1] 연도별 분할 성과")
    print("=" * 70)
    yr = yearly_report(df)
    print(yr.to_string(index=False))
    yr.to_csv(outdir / "wf_yearly.csv", index=False, encoding="utf-8-sig")

    print()
    print("=" * 70)
    print("[2] 앵커드 워크포워드 (T 이전 누적 추정 vs T년 실현)")
    print("=" * 70)
    wf = anchored_walkforward(df, args.min_train_years, args.min_train_trades)
    if not wf.empty:
        disp = wf.copy()
        for c in ["추정승률", "실현승률", "승률오차(추정-실현)", "훈련기준_켈리", "실현기대값"]:
            disp[c] = (disp[c] * 100).round(1).astype(str) + "%"
        for c in ["추정손익비", "실현손익비"]:
            disp[c] = disp[c].round(2)
        print(disp.to_string(index=False))
    print()
    print(summarize_wf(wf))
    wf.to_csv(outdir / "wf_anchored.csv", index=False, encoding="utf-8-sig")

    if args.holdout_start and args.holdout_end:
        print()
        print("=" * 70)
        print("[3] 홀드아웃 비교 (설계에 참고하지 않은 구간)")
        print("=" * 70)
        ho = holdout_report(df, args.holdout_start, args.holdout_end)
        print(ho.to_string(index=False))
        ho.to_csv(outdir / "wf_holdout.csv", index=False, encoding="utf-8-sig")

    print()
    print(f"[완료] 결과 저장: {outdir}/wf_yearly.csv, wf_anchored.csv" +
          (", wf_holdout.csv" if args.holdout_start else ""))


if __name__ == "__main__":
    main()
