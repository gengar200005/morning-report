"""
Step 6: Phase 3 백테스트 데이터 무결성 검증.

Step 5에서 수집한 backtest/data/ohlcv/*.parquet 과 backtest/data/index/*.parquet
의 품질을 읽기 전용으로 점검한다. 데이터는 건드리지 않는다.

사용:
    python backtest/02_validate_data.py
    python backtest/02_validate_data.py --min-rows 500     # 과소 데이터 기준
    python backtest/02_validate_data.py --gap-days 7       # 누락 구간 임계

검증 항목:
    1. 파일 커버리지 — universe 164 종목 Parquet 존재 여부
    2. 행 수 분포    — 평균/최소/최대 + 과소 종목 flag
    3. 결측/이상치  — NaN, 0 이하 가격, 음수 volume
    4. OHLC 정합성  — low ≤ min(o,c), max(o,c) ≤ high 위반
    5. 날짜 연속성  — 영업일 기준 N일 이상 gap 탐지
    6. 지수 sanity  — KOSPI/KOSDAQ 행 수 + change_pct 분포

출력:
    콘솔 요약 (정상/경고/치명)
    backtest/data/validation_report.json (상세)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe import UNIVERSE, INDICES  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OHLCV_DIR = DATA_DIR / "ohlcv"
INDEX_DIR = DATA_DIR / "index"
REPORT_PATH = DATA_DIR / "validation_report.json"


@dataclass
class TickerCheck:
    ticker: str
    name: str
    status: str = "ok"            # ok / warn / fail / missing
    rows: int = 0
    first: str | None = None
    last: str | None = None
    issues: list[str] = field(default_factory=list)
    nan_count: int = 0
    zero_or_neg_price: int = 0
    neg_volume: int = 0
    ohlc_violations: int = 0
    halt_days: int = 0            # 거래정지일 (volume=0 + price=0) — 제외 후 집계
    max_gap_days: int = 0
    gap_periods: list[tuple[str, str, int]] = field(default_factory=list)


def load_parquet_safe(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def check_ticker(ticker: str, name: str, path: Path,
                 min_rows: int, gap_days: int) -> TickerCheck:
    c = TickerCheck(ticker=ticker, name=name)

    if not path.exists():
        c.status = "missing"
        c.issues.append("parquet file not found")
        return c

    df = load_parquet_safe(path)
    if df is None:
        c.status = "fail"
        c.issues.append("parquet read error")
        return c

    c.rows = len(df)
    if c.rows > 0:
        c.first = str(df.index.min().date())
        c.last = str(df.index.max().date())

    # 2. 행 수
    if c.rows == 0:
        c.status = "fail"
        c.issues.append("empty dataframe")
        return c
    if c.rows < min_rows:
        c.status = "warn"
        c.issues.append(f"low row count ({c.rows} < {min_rows})")

    # 3. 결측/이상치
    price_cols = [col for col in ["open", "high", "low", "close"] if col in df.columns]

    c.nan_count = int(df[price_cols].isna().sum().sum())
    if c.nan_count > 0:
        c.status = "warn" if c.status == "ok" else c.status
        c.issues.append(f"NaN in OHLC: {c.nan_count}")

    # 거래정지일 마스크: volume=0 이고 open=0 (pykrx 거래정지일 표기 방식)
    # — 액면분할/인적분할/관리종목 거래정지 등은 정상적 시장 이벤트이므로
    #   "데이터 품질 이슈"가 아님. 별도 집계 후 zero/neg + OHLC 위반에서 제외.
    if "volume" in df.columns and "open" in df.columns:
        halt_mask = (df["volume"] == 0) & (df["open"] == 0)
    else:
        halt_mask = pd.Series(False, index=df.index)
    c.halt_days = int(halt_mask.sum())

    # 거래정지일 제외 후 zero/neg price 집계
    df_trading = df[~halt_mask]
    c.zero_or_neg_price = int((df_trading[price_cols] <= 0).sum().sum())
    if c.zero_or_neg_price > 0:
        c.status = "fail"
        c.issues.append(f"zero/negative price: {c.zero_or_neg_price}")

    if "volume" in df.columns:
        c.neg_volume = int((df["volume"] < 0).sum())
        if c.neg_volume > 0:
            c.status = "fail"
            c.issues.append(f"negative volume: {c.neg_volume}")

    # 4. OHLC 정합성 (거래정지일 제외)
    # pykrx 수정주가 계산 시 close/high 간 1~6원 라운딩 편차(~0.03%)가 흔함.
    # 0.1% 톨러런스 적용: |차이| > 0.1% 일 때만 실제 위반으로 간주.
    TOL = 0.001
    if all(col in df.columns for col in ["open", "high", "low", "close"]):
        oc_min = df_trading[["open", "close"]].min(axis=1)
        oc_max = df_trading[["open", "close"]].max(axis=1)
        # low가 min(o,c) 보다 TOL 이상 큰 경우만 위반
        low_viol = df_trading["low"] > oc_min * (1 + TOL)
        # high가 max(o,c) 보다 TOL 이상 작은 경우만 위반
        high_viol = df_trading["high"] < oc_max * (1 - TOL)
        # low > high (비정상)
        lh_viol = df_trading["low"] > df_trading["high"] * (1 + TOL)
        violations = (low_viol | high_viol | lh_viol).sum()
        c.ohlc_violations = int(violations)
        if violations > 0:
            c.status = "fail"
            c.issues.append(f"OHLC integrity violations: {violations}")

    # 거래정지일 기록 (정보용, fail 처리 X)
    if c.halt_days > 0:
        c.issues.append(f"trading halts (excluded): {c.halt_days}")

    # 5. 날짜 연속성 (영업일 기준 gap)
    if c.rows > 1:
        dates = df.index.sort_values()
        bdays_between = pd.Series(dates).diff().dt.days.fillna(0)
        # 영업일 환산 근사: 달력일 기준 gap_days 초과를 flag (주말 포함)
        # 주말 2일 + 공휴일 감안해서 임계를 넉넉히 볼 것
        mask = bdays_between > gap_days
        if mask.any():
            max_gap = int(bdays_between.max())
            c.max_gap_days = max_gap
            # 상위 3개 gap만 기록
            gap_idx = bdays_between[mask].nlargest(3).index
            for i in gap_idx:
                prev_date = str(dates[i - 1].date())
                curr_date = str(dates[i].date())
                gap = int(bdays_between.iloc[i])
                c.gap_periods.append((prev_date, curr_date, gap))
            if max_gap > gap_days * 3:  # 아주 긴 gap만 warn
                c.status = "warn" if c.status == "ok" else c.status
                c.issues.append(f"long gap: {max_gap} days (max)")

    return c


def check_index(name: str, code: str, path: Path) -> dict:
    result = {
        "name": name, "code": code, "status": "ok",
        "rows": 0, "issues": [],
    }
    if not path.exists():
        result["status"] = "missing"
        result["issues"].append("parquet not found")
        return result

    df = load_parquet_safe(path)
    if df is None or df.empty:
        result["status"] = "fail"
        result["issues"].append("empty or unreadable")
        return result

    result["rows"] = len(df)
    result["first"] = str(df.index.min().date())
    result["last"] = str(df.index.max().date())

    # change_pct 분포 sanity check
    if "change_pct" in df.columns:
        cp = df["change_pct"]
        result["change_pct_stats"] = {
            "mean": round(float(cp.mean()), 4),
            "std": round(float(cp.std()), 4),
            "min": round(float(cp.min()), 4),
            "max": round(float(cp.max()), 4),
        }
        # 지수가 하루에 ±15% 넘게 움직이면 이상
        extreme = int((cp.abs() > 15).sum())
        if extreme > 0:
            result["status"] = "warn"
            result["issues"].append(f"extreme daily move (>15%): {extreme} days")

    # volume=0 행 (DATA_NOTES.md에 알려진 이슈)
    if "volume" in df.columns:
        zero_vol = int((df["volume"] == 0).sum())
        result["volume_zero_rows"] = zero_vol
        if zero_vol > 5:  # DATA_NOTES는 2건까지만 언급 → 5초과면 조사
            result["status"] = "warn" if result["status"] == "ok" else result["status"]
            result["issues"].append(f"unexpected volume=0 rows: {zero_vol}")

    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rows", type=int, default=500,
                    help="이 행 수 미만이면 warn (기본 500 ≈ 2년)")
    ap.add_argument("--gap-days", type=int, default=7,
                    help="이 일수 초과 gap부터 기록 (기본 7)")
    ap.add_argument("--verbose", action="store_true",
                    help="모든 종목 상세 출력")
    args = ap.parse_args()

    if not OHLCV_DIR.exists():
        print(f"[error] {OHLCV_DIR} 없음. Step 5를 먼저 실행하세요.")
        return 1

    print(f"[검증] {len(UNIVERSE)} 종목 + {len(INDICES)} 지수")
    print(f"[기준] min_rows={args.min_rows}, gap_days={args.gap_days}\n")

    # 1) 종목 검증
    ticker_results: list[TickerCheck] = []
    for ticker, name in UNIVERSE:
        path = OHLCV_DIR / f"{ticker}.parquet"
        ticker_results.append(
            check_ticker(ticker, name, path, args.min_rows, args.gap_days)
        )

    # 2) 지수 검증
    index_results = []
    for name, code in INDICES.items():
        path = INDEX_DIR / f"{name}.parquet"
        index_results.append(check_index(name, code, path))

    # ── 집계 ────────────────────────────────────
    ok = [t for t in ticker_results if t.status == "ok"]
    warn = [t for t in ticker_results if t.status == "warn"]
    fail = [t for t in ticker_results if t.status == "fail"]
    missing = [t for t in ticker_results if t.status == "missing"]

    # 행 수 분포 (정상 + 경고 기준)
    valid_rows = [t.rows for t in ticker_results if t.rows > 0]
    row_stats = {}
    if valid_rows:
        s = pd.Series(valid_rows)
        row_stats = {
            "count": len(valid_rows),
            "min": int(s.min()),
            "p25": int(s.quantile(0.25)),
            "median": int(s.median()),
            "p75": int(s.quantile(0.75)),
            "max": int(s.max()),
            "mean": round(float(s.mean()), 1),
        }

    # ── 콘솔 리포트 ──────────────────────────────
    print("=" * 60)
    print(f"종목 검증 결과 ({len(ticker_results)}개)")
    print("=" * 60)
    print(f"  ✅ 정상(ok):    {len(ok)}")
    print(f"  ⚠️  경고(warn):  {len(warn)}")
    print(f"  ❌ 실패(fail):  {len(fail)}")
    print(f"  ❓ 파일없음:    {len(missing)}")
    if row_stats:
        print(f"\n행 수 분포: min={row_stats['min']} · median={row_stats['median']} "
              f"· max={row_stats['max']} · mean={row_stats['mean']}")

    if warn:
        print("\n[경고 상세]")
        for t in warn[:20]:
            print(f"  - {t.ticker} {t.name:12s} rows={t.rows} :: {'; '.join(t.issues)}")
        if len(warn) > 20:
            print(f"  ... 외 {len(warn)-20}건 (report.json 참조)")

    if fail:
        print("\n[실패 상세]")
        for t in fail:
            print(f"  - {t.ticker} {t.name:12s} rows={t.rows} :: {'; '.join(t.issues)}")

    if missing:
        print("\n[파일 없음]")
        for t in missing:
            print(f"  - {t.ticker} {t.name}")

    print("\n" + "=" * 60)
    print(f"지수 검증 결과 ({len(index_results)}개)")
    print("=" * 60)
    for r in index_results:
        status_icon = {"ok": "✅", "warn": "⚠️", "fail": "❌", "missing": "❓"}[r["status"]]
        print(f"  {status_icon} {r['name']:7s} ({r['code']:6s})  "
              f"rows={r.get('rows', 0)}  {r.get('first', '')} ~ {r.get('last', '')}")
        if r.get("change_pct_stats"):
            s = r["change_pct_stats"]
            print(f"     change_pct: mean={s['mean']:+.3f}%  std={s['std']:.3f}  "
                  f"range=[{s['min']:+.2f}%, {s['max']:+.2f}%]")
        if r.get("volume_zero_rows") is not None:
            print(f"     volume=0 rows: {r['volume_zero_rows']}")
        if r["issues"]:
            for issue in r["issues"]:
                print(f"     ⚠ {issue}")

    # ── JSON 리포트 저장 ─────────────────────────
    report = {
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "criteria": {
            "min_rows": args.min_rows,
            "gap_days": args.gap_days,
        },
        "summary": {
            "total_tickers": len(ticker_results),
            "ok": len(ok),
            "warn": len(warn),
            "fail": len(fail),
            "missing": len(missing),
            "row_stats": row_stats,
        },
        "tickers": [asdict(t) for t in ticker_results],
        "indices": index_results,
    }

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n리포트 저장: {REPORT_PATH}")

    # 종료 코드: fail/missing 있으면 2, warn만 있으면 1, 정상이면 0
    if fail or missing:
        return 2
    if warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
