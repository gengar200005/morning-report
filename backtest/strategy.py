"""
Phase 3 확정 전략 모듈 — 진실의 원천 (single source of truth).

백테(99_*.py) 와 실시간 스크리닝(kr_report.py) 양쪽이 이 모듈을 import 하여
시그널 로직·리스크 관리를 공유한다. 파라미터는 strategy_config.yaml.

사용:
    from strategy import load_config, check_signal, run_backtest

    cfg = load_config()                       # strategy_config.yaml 로드
    ok  = check_signal(closes, volumes, i, rs_pct, cfg)
    eq, trades = run_backtest(dates, stock_arr, kospi_arr, cfg)
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "strategy_config.yaml"
VALIDATION_REPORT = DATA_DIR / "validation_report.json"
OHLCV_DIR = DATA_DIR / "ohlcv"
INDEX_DIR = DATA_DIR / "index"


# ══════════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════════
def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """strategy_config.yaml 로드. 경로 미지정 시 기본 위치."""
    p = Path(path) if path else CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ══════════════════════════════════════════════════════════════════
#  Signal
# ══════════════════════════════════════════════════════════════════
def check_minervini_detailed(c: np.ndarray, i: int, cfg: dict) -> dict:
    """Minervini 8조건 + 지표값 상세 반환 (라이브 리포트에서 개별 표시용).

    Returns dict with:
      - conds: list[bool] of 8 conditions (c1-c8)
      - core_ok: all(conds)
      - aligned: all(c1-c5)       # MA 정배열 여부
      - ma200_up: c6              # MA200 상승 여부
      - win52_ok: c7 and c8       # 52주 범위 조건
      - ma50, ma150, ma200, ma200_prev, hi52, lo52, cur: 지표값
    """
    sig = cfg["signal"]["minervini"]
    lookback = sig["lookback_52w"]
    if i < lookback or c[i - lookback] <= 0:
        return {"core_ok": False, "conds": [False]*8,
                "aligned": False, "ma200_up": False, "win52_ok": False,
                "ma50": None, "ma150": None, "ma200": None,
                "ma200_prev": None, "hi52": None, "lo52": None, "cur": c[i]}

    cur = c[i]
    ma50 = c[i-50:i].mean()
    ma150 = c[i-150:i].mean()
    ma200 = c[i-200:i].mean()
    accel_days = sig["trend_acceleration_days"]
    ma200_prev = c[i-lookback:i-accel_days].mean()
    hi52 = c[max(0, i-lookback):i].max()
    lo52 = c[max(0, i-lookback):i].min()

    conds = [
        cur > ma50, cur > ma150, cur > ma200,
        ma50 > ma150, ma150 > ma200,
        ma200 > ma200_prev,
        cur >= lo52 * sig["lo52_threshold"],
        cur >= hi52 * sig["hi52_threshold"],
    ]
    return {
        "core_ok": all(conds),
        "conds": conds,
        "aligned": all(conds[:5]),
        "ma200_up": conds[5],
        "win52_ok": conds[6] and conds[7],
        "ma50": ma50, "ma150": ma150, "ma200": ma200,
        "ma200_prev": ma200_prev,
        "hi52": hi52, "lo52": lo52, "cur": cur,
    }


def check_minervini_core(c: np.ndarray, i: int, cfg: dict) -> bool:
    """Minervini 트렌드 템플릿 8조건 (RS 제외 — 별도 판정). 불린만 반환."""
    return check_minervini_detailed(c, i, cfg)["core_ok"]


def check_supply(v: np.ndarray, c: np.ndarray, i: int, cfg: dict) -> bool:
    """수급 프록시: 최근 20일 up/down volume 비율."""
    supply = cfg["signal"]["supply"]
    lookback = supply["lookback_days"]
    if i < lookback + 1:
        return False
    up_vol, dn_vol = 0.0, 0.0
    for j in range(i - lookback, i):
        if c[j] > c[j-1]:
            up_vol += v[j]
        else:
            dn_vol += v[j]
    ratio = up_vol / dn_vol if dn_vol > 0 else 999.0
    return ratio >= supply["ratio_min"]


def check_market_gate(kospi_arr: np.ndarray, i: int, cfg: dict) -> bool:
    """시장 게이트: KOSPI close > MA{N}."""
    ma_n = cfg["signal"]["market_gate"]["kospi_ma"]
    if i < ma_n:
        return False
    return kospi_arr[i] > kospi_arr[i-ma_n:i].mean()


def check_signal(c: np.ndarray, v: np.ndarray, i: int,
                 rs_pct: float | None, cfg: dict) -> bool:
    """전체 시그널: Minervini + 수급 + RS. 시장 게이트는 엔진에서 별도 적용."""
    if not check_minervini_core(c, i, cfg):
        return False
    rs_min = cfg["signal"]["minervini"]["rs_min"]
    if rs_pct is not None and rs_pct < rs_min:
        return False
    return check_supply(v, c, i, cfg)


# ══════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════
def load_universe_ok() -> list[tuple[str, str]]:
    """validation_report.json 에서 status='ok' 만 추출."""
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    return [(t["ticker"], t["name"]) for t in report["tickers"]
            if t["status"] == "ok"]


def load_data(universe: list[tuple[str, str]]):
    """KOSPI 날짜 기준으로 종목 OHLCV 정렬."""
    kospi = pd.read_parquet(INDEX_DIR / "kospi.parquet")
    kospi.index = pd.to_datetime(kospi.index)
    all_dates = sorted(kospi.index)
    idx = pd.DatetimeIndex(all_dates)
    kospi_arr = (kospi["close"].reindex(idx).ffill()
                 .values.astype(float))

    stock_arr = {}
    # intraday stop 시뮬용 high/low — stock_arr 튜플 구조는 변경 없이 별도 dict.
    # close 모드에서는 미사용, intraday 모드에서만 참조 → close 모드 결과 byte-exact 보존.
    _INTRADAY_DATA.clear()
    for ticker, _name in universe:
        path = OHLCV_DIR / f"{ticker}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        c = df["close"].reindex(idx).ffill().fillna(0).values.astype(float)
        o = df["open"].reindex(idx).ffill().fillna(0).values.astype(float)
        v = df["volume"].reindex(idx).ffill().fillna(0).values.astype(float)
        stock_arr[ticker] = (c, o, v)
        if "high" in df.columns and "low" in df.columns:
            h = df["high"].reindex(idx).ffill().fillna(0).values.astype(float)
            lo = df["low"].reindex(idx).ffill().fillna(0).values.astype(float)
            _INTRADAY_DATA[ticker] = (h, lo)
    return all_dates, stock_arr, kospi_arr


# intraday stop 시뮬을 위한 high/low 시계열 (load_data 에서 채움).
_INTRADAY_DATA: dict[str, tuple[np.ndarray, np.ndarray]] = {}


# ══════════════════════════════════════════════════════════════════
#  Sector gate (ADR-004)
# ══════════════════════════════════════════════════════════════════
_REPO_ROOT = BASE_DIR.parent
_SECTOR_MAP_PATH = DATA_DIR / "sector" / "sector_map.parquet"
_SECTOR_OVERRIDES_PATH = _REPO_ROOT / "reports" / "sector_overrides.yaml"


def _build_stocks_daily_long(all_dates, stock_arr) -> pd.DataFrame:
    """stock_arr dict → sector_breadth 가 기대하는 long format DataFrame.

    Columns: [날짜, ticker, 종가]. close <= 0 인 행은 제외 (상장 전/정지일).
    """
    dates = pd.to_datetime(all_dates)
    frames = []
    for ticker, (c, _o, _v) in stock_arr.items():
        mask = c > 0
        if not mask.any():
            continue
        frames.append(pd.DataFrame({
            "날짜": dates[mask],
            "ticker": ticker,
            "종가": c[mask],
        }))
    if not frames:
        return pd.DataFrame(columns=["날짜", "ticker", "종가"])
    return (pd.concat(frames, ignore_index=True)
            .sort_values(["ticker", "날짜"])
            .reset_index(drop=True))


def precompute_sector_tiers(all_dates, stock_arr, cfg) -> dict[int, dict[str, str]]:
    """날짜 인덱스별 {ticker: grade} 사전계산.

    성능: recompute_every 거래일마다 compute_sector_scores 재계산, 중간 날짜는
    직전 등급 재사용. grade ∈ {"주도", "강세", "중립", "약세", "N/A"}.

    룩어헤드 방지: day i 의 게이트 판정은 all_dates[i-1] 종가까지만 사용.
    """
    import sys as _sys
    if str(_REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(_REPO_ROOT))
    import sector_breadth as sb  # noqa: E402

    gate = cfg.get("signal", {}).get("sector_gate", {})
    if not gate.get("enabled", False):
        return {}

    recompute_every = int(gate.get("recompute_every", 5))
    warmup = cfg["execution"]["warmup_days"]

    sm = sb.load_sector_map(_SECTOR_MAP_PATH)
    overrides = sb.load_overrides(_SECTOR_OVERRIDES_PATH)
    sm = sb.apply_ticker_overrides(sm, overrides)
    ticker_to_sector = dict(zip(sm["ticker"].astype(str).str.zfill(6),
                                 sm["sector"]))

    stocks_long = _build_stocks_daily_long(all_dates, stock_arr)

    n = len(all_dates)
    cache: dict[int, dict[str, str]] = {}
    last: dict[str, str] = {}
    computed = 0
    for i in range(warmup, n):
        if (i - warmup) % recompute_every == 0:
            end_date = all_dates[i - 1]
            try:
                scores = sb.compute_sector_scores(
                    sector_map=sm, stocks_daily=stocks_long, end_date=end_date,
                )
                sector_grade = scores["grade"].to_dict()
                last = {t: sector_grade.get(s, "N/A")
                        for t, s in ticker_to_sector.items()}
                computed += 1
            except Exception as e:
                # compute 실패 시 직전 결과 유지
                if computed == 0:
                    last = {t: "N/A" for t in ticker_to_sector}
        cache[i] = last
    return cache


def check_sector_gate(ticker: str, i: int,
                      tier_cache: dict[int, dict[str, str]],
                      cfg: dict) -> bool:
    """섹터 게이트 통과 여부.

    - enabled=False → 항상 True (baseline)
    - ticker 매핑 없음 → N/A 정책 적용
    - 섹터 등급이 tiers 에 있으면 True, 아니면 False
    """
    gate = cfg.get("signal", {}).get("sector_gate", {})
    if not gate.get("enabled", False):
        return True
    tk = str(ticker).zfill(6)
    grade = tier_cache.get(i, {}).get(tk, "N/A")
    if grade == "N/A":
        return gate.get("fallback_on_na", "pass") == "pass"
    return grade in gate.get("tiers", ["주도", "강세"])


# ══════════════════════════════════════════════════════════════════
#  Backtest engine
# ══════════════════════════════════════════════════════════════════
def run_backtest(all_dates, stock_arr, kospi_arr, cfg: dict,
                 trail_stop: float | None = None,
                 cooldown: int | None = None,
                 stop_loss: float | None = None,
                 sector_tier_cache: dict | None = None):
    """
    config 기반 포트폴리오 백테. trail_stop/cooldown/stop_loss 파라미터는
    그리드 스윕용 오버라이드 — None 이면 cfg 값 사용.

    sector_tier_cache: precompute_sector_tiers 결과. None 이면 cfg 에서
        sector_gate.enabled=True 일 때 자동 계산. enabled=False 면 무시.

    Returns:
        (equity_df, trades_df)
    """
    risk = cfg["risk"]
    exec_cfg = cfg["execution"]
    sl = stop_loss if stop_loss is not None else risk["stop_loss"]
    ts = trail_stop if trail_stop is not None else risk["trail_stop"]
    cd = cooldown if cooldown is not None else cfg["cooldown_days"]
    cost = exec_cfg["cost_one_way"]
    max_hold = risk["max_hold_days"]
    max_pos = risk["max_positions"]
    warmup = exec_cfg["warmup_days"]
    stop_trigger = risk.get("stop_trigger", "close")  # "close" | "intraday"
    intraday_slip_extra = risk.get("intraday_extra_slippage", 0.0)

    gate_enabled = cfg.get("signal", {}).get("sector_gate", {}).get("enabled", False)
    if gate_enabled and sector_tier_cache is None:
        sector_tier_cache = precompute_sector_tiers(all_dates, stock_arr, cfg)
    elif not gate_enabled:
        sector_tier_cache = {}

    n_days = len(all_dates)
    cash = 1.0
    positions: dict[str, dict] = {}
    pending_entry: list[tuple[str, int]] = []
    pending_exit: list[tuple[str, str]] = []
    equity_curve: list[dict] = []
    trade_log: list[dict] = []
    last_exit_i: dict[str, int] = {}

    for i in range(warmup, n_days):
        # 1) 어제 신호 → 오늘 시가 entry
        for tk, _sig_i in pending_entry:
            if tk in positions:
                continue
            c, o, v = stock_arr[tk]
            if i >= len(o) or o[i] <= 0:
                continue
            open_slots = max_pos - len(positions)
            if open_slots <= 0:
                break
            entry_price = o[i] * (1 + cost)
            alloc = cash / open_slots
            if alloc <= 0:
                break
            shares = alloc / entry_price
            positions[tk] = {
                "entry_price": entry_price, "peak": entry_price,
                "entry_i": i, "shares": shares,
            }
            cash -= shares * entry_price
        pending_entry = []

        # 2) 어제 신호 → 오늘 시가 exit
        for tk, reason in pending_exit:
            if tk not in positions:
                continue
            pos = positions[tk]
            c, o, v = stock_arr[tk]
            if i >= len(o) or o[i] <= 0:
                continue
            exit_price = o[i] * (1 - cost)
            ret = exit_price / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[i], "ticker": tk,
                "ret": round(ret*100, 2),
                "hold_days": i - pos["entry_i"], "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
            last_exit_i[tk] = i
        pending_exit = []

        # 3) 보유 청산 체크
        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue

            if stop_trigger == "intraday" and tk in _INTRADAY_DATA:
                # Intraday 모드: 당일 고가 peak 추적 + 당일 저가 hit 즉시 매도
                h, lo = _INTRADAY_DATA[tk]
                if i < len(h) and h[i] > 0:
                    pos["peak"] = max(pos["peak"], h[i])
                else:
                    pos["peak"] = max(pos["peak"], c[i])
                stop = pos["entry_price"] * (1 - sl)
                trail = pos["peak"] * (1 - ts)
                stop_level = max(stop, trail)
                if i < len(lo) and lo[i] > 0 and lo[i] <= stop_level:
                    # 갭다운 (시가 ≤ stop_level) 이면 시가 매도, 일반이면 stop_level + 추가 슬리피지
                    if o[i] > 0 and o[i] <= stop_level:
                        exit_price = o[i] * (1 - cost)
                    else:
                        exit_price = stop_level * (1 - cost - intraday_slip_extra)
                    ret = exit_price / pos["entry_price"] - 1
                    reason = "trailing" if trail >= stop else "stop_loss"
                    trade_log.append({
                        "entry_date": all_dates[pos["entry_i"]],
                        "exit_date": all_dates[i], "ticker": tk,
                        "ret": round(ret*100, 2),
                        "hold_days": i - pos["entry_i"], "reason": reason,
                    })
                    cash += pos["shares"] * exit_price
                    del positions[tk]
                    last_exit_i[tk] = i
                elif i - pos["entry_i"] >= max_hold:
                    pending_exit.append((tk, "max_hold"))
            else:
                # Close 모드 (기존, byte-exact 보존)
                price = c[i]
                pos["peak"] = max(pos["peak"], price)
                stop = pos["entry_price"] * (1 - sl)
                trail = pos["peak"] * (1 - ts)
                if price <= max(stop, trail):
                    reason = "trailing" if trail >= stop else "stop_loss"
                    pending_exit.append((tk, reason))
                elif i - pos["entry_i"] >= max_hold:
                    pending_exit.append((tk, "max_hold"))

        # 4) 신규 신호 (시장 게이트)
        gate_open = check_market_gate(kospi_arr, i, cfg)
        open_slots = max_pos - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            # RS 백분위 계산 (252일 수익률)
            rets = {}
            for tk, (c, _, _) in stock_arr.items():
                if (i < len(c) and c[i] > 0
                        and i >= 252 and c[i-252] > 0):
                    rets[tk] = c[i] / c[i-252] - 1
            rs_map = {}
            if rets:
                vals = sorted(rets.values())
                n = len(vals)
                rs_map = {t: sum(1 for vv in vals if vv <= r)/n*100
                          for t, r in rets.items()}

            candidates = []
            for tk, (c, o, v) in stock_arr.items():
                if tk in positions or i >= len(c) or c[i] <= 0:
                    continue
                if any(tk == e[0] for e in pending_entry):
                    continue
                if cd > 0 and tk in last_exit_i:
                    if i - last_exit_i[tk] < cd:
                        continue
                if check_signal(c, v, i, rs_map.get(tk), cfg):
                    if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                        continue
                    candidates.append((tk, rs_map.get(tk, 0)))

            candidates.sort(key=lambda x: -x[1])
            for tk, _ in candidates[:open_slots]:
                pending_entry.append((tk, i))

        # 5) Equity curve
        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    # 최종 강제 청산
    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-cost) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100, 2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })
    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


# ══════════════════════════════════════════════════════════════════
#  Metrics
# ══════════════════════════════════════════════════════════════════
def calc_metrics(eq_df: pd.DataFrame, tr_df: pd.DataFrame,
                 start=None, end=None) -> dict | None:
    """전체 또는 기간 지정 CAGR / MDD / PF / 승률."""
    e = eq_df.set_index("date")["equity"]
    if start is not None:
        e = e.loc[start:end]
        if len(e) < 2:
            return None
        e = e / e.iloc[0]
        t = tr_df[(tr_df["entry_date"] >= start)
                 & (tr_df["entry_date"] <= end)]
    else:
        t = tr_df
    years = (e.index[-1] - e.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1/years) - 1
    mdd = ((e - e.cummax()) / e.cummax() * 100).min()
    r = t["ret"] if len(t) else pd.Series([0.0])
    wins = t[t["ret"] > 0]
    losses = t[t["ret"] <= 0]
    pf = (wins["ret"].sum() / abs(losses["ret"].sum())
          if len(losses) and losses["ret"].sum() != 0 else 0.0)
    return {
        "cagr": cagr * 100,
        "mdd": float(mdd),
        "trades": len(t),
        "pf": float(pf),
        "win_rate": float((r > 0).mean() * 100) if len(t) else 0.0,
    }


# ══════════════════════════════════════════════════════════════════
#  CLI: python strategy.py → 확정 T10/CD60 백테 실행
# ══════════════════════════════════════════════════════════════════
def _main():
    cfg = load_config()
    print(f"[전략] {cfg['name']} — {cfg['description']}")
    print(f"[확정] {cfg['confirmed_at']}")
    print(f"[리스크] SL {cfg['risk']['stop_loss']:.0%} / "
          f"Trail {cfg['risk']['trail_stop']:.0%} / "
          f"CD {cfg['cooldown_days']}d / "
          f"Pos {cfg['risk']['max_positions']}")

    universe = load_universe_ok()
    print(f"[유니버스] {len(universe)}종목 (validation ok)")
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    print("\n백테 실행 중...")
    eq, tr = run_backtest(all_dates, stock_arr, kospi_arr, cfg)
    m = calc_metrics(eq, tr)
    print(f"\n{'='*52}")
    print(f"  {cfg['name']} — 전체 11.3년")
    print(f"{'='*52}")
    print(f"  CAGR      : {m['cagr']:+.2f}%")
    print(f"  MDD       : {m['mdd']:.2f}%")
    print(f"  거래      : {m['trades']}건")
    print(f"  승률      : {m['win_rate']:.1f}%")
    print(f"  PF        : {m['pf']:.2f}")

    # 기간 분해
    print(f"\n{'─'*52}")
    print("  기간 분해")
    print(f"{'─'*52}")
    for label, s, e in [
        ("2015-2019 박스권", "2015-01-01", "2019-12-31"),
        ("2020-2024",        "2020-01-01", "2024-12-31"),
        ("2025+ 강세장",     "2025-01-01", "2026-12-31"),
    ]:
        m = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
        if m:
            print(f"  {label:<14} CAGR {m['cagr']:+7.2f}% "
                  f"MDD {m['mdd']:6.1f}%  거래 {m['trades']}")


if __name__ == "__main__":
    _main()
