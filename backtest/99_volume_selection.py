"""
V1 검증: A등급 통과 종목 중 종목 선정 키 변경.

  baseline : RS percentile desc Top 5      (strategy.py 와 동일)
  V1a      : 3일 거래대금 (close × volume) desc Top 5
  V1b      : 3일 거래량 (shares only)       desc Top 5

종목 선정 키 외 모든 룰 (Minervini 8조건 + 수급 + 시장 게이트 + STOP/TRAIL +
쿨다운 + 균등 가중) 은 baseline 과 100% 동일. strategy.py 는 진실의 원천이라
건드리지 않고, run_backtest 를 sort_mode 매개변수와 함께 복사 — 한국 시장
ADR-010 메타 원칙 5번째 검증 사례 데이터 산출 목적.

사전 기댓값 (FAIL 가능성 높음 — 마스터 인지):
  - 1차 출처 없음 (Minervini 거래량은 timing confirm 도구지 selection 키 아님)
  - ADR-001/004/005/010 4번 연속 "추가 필터/정렬 변경 baseline 깎음" 패턴
  - chase entry 페널티 위험

Pass 기준 (사전 정의, 통과 시에만 V2/sensitivity 진행):
  1. 전체 CAGR ≥ baseline +0%p
  2. 전체 MDD ≤ baseline +3%p (덜 깊거나 비슷)
  3. 박스권 (2015-19) CAGR ≥ baseline -2%p

실행:
  python backtest/99_volume_selection.py

데이터 의존: backtest/data/ohlcv/*.parquet, backtest/data/index/kospi.parquet
없으면 먼저 `python backtest/01_fetch_data.py` (pykrx, 30~60분).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from strategy import (
    load_config, load_universe_ok, load_data,
    check_signal, check_market_gate, calc_metrics,
)

VOLUME_LOOKBACK = 3


def run_backtest_with_sort(all_dates, stock_arr, kospi_arr, cfg,
                           sort_mode: str = "rs",
                           size_mode: str = "equal"):
    """
    strategy.run_backtest 의 sort 키 + sizing 키 매개변수화 버전.

    sort_mode (종목 선정):
      "rs"          → RS percentile desc (baseline)
      "vol3d_value" → 직전 3일 (close × volume) 합 desc
      "vol3d_shares"→ 직전 3일 volume 합 desc

    size_mode (포지션 가중):
      "equal"                       → 균등 (baseline, cash/open_slots 매번 재계산)
      "vol3d_value_proportional"    → 3일 거래대금 비례 가중
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

    n_days = len(all_dates)
    cash = 1.0
    positions: dict[str, dict] = {}
    pending_entry: list[tuple[str, int, float]] = []  # (ticker, sig_i, sizing_score)
    pending_exit: list[tuple[str, str]] = []
    equity_curve: list[dict] = []
    trade_log: list[dict] = []
    last_exit_i: dict[str, int] = {}

    for i in range(warmup, n_days):
        if size_mode == "equal":
            for tk, _sig_i, _score in pending_entry:
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
        elif size_mode == "vol3d_value_proportional":
            valid = []
            for tk, sig_i, score in pending_entry:
                if tk in positions:
                    continue
                c, o, v = stock_arr[tk]
                if i >= len(o) or o[i] <= 0:
                    continue
                if max_pos - len(positions) - len(valid) <= 0:
                    break
                valid.append((tk, sig_i, score))
            if valid:
                total = sum(s for _, _, s in valid)
                if total > 0:
                    weights = [s / total for _, _, s in valid]
                else:
                    weights = [1.0 / len(valid)] * len(valid)
                base_cash = cash
                for (tk, _sig_i, _s), w in zip(valid, weights):
                    c, o, v = stock_arr[tk]
                    alloc = base_cash * w
                    if alloc <= 0:
                        continue
                    entry_price = o[i] * (1 + cost)
                    shares = alloc / entry_price
                    positions[tk] = {
                        "entry_price": entry_price, "peak": entry_price,
                        "entry_i": i, "shares": shares,
                    }
                    cash -= shares * entry_price
        else:
            raise ValueError(f"unknown size_mode: {size_mode}")
        pending_entry = []

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
                "ret": round(ret * 100, 2),
                "hold_days": i - pos["entry_i"], "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
            last_exit_i[tk] = i
        pending_exit = []

        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
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

        gate_open = check_market_gate(kospi_arr, i, cfg)
        open_slots = max_pos - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            rets = {}
            for tk, (c, _, _) in stock_arr.items():
                if (i < len(c) and c[i] > 0
                        and i >= 252 and c[i - 252] > 0):
                    rets[tk] = c[i] / c[i - 252] - 1
            rs_map = {}
            if rets:
                vals = sorted(rets.values())
                n = len(vals)
                rs_map = {t: sum(1 for vv in vals if vv <= r) / n * 100
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
                if not check_signal(c, v, i, rs_map.get(tk), cfg):
                    continue

                if sort_mode == "rs":
                    score = rs_map.get(tk, 0.0)
                elif sort_mode == "vol3d_value":
                    if i + 1 >= VOLUME_LOOKBACK:
                        s = i + 1 - VOLUME_LOOKBACK
                        score = float((c[s:i + 1] * v[s:i + 1]).sum())
                    else:
                        score = 0.0
                elif sort_mode == "vol3d_shares":
                    if i + 1 >= VOLUME_LOOKBACK:
                        s = i + 1 - VOLUME_LOOKBACK
                        score = float(v[s:i + 1].sum())
                    else:
                        score = 0.0
                else:
                    raise ValueError(f"unknown sort_mode: {sort_mode}")
                candidates.append((tk, score))

            candidates.sort(key=lambda x: -x[1])
            for tk, _ in candidates[:open_slots]:
                c, _o, v = stock_arr[tk]
                if i + 1 >= VOLUME_LOOKBACK:
                    s = i + 1 - VOLUME_LOOKBACK
                    sizing_score = float((c[s:i + 1] * v[s:i + 1]).sum())
                else:
                    sizing_score = 0.0
                pending_entry.append((tk, i, sizing_score))

        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days - 1 < len(c) and c[n_days - 1] > 0:
            ret = c[n_days - 1] * (1 - cost) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days - 1],
                "ticker": tk, "ret": round(ret * 100, 2),
                "hold_days": n_days - 1 - pos["entry_i"], "reason": "final",
            })
    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


PERIODS = [
    ("전체",             None,         None),
    ("2015-2019 박스권", "2015-01-01", "2019-12-31"),
    ("2020-2024 중립",   "2020-01-01", "2024-12-31"),
    ("2025+ 강세장",     "2025-01-01", "2026-12-31"),
]


def print_report(label, eq, tr):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    for plabel, s, e in PERIODS:
        if s is None:
            m = calc_metrics(eq, tr)
        else:
            m = calc_metrics(eq, tr, pd.Timestamp(s), pd.Timestamp(e))
        if m:
            print(f"  {plabel:<18} CAGR {m['cagr']:+7.2f}%  "
                  f"MDD {m['mdd']:+6.1f}%  거래 {m['trades']:>4}  "
                  f"승률 {m['win_rate']:5.1f}%  PF {m['pf']:.2f}")


def diff_table(name_b, eq_b, tr_b, name_v, eq_v, tr_v):
    print(f"\n{'─' * 60}")
    print(f"  Δ ({name_v} − {name_b})")
    print(f"{'─' * 60}")
    for plabel, s, e in PERIODS:
        if s is None:
            mb = calc_metrics(eq_b, tr_b)
            mv = calc_metrics(eq_v, tr_v)
        else:
            mb = calc_metrics(eq_b, tr_b, pd.Timestamp(s), pd.Timestamp(e))
            mv = calc_metrics(eq_v, tr_v, pd.Timestamp(s), pd.Timestamp(e))
        if mb and mv:
            d_cagr = mv["cagr"] - mb["cagr"]
            d_mdd = mv["mdd"] - mb["mdd"]
            print(f"  {plabel:<18} ΔCAGR {d_cagr:+6.2f}%p  "
                  f"ΔMDD {d_mdd:+5.1f}%p  "
                  f"거래 {mb['trades']:>4} → {mv['trades']:>4}")


def pass_check(name, eq_b, tr_b, eq_v, tr_v):
    mb_full = calc_metrics(eq_b, tr_b)
    mv_full = calc_metrics(eq_v, tr_v)
    mb_box = calc_metrics(eq_b, tr_b,
                          pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-31"))
    mv_box = calc_metrics(eq_v, tr_v,
                          pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-31"))

    checks = [
        ("전체 CAGR ≥ baseline +0%p",
         mv_full["cagr"] >= mb_full["cagr"]),
        ("전체 MDD ≤ baseline +3%p",
         mv_full["mdd"] >= mb_full["mdd"] - 3),
        ("박스권 CAGR ≥ baseline -2%p",
         mv_box["cagr"] >= mb_box["cagr"] - 2),
    ]
    print(f"\n{'─' * 60}")
    print(f"  Pass 판정 — {name}")
    print(f"{'─' * 60}")
    all_pass = True
    for desc, ok in checks:
        marker = "✓" if ok else "✗"
        print(f"  [{marker}] {desc}")
        if not ok:
            all_pass = False
    verdict = ("PASS — sensitivity 후속 검증 권장"
               if all_pass else "FAIL — 기각, ADR-010 사례 추가")
    print(f"\n  → {name}: {verdict}")
    return all_pass


def main():
    cfg = load_config()
    print(f"[전략] {cfg['name']} — {cfg['description']}")
    print(f"[V1 변형] A등급 통과 종목 중 선정 키 변경 (RS → 거래량/거래대금)")
    print(f"[리스크] SL {cfg['risk']['stop_loss']:.0%} / "
          f"Trail {cfg['risk']['trail_stop']:.0%} / "
          f"CD {cfg['cooldown_days']}d / Pos {cfg['risk']['max_positions']}")

    universe = load_universe_ok()
    print(f"[유니버스] {len(universe)}종목 (validation ok)")
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"[데이터] {len(stock_arr)}종목 × {len(all_dates)}영업일")

    print("\n[1/4] BASELINE (RS Top 5, 균등) 백테 실행...")
    eq_b, tr_b = run_backtest_with_sort(all_dates, stock_arr, kospi_arr, cfg,
                                        sort_mode="rs", size_mode="equal")
    print_report("BASELINE — RS percentile desc Top 5, 균등 가중", eq_b, tr_b)

    print("\n[2/4] V1a (3일 거래대금 Top 5, 균등) 백테 실행...")
    eq_va, tr_va = run_backtest_with_sort(all_dates, stock_arr, kospi_arr, cfg,
                                          sort_mode="vol3d_value",
                                          size_mode="equal")
    print_report("V1a — 3일 거래대금 desc Top 5, 균등 가중", eq_va, tr_va)

    print("\n[3/4] V1b (3일 거래량 Top 5, 균등) 백테 실행...")
    eq_vb, tr_vb = run_backtest_with_sort(all_dates, stock_arr, kospi_arr, cfg,
                                          sort_mode="vol3d_shares",
                                          size_mode="equal")
    print_report("V1b — 3일 거래량 desc Top 5, 균등 가중", eq_vb, tr_vb)

    print("\n[4/4] V1c (RS Top 5, 거래대금 비례 가중) 백테 실행...")
    eq_vc, tr_vc = run_backtest_with_sort(all_dates, stock_arr, kospi_arr, cfg,
                                          sort_mode="rs",
                                          size_mode="vol3d_value_proportional")
    print_report("V1c — RS Top 5 + 3일 거래대금 비례 가중 (sizing 채널)", eq_vc, tr_vc)

    diff_table("baseline", eq_b, tr_b, "V1a 거래대금 sel",   eq_va, tr_va)
    diff_table("baseline", eq_b, tr_b, "V1b 거래량 sel",    eq_vb, tr_vb)
    diff_table("baseline", eq_b, tr_b, "V1c sizing",        eq_vc, tr_vc)

    pa = pass_check("V1a 거래대금 selection", eq_b, tr_b, eq_va, tr_va)
    pb = pass_check("V1b 거래량 selection",   eq_b, tr_b, eq_vb, tr_vb)
    pc = pass_check("V1c sizing (RS+vol weight)", eq_b, tr_b, eq_vc, tr_vc)

    print(f"\n{'=' * 60}")
    print(f"  종합")
    print(f"{'=' * 60}")
    print(f"  V1a (selection 거래대금) : {'PASS' if pa else 'FAIL'}")
    print(f"  V1b (selection 거래량)   : {'PASS' if pb else 'FAIL'}")
    print(f"  V1c (sizing 거래대금)    : {'PASS' if pc else 'FAIL'}")
    print()
    if pc and not (pa or pb):
        print("  → sizing 채널이 알파 회수. selection 무효 + sizing 유효 패턴.")
        print("    ADR-010 본문 명시 sizing 예외 채널 검증 성공.")
    elif not (pa or pb or pc):
        print("  → 모두 FAIL. selection/sizing 양 채널 무효.")
        print("    ADR-010 5번째 사례 + 박스권 부산물도 sizing 으로 회수 안 됨.")
    elif pc and (pa or pb):
        print("  → sizing 도 PASS 이나 selection 도 일부 PASS — 추가 sensitivity 필요.")
    else:
        print("  → 혼재 결과. 개별 검토.")


if __name__ == "__main__":
    main()
