import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pytz

import yfinance as yf
from pykrx import stock
import anthropic

# ── 설정 ──────────────────────────────────────────
GMAIL_USER     = "sieun8475@gmail.com"
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SEND_TO        = "sieun8475@gmail.com"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일")

def prev_trading_day(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d

PREV_KR = prev_trading_day(NOW).strftime("%Y%m%d")

# ── 헬퍼 ──────────────────────────────────────────
def get_ma(series, n):
    if len(series) < n:
        return None
    return round(float(series.iloc[-n:].mean()), 0)

def yf_quote(sym):
    """yfinance로 종가·등락률 반환"""
    try:
        hist = yf.Ticker(sym).history(period="5d")
        if len(hist) >= 2:
            prev  = float(hist["Close"].iloc[-2])
            close = float(hist["Close"].iloc[-1])
            pct   = (close - prev) / prev * 100
            return {"close": round(close, 2), "pct": round(pct, 2)}
    except:
        pass
    return {"close": None, "pct": None}

def pykrx_col(df, keyword):
    """pykrx DataFrame에서 키워드 포함 컬럼명 반환"""
    df.columns = [c.strip() for c in df.columns]
    cols = [c for c in df.columns if keyword in c]
    return cols[0] if cols else None

# ── 1. 미장 데이터 (yfinance 전용) ────────────────
def get_us_data():
    symbols = {
        "S&P500":  "^GSPC",
        "나스닥":  "^IXIC",
        "다우":    "^DJI",
        "VIX":     "^VIX",
        "달러/원": "KRW=X",
        "WTI":     "CL=F",
        "금":      "GC=F",
    }
    result = {k: yf_quote(v) for k, v in symbols.items()}

    sectors = {
        "반도체": "SOXX",
        "테크":   "XLK",
        "에너지": "XLE",
        "금융":   "XLF",
        "헬스케어": "XLV",
    }
    result["섹터"] = {k: yf_quote(v)["pct"] for k, v in sectors.items()}
    return result

# ── 2. 국장 데이터 (pykrx + yfinance 혼용) ────────
def get_kr_data():
    result = {}
    try:
        # 코스피·코스닥 — yfinance (pykrx 지수 API 불안정)
        kospi_q  = yf_quote("^KS11")
        kosdaq_q = yf_quote("^KQ11")
        result["코스피"]       = kospi_q["close"]
        result["코스피_등락"]  = kospi_q["pct"]
        result["코스닥"]       = kosdaq_q["close"]
        result["코스닥_등락"]  = kosdaq_q["pct"]

        # 수급 — pykrx (거래소 공식)
        trading = stock.get_market_trading_volume_by_date(PREV_KR, PREV_KR, "KOSPI")
        if not trading.empty:
            trading.columns = [c.strip() for c in trading.columns]
            row = trading.iloc[-1]
            for key in ["외국인", "기관합계", "기관", "개인"]:
                if key in row:
                    result[key] = int(row[key])
    except Exception as e:
        result["error"] = str(e)
    return result

# ── 3. 체크리스트 스크리닝 ────────────────────────
FCF_UNIVERSE = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "035420",  # NAVER
    "051910",  # LG화학
    "068270",  # 셀트리온
    "028260",  # 삼성물산
    "105560",  # KB금융
    "055550",  # 신한지주
    "012330",  # 현대모비스
]

def screen_stocks():
    result    = []
    start200  = (NOW - timedelta(days=280)).strftime("%Y%m%d")
    start10   = (NOW - timedelta(days=14)).strftime("%Y%m%d")

    # 코스피 추세 — yfinance로 대체 (pykrx 지수 API 버그 회피)
    ks11 = yf.Ticker("^KS11").history(period="200d")
    if not ks11.empty:
        ks_close    = ks11["Close"]
        ks_ma60     = get_ma(ks_close, 60)
        ks_ma120    = get_ma(ks_close, 120)
        ks_now      = float(ks_close.iloc[-1])
        kospi_trend = bool(ks_ma60 and ks_ma120 and ks_now > ks_ma60 and ks_now > ks_ma120)
    else:
        kospi_trend = False

    # VIX
    vix_hist = yf.Ticker("^VIX").history(period="2d")
    vix_val  = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 99
    vix_ok   = vix_val < 20

    for code in FCF_UNIVERSE:
        try:
            name  = stock.get_market_ticker_name(code)
            ohlcv = stock.get_market_ohlcv_by_date(start200, PREV_KR, code)
            if ohlcv.empty or len(ohlcv) < 60:
                continue

            ohlcv.columns = [c.strip() for c in ohlcv.columns]
            close_col = pykrx_col(ohlcv, "종가")
            vol_col   = pykrx_col(ohlcv, "거래량")
            if not close_col or not vol_col:
                continue

            close_s   = ohlcv[close_col]
            vol_s     = ohlcv[vol_col]
            close_now = float(close_s.iloc[-1])

            ma20  = get_ma(close_s, 20)
            ma60  = get_ma(close_s, 60)
            ma120 = get_ma(close_s, 120)
            aligned = bool(ma20 and ma60 and ma120 and ma20 > ma60 > ma120)

            vol_now = float(vol_s.iloc[-1])
            vol_avg = float(vol_s.iloc[-21:-1].mean()) if len(vol_s) > 20 else vol_now
            vol_ok  = vol_now >= vol_avg * 1.5

            trading = stock.get_market_trading_volume_by_date(start10, PREV_KR, code)
            foreign_5d, foreign_ok = 0, False
            if not trading.empty:
                trading.columns = [c.strip() for c in trading.columns]
                fcol = pykrx_col(trading, "외국인")
                if fcol:
                    foreign_5d = int(trading[fcol].iloc[-5:].sum())
                    foreign_ok = foreign_5d > 0

            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

            score = sum([aligned, vol_ok, foreign_ok, kospi_trend, vix_ok])
            if score >= 4 and aligned:
                grade = "A"
            elif score >= 3:
                grade = "B"
            else:
                continue

            result.append({
                "종목명":       name,
                "종목코드":     code,
                "현재가":       int(close_now),
                "등급":         grade,
                "MA20":         int(ma20) if ma20 else 0,
                "MA60":         int(ma60) if ma60 else 0,
                "MA120":        int(ma120) if ma120 else 0,
                "이평선정배열": aligned,
                "거래량":       vol_ok,
                "외국인5일":    foreign_ok,
                "외국인순매수": foreign_5d,
                "코스피추세":   kospi_trend,
                "VIX안정":      vix_ok,
                "VIX":          round(vix_val, 2),
                "손절가":       int(stop),
                "목표가":       int(target),
            })
        except Exception as e:
            print(f"  {code} 스킵: {e}")
            continue

    result.sort(key=lambda x: (x["등급"], -x["현재가"]))
    return result, kospi_trend, round(vix_val, 2)

# ── 4. Claude API 분석 ────────────────────────────
def get_claude_analysis(us, kr, candidates):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def fmt(d, k):
        v = d.get(k, {})
        if isinstance(v, dict):
            c, p = v.get("close"), v.get("pct")
            sign = "+" if p and p > 0 else ""
            return f"{c:,.2f} ({sign}{p:.2f}%)" if c else "N/A"
        return str(v) if v else "N/A"

    cand_text = ""
    for c in candidates:
        cand_text += f"""
▶ {c['종목명']} ({c['종목코드']}) [{c['등급']}등급]
  현재가 {c['현재가']:,}원 | MA20 {c['MA20']:,} | MA60 {c['MA60']:,} | MA120 {c['MA120']:,}
  이평선정배열 {'✓' if c['이평선정배열'] else '✗'} | 거래량1.5배 {'✓' if c['거래량'] else '✗'} | 외국인5일순매수 {'✓' if c['외국인5일'] else '✗'} ({c['외국인순매수']:+,}주)
  손절가 {c['손절가']:,}원 (-7%) | 1차목표 {c['목표가']:,}원 (+18%)
"""
    if not cand_text:
        cand_text = "오늘 조건 충족 종목 없음 — 진입 보류"

    prompt = f"""오늘은 {TODAY_STR}입니다. 아래 데이터로 모닝 리포트를 작성해주세요.

【미장 — 뉴욕 전일 마감】
S&P500: {fmt(us,'S&P500')} | 나스닥: {fmt(us,'나스닥')} | 다우: {fmt(us,'다우')}
VIX: {us.get('VIX',{}).get('close')} | 달러/원: {us.get('달러/원',{}).get('close')} | WTI: {fmt(us,'WTI')} | 금: {fmt(us,'금')}
섹터: {us.get('섹터')}

【국내 시장 — 전일 마감】
코스피: {kr.get('코스피')} ({kr.get('코스피_등락')}%) | 코스닥: {kr.get('코스닥')} ({kr.get('코스닥_등락')}%)
외국인: {kr.get('외국인','N/A')} | 기관: {kr.get('기관합계', kr.get('기관','N/A'))} | 개인: {kr.get('개인','N/A')}

【스크리닝 결과】
{cand_text}

아래 순서로 작성해주세요 (출근길 5분 안에 읽을 수 있게 간결하게):

1. 📊 시황 요약 (3줄)
2. 🇺🇸 미장 핵심 포인트
3. 🇰🇷 국내 시장 분석
4. 📰 핵심 뉴스 3개 (①개원/부동산 ②의료정책 ③자산관리)
5. 📈 오늘 스크리닝 결과 및 진입 전략
6. 💡 오늘의 한 줄 인사이트
"""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

# ── 5. Gmail 발송 ─────────────────────────────────
def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = SEND_TO

    html = f"""<html><body style="font-family:sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#1A2033;">
<div style="background:#1A3A5C;color:white;padding:16px 20px;border-radius:10px 10px 0 0;">
  <h2 style="margin:0;font-size:18px;">📊 추세추종 모닝 리포트</h2>
  <p style="margin:4px 0 0;font-size:12px;color:#A0B0C8;">{TODAY_STR}</p>
</div>
<div style="background:#fff;border:1px solid #D8DEE9;border-top:none;border-radius:0 0 10px 10px;padding:20px;">
  <pre style="white-space:pre-wrap;font-size:13px;line-height:1.8;color:#1A2033;">{body}</pre>
</div>
<p style="font-size:10px;color:#8B95B0;text-align:center;margin-top:12px;">
본 리포트는 개인 투자 학습 목적입니다. 투자 판단의 최종 책임은 본인에게 있습니다.
</p></body></html>"""

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, SEND_TO, msg.as_string())
    print(f"✅ 발송 완료 → {SEND_TO}")

# ── 메인 ──────────────────────────────────────────
if __name__ == "__main__":
    print("📡 미장 데이터 수집 중...")
    us_data = get_us_data()

    print("📡 국장 데이터 수집 중...")
    kr_data = get_kr_data()

    print("📡 스크리닝 중...")
    candidates, kospi_trend, vix = screen_stocks()
    print(f"  → 후보 종목 {len(candidates)}개 | 코스피추세 {'✓' if kospi_trend else '✗'} | VIX {vix}")

    print("🤖 Claude 분석 중...")
    report = get_claude_analysis(us_data, kr_data, candidates)

    subject = f"[모닝리포트] {TODAY_STR} — 후보 {len(candidates)}종목"
    send_email(subject, report)
    print("🎉 완료!")
