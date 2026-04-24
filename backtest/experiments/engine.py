"""
Experiments 공용 엔진 — strategy.run_backtest 를 fork 하여 진입 로직과
계측을 파라미터화. 기존 backtest/strategy.py 는 unchanged.

세 실험이 공유하는 hook:
- select_fn: (ctx) -> list[(tk, rs_pct)]  # Step 4 candidate 선정 전체
- entry_mode: 'open_next_day' (baseline) | 'close_same_day' (실전형)
- trade_extra_fn: 선정 시점에 trade 에 추가 기록할 dict 반환

ctx dict: i, all_dates, stock_arr, kospi_arr, cfg, positions, pending_entry,
         last_exit_i, signal_streak (dict[tk] -> int), rs_map
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from strategy import (  # noqa: E402
    check_signal, check_minervini_core, check_market_gate,
    check_sector_gate, precompute_sector_tiers,
)


def compute_signal_streak_update(streak: dict, stock_arr, rs_map, i, cfg):
    """매 거래일 종목별 check_signal streak 갱신.

    신호 만족 → streak[tk]++, 불만족 → streak[tk]=0. i 일 종가 기준.
    """
    for tk, (c, _o, v) in stock_arr.items():
        if i >= len(c) or c[i] <= 0:
            streak[tk] = 0
            continue
        rs = rs_map.get(tk)
        if check_signal(c, v, i, rs, cfg):
            streak[tk] = streak.get(tk, 0) + 1
        else:
            streak[tk] = 0


def compute_rs_map(stock_arr, i, lookback=252):
    """252일 수익률 기반 RS 백분위."""
    rets = {}
    for tk, (c, _, _) in stock_arr.items():
        if (i < len(c) and c[i] > 0 and i >= lookback and c[i-lookback] > 0):
            rets[tk] = c[i] / c[i-lookback] - 1
    if not rets:
        return {}
    vals = sorted(rets.values())
    n = len(vals)
    return {t: sum(1 for vv in vals if vv <= r)/n*100 for t, r in rets.items()}


def run_backtest_hooked(all_dates, stock_arr, kospi_arr, cfg,
                        select_fn, entry_mode='open_next_day',
                        trade_extra_fn=None,
                        sector_tier_cache=None):
    """generic backtest engine with hooks.

    select_fn(ctx) -> list[(tk, rs_pct)]  선정 결과 (Top N 절단까지 select_fn 책임).
    entry_mode: 'open_next_day' = o[i+1]*(1+cost) / 'close_same_day' = c[i]*(1+cost)
    trade_extra_fn(tk, ctx) -> dict: trade 레코드에 추가로 기록할 컬럼
    """
    risk = cfg["risk"]
    exec_cfg = cfg["execution"]
    sl = risk["stop_loss"]
    ts = risk["trail_stop"]
    cd = cfg["cooldown_days"]
    cost = exec_cfg["cost_one_way"]
    max_hold = risk["max_hold_days"]
    max_pos = risk["max_positions"]
    warmup = exec_cfg["warmup_days"]

    if sector_tier_cache is None:
        gate_on = cfg.get("signal", {}).get("sector_gate", {}).get("enabled", False)
        sector_tier_cache = (precompute_sector_tiers(all_dates, stock_arr, cfg)
                             if gate_on else {})

    n_days = len(all_dates)
    cash = 1.0
    positions: dict[str, dict] = {}
    pending_entry: list[tuple[str, int, dict]] = []  # (tk, sel_i, extra)
    pending_exit: list[tuple[str, str]] = []
    equity_curve: list[dict] = []
    trade_log: list[dict] = []
    last_exit_i: dict[str, int] = {}
    signal_streak: dict[str, int] = {}

    for i in range(warmup, n_days):
        rs_map = compute_rs_map(stock_arr, i)
        compute_signal_streak_update(signal_streak, stock_arr, rs_map, i, cfg)

        # 1) entry 체결
        if entry_mode == 'open_next_day':
            entries_this_step = pending_entry
            pending_entry = []
            price_col = 'o'
            price_idx = i
        else:  # close_same_day: 당일 종가 체결 — ctx 판정 즉시 같은 거래일 체결
            entries_this_step = []
            price_col = 'c'
            price_idx = i

        for tk, sel_i, extra in entries_this_step:
            if tk in positions:
                continue
            c, o, v = stock_arr[tk]
            if entry_mode == 'open_next_day':
                if price_idx >= len(o) or o[price_idx] <= 0:
                    continue
                px = o[price_idx]
            else:
                if price_idx >= len(c) or c[price_idx] <= 0:
                    continue
                px = c[price_idx]
            open_slots = max_pos - len(positions)
            if open_slots <= 0:
                break
            entry_price = px * (1 + cost)
            alloc = cash / open_slots
            if alloc <= 0:
                break
            shares = alloc / entry_price
            positions[tk] = {
                "entry_price": entry_price, "peak": entry_price,
                "entry_i": price_idx, "shares": shares,
                "sel_i": sel_i, "extra": extra,
            }
            cash -= shares * entry_price

        # 2) exit 체결 (항상 익일 시가)
        for tk, reason in pending_exit:
            if tk not in positions:
                continue
            pos = positions[tk]
            _c, o, _v = stock_arr[tk]
            if i >= len(o) or o[i] <= 0:
                continue
            exit_price = o[i] * (1 - cost)
            ret = exit_price / pos["entry_price"] - 1
            rec = {
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[i], "ticker": tk,
                "ret": round(ret*100, 2),
                "hold_days": i - pos["entry_i"], "reason": reason,
                "signal_age_at_sel": pos["extra"].get("signal_age_at_sel"),
                "rs_at_sel": pos["extra"].get("rs_at_sel"),
            }
            trade_log.append(rec)
            cash += pos["shares"] * exit_price
            del positions[tk]
            last_exit_i[tk] = i
        pending_exit = []

        # 3) 청산 체크 (종가)
        for tk, pos in list(positions.items()):
            c, _o, _v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue
            price = c[i]
            pos["peak"] = max(pos["peak"], price)
            stop = pos["entry_price"] * (1 - sl)
            trail = pos["peak"] * (1 - ts)
            if price <= max(stop, trail):
                reason = "trailing" if trail >= stop else "stop_loss"
                pending_exit.append((tk, reason))
            elif i - pos["entry_i"] >= max_hold:
                pending_exit.append((tk, "max_hold"))

        # 4) 신규 선정 — select_fn
        gate_open = check_market_gate(kospi_arr, i, cfg)
        if gate_open and i + (0 if entry_mode == 'close_same_day' else 1) < n_days:
            open_slots = max_pos - len(positions) + len(pending_exit)
            if entry_mode == 'close_same_day':
                # 당일 종가 진입: 오늘 채워질 슬롯 + 내일 청산 확정분은 내일 채움
                open_slots = max_pos - len(positions)
            if open_slots > 0:
                ctx = dict(
                    i=i, all_dates=all_dates, stock_arr=stock_arr,
                    kospi_arr=kospi_arr, cfg=cfg, positions=positions,
                    last_exit_i=last_exit_i, signal_streak=signal_streak,
                    rs_map=rs_map, open_slots=open_slots, cd=cd,
                    sector_tier_cache=sector_tier_cache,
                )
                selected = select_fn(ctx)  # list[(tk, rs_pct)]
                for tk, rs_pct in selected[:open_slots]:
                    if tk in positions:
                        continue
                    extra = {"rs_at_sel": rs_pct,
                             "signal_age_at_sel": signal_streak.get(tk, 0)}
                    if trade_extra_fn is not None:
                        extra.update(trade_extra_fn(tk, ctx))
                    if entry_mode == 'close_same_day':
                        # 당일 종가 체결: pending 거치지 않고 즉시 체결
                        c, _o, _v = stock_arr[tk]
                        if i >= len(c) or c[i] <= 0:
                            continue
                        open_slots_cur = max_pos - len(positions)
                        if open_slots_cur <= 0:
                            break
                        entry_price = c[i] * (1 + cost)
                        alloc = cash / open_slots_cur
                        if alloc <= 0:
                            break
                        shares = alloc / entry_price
                        positions[tk] = {
                            "entry_price": entry_price, "peak": entry_price,
                            "entry_i": i, "shares": shares,
                            "sel_i": i, "extra": extra,
                        }
                        cash -= shares * entry_price
                    else:
                        pending_entry.append((tk, i, extra))

        # 5) equity
        port_value = cash
        for tk, pos in positions.items():
            c, _o, _v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    # final force-close
    for tk, pos in list(positions.items()):
        c, _o, _v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-cost) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100, 2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
                "signal_age_at_sel": pos["extra"].get("signal_age_at_sel"),
                "rs_at_sel": pos["extra"].get("rs_at_sel"),
            })
    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


# ══════════════════════════════════════════════════════════════════
#  Selection functions — 각 실험별
# ══════════════════════════════════════════════════════════════════
def select_baseline(ctx):
    """baseline: check_signal=True 종목 RS 내림차순 (실험 A)."""
    cfg = ctx["cfg"]
    i = ctx["i"]
    rs_map = ctx["rs_map"]
    cd = ctx["cd"]
    positions = ctx["positions"]
    last_exit_i = ctx["last_exit_i"]
    sector_tier_cache = ctx["sector_tier_cache"]

    cand = []
    for tk, (c, _o, v) in ctx["stock_arr"].items():
        if tk in positions or i >= len(c) or c[i] <= 0:
            continue
        if cd > 0 and tk in last_exit_i and (i - last_exit_i[tk]) < cd:
            continue
        if check_signal(c, v, i, rs_map.get(tk), cfg):
            if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                continue
            cand.append((tk, rs_map.get(tk, 0)))
    cand.sort(key=lambda x: -x[1])
    return cand


def select_live_equivalent(ctx):
    """실험 B: Minervini core 만 필터, 수급·rs_min 제거.

    실전 A등급 = core+rs_ok+supply_ok. 여기선 수급/rs_min 조건도 제거
    → "리포트 어떤 식으로 Top 5 를 뽑든 맞춰본다" 는 공격적 가정.
    (수급/rs_min 제거 효과를 먼저 본 뒤, 남기는 variant 는 다음 ADR)
    """
    cfg = ctx["cfg"]
    i = ctx["i"]
    rs_map = ctx["rs_map"]
    cd = ctx["cd"]
    positions = ctx["positions"]
    last_exit_i = ctx["last_exit_i"]
    sector_tier_cache = ctx["sector_tier_cache"]

    cand = []
    for tk, (c, _o, _v) in ctx["stock_arr"].items():
        if tk in positions or i >= len(c) or c[i] <= 0:
            continue
        if cd > 0 and tk in last_exit_i and (i - last_exit_i[tk]) < cd:
            continue
        if check_minervini_core(c, i, cfg):
            if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                continue
            cand.append((tk, rs_map.get(tk, 0)))
    cand.sort(key=lambda x: -x[1])
    return cand


def make_select_fresh_only(max_streak: int = 3):
    """실험 C: baseline candidate AND signal_streak ∈ [1, max_streak]."""
    def _sel(ctx):
        cfg = ctx["cfg"]
        i = ctx["i"]
        rs_map = ctx["rs_map"]
        cd = ctx["cd"]
        positions = ctx["positions"]
        last_exit_i = ctx["last_exit_i"]
        streak = ctx["signal_streak"]
        sector_tier_cache = ctx["sector_tier_cache"]

        cand = []
        for tk, (c, _o, v) in ctx["stock_arr"].items():
            if tk in positions or i >= len(c) or c[i] <= 0:
                continue
            if cd > 0 and tk in last_exit_i and (i - last_exit_i[tk]) < cd:
                continue
            s = streak.get(tk, 0)
            if s < 1 or s > max_streak:
                continue
            if check_signal(c, v, i, rs_map.get(tk), cfg):
                if not check_sector_gate(tk, i, sector_tier_cache, cfg):
                    continue
                cand.append((tk, rs_map.get(tk, 0)))
        cand.sort(key=lambda x: -x[1])
        return cand
    return _sel
