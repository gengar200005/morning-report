import os
import smtplib
import json
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

KST = pytz.timezone("Asia/Seoul")
NOW = datetime.now(KST)
TODAY_STR  = NOW.strftime("%Y년 %m월 %d일")
TODAY_DATE = NOW.strftime("%Y%m%d")

# 전 거래일 (주말 처리)
def prev_trading_day(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d

PREV_KR = prev_trading_day(NOW).strftime("%Y%m%d")

# ── 1. 미장 데이터 (yfinance) ───────────────────────
def get_us_data():
    tickers = {
        "S&P500":  "^GSPC",
        "나스닥":  "^IXIC",
        "다우":    "^DJI",
        "VIX":     "^VIX",
        "달러/원": "KRW=X",
        "WTI":     "CL=F",
        "금":      "GC=F",
    }
    result = {}
    for name, sym in tickers.items():
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="2d")
            if len(hist) >= 2:
                prev  = hist["Close"].iloc[-2]
                close = hist["Close"].iloc[-1]
                chg   = close - prev
                pct   = chg / prev * 100
                result[name] = {
                    "close": round(close, 2),
                    "chg":   round(chg, 2),
                    "pct":   round(pct, 2),
                }
        except Exception as e:
            result[name] = {"error": str(e)}

    # 섹터 ETF
    sectors = {
        "반도체": "SOXX",
        "테크":   "XLK",
        "에너지": "XLE",
        "금융":   "XLF",
        "헬스케어": "XLV",
    }
    sector_result = {}
    for name, sym in sectors.items():
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="2d")
            if len(hist) >= 2:
                prev  = hist["Close"].iloc[-2]
                close = hist["Close"].iloc[-1]
                pct   = (close - prev) / prev * 100
                sector_result[name] = round(pct, 2)
        except:
            sector_result[name] = None
    result["섹터"] = sector_result
    return result

# ── 2. 국장 데이터 (pykrx) ─────────────────────────
def get_kr_data():
    result = {}
    try:
        # 코스피·코스닥 종가
        kospi  = stock.get_index_ohlcv_by_date(PREV_KR, PREV_KR, "1001")
        kosdaq = stock.get_index_ohlcv_by_date(PREV_KR, PREV_KR, "2001")
        result["코스피"]  = round(float(kospi["종가"].iloc[-1]), 2)  if not kospi.empty  else None
        result["코스닥"]  = round(float(kosdaq["종가"].iloc[-1]), 2) if not kosdaq.empty else None

        # 코스피 등락률
        kospi_hist = stock.get_index_ohlcv_by_date(
            (NOW - timedelta(days=7)).strftime("%Y%m%d"), PREV_KR, "1001"
        )
        if len(kospi_hist) >= 2:
            prev  = float(kospi_hist["종가"].iloc[-2])
            close = float(kospi_hist["종가"].iloc[-1])
            result["코스피_등락"] = round((close - prev) / prev * 100, 2)
        kosdaq_hist = stock.get_index_ohlcv_by_date(
            (NOW - timedelta(days=7)).strftime("%Y%m%d"), PREV_KR, "2001"
        )
        if len(kosdaq_hist) >= 2:
            prev  = float(kosdaq_hist["종가"].iloc[-2])
            close = float(kosdaq_hist["종가"].iloc[-1])
            result["코스닥_등락"] = round((close - prev) / prev * 100, 2)

        # 외국인·기관·개인 수급
        trading = stock.get_market_trading_volume_by_date(PREV_KR, PREV_KR, "KOSPI")
        if not trading.empty:
            row = trading.iloc[-1]
            result["외국인"] = int(row.get("외국인", 0))
            result["기관"]   = int(row.get("기관합계", 0))
            result["개인"]   = int(row.get("개인", 0))
    except Exception as e:
        result["error"] = str(e)
    return result

# ── 3. 체크리스트 스크리닝 (pykrx) ────────────────
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

def get_ma(prices, n):
    if len(prices) < n:
        return None
    return round(float(prices.iloc[-n:].mean()), 0)

def screen_stocks():
    result = []
    # 코스피 추세 확인
    kospi_hist = stock.get_index_ohlcv_by_date(
        (NOW - timedelta(days=200)).strftime("%Y%m%d"), PREV_KR, "1001"
    )
    kospi_close = kospi_hist["종가"]
    kospi_ma60  = get_ma(kospi_close, 60)
    kospi_ma120 = get_ma(kospi_close, 120)
    kospi_now   = float(kospi_close.iloc[-1])
    kospi_trend = kospi_now > kospi_ma60 and kospi_now > kospi_ma120

    # VIX
    vix_data = yf.Ticker("^VIX").history(period="2d")
    vix_val  = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else 99
    vix_ok   = vix_val < 20

    for code in FCF_UNIVERSE:
        try:
            name = stock.get_market_ticker_name(code)
            ohlcv = stock.get_market_ohlcv_by_date(
                (NOW - timedelta(days=200)).strftime("%Y%m%d"), PREV_KR, code
            )
            if ohlcv.empty or len(ohlcv) < 60:
                continue

            close_series = ohlcv["종가"]
            vol_series   = ohlcv["거래량"]
            close_now    = float(close_series.iloc[-1])

            ma20  = get_ma(close_series, 20)
            ma60  = get_ma(close_series, 60)
            ma120 = get_ma(close_series, 120)

            # 이평선 정배열
            aligned = ma20 and ma60 and ma120 and ma20 > ma60 > ma120

            # 거래량 1.5배
            vol_now = float(vol_series.iloc[-1])
            vol_avg = float(vol_series.iloc[-21:-1].mean())
            vol_ok  = vol_now >= vol_avg * 1.5

            # 외국인 5일 순매수
            trading = stock.get_market_trading_volume_by_date(
                (NOW - timedelta(days=10)).strftime("%Y%m%d"), PREV_KR, code
            )
            if not trading.empty and "외국인" in trading.columns:
                foreign_5d = int(trading["외국인"].iloc[-5:].sum())
                foreign_ok = foreign_5d > 0
            else:
                foreign_5d = 0
                foreign_ok = False

            # 손절가·목표가
            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

            # 필수 5개 통과 여부
            must_pass = all([True, True, kospi_trend, True, True])
            # (FCF·밸류는 수동 확인 항목 — 유니버스 편입 시 이미 검증됨)

            # 등급
            score = sum([aligned, vol_ok, foreign_ok, kospi_trend, vix_ok])
            if score >= 4 and aligned:
                grade = "A"
            elif score >= 3:
                grade = "B"
            else:
                continue  # C등급 이하 제외

            result.append({
                "종목명":      name,
                "종목코드":    code,
                "현재가":      int(close_now),
                "등급":        grade,
                "MA20":        int(ma20) if ma20 else None,
                "MA60":        int(ma60) if ma60 else None,
                "MA120":       int(ma120) if ma120 else None,
                "이평선정배열": aligned,
                "거래량":      vol_ok,
                "외국인5일":   foreign_ok,
                "외국인순매수": foreign_5d,
                "코스피추세":  kospi_trend,
                "VIX안정":    vix_ok,
                "VIX":        round(vix_val, 2),
                "손절가":      int(stop),
                "목표가":      int(target),
            })
        except Exception as e:
            print(f"{code} 오류: {e}")
            continue

    result.sort(key=lambda x: (x["등급"], -x["현재가"]))
    return result, kospi_trend, round(vix_val, 2)

# ── 4. Claude API 호출 ────────────────────────────
def get_claude_analysis(us_data, kr_data, candidates):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    candidates_text = ""
    if candidates:
        for c in candidates:
            candidates_text += f"""
- {c['종목명']} ({c['종목코드']}) [{c['등급']}등급]
  현재가: {c['현재가']:,}원 | MA20: {c['MA20']:,} | MA60: {c['MA60']:,} | MA120: {c['MA120']:,}
  이평선정배열: {'✓' if c['이평선정배열'] else '✗'} | 거래량1.5배: {'✓' if c['거래량'] else '✗'} | 외국인5일순매수: {'✓' if c['외국인5일'] else '✗'} ({c['외국인순매수']:+,}주)
  손절가: {c['손절가']:,}원 (-7%) | 1차목표: {c['목표가']:,}원 (+18%)
"""
    else:
        candidates_text = "오늘 조건 충족 종목 없음"

    prompt = f"""
오늘은 {TODAY_STR}입니다. 아래 데이터를 바탕으로 모닝 리포트를 작성해주세요.

## 미장 데이터 (뉴욕 전일 마감)
- S&P500: {us_data.get('S&P500', {}).get('close')} ({us_data.get('S&P500', {}).get('pct')}%)
- 나스닥: {us_data.get('나스닥', {}).get('close')} ({us_data.get('나스닥', {}).get('pct')}%)
- 다우: {us_data.get('다우', {}).get('close')} ({us_data.get('다우', {}).get('pct')}%)
- VIX: {us_data.get('VIX', {}).get('close')}
- 달러/원: {us_data.get('달러/원', {}).get('close')}
- WTI: {us_data.get('WTI', {}).get('close')} ({us_data.get('WTI', {}).get('pct')}%)
- 금: {us_data.get('금', {}).get('close')} ({us_data.get('금', {}).get('pct')}%)
- 섹터별: {us_data.get('섹터')}

## 국내 시장 (전일 마감)
- 코스피: {kr_data.get('코스피')} ({kr_data.get('코스피_등락')}%)
- 코스닥: {kr_data.get('코스닥')} ({kr_data.get('코스닥_등락')}%)
- 외국인: {kr_data.get('외국인'):,}백만원
- 기관: {kr_data.get('기관'):,}백만원
- 개인: {kr_data.get('개인'):,}백만원

## 오늘 스크리닝 후보
{candidates_text}

아래 형식으로 작성해주세요:

1. 당일 시황 요약 (3줄)
2. 미장 핵심 포인트 (섹터별 등락 포함)
3. 국내 시장 분석 (수급 포함)
4. 핵심 뉴스 3개 (개원/부동산, 의료정책, 자산관리 관련)
5. 스크리닝 결과 및 종목별 진입 전략 (후보 없으면 "오늘 진입 보류" 명시)
6. 오늘의 한 줄 인사이트

간결하고 실용적으로, 출근길 5분 안에 읽을 수 있게 작성해주세요.
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

# ── 5. Gmail 발송 ─────────────────────────────────
def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = SEND_TO

    html = f"""
<html><body style="font-family: 'Noto Sans KR', sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #1A2033;">
<div style="background: #1A3A5C; color: white; padding: 16px 20px; border-radius: 10px 10px 0 0;">
  <h2 style="margin:0; font-size:18px;">📊 추세추종 모닝 리포트</h2>
  <p style="margin:4px 0 0; font-size:12px; color:#A0B0C8;">{TODAY_STR}</p>
</div>
<div style="background: #fff; border: 1px solid #D8DEE9; border-top: none; border-radius: 0 0 10px 10px; padding: 20px;">
  <pre style="white-space: pre-wrap; font-family: 'Noto Sans KR', sans-serif; font-size: 13px; line-height: 1.8; color: #1A2033;">{body}</pre>
</div>
<p style="font-size: 10px; color: #8B95B0; text-align: center; margin-top: 12px;">
본 리포트는 개인 투자 학습 목적입니다. 투자 판단의 최종 책임은 본인에게 있습니다.
</p>
</body></html>
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, SEND_TO, msg.as_string())
    print(f"✅ 이메일 발송 완료: {SEND_TO}")

# ── 메인 ──────────────────────────────────────────
if __name__ == "__main__":
    print("📡 데이터 수집 중...")
    us_data    = get_us_data()
    kr_data    = get_kr_data()
    candidates, kospi_trend, vix = screen_stocks()

    print(f"✅ 미장·국장 수집 완료 | 후보 종목: {len(candidates)}개")

    print("🤖 Claude 분석 중...")
    report = get_claude_analysis(us_data, kr_data, candidates)

    subject = f"[모닝리포트] {TODAY_STR} — 후보 {len(candidates)}종목"
    send_email(subject, report)
    print("🎉 완료!")
