import os
import json
import base64
import requests
from datetime import datetime
import pytz

import yfinance as yf

# ── 설정 ──────────────────────────────────────────
GITHUB_TOKEN = os.environ["MY_GITHUB_TOKEN"]
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_FILE  = "us_data.txt"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

# ── 헬퍼 ──────────────────────────────────────────
def q(sym, period="5d"):
    try:
        hist = yf.Ticker(sym).history(period=period)
        if len(hist) >= 2:
            prev  = float(hist["Close"].iloc[-2])
            close = float(hist["Close"].iloc[-1])
            chg   = close - prev
            pct   = chg / prev * 100
            return {"close": round(close, 2), "chg": round(chg, 2), "pct": round(pct, 2)}
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

# ── 데이터 수집 ────────────────────────────────────
def get_all_data():
    print("📡 주요 지수 수집 중...")
    indices = {
        "S&P500":   q("^GSPC"),
        "나스닥":   q("^IXIC"),
        "다우":     q("^DJI"),
        "러셀2000": q("^RUT"),
    }

    print("📡 공포탐욕지수 수집 중...")
    fg = {"score": None, "rating": "N/A"}
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        data = r.json()
        score  = round(float(data["fear_and_greed"]["score"]), 1)
        rating = data["fear_and_greed"]["rating"]
        rating_kr = {
            "Extreme Fear": "극단적 공포",
            "Fear": "공포",
            "Neutral": "중립",
            "Greed": "탐욕",
            "Extreme Greed": "극단적 탐욕",
        }.get(rating, rating)
        fg = {"score": score, "rating": rating_kr}
    except Exception as e:
        print(f"  공포탐욕 오류: {e}")

    print("📡 금리·달러 수집 중...")
    rates = {
        "미국채10년": q("^TNX"),
        "미국채2년":  q("^IRX"),
        "달러인덱스": q("DX-Y.NYB"),
        "달러/원":    q("KRW=X"),
        "달러/엔":    q("JPY=X"),
    }

    print("📡 원자재 수집 중...")
    comms = {
        "WTI":    q("CL=F"),
        "브렌트": q("BZ=F"),
        "금":     q("GC=F"),
        "은":     q("SI=F"),
    }

    print("📡 VIX 수집 중...")
    vix = q("^VIX")

    print("📡 반도체·M7 수집 중...")
    semis = {
        "엔비디아":      q("NVDA"),
        "TSMC":          q("TSM"),
        "ASML":          q("ASML"),
        "AMD":           q("AMD"),
        "인텔":          q("INTC"),
        "삼성전자ADR":   q("SSNLF"),
    }
    m7 = {
        "애플":          q("AAPL"),
        "마이크로소프트": q("MSFT"),
        "아마존":        q("AMZN"),
        "알파벳":        q("GOOGL"),
        "메타":          q("META"),
        "테슬라":        q("TSLA"),
        "엔비디아":      q("NVDA"),
    }

    print("📡 섹터 ETF 수집 중...")
    sectors = {
        "반도체(SOXX)":  q("SOXX"),
        "테크(XLK)":     q("XLK"),
        "에너지(XLE)":   q("XLE"),
        "금융(XLF)":     q("XLF"),
        "헬스케어(XLV)": q("XLV"),
        "소비재(XLY)":   q("XLY"),
        "유틸리티(XLU)": q("XLU"),
    }

    return indices, fg, rates, comms, vix, semis, m7, sectors

# ── 텍스트 포맷 ────────────────────────────────────
def build_text(indices, fg, rates, comms, vix, semis, m7, sectors):
    lines = []
    lines.append(f"{'='*52}")
    lines.append(f"  미장 데이터 브리핑 — {TODAY_STR}")
    lines.append(f"  뉴욕 전일 마감 기준")
    lines.append(f"{'='*52}")

    # 공포탐욕
    score = fg["score"]
    if score:
        filled  = int(score / 10)
        bar     = "█" * filled + "░" * (10 - filled)
        emoji   = "😱" if score < 25 else "😰" if score < 45 else "😐" if score < 55 else "😏" if score < 75 else "🤑"
        lines.append(f"\n【 공포탐욕지수 】")
        lines.append(f"  {emoji} {score} / 100  [{bar}]  {fg['rating']}")
        lines.append(f"  ※ 25이하=매수기회 / 75이상=과열주의")

    # 주요 지수
    lines.append(f"\n【 주요 지수 】")
    for name, d in indices.items():
        lines.append(f"  {name:<10} {fmt_price(d['close']):>12}  {arrow(d['pct'])} {fmt_pct(d['pct'])}")

    # VIX
    vix_comment = "안정" if vix['close'] and vix['close'] < 20 else "주의" if vix['close'] and vix['close'] < 30 else "위험"
    lines.append(f"\n【 VIX (변동성) 】")
    lines.append(f"  {fmt_price(vix['close'])}  [{vix_comment}]  ※ 20이하=안정 / 30이상=위험")

    # 금리·달러
    lines.append(f"\n【 금리·달러 】")
    for name, d in rates.items():
        lines.append(f"  {name:<12} {fmt_price(d['close']):>10}  {arrow(d['pct'])} {fmt_pct(d['pct'])}")
    t10 = rates.get("미국채10년", {}).get("close")
    t2  = rates.get("미국채2년",  {}).get("close")
    if t10 and t2:
        spread = round(t10 - t2, 3)
        comment = "정상" if spread > 0 else "역전 ⚠️ 경기침체 신호"
        lines.append(f"  → 장단기 금리차(10Y-2Y): {spread:+.3f}%  [{comment}]")

    # 원자재
    lines.append(f"\n【 원자재 】")
    for name, d in comms.items():
        lines.append(f"  {name:<8} {fmt_price(d['close']):>10}  {arrow(d['pct'])} {fmt_pct(d['pct'])}")

    # 섹터
    lines.append(f"\n【 섹터별 등락 】")
    sorted_s = sorted(
        [(k, v) for k, v in sectors.items() if v['pct'] is not None],
        key=lambda x: x[1]['pct'], reverse=True
    )
    for name, d in sorted_s:
        bar_len = min(abs(int(d['pct'] * 2)), 10)
        bar = ("▲" * bar_len) if d['pct'] >= 0 else ("▼" * bar_len)
        lines.append(f"  {name:<18} {fmt_pct(d['pct']):>8}  {bar}")

    # 반도체
    lines.append(f"\n【 반도체 개별주 】")
    for name, d in semis.items():
        lines.append(f"  {name:<16} {fmt_price(d['close']):>10}  {arrow(d['pct'])} {fmt_pct(d['pct'])}")

    # M7
    lines.append(f"\n【 빅테크 M7 】")
    for name, d in m7.items():
        lines.append(f"  {name:<16} {fmt_price(d['close']):>10}  {arrow(d['pct'])} {fmt_pct(d['pct'])}")

    lines.append(f"\n{'='*52}")
    return "\n".join(lines)

# ── GitHub에 파일 저장 ─────────────────────────────
def save_to_github(content):
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 기존 파일 SHA 조회 (업데이트 시 필요)
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    # 파일 업로드
    payload = {
        "message": f"미장 데이터 업데이트 — {TODAY_STR}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"✅ GitHub 저장 완료 → {GITHUB_FILE}")
    else:
        print(f"❌ GitHub 저장 실패: {r.status_code} {r.text}")

# ── 메인 ──────────────────────────────────────────
if __name__ == "__main__":
    indices, fg, rates, comms, vix, semis, m7, sectors = get_all_data()

    print("📝 텍스트 생성 중...")
    text = build_text(indices, fg, rates, comms, vix, semis, m7, sectors)

    print(text)

    print("💾 GitHub 저장 중...")
    save_to_github(text)

    print("🎉 완료!")
