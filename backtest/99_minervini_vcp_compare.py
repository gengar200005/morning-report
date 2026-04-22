"""
Phase 3 백테스트 그리드 스윕: TRAIL × 쿨다운 조합 비교 + 기간 분해.

이 스크립트는 strategy.py 를 공통 로직으로 사용한다. 시그널/엔진 로직은
strategy.py 를 single source of truth 로 유지; 이 파일은 그리드 스윕 ·
리포트 생성에만 집중.

데이터: pykrx 수집본 (backtest/data/ohlcv, 2015-01-01 ~ 2026-04-21)
유니버스: validation status='ok' 종목 (현재 162종목)

VCP 3요소 (옵션, 과거 비교용):
  피벗 = 최근 50일 고점, ±5%
  돌파 거래량 ≥ 50일 평균 × 1.2
  직전 수축: 10일 평균 / 50일 평균 ≤ 0.8
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# strategy.py — 진실의 원천
from strategy import (
    load_config, load_universe_ok, load_data,
    check_signal, check_market_gate,
    run_backtest,
)

# ── 호환용 re-export (walkforward 등 기존 호출자 지원) ──
CFG = load_config()
STOP_LOSS = CFG["risk"]["stop_loss"]
TRAIL_STOP = CFG["risk"]["trail_stop"]
MAX_HOLD = CFG["risk"]["max_hold_days"]
MAX_POSITIONS = CFG["risk"]["max_positions"]
COST = CFG["execution"]["cost_one_way"]

# ── VCP 파라미터 (이 스크립트 전용, 과거 비교용) ──
VCP_PIVOT_DAYS = 50
VCP_PIVOT_TOL = 0.05
VCP_BREAKOUT_VOL_RATIO = 1.2
VCP_DRY_UP_RATIO = 0.8
VCP_DRY_UP_RECENT = 10
VCP_DRY_UP_BASELINE = 50


def kospi_above_ma60(kospi_arr, i):
    """호환 래퍼 — strategy.check_market_gate 로 delegate."""
    return check_market_gate(kospi_arr, i, CFG)


def check_minervini_supply(c, v, i, rs_pct=None):
    """호환 래퍼 — strategy.check_signal 로 delegate (T10/CD60 기본값)."""
    return check_signal(c, v, i, rs_pct, CFG)


def run_portfolio(all_dates, stock_arr, kospi_arr, signal_fn,
                  warmup=252, cooldown=0, skip_prob=0.0, seed=0,
                  stop_loss=None, trail_stop=None):
    """호환 래퍼 — signal_fn 은 strategy.check_signal 과 동일한 경우만 유효.
    VCP 등 다른 시그널을 쓰려면 아래 _run_portfolio_custom 사용."""
    if signal_fn is check_minervini_supply:
        return run_backtest(all_dates, stock_arr, kospi_arr, CFG,
                            trail_stop=trail_stop, cooldown=cooldown,
                            stop_loss=stop_loss)
    # 비표준 signal (VCP 등): 아래 custom 엔진
    return _run_portfolio_custom(all_dates, stock_arr, kospi_arr,
                                 signal_fn, warmup, cooldown,
                                 stop_loss, trail_stop)


def _check_minervini_supply_core(c, v, i, rs_pct,
                                  hi52_mult, lo52_mult, rs_min):
    """Minervini + 수급 커스텀 (hi52/lo52/rs 완화 실험용)."""
    if i < 252 or c[i-252] <= 0:
        return False
    cur = c[i]
    ma50 = c[i-50:i].mean()
    ma150 = c[i-150:i].mean()
    ma200 = c[i-200:i].mean()
    ma200_1m = c[i-252:i-22].mean()
    hi52 = c[max(0, i-252):i].max()
    lo52 = c[max(0, i-252):i].min()
    conds = [
        cur > ma50, cur > ma150, cur > ma200,
        ma50 > ma150, ma150 > ma200, ma200 > ma200_1m,
        cur >= lo52 * lo52_mult, cur >= hi52 * hi52_mult,
    ]
    if rs_pct is not None:
        conds.append(rs_pct >= rs_min)
    if not all(conds):
        return False
    # 수급 프록시 (20일 up/dn volume ratio ≥ 1.2)
    if i < 21:
        return False
    up_vol, dn_vol = 0.0, 0.0
    for j in range(i-20, i):
        if c[j] > c[j-1]:
            up_vol += v[j]
        else:
            dn_vol += v[j]
    return (up_vol / dn_vol if dn_vol > 0 else 999) >= 1.2


def check_minervini_supply(c, v, i, rs_pct=None):
    """표준: hi52*0.75, lo52*1.25, RS≥70."""
    return _check_minervini_supply_core(c, v, i, rs_pct, 0.75, 1.25, 70)


def check_minervini_loose(c, v, i, rs_pct=None):
    """완화: hi52*0.60, lo52*1.25, RS≥60."""
    return _check_minervini_supply_core(c, v, i, rs_pct, 0.60, 1.25, 60)


def check_vcp(c, v, i):
    """VCP auto 3요소: 피벗 돌파 + 돌파 거래량 + 직전 수축."""
    if i < VCP_DRY_UP_BASELINE:
        return False
    # 1) 피벗 = 최근 50일 고점 (당일 제외), ±2% 근처
    pivot = c[i-VCP_PIVOT_DAYS:i].max()
    if pivot <= 0:
        return False
    if not (pivot * (1 - VCP_PIVOT_TOL) <= c[i] <= pivot * (1 + VCP_PIVOT_TOL)):
        return False
    # 2) 돌파일 거래량 ≥ 50일 평균 × 1.3
    avg50_vol = v[i-VCP_DRY_UP_BASELINE:i].mean()
    if avg50_vol <= 0 or v[i] < avg50_vol * VCP_BREAKOUT_VOL_RATIO:
        return False
    # 3) 직전 10일 평균 / 50일 평균 ≤ 0.6
    avg10_vol = v[i-VCP_DRY_UP_RECENT:i].mean()
    if avg10_vol / avg50_vol > VCP_DRY_UP_RATIO:
        return False
    return True


def check_minervini_vcp(c, v, i, rs_pct=None):
    return (check_minervini_supply(c, v, i, rs_pct)
            and check_vcp(c, v, i))


# ── 커스텀 시그널용 백테 엔진 (VCP 등, 비표준 signal_fn 전용) ────────
def _run_portfolio_custom(all_dates, stock_arr, kospi_arr, signal_fn,
                          warmup=252, cooldown=0,
                          stop_loss=None, trail_stop=None):
    """strategy.run_backtest 와 동일 로직 — 단 signal_fn 을 외부에서 주입.
    T10/CD60 표준 시그널(check_minervini_supply)은 strategy.run_backtest 직접 사용."""
    import random as _rnd  # noqa: F401 (호환성)
    sl = STOP_LOSS if stop_loss is None else stop_loss
    ts = TRAIL_STOP if trail_stop is None else trail_stop
    rng = None
    n_days = len(all_dates)
    cash = 1.0
    positions = {}
    pending_entry = []
    pending_exit = []
    equity_curve = []
    trade_log = []
    last_exit_i = {}  # 쿨다운 추적

    for i in range(warmup, n_days):
        # 1) 어제 신호 → 오늘 시가 entry
        for tk, _sig_i in pending_entry:
            if tk in positions:
                continue
            c, o, v = stock_arr[tk]
            if i >= len(o) or o[i] <= 0:
                continue
            open_slots = MAX_POSITIONS - len(positions)
            if open_slots <= 0:
                break
            entry_price = o[i] * (1 + COST)
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
            exit_price = o[i] * (1 - COST)
            ret = exit_price / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[i], "ticker": tk,
                "ret": round(ret*100, 2),
                "hold_days": i - pos["entry_i"], "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
            last_exit_i[tk] = i  # 쿨다운 시작
        pending_exit = []

        # 3) 보유 청산 체크 (종가)
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
            elif i - pos["entry_i"] >= MAX_HOLD:
                pending_exit.append((tk, "max_hold"))

        # 4) 신규 신호 (코스피 MA60 게이트)
        gate_open = kospi_above_ma60(kospi_arr, i)
        open_slots = MAX_POSITIONS - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            rets = {}
            for tk, (c, o, v) in stock_arr.items():
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
                # 쿨다운: 최근 청산 이후 cooldown 거래일 미만이면 스킵
                if cooldown > 0 and tk in last_exit_i:
                    if i - last_exit_i[tk] < cooldown:
                        continue
                if signal_fn(c, v, i, rs_map.get(tk)):
                    candidates.append((tk, rs_map.get(tk, 0)))
            candidates.sort(key=lambda x: -x[1])
            if rng is not None:
                candidates = [cd for cd in candidates
                              if rng.random() >= skip_prob]
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
            ret = c[n_days-1]*(1-COST) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100, 2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })
    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


# ── 리포트 ────────────────────────────────────────
def print_result(eq_df, trade_df, kospi_arr, all_dates, label):
    print(f"\n{'━'*62}")
    print(f"  {label}")
    print(f"{'━'*62}")
    if trade_df.empty:
        print("  거래 없음")
        return
    eq = eq_df.set_index("date")["equity"]
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    mdd = dd.min()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/years) - 1

    k_s = list(all_dates).index(eq.index[0])
    k_e = list(all_dates).index(eq.index[-1])
    k_cagr = (kospi_arr[k_e] / kospi_arr[k_s]) ** (1/years) - 1
    ks = pd.Series(kospi_arr[k_s:k_e+1], index=all_dates[k_s:k_e+1])
    k_mdd = ((ks - ks.cummax()) / ks.cummax() * 100).min()

    r = trade_df["ret"]
    wins = trade_df[r > 0]
    losses = trade_df[r <= 0]
    aw = wins["ret"].mean() if len(wins) else 0
    al = abs(losses["ret"].mean()) if len(losses) else 1
    pf = (wins["ret"].sum() / abs(losses["ret"].sum())
          if losses["ret"].sum() != 0 else 0)

    print(f"\n  ── 포트폴리오 ({years:.1f}년) ──")
    print(f"  CAGR: {cagr*100:+.2f}%  누적: {(eq.iloc[-1]/eq.iloc[0]-1)*100:+.1f}%")
    print(f"  MDD:  {mdd:.2f}%")
    print(f"  코스피: CAGR {k_cagr*100:+.2f}%  MDD {k_mdd:.1f}%")
    print(f"\n  ── 거래 ──")
    print(f"  총 {len(trade_df)}건  승률 {(r>0).mean()*100:.1f}%  "
          f"손익비 {aw/al:.2f}x  PF {pf:.2f}")
    print(f"  평균보유 {trade_df['hold_days'].mean():.0f}일  "
          f"평균수익 {aw:+.1f}%  평균손실 {losses['ret'].mean():+.1f}%")
    print(f"\n  ── 청산 사유 ──")
    for reason in ["stop_loss", "trailing", "max_hold", "final"]:
        cnt = (trade_df["reason"] == reason).sum()
        if cnt:
            ar = trade_df[trade_df["reason"] == reason]["ret"].mean()
            lb = {"stop_loss": "손절", "trailing": "트레일링",
                  "max_hold": "만기", "final": "최종"}[reason]
            print(f"  {lb:<8} {cnt:>4}건 ({cnt/len(trade_df)*100:.1f}%)  "
                  f"평균 {ar:+.2f}%")
    print(f"\n  ── 연도별 ──")
    eq_yr = eq.resample("YE").last()
    for j in range(len(eq_yr)):
        yr = eq_yr.index[j].year
        prev = eq.iloc[0] if j == 0 else eq_yr.iloc[j-1]
        yr_r = (eq_yr.iloc[j] / prev - 1) * 100
        yt = trade_df[trade_df["exit_date"].dt.year == yr]
        wr = (yt["ret"] > 0).mean() * 100 if len(yt) else 0
        print(f"  {yr}: {'▲' if yr_r > 0 else '▼'} {yr_r:+.2f}%  "
              f"({len(yt)}건, 승률 {wr:.0f}%)")


def period_stats(eq_df, trade_df, kospi_arr, all_dates, start_dt, end_dt):
    """eq/trade를 [start, end] 범위로 잘라서 CAGR/MDD 등 통계 반환."""
    eq = eq_df.set_index("date")["equity"]
    eq_slice = eq.loc[start_dt:end_dt]
    if len(eq_slice) < 2:
        return None
    base = eq_slice.iloc[0]
    eq_rb = eq_slice / base
    dd = (eq_rb - eq_rb.cummax()) / eq_rb.cummax() * 100
    mdd = dd.min()
    years = (eq_slice.index[-1] - eq_slice.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = eq_rb.iloc[-1] ** (1/years) - 1

    t = trade_df[(trade_df["entry_date"] >= start_dt)
                 & (trade_df["entry_date"] <= end_dt)]
    r = t["ret"]
    if len(r):
        wins = t[r > 0]; losses = t[r <= 0]
        pf = (wins["ret"].sum() / abs(losses["ret"].sum())
              if losses["ret"].sum() != 0 else 0)
        win_rate = (r > 0).mean() * 100
    else:
        pf, win_rate = 0, 0

    try:
        k_s = list(all_dates).index(eq_slice.index[0])
        k_e = list(all_dates).index(eq_slice.index[-1])
        k_cagr = (kospi_arr[k_e] / kospi_arr[k_s]) ** (1/years) - 1
        ks = pd.Series(kospi_arr[k_s:k_e+1], index=all_dates[k_s:k_e+1])
        k_mdd = ((ks - ks.cummax()) / ks.cummax() * 100).min()
    except Exception:
        k_cagr, k_mdd = 0, 0

    return {
        "cagr": cagr * 100, "mdd": mdd, "trades": len(t),
        "win_rate": win_rate, "pf": pf,
        "k_cagr": k_cagr * 100, "k_mdd": k_mdd,
    }


def print_period_table(results, kospi_arr, all_dates):
    """results = {label: (eq_df, trade_df)} for 3 variants."""
    periods = [
        ("2015~2019", pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-31")),
        ("2020~2024", pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")),
        ("2025~현재", pd.Timestamp("2025-01-01"), pd.Timestamp("2026-12-31")),
        ("전체",       pd.Timestamp("2015-01-01"), pd.Timestamp("2026-12-31")),
    ]

    print(f"\n{'='*78}")
    print(f"  기간별 분해 (CAGR / MDD / 거래 / PF)")
    print(f"{'='*78}")
    header = f"  {'변형':<10}"
    for pname, _, _ in periods:
        header += f" │ {pname:^22}"
    print(header)
    print("  " + "─"*(12 + len(periods)*25))

    # 전략 row
    for label, (eq_df, trade_df) in results.items():
        row = f"  {label:<10}"
        for _, s, e in periods:
            st = period_stats(eq_df, trade_df, kospi_arr, all_dates, s, e)
            if st is None:
                row += f" │ {'(no data)':^22}"
            else:
                cell = (f"{st['cagr']:+6.2f}% / {st['mdd']:6.1f}% "
                        f"/ {st['trades']:>3}/{st['pf']:.2f}")
                row += f" │ {cell:<22}"
        print(row)

    # 코스피 row
    row = f"  {'코스피':<10}"
    for _, s, e in periods:
        try:
            k_s = next(i for i, d in enumerate(all_dates) if d >= s)
            k_e_candidates = [i for i, d in enumerate(all_dates) if d <= e]
            if not k_e_candidates:
                row += f" │ {'(no data)':^22}"
                continue
            k_e = k_e_candidates[-1]
            years = (all_dates[k_e] - all_dates[k_s]).days / 365.25
            if years <= 0:
                row += f" │ {'(no data)':^22}"
                continue
            k_cagr = (kospi_arr[k_e]/kospi_arr[k_s])**(1/years) - 1
            ks = pd.Series(kospi_arr[k_s:k_e+1], index=all_dates[k_s:k_e+1])
            k_mdd = ((ks - ks.cummax())/ks.cummax()*100).min()
            cell = f"{k_cagr*100:+6.2f}% / {k_mdd:6.1f}%"
            row += f" │ {cell:<22}"
        except Exception:
            row += f" │ {'(err)':^22}"
    print(row)
    print()


def deep_analyze_period(trade_df, universe_dict, label, start_dt, end_dt):
    t = trade_df[(trade_df["entry_date"] >= start_dt)
                 & (trade_df["entry_date"] <= end_dt)].copy()
    if t.empty:
        print(f"\n  [{label}] 해당 구간 거래 없음")
        return
    print(f"\n{'━'*70}")
    print(f"  [{label}] {start_dt.date()} ~ {end_dt.date()}  총 {len(t)}건")
    print(f"{'━'*70}")

    r = t["ret"]
    wins = t[r > 0]; losses = t[r <= 0]
    pf = (wins["ret"].sum() / abs(losses["ret"].sum())
          if losses["ret"].sum() != 0 else 0)
    print(f"  승률 {(r>0).mean()*100:.1f}%  평균수익 {wins['ret'].mean():+.2f}%  "
          f"평균손실 {losses['ret'].mean():+.2f}%  PF {pf:.2f}")
    print(f"  평균보유 {t['hold_days'].mean():.0f}일  "
          f"중앙값 {t['hold_days'].median():.0f}일  최단 {t['hold_days'].min()}일")

    print(f"\n  ── 청산 사유 ──")
    for reason in ["stop_loss", "trailing", "max_hold", "final"]:
        sub = t[t["reason"] == reason]
        if len(sub):
            lb = {"stop_loss": "손절", "trailing": "트레일링",
                  "max_hold": "만기", "final": "최종"}[reason]
            print(f"  {lb:<8} {len(sub):>3}건 ({len(sub)/len(t)*100:.1f}%)  "
                  f"평균 {sub['ret'].mean():+6.2f}%  평균보유 {sub['hold_days'].mean():.0f}일")

    # 최악 손실 Top 12
    print(f"\n  ── 최악 손실 Top 12 ──")
    worst = t.nsmallest(12, "ret")
    for _, row in worst.iterrows():
        nm = universe_dict.get(row['ticker'], '')[:10]
        print(f"  {row['ticker']}  {nm:<10}  "
              f"{row['entry_date'].date()} → {row['exit_date'].date()}  "
              f"{row['ret']:+7.2f}%  {int(row['hold_days']):>3}d  {row['reason']}")

    # 반복 진입 종목 (fake-out 패턴)
    print(f"\n  ── 반복 진입 종목 (2회 이상, 평균손실 큰 순) ──")
    g = t.groupby("ticker").agg(
        n=("ret", "size"),
        mean=("ret", "mean"),
        total=("ret", "sum"),
        wr=("ret", lambda s: (s > 0).mean() * 100),
    ).reset_index()
    rep = g[g["n"] >= 2].sort_values("mean").head(12)
    for _, row in rep.iterrows():
        nm = universe_dict.get(row['ticker'], '')[:10]
        print(f"  {row['ticker']}  {nm:<10}  "
              f"{int(row['n']):>2}회  평균 {row['mean']:+6.2f}%  "
              f"승률 {row['wr']:.0f}%  누적 {row['total']:+6.2f}%")

    # 연도별
    print(f"\n  ── 연도별 ──")
    t["ey"] = t["entry_date"].dt.year
    for yr in sorted(t["ey"].unique()):
        sub = t[t["ey"] == yr]
        sr = sub["ret"]
        sl = (sub["reason"] == "stop_loss").sum()
        tr = (sub["reason"] == "trailing").sum()
        print(f"  {yr}: {len(sub):>3}건  승률 {(sr>0).mean()*100:>4.0f}%  "
              f"평균 {sr.mean():+6.2f}%  손절 {sl}건  트레일 {tr}건")


def main():
    print("=" * 62)
    print("  Phase 3 백테스트: Minervini+수급+게이트 vs +VCP")
    print(f"  데이터: pykrx parquet (2015-01-01 ~ 2026-04-21)")
    print(f"  기본: SL {STOP_LOSS:.0%} / Trail {TRAIL_STOP:.0%} / "
          f"Hold {MAX_HOLD}d / Pos {MAX_POSITIONS} / Cost {COST*2:.1%}")
    print(f"  VCP:  피벗 {VCP_PIVOT_DAYS}d ±{VCP_PIVOT_TOL:.0%} / "
          f"돌파 x{VCP_BREAKOUT_VOL_RATIO} / "
          f"dry-up {VCP_DRY_UP_RECENT}d/{VCP_DRY_UP_BASELINE}d ≤ {VCP_DRY_UP_RATIO}")
    print("=" * 62)

    print("\n[1/3] 검증 통과 유니버스 로드...")
    universe = load_universe_ok()
    print(f"  → {len(universe)}종목")

    print("\n[2/3] pykrx parquet 로드...")
    all_dates, stock_arr, kospi_arr = load_data(universe)
    print(f"  → {len(stock_arr)}종목, 영업일 {len(all_dates)}일 "
          f"({all_dates[0].date()} ~ {all_dates[-1].date()})")

    print("\n[3/3] TRAIL × 쿨다운 그리드...")
    trails = [0.10, 0.15, 0.20, 0.25]
    cooldowns = [0, 60, 120]
    grid = {}
    for ts in trails:
        for cd in cooldowns:
            lab = f"T{int(ts*100)}/CD{cd}"
            print(f"  {lab} ...")
            eq, tr = run_portfolio(all_dates, stock_arr, kospi_arr,
                                   check_minervini_supply,
                                   cooldown=cd, trail_stop=ts)
            grid[(ts, cd)] = (eq, tr)

    # 그리드 요약: 메트릭별 4x3 표
    def calc_metrics(eq, tr, start=None, end=None):
        e = eq.set_index("date")["equity"]
        if start is not None:
            e = e.loc[start:end]
            if len(e) < 2:
                return None
            base = e.iloc[0]
            e = e / base
            t = tr[(tr["entry_date"] >= start)
                   & (tr["entry_date"] <= end)]
        else:
            t = tr
        years = (e.index[-1] - e.index[0]).days / 365.25
        if years <= 0:
            return None
        cagr = (e.iloc[-1] / e.iloc[0]) ** (1/years) - 1
        mdd = ((e - e.cummax()) / e.cummax() * 100).min()
        r = t["ret"] if len(t) else pd.Series([0])
        wins = t[t["ret"] > 0]
        losses = t[t["ret"] <= 0]
        pf = (wins["ret"].sum() / abs(losses["ret"].sum())
              if len(losses) and losses["ret"].sum() != 0 else 0)
        return {
            "cagr": cagr * 100, "mdd": mdd, "trades": len(t),
            "pf": pf,
            "win_rate": (r > 0).mean() * 100 if len(t) else 0,
            "avg_win": wins["ret"].mean() if len(wins) else 0,
            "max_win": r.max() if len(t) else 0,
            "avg_hold": t["hold_days"].mean() if len(t) else 0,
        }

    def print_grid_table(title, metric_key, fmt):
        print(f"\n{'─'*62}")
        print(f"  {title}")
        print(f"{'─'*62}")
        print(f"  {'TRAIL':<6} │ {'CD=0':>10} │ {'CD=60':>10} │ {'CD=120':>10}")
        print("  " + "─"*45)
        for ts in trails:
            row = f"  {int(ts*100)}%    "
            for cd in cooldowns:
                eq, tr = grid[(ts, cd)]
                m = calc_metrics(eq, tr)
                if m is None:
                    row += f" │ {'--':>10}"
                else:
                    row += f" │ {fmt.format(m[metric_key]):>10}"
            print(row)

    print(f"\n{'='*62}")
    print(f"  TRAIL × 쿨다운 그리드 (전체 11.3년)")
    print(f"{'='*62}")
    print_grid_table("전체 CAGR",        "cagr",     "{:+6.2f}%")
    print_grid_table("전체 MDD",         "mdd",      "{:6.1f}%")
    print_grid_table("Profit Factor",    "pf",       "{:.2f}")
    print_grid_table("평균 수익 거래 (%)", "avg_win",  "{:+5.1f}%")
    print_grid_table("최대 수익 거래 (%)", "max_win",  "{:+6.1f}%")
    print_grid_table("평균 보유 (일)",    "avg_hold", "{:.0f}")
    print_grid_table("거래 건수",         "trades",   "{:.0f}")

    # 2025~현재 그리드 (강세장 효과)
    s25 = pd.Timestamp("2025-01-01")
    e25 = pd.Timestamp("2026-12-31")
    def calc_2025(eq, tr):
        return calc_metrics(eq, tr, s25, e25)

    print(f"\n{'='*62}")
    print(f"  TRAIL × 쿨다운 그리드 (2025-01 ~ 현재, 1.3년 강세장)")
    print(f"{'='*62}")
    print(f"\n{'─'*62}")
    print(f"  2025+ CAGR")
    print(f"{'─'*62}")
    print(f"  {'TRAIL':<6} │ {'CD=0':>10} │ {'CD=60':>10} │ {'CD=120':>10}")
    print("  " + "─"*45)
    for ts in trails:
        row = f"  {int(ts*100)}%    "
        for cd in cooldowns:
            eq, tr = grid[(ts, cd)]
            m = calc_2025(eq, tr)
            if m is None:
                row += f" │ {'--':>10}"
            else:
                row += f" │ {m['cagr']:+9.2f}%"
        print(row)
    print(f"\n{'─'*62}")
    print(f"  2025+ 최대 수익 거래 (%)")
    print(f"{'─'*62}")
    print(f"  {'TRAIL':<6} │ {'CD=0':>10} │ {'CD=60':>10} │ {'CD=120':>10}")
    print("  " + "─"*45)
    for ts in trails:
        row = f"  {int(ts*100)}%    "
        for cd in cooldowns:
            eq, tr = grid[(ts, cd)]
            m = calc_2025(eq, tr)
            if m is None:
                row += f" │ {'--':>10}"
            else:
                row += f" │ {m['max_win']:+9.1f}%"
        print(row)

    # 참고용: 전 기간 기본 세팅 (T10/CD0) 만 지속적으로 사용하므로 관성 있는 이름 유지
    results = {
        f"T{int(ts*100)}/CD{cd}": grid[(ts, cd)]
        for ts in trails for cd in cooldowns
    }

    # 기간 분할 표 (전체 + 2015-2019 + 2020-2024 + 2025+)
    print_period_table(results, kospi_arr, all_dates)


    print(f"\n{'='*62}")
    print("  ※ pykrx 수정주가, 유니버스 검증 fail 61종목 제외")
    print("  ※ 생존편향: 2015년 기준 유니버스 고정 (이후 변동 미반영)")
    print("  ※ 기간 분할은 2015 시작 equity curve를 슬라이스 (리베이스)")
    print("=" * 62)


if __name__ == "__main__":
    main()
