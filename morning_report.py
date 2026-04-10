import os
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pytz

import yfinance as yf

# ── 설정 ──────────────────────────────────────────
GMAIL_USER     = "sieun8475@gmail.com"
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SEND_TO        = "sieun8475@gmail.com"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

# ── 헬퍼 ──────────────────────────────────────────
def q(sym, period="5d"):
    """종가·등락률·등락폭 반환"""
    try:
        hist = yf.Ticker(sym).history(period=period)
        if len(hist) >= 2:
            prev  = float(hist["Close"].iloc[-2])
            close = float(hist["Close"].iloc[-1])
            chg   = close - prev
            pct   = chg / prev * 100
            return {
                "close": round(close, 2),
                "chg":   round(chg, 2),
                "pct":   round(pct, 2),
            }
    except:
        pass
    return {"close": None, "chg": None, "pct": None}

def arrow(pct):
    if pct is None: return "–"
    return "▲" if pct >= 0 else "▼"

def fmt_pct(pct):
    if pct is None: return "N/A"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"

def fmt_price(val, decimals=2):
    if val is None: return "N/A"
    return f"{val:,.{decimals}f}"

# ── 1. 주요 지수 ───────────────────────────────────
def get_indices():
    return {
        "S&P500":  q("^GSPC"),
        "나스닥":  q("^IXIC"),
        "다우":    q("^DJI"),
        "러셀2000": q("^RUT"),
    }

# ── 2. 공포탐욕지수 ────────────────────────────────
def get_fear_greed():
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        data = r.json()
        score = round(float(data["fear_and_greed"]["score"]), 1)
        rating = data["fear_and_greed"]["rating"]
        rating_kr = {
            "Extreme Fear": "극단적 공포",
            "Fear": "공포",
            "Neutral": "중립",
            "Greed": "탐욕",
            "Extreme Greed": "극단적 탐욕",
        }.get(rating, rating)
        return {"score": score, "rating": rating_kr}
    except:
        return {"score": None, "rating": "N/A"}

# ── 3. 금리·달러 ───────────────────────────────────
def get_rates():
    return {
        "미국채10년": q("^TNX"),
        "미국채2년":  q("^IRX"),
        "달러인덱스": q("DX-Y.NYB"),
        "달러/원":    q("KRW=X"),
        "달러/엔":    q("JPY=X"),
    }

# ── 4. 원자재 ──────────────────────────────────────
def get_commodities():
    return {
        "WTI":   q("CL=F"),
        "브렌트": q("BZ=F"),
        "금":    q("GC=F"),
        "은":    q("SI=F"),
    }

# ── 5. VIX ────────────────────────────────────────
def get_vix():
    return q("^VIX")

# ── 6. 반도체·M7 개별주 ───────────────────────────
def get_tech_stocks():
    semis = {
        "엔비디아":    "NVDA",
        "TSMC":        "TSM",
        "ASML":        "ASML",
        "AMD":         "AMD",
        "인텔":        "INTC",
        "삼성ADR":     "SSNLF",
        "SK하이닉스ADR": "HXSCL",
    }
    m7 = {
        "애플":     "AAPL",
        "마이크로소프트": "MSFT",
        "아마존":   "AMZN",
        "알파벳":   "GOOGL",
        "메타":     "META",
        "테슬라":   "TSLA",
        "엔비디아": "NVDA",
    }
    return {
        "반도체": {k: q(v) for k, v in semis.items()},
        "M7":     {k: q(v) for k, v in m7.items()},
    }

# ── 7. 섹터 ETF ────────────────────────────────────
def get_sectors():
    sectors = {
        "반도체(SOXX)":  "SOXX",
        "테크(XLK)":     "XLK",
        "에너지(XLE)":   "XLE",
        "금융(XLF)":     "XLF",
        "헬스케어(XLV)": "XLV",
        "소비재(XLY)":   "XLY",
        "유틸리티(XLU)": "XLU",
    }
    return {k: q(v) for k, v in sectors.items()}

# ── 이메일 본문 생성 ───────────────────────────────
def build_body(indices, fg, rates, comms, vix, tech, sectors):
    lines = []
    lines.append(f"{'='*50}")
    lines.append(f"  미장 데이터 브리핑 — {TODAY_STR}")
    lines.append(f"  (뉴욕 전일 마감 기준)")
    lines.append(f"{'='*50}")

    # 공포탐욕
    fg_score = fg['score']
    fg_bar   = ""
    if fg_score:
        filled = int(fg_score / 10)
        fg_bar = "█" * filled + "░" * (10 - filled)
        fg_emoji = "😱" if fg_score < 25 else "😰" if fg_score < 45 else "😐" if fg_score < 55 else "😏" if fg_score < 75 else "🤑"
    lines.append(f"\n【 공포탐욕지수 】")
    lines.append(f"  {fg_emoji} {fg_score} / 100  [{fg_bar}]  {fg['rating']}")
    lines.append(f"  ※ 25이하=매수기회 / 75이상=과열주의")

    # 3대지수
    lines.append(f"\n【 주요 지수 】")
    for name, d in indices.items():
        a = arrow(d['pct'])
        lines.append(f"  {name:<10} {fmt_price(d['close']):>12}  {a} {fmt_pct(d['pct'])}")

    # VIX
    vix_comment = "안정" if vix['close'] and vix['close'] < 20 else "주의" if vix['close'] and vix['close'] < 30 else "위험"
    lines.append(f"\n【 VIX (변동성) 】")
    lines.append(f"  {fmt_price(vix['close'])}  [{vix_comment}]  ※ 20이하=안정 / 30이상=위험")

    # 금리·달러
    lines.append(f"\n【 금리·달러 】")
    for name, d in rates.items():
        a = arrow(d['pct'])
        lines.append(f"  {name:<12} {fmt_price(d['close']):>10}  {a} {fmt_pct(d['pct'])}")

    # 장단기 금리차
    t10 = rates.get("미국채10년", {}).get("close")
    t2  = rates.get("미국채2년",  {}).get("close")
    if t10 and t2:
        spread = round(t10 - t2, 3)
        spread_comment = "정상" if spread > 0 else "역전 (경기침체 신호)"
        lines.append(f"  → 장단기 금리차(10Y-2Y): {spread:+.3f}%  [{spread_comment}]")

    # 원자재
    lines.append(f"\n【 원자재 】")
    for name, d in comms.items():
        a = arrow(d['pct'])
        lines.append(f"  {name:<8} {fmt_price(d['close']):>10}  {a} {fmt_pct(d['pct'])}")

    # 섹터
    lines.append(f"\n【 섹터별 등락 】")
    sorted_sectors = sorted(
        [(k, v) for k, v in sectors.items() if v['pct'] is not None],
        key=lambda x: x[1]['pct'], reverse=True
    )
    for name, d in sorted_sectors:
        bar_len = min(abs(int(d['pct'] * 2)), 10)
        bar = ("▲" * bar_len) if d['pct'] >= 0 else ("▼" * bar_len)
        lines.append(f"  {name:<16} {fmt_pct(d['pct']):>8}  {bar}")

    # 반도체 개별주
    lines.append(f"\n【 반도체 개별주 】")
    for name, d in tech["반도체"].items():
        a = arrow(d['pct'])
        lines.append(f"  {name:<14} {fmt_price(d['close']):>10}  {a} {fmt_pct(d['pct'])}")

    # M7
    lines.append(f"\n【 빅테크 M7 】")
    for name, d in tech["M7"].items():
        a = arrow(d['pct'])
        lines.append(f"  {name:<14} {fmt_price(d['close']):>10}  {a} {fmt_pct(d['pct'])}")

    lines.append(f"\n{'='*50}")
    lines.append(f"  ※ 이 데이터를 Claude에게 붙여넣으면")
    lines.append(f"     풀퀄리티 모닝리포트가 생성됩니다.")
    lines.append(f"{'='*50}")

    return "\n".join(lines)

# ── 이메일 발송 ────────────────────────────────────
def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = SEND_TO

    html = f"""<html><body style="font-family:monospace;max-width:680px;margin:0 auto;padding:20px;background:#f5f7fa;">
<div style="background:#1A3A5C;color:white;padding:16px 20px;border-radius:10px 10px 0 0;">
  <h2 style="margin:0;font-size:18px;">🌏 미장 데이터 브리핑</h2>
  <p style="margin:4px 0 0;font-size:12px;color:#A0B0C8;">{TODAY_STR} — 뉴욕 전일 마감 기준</p>
</div>
<div style="background:#fff;border:1px solid #D8DEE9;border-top:none;border-radius:0 0 10px 10px;padding:20px;">
  <pre style="white-space:pre-wrap;font-size:13px;line-height:1.9;color:#1A2033;font-family:monospace;">{body}</pre>
</div>
</body></html>"""

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, SEND_TO, msg.as_string())
    print(f"✅ 발송 완료 → {SEND_TO}")

# ── 메인 ──────────────────────────────────────────
if __name__ == "__main__":
    print("📡 미장 데이터 수집 중...")

    indices  = get_indices()
    fg       = get_fear_greed()
    rates    = get_rates()
    comms    = get_commodities()
    vix      = get_vix()
    tech     = get_tech_stocks()
    sectors  = get_sectors()

    print("📝 리포트 생성 중...")
    body    = build_body(indices, fg, rates, comms, vix, tech, sectors)
    subject = f"[미장브리핑] {TODAY_STR}"

    print(body)
    send_email(subject, body)
    print("🎉 완료!")
