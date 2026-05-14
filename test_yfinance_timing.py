"""
yfinance 한국 지수 데이터 가용 시간 측정 스크립트
실행: python3 test_yfinance_timing.py
매 실행마다 현재 시각 + 최신 반환 날짜를 기록 → 언제부터 전일 데이터가 잡히는지 파악
"""
import yfinance as yf
from datetime import datetime, timedelta
import pytz, json, os

KST = pytz.timezone("Asia/Seoul")
now = datetime.now(KST)
LOG_FILE = "yfinance_timing_log.jsonl"

def prev_trading_day():
    d = now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

prev = prev_trading_day()
results = {"time_kst": now.strftime("%Y-%m-%d %H:%M:%S"), "prev_trading_day": str(prev), "tickers": {}}

for ticker in ["^KS11", "^KQ11"]:
    try:
        hist = yf.Ticker(ticker).history(period="10d")
        closes = hist["Close"].dropna()
        if closes.empty:
            results["tickers"][ticker] = {"status": "empty"}
            continue
        latest_date = closes.index[-1].date()
        is_correct = (latest_date == prev)
        results["tickers"][ticker] = {
            "latest_date": str(latest_date),
            "latest_close": round(float(closes.iloc[-1]), 2),
            "correct": is_correct,
            "lag_days": (prev - latest_date).days,
        }
        flag = "✅" if is_correct else f"❌ ({(prev - latest_date).days}일 지연)"
        print(f"{ticker}: {latest_date} {closes.iloc[-1]:,.2f}  {flag}")
    except Exception as e:
        results["tickers"][ticker] = {"status": f"error: {e}"}
        print(f"{ticker}: 오류 — {e}")

print(f"\n기준 전거래일: {prev}")
print(f"측정 시각: {now.strftime('%H:%M KST')}")

with open(LOG_FILE, "a") as f:
    f.write(json.dumps(results, ensure_ascii=False) + "\n")
print(f"→ {LOG_FILE} 기록 완료")
