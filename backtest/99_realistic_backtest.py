"""
KOSPI 백테스트 — 원래 전략 (MA20/60/120 + 거래량1.5배) + 트레일링 스탑
현실 보정: 익일시가 진입/청산, 거래비용 0.3%, 매일 체크
Colab: !pip install yfinance pandas numpy -q
"""

import pandas as pd
import numpy as np
import yfinance as yf

START_DATE = "2018-01-01"
END_DATE   = "2025-12-31"

STOP_LOSS  = 0.07
TRAIL_STOP = 0.10
MAX_HOLD   = 252
MAX_POSITIONS = 5
COST = 0.0015

KOSPI_UNIVERSE = [
    ("005930.KS", "삼성전자"),      ("000660.KS", "SK하이닉스"),
    ("373220.KS", "LG에너지솔루션"),("207940.KS", "삼성바이오로직스"),
    ("005380.KS", "현대차"),        ("000270.KS", "기아"),
    ("051910.KS", "LG화학"),        ("006400.KS", "삼성SDI"),
    ("035420.KS", "NAVER"),         ("105560.KS", "KB금융"),
    ("055550.KS", "신한지주"),      ("012330.KS", "현대모비스"),
    ("028260.KS", "삼성물산"),      ("003550.KS", "LG"),
    ("086790.KS", "하나금융지주"),  ("034730.KS", "SK"),
    ("096770.KS", "SK이노베이션"),  ("017670.KS", "SK텔레콤"),
    ("316140.KS", "우리금융지주"),  ("032830.KS", "삼성생명"),
    ("000810.KS", "삼성화재"),      ("003670.KS", "포스코홀딩스"),
    ("066570.KS", "LG전자"),        ("030200.KS", "KT"),
    ("015760.KS", "한국전력"),      ("035720.KS", "카카오"),
    ("012450.KS", "한화에어로스페이스"),("009150.KS", "삼성전기"),
    ("032640.KS", "LG유플러스"),    ("090430.KS", "아모레퍼시픽"),
    ("010950.KS", "S-Oil"),         ("003490.KS", "대한항공"),
    ("011170.KS", "롯데케미칼"),    ("047810.KS", "한국항공우주"),
    ("042660.KS", "한화오션"),      ("034020.KS", "두산에너빌리티"),
    ("259960.KS", "크래프톤"),      ("036570.KS", "엔씨소프트"),
    ("021240.KS", "코웨이"),        ("128940.KS", "한미약품"),
    ("000100.KS", "유한양행"),      ("068270.KS", "셀트리온"),
    ("018260.KS", "삼성에스디에스"),("010130.KS", "고려아연"),
    ("004020.KS", "현대제철"),      ("073240.KS", "금호석유"),
    ("024110.KS", "IBK기업은행"),   ("000720.KS", "현대건설"),
    ("011070.KS", "LG이노텍"),      ("004170.KS", "신세계"),
    ("047050.KS", "포스코인터내셔널"),("001450.KS", "현대해상"),
    ("078930.KS", "GS"),            ("036460.KS", "한국가스공사"),
    ("010140.KS", "삼성중공업"),    ("033780.KS", "KT&G"),
    ("006800.KS", "미래에셋증권"),  ("352820.KS", "하이브"),
    ("267250.KS", "HD현대"),        ("329180.KS", "HD현대중공업"),
    ("241560.KS", "두산밥캣"),      ("338220.KS", "에코프로비엠"),
    ("247540.KS", "에코프로"),      ("282330.KS", "BGF리테일"),
    ("007070.KS", "GS리테일"),      ("003230.KS", "삼양식품"),
    ("271560.KS", "오리온"),        ("030000.KS", "제일기획"),
    ("000150.KS", "두산"),          ("006360.KS", "GS건설"),
    ("326030.KS", "SK바이오팜"),    ("302440.KS", "SK바이오사이언스"),
    ("011790.KS", "SKC"),           ("029780.KS", "삼성카드"),
    ("005870.KS", "한화생명"),      ("016360.KS", "삼성증권"),
    ("005830.KS", "DB손해보험"),    ("000080.KS", "하이트진로"),
    ("161390.KS", "한국타이어앤테크놀로지"),("004990.KS", "롯데지주"),
    ("010060.KS", "OCI"),           ("042670.KS", "HD현대인프라코어"),
    ("004000.KS", "롯데정밀화학"),  ("000990.KS", "DB하이텍"),
    ("023530.KS", "롯데쇼핑"),      ("002790.KS", "아모레퍼시픽그룹"),
    ("009830.KS", "한화솔루션"),    ("001120.KS", "LX인터내셔널"),
    ("251270.KS", "넷마블"),        ("041510.KS", "에스엠"),
    ("035900.KS", "JYP엔터테인먼트"),("018880.KS", "한온시스템"),
    ("139480.KS", "이마트"),        ("011200.KS", "HMM"),
    ("009540.KS", "한진칼"),        ("034230.KS", "파라다이스"),
    ("003380.KS", "하림지주"),
    ("097950.KS", "CJ제일제당"),    ("000120.KS", "CJ대한통운"),
    ("001040.KS", "CJ"),            ("005300.KS", "롯데칠성"),
    ("280360.KS", "롯데웰푸드"),    ("004370.KS", "농심"),
    ("007310.KS", "오뚜기"),        ("008770.KS", "호텔신라"),
    ("000215.KS", "DL이앤씨"),      ("000210.KS", "DL"),
    ("138040.KS", "메리츠금융지주"),("000060.KS", "메리츠화재"),
    ("005940.KS", "NH투자증권"),    ("071050.KS", "한국금융지주"),
    ("039490.KS", "키움증권"),      ("377300.KS", "카카오페이"),
    ("293490.KS", "카카오뱅크"),    ("000880.KS", "한화"),
    ("272210.KS", "한화시스템"),    ("079550.KS", "LIG넥스원"),
    ("010120.KS", "LS ELECTRIC"),   ("006260.KS", "LS"),
    ("298040.KS", "효성중공업"),    ("298000.KS", "효성티앤씨"),
    ("004800.KS", "효성"),          ("022100.KS", "포스코DX"),
    ("000070.KS", "삼양홀딩스"),    ("192820.KS", "코스맥스"),
    ("051600.KS", "한전KPS"),       ("028050.KS", "삼성엔지니어링"),
    ("012750.KS", "에스원"),        ("001740.KS", "SK네트웍스"),
    ("007700.KS", "F&F"),           ("035250.KS", "강원랜드"),
    ("069960.KS", "현대백화점"),    ("057050.KS", "현대홈쇼핑"),
    ("010620.KS", "현대미포조선"),  ("014680.KS", "한솔케미칼"),
    ("085620.KS", "미래에셋생명"),  ("000370.KS", "한화손해보험"),
    ("006120.KS", "SK디스커버리"),  ("001230.KS", "동국제강"),
    ("017800.KS", "현대엘리베이터"),("003410.KS", "쌍용C&E"),
    ("000670.KS", "영풍"),          ("001680.KS", "대상"),
    ("032350.KS", "롯데렌탈"),      ("114090.KS", "GKL"),
    ("267270.KS", "현대건설기계"),  ("111770.KS", "영원무역"),
    ("009970.KS", "영원무역홀딩스"),("004490.KS", "세방전지"),
    ("009240.KS", "한샘"),          ("192400.KS", "쿠쿠홀딩스"),
    ("204320.KS", "만도"),          ("012630.KS", "HDC"),
    ("294870.KS", "HDC현대산업개발"),("005960.KS", "동원F&B"),
    ("008560.KS", "메리츠증권"),    ("010780.KS", "아이에스동서"),
    ("002350.KS", "넥센타이어"),    ("002410.KS", "한진"),
    ("003690.KS", "코리안리"),      ("005610.KS", "SPC삼립"),
    ("008930.KS", "한미사이언스"),  ("006650.KS", "대한유화"),
    ("000240.KS", "한국앤컴퍼니"),  ("014820.KS", "동원시스템즈"),
    ("001800.KS", "오리온홀딩스"),  ("005490.KS", "POSCO"),
    ("079960.KS", "동양생명"),
]


def check_signal(c, v, i):
    if i < 121:
        return False
    cur   = c[i]
    ma20  = c[i-20:i].mean()
    ma60  = c[i-60:i].mean()
    ma120 = c[i-120:i].mean()
    if not (cur > ma20 > ma60 > ma120):
        return False
    vol_avg = v[i-20:i].mean()
    return vol_avg > 0 and v[i] >= vol_avg * 1.5


def supply_proxy(c, v, i):
    if i < 21:
        return False
    up_vol, dn_vol = 0.0, 0.0
    for j in range(i - 20, i):
        if c[j] > c[j - 1]:
            up_vol += v[j]
        else:
            dn_vol += v[j]
    return (up_vol / dn_vol if dn_vol > 0 else 999) >= 1.2


def run_portfolio(all_dates, stock_arr, kospi_arr):
    n_days = len(all_dates)
    cash = 1.0
    positions = {}
    pending_entry = []
    pending_exit = []
    equity_curve = []
    trade_log = []

    for i in range(121, n_days):
        for tk, sig_i in pending_entry:
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
                "exit_date": all_dates[i],
                "ticker": tk,
                "ret": round(ret * 100, 2),
                "hold_days": i - pos["entry_i"],
                "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
        pending_exit = []

        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue
            price = c[i]
            pos["peak"] = max(pos["peak"], price)
            stop = pos["entry_price"] * (1 - STOP_LOSS)
            trail = pos["peak"] * (1 - TRAIL_STOP)
            if price <= max(stop, trail):
                reason = "trailing" if trail >= stop else "stop_loss"
                pending_exit.append((tk, reason))
            elif i - pos["entry_i"] >= MAX_HOLD:
                pending_exit.append((tk, "max_hold"))

        open_slots = MAX_POSITIONS - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days:
            candidates = []
            for tk, (c, o, v) in stock_arr.items():
                if tk in positions or i >= len(c) or c[i] <= 0:
                    continue
                if any(tk == e[0] for e in pending_entry):
                    continue
                if check_signal(c, v, i):
                    sup = 1 if supply_proxy(c, v, i) else 0
                    candidates.append((tk, sup, float(c[i])))
            candidates.sort(key=lambda x: (-x[1], -x[2]))
            for tk, _, _ in candidates[:open_slots]:
                pending_entry.append((tk, i))

        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-COST) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100,2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })

    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


def print_result(eq_df, trade_df, kospi_arr, all_dates):
    if trade_df.empty:
        print("  거래 없음"); return
    eq = eq_df.set_index("date")["equity"]
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    mdd = dd.min()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/years) - 1

    k_s = list(all_dates).index(eq.index[0])
    k_e = list(all_dates).index(eq.index[-1])
    k_cagr = (kospi_arr[k_e]/kospi_arr[k_s])**(1/years)-1
    ks = pd.Series(kospi_arr[k_s:k_e+1], index=all_dates[k_s:k_e+1])
    k_mdd = ((ks-ks.cummax())/ks.cummax()*100).min()

    r = trade_df["ret"]
    wins = trade_df[r>0]; losses = trade_df[r<=0]
    aw = wins["ret"].mean() if len(wins) else 0
    al = abs(losses["ret"].mean()) if len(losses) else 1
    pf = wins["ret"].sum()/abs(losses["ret"].sum()) if losses["ret"].sum()!=0 else 0

    print(f"\n  ── 포트폴리오 ──")
    print(f"  CAGR: {cagr*100:+.2f}%  누적: {(eq.iloc[-1]/eq.iloc[0]-1)*100:+.1f}%  ({years:.1f}년)")
    print(f"  MDD:  {mdd:.2f}%")
    print(f"  코스피: CAGR {k_cagr*100:+.2f}%  MDD {k_mdd:.1f}%")
    print(f"\n  ── 거래 ──")
    print(f"  총 {len(trade_df)}건  승률 {(r>0).mean()*100:.1f}%  손익비 {aw/al:.2f}x  PF {pf:.2f}")
    print(f"  평균보유 {trade_df['hold_days'].mean():.0f}일  평균수익 {aw:+.1f}%  평균손실 {losses['ret'].mean():+.1f}%")

    print(f"\n  ── 청산 사유 ──")
    for reason in ["stop_loss","trailing","max_hold","final"]:
        cnt=(trade_df["reason"]==reason).sum()
        if cnt:
            ar=trade_df[trade_df["reason"]==reason]["ret"].mean()
            lb={"stop_loss":"손절","trailing":"트레일링","max_hold":"만기","final":"최종"}[reason]
            print(f"  {lb:<8} {cnt:>4}건 ({cnt/len(trade_df)*100:.1f}%)  평균 {ar:+.2f}%")

    print(f"\n  ── 연도별 ──")
    eq_yr = eq.resample("YE").last()
    for j in range(len(eq_yr)):
        yr = eq_yr.index[j].year
        prev = eq.iloc[0] if j==0 else eq_yr.iloc[j-1]
        yr_r = (eq_yr.iloc[j]/prev-1)*100
        yt = trade_df[trade_df["exit_date"].dt.year==yr]
        wr = (yt["ret"]>0).mean()*100 if len(yt) else 0
        print(f"  {yr}: {'▲' if yr_r>0 else '▼'} {yr_r:+.2f}%  ({len(yt)}건, 승률 {wr:.0f}%)")


print("="*62)
print(f"  원래 전략 (MA20/60/120 + vol1.5x) + 트레일링 스탑")
print(f"  현실 보정 | 익일시가 | 비용 {COST*2*100:.1f}% | 최대 {MAX_POSITIONS}종목")
print(f"  기간: {START_DATE}~{END_DATE} | 유니버스: {len(KOSPI_UNIVERSE)}종목")
print("="*62)

tickers = list(dict.fromkeys(tk for tk,_ in KOSPI_UNIVERSE))
print(f"\n[1/3] 다운로드 ({len(tickers)}종목)...")
raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                  auto_adjust=True, group_by="ticker", threads=True, progress=True)
raw.index = raw.index.tz_localize(None)

stock_data = {}
for tk in tickers:
    try:
        df = raw[tk].dropna(how="all")
        if len(df) >= 200: stock_data[tk] = df
    except: pass
print(f"  → 유효 {len(stock_data)}종목")

print("\n[2/3] 코스피...")
kdf = yf.Ticker("^KS11").history(start=START_DATE, end=END_DATE, auto_adjust=True)
kdf.index = kdf.index.tz_localize(None)
all_dates = sorted(kdf.index.normalize())
kospi_arr = kdf["Close"].reindex(pd.DatetimeIndex(all_dates)).ffill().values.astype(float)

stock_arr = {}
for tk, df in stock_data.items():
    idx = pd.DatetimeIndex(all_dates)
    c = df["Close"].reindex(idx).ffill().fillna(0).values.astype(float)
    o = df["Open"].reindex(idx).ffill().fillna(0).values.astype(float)
    v = df["Volume"].reindex(idx).ffill().fillna(0).values.astype(float)
    stock_arr[tk] = (c, o, v)

print(f"\n[3/3] 시뮬레이션...")
eq_df, trade_df = run_portfolio(all_dates, stock_arr, kospi_arr)

print(f"\n{'━'*62}")
print_result(eq_df, trade_df, kospi_arr, all_dates)
print(f"\n{'='*62}")
print(f"  ✓ 익일시가 진입/청산 | ✓ 비용 0.3% | ✓ 수급프록시는 정렬용만")
print(f"  ※ 생존편향 있음")
print(f"{'='*62}")

# 코스피 MA60 게이트 추가 — 코스피가 60일선 아래면 신규 진입 금지
def kospi_above_ma60(kospi_arr, i):
    if i < 60:
        return False
    ma60 = kospi_arr[i-60:i].mean()
    return kospi_arr[i] > ma60

# run_portfolio 내부 신호 탐색 부분만 수정 — 전체 재실행 필요
# "open_slots > 0 and i + 1 < n_days:" 아래에 게이트 추가

def run_portfolio(all_dates, stock_arr, kospi_arr):
    n_days = len(all_dates)
    cash = 1.0
    positions = {}
    pending_entry = []
    pending_exit = []
    equity_curve = []
    trade_log = []

    for i in range(121, n_days):
        for tk, sig_i in pending_entry:
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
                "exit_date": all_dates[i],
                "ticker": tk,
                "ret": round(ret * 100, 2),
                "hold_days": i - pos["entry_i"],
                "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
        pending_exit = []

        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue
            price = c[i]
            pos["peak"] = max(pos["peak"], price)
            stop = pos["entry_price"] * (1 - STOP_LOSS)
            trail = pos["peak"] * (1 - TRAIL_STOP)
            if price <= max(stop, trail):
                reason = "trailing" if trail >= stop else "stop_loss"
                pending_exit.append((tk, reason))
            elif i - pos["entry_i"] >= MAX_HOLD:
                pending_exit.append((tk, "max_hold"))

        # ★ 게이트: 코스피 > MA60일 때만 신규 진입
        gate_open = kospi_above_ma60(kospi_arr, i)

        open_slots = MAX_POSITIONS - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            candidates = []
            for tk, (c, o, v) in stock_arr.items():
                if tk in positions or i >= len(c) or c[i] <= 0:
                    continue
                if any(tk == e[0] for e in pending_entry):
                    continue
                if check_signal(c, v, i):
                    sup = 1 if supply_proxy(c, v, i) else 0
                    candidates.append((tk, sup, float(c[i])))
            candidates.sort(key=lambda x: (-x[1], -x[2]))
            for tk, _, _ in candidates[:open_slots]:
                pending_entry.append((tk, i))

        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-COST) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100,2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })

    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)

# 재실행
print("[3/3] 시뮬레이션 (코스피 MA60 게이트 적용)...")
eq_df, trade_df = run_portfolio(all_dates, stock_arr, kospi_arr)

print(f"\n{'━'*62}")
print(f"  원래 전략 + 트레일링 + 코스피MA60 게이트")
print(f"{'━'*62}")
print_result(eq_df, trade_df, kospi_arr, all_dates)

# 게이트가 닫힌 기간 확인
gate_closed = sum(1 for i in range(60, len(all_dates))
                  if not kospi_above_ma60(kospi_arr, i))
print(f"\n  게이트 닫힌 날: {gate_closed}일 / 전체 {len(all_dates)-60}일 ({gate_closed/(len(all_dates)-60)*100:.0f}%)")


# =============================================================
# Minervini + 수급 + 코스피MA60 게이트
# =============================================================
def check_minervini_supply(c, v, i, rs_pct=None):
    if i < 252:
        return False
    cur      = c[i]
    ma50     = c[i-50:i].mean()
    ma150    = c[i-150:i].mean()
    ma200    = c[i-200:i].mean()
    ma200_1m = c[i-252:i-22].mean()
    hi52     = c[max(0,i-252):i].max()
    lo52     = c[max(0,i-252):i].min()
    conds = [
        cur > ma50, cur > ma150, cur > ma200,
        ma50 > ma150, ma150 > ma200, ma200 > ma200_1m,
        cur >= lo52 * 1.25, cur >= hi52 * 0.75,
    ]
    if rs_pct is not None:
        conds.append(rs_pct >= 70)
    if not all(conds):
        return False
    # 수급 프록시
    if i < 21:
        return False
    up_vol, dn_vol = 0.0, 0.0
    for j in range(i - 20, i):
        if c[j] > c[j - 1]:
            up_vol += v[j]
        else:
            dn_vol += v[j]
    return (up_vol / dn_vol if dn_vol > 0 else 999) >= 1.2


def run_minervini_portfolio(all_dates, stock_arr, kospi_arr):
    n_days = len(all_dates)
    cash = 1.0
    positions = {}
    pending_entry = []
    pending_exit = []
    equity_curve = []
    trade_log = []

    for i in range(252, n_days):
        for tk, sig_i in pending_entry:
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
                "exit_date": all_dates[i],
                "ticker": tk,
                "ret": round(ret * 100, 2),
                "hold_days": i - pos["entry_i"],
                "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
        pending_exit = []

        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue
            price = c[i]
            pos["peak"] = max(pos["peak"], price)
            stop = pos["entry_price"] * (1 - STOP_LOSS)
            trail = pos["peak"] * (1 - TRAIL_STOP)
            if price <= max(stop, trail):
                reason = "trailing" if trail >= stop else "stop_loss"
                pending_exit.append((tk, reason))
            elif i - pos["entry_i"] >= MAX_HOLD:
                pending_exit.append((tk, "max_hold"))

        # ★ 게이트: 코스피 > MA60
        gate_open = kospi_above_ma60(kospi_arr, i)

        open_slots = MAX_POSITIONS - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            # RS 계산
            rets = {}
            for tk, (c, o, v) in stock_arr.items():
                if i < len(c) and c[i] > 0 and i >= 252 and c[i-252] > 0:
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
                if check_minervini_supply(c, v, i, rs_map.get(tk)):
                    candidates.append((tk, rs_map.get(tk, 0)))
            candidates.sort(key=lambda x: -x[1])
            for tk, _ in candidates[:open_slots]:
                pending_entry.append((tk, i))

        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-COST) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100,2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })

    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


print("[3/3] Minervini+수급+게이트 시뮬레이션...")
eq_df2, trade_df2 = run_minervini_portfolio(all_dates, stock_arr, kospi_arr)

print(f"\n{'━'*62}")
print(f"  Minervini+수급 + 코스피MA60 게이트")
print(f"{'━'*62}")
print_result(eq_df2, trade_df2, kospi_arr, all_dates)

# CMA 금리 반영 버전
CMA_ANNUAL = 0.03  # 연 3% (보수적 가정)
CMA_DAILY = (1 + CMA_ANNUAL) ** (1/365) - 1

def run_minervini_cma(all_dates, stock_arr, kospi_arr):
    n_days = len(all_dates)
    cash = 1.0
    positions = {}
    pending_entry = []
    pending_exit = []
    equity_curve = []
    trade_log = []

    for i in range(252, n_days):
        # 현금에 CMA 일일 이자 적용
        cash *= (1 + CMA_DAILY)

        for tk, sig_i in pending_entry:
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
                "exit_date": all_dates[i],
                "ticker": tk,
                "ret": round(ret * 100, 2),
                "hold_days": i - pos["entry_i"],
                "reason": reason,
            })
            cash += pos["shares"] * exit_price
            del positions[tk]
        pending_exit = []

        for tk, pos in list(positions.items()):
            c, o, v = stock_arr[tk]
            if i >= len(c) or c[i] <= 0:
                continue
            price = c[i]
            pos["peak"] = max(pos["peak"], price)
            stop = pos["entry_price"] * (1 - STOP_LOSS)
            trail = pos["peak"] * (1 - TRAIL_STOP)
            if price <= max(stop, trail):
                reason = "trailing" if trail >= stop else "stop_loss"
                pending_exit.append((tk, reason))
            elif i - pos["entry_i"] >= MAX_HOLD:
                pending_exit.append((tk, "max_hold"))

        gate_open = kospi_above_ma60(kospi_arr, i)
        open_slots = MAX_POSITIONS - len(positions) + len(pending_exit)
        if open_slots > 0 and i + 1 < n_days and gate_open:
            rets = {}
            for tk, (c, o, v) in stock_arr.items():
                if i < len(c) and c[i] > 0 and i >= 252 and c[i-252] > 0:
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
                if check_minervini_supply(c, v, i, rs_map.get(tk)):
                    candidates.append((tk, rs_map.get(tk, 0)))
            candidates.sort(key=lambda x: -x[1])
            for tk, _ in candidates[:open_slots]:
                pending_entry.append((tk, i))

        port_value = cash
        for tk, pos in positions.items():
            c, o, v = stock_arr[tk]
            if i < len(c) and c[i] > 0:
                port_value += pos["shares"] * c[i]
        equity_curve.append({"date": all_dates[i], "equity": port_value})

    for tk, pos in list(positions.items()):
        c, o, v = stock_arr[tk]
        if n_days-1 < len(c) and c[n_days-1] > 0:
            ret = c[n_days-1]*(1-COST) / pos["entry_price"] - 1
            trade_log.append({
                "entry_date": all_dates[pos["entry_i"]],
                "exit_date": all_dates[n_days-1],
                "ticker": tk, "ret": round(ret*100,2),
                "hold_days": n_days-1-pos["entry_i"], "reason": "final",
            })
    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)

print("Minervini+게이트+CMA 3% 시뮬레이션...")
eq_cma, trade_cma = run_minervini_cma(all_dates, stock_arr, kospi_arr)

print(f"\n{'━'*62}")
print(f"  Minervini+수급+게이트 + CMA 연 {CMA_ANNUAL*100:.0f}%")
print(f"{'━'*62}")
print_result(eq_cma, trade_cma, kospi_arr, all_dates)
