import os
import json
import base64
import requests
from datetime import datetime, timedelta
import pytz

# ── 설정 ──────────────────────────────────────────
KIS_APP_KEY    = os.environ["KIS_APP_KEY"]
KIS_APP_SECRET = os.environ["KIS_APP_SECRET"]
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"

GITHUB_TOKEN = os.environ["MORNINGREPOT"]
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_FILE  = "kr_data.txt"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

# FCF 흑자 확인된 유니버스 (분기별 수동 업데이트)
FCF_UNIVERSE = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("005380", "현대차"),
    ("035420", "NAVER"),
    ("051910", "LG화학"),
    ("068270", "셀트리온"),
    ("028260", "삼성물산"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("012330", "현대모비스"),
]

# ── KIS API 토큰 발급 ──────────────────────────────
def get_token():
    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }
    r = requests.post(url, headers=headers, json=body, timeout=10)
    return r.json()["access_token"]

# ── KIS API 헬퍼 ──────────────────────────────────
def kis_get(token, path, tr_id, params):
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
    }
    r = requests.get(
        f"{KIS_BASE_URL}{path}",
        headers=headers,
        params=params,
        timeout=10,
    )
    return r.json()

# ── MA 계산 ───────────────────────────────────────
def calc_ma(prices, n):
    if len(prices) < n:
        return None
    return round(sum(prices[-n:]) / n, 0)

# ── 1. 코스피·코스닥 지수 ────────────────────────
def get_index(token):
    result = {}
    indices = [
        ("0001", "코스피"),
        ("1001", "코스닥"),
    ]
    for code, name in indices:
        try:
            data = kis_get(token,
                "/uapi/domestic-stock/v1/quotations/inquire-index-price",
                "FHPUP02100000",
                {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code}
            )
            out = data.get("output", {})
            close = float(out.get("bstp_nmix_prpr", 0))
            prev  = float(out.get("bstp_nmix_prdy_vrss", 0))
            pct   = float(out.get("bstp_nmix_prdy_ctrt", 0))
            result[name] = {
                "close": round(close, 2),
                "chg":   round(prev, 2),
                "pct":   round(pct, 2),
            }
        except Exception as e:
            print(f"  {name} 지수 오류: {e}")
            result[name] = {"close": None, "chg": None, "pct": None}
    return result

# ── 2. 외국인·기관·개인 수급 ──────────────────────
def get_trading(token):
    result = {}
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHPTJ04010000",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "0001"}
        )
        out = data.get("output", [{}])[0]
        result["외국인"] = int(out.get("frgn_ntby_qty", 0))
        result["기관"]   = int(out.get("orgn_ntby_qty", 0))
        result["개인"]   = int(out.get("indv_ntby_qty", 0))
    except Exception as e:
        print(f"  수급 오류: {e}")
    return result

# ── 3. 종목 일봉 데이터 ───────────────────────────
def get_ohlcv(token, code, days=130):
    try:
        end   = NOW.strftime("%Y%m%d")
        start = (NOW - timedelta(days=days * 2)).strftime("%Y%m%d")
        data  = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST01010400",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
            }
        )
        items = data.get("output2", []) or data.get("output", [])
        closes = []
        volumes = []
        for item in reversed(items):
            try:
                closes.append(float(item.get("stck_clpr", 0)))
                volumes.append(int(item.get("acml_vol", 0)))
            except:
                continue
        return closes, volumes
    except Exception as e:
        print(f"  {code} 일봉 오류: {e}")
        return [], []

# ── 4. 외국인 5일 순매수 ──────────────────────────
def get_foreign_5d(token, code):
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHPTJ04010000",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        )
        items = data.get("output", [])[:5]
        total = sum(int(i.get("frgn_ntby_qty", 0)) for i in items)
        return total
    except:
        return 0

# ── 5. 체크리스트 스크리닝 ────────────────────────
def screen_stocks(token, kospi_trend):
    results = []

    for code, name in FCF_UNIVERSE:
        try:
            closes, volumes = get_ohlcv(token, code)
            if len(closes) < 120 or len(volumes) < 21:
                print(f"  {name} 데이터 부족 스킵")
                continue

            close_now = closes[-1]
            ma20  = calc_ma(closes, 20)
            ma60  = calc_ma(closes, 60)
            ma120 = calc_ma(closes, 120)

            # 이평선 정배열
            aligned = bool(ma20 and ma60 and ma120 and ma20 > ma60 > ma120)

            # 거래량 1.5배
            vol_now = volumes[-1]
            vol_avg = sum(volumes[-21:-1]) / 20
            vol_ok  = vol_now >= vol_avg * 1.5

            # 외국인 5일 순매수
            foreign_5d = get_foreign_5d(token, code)
            foreign_ok = foreign_5d > 0

            # 손절가·목표가
            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

            # 등급 판정
            score = sum([aligned, vol_ok, foreign_ok, kospi_trend])
            if score >= 3 and aligned:
                grade = "A"
            elif score >= 2:
                grade = "B"
            else:
                grade = "C"

            if grade in ("A", "B"):
                results.append({
                    "종목명":       name,
                    "종목코드":     code,
                    "현재가":       int(close_now),
                    "등급":         grade,
                    "MA20":         int(ma20) if ma20 else 0,
                    "MA60":         int(ma60) if ma60 else 0,
                    "MA120":        int(ma120) if ma120 else 0,
                    "이평선정배열": "✓" if aligned else "✗",
                    "거래량":       "✓" if vol_ok else "✗",
                    "외국인5일":    "✓" if foreign_ok else "✗",
                    "외국인순매수": foreign_5d,
                    "코스피추세":   "✓" if kospi_trend else "✗",
                    "손절가":       int(stop),
                    "목표가":       int(target),
                })
            print(f"  {name} [{grade}] 처리 완료")

        except Exception as e:
            print(f"  {name} 오류: {e}")
            continue

    results.sort(key=lambda x: (x["등급"], -x["현재가"]))
    return results

# ── 텍스트 포맷 ────────────────────────────────────
def build_text(indices, trading, candidates):
    lines = []
    lines.append(f"{'='*52}")
    lines.append(f"  국장 데이터 브리핑 — {TODAY_STR}")
    lines.append(f"  전일 마감 기준")
    lines.append(f"{'='*52}")

    # 지수
    lines.append(f"\n【 주요 지수 】")
    for name, d in indices.items():
        if d["close"]:
            sign = "▲" if d["pct"] >= 0 else "▼"
            pct  = f"{'+' if d['pct'] >= 0 else ''}{d['pct']:.2f}%"
            lines.append(f"  {name:<8} {d['close']:>10,.2f}  {sign} {pct}")

    # 수급
    lines.append(f"\n【 수급 (코스피) 】")
    for key in ["외국인", "기관", "개인"]:
        val = trading.get(key, 0)
        sign = "+" if val >= 0 else ""
        lines.append(f"  {key:<6} {sign}{val:,}주")

    # 체크리스트 결과
    lines.append(f"\n【 체크리스트 스크리닝 결과 】")
    if candidates:
        for c in candidates:
            lines.append(f"\n  ▶ {c['종목명']} ({c['종목코드']}) [{c['등급']}등급]")
            lines.append(f"    현재가: {c['현재가']:,}원")
            lines.append(f"    MA20: {c['MA20']:,} | MA60: {c['MA60']:,} | MA120: {c['MA120']:,}")
            lines.append(f"    이평선정배열: {c['이평선정배열']} | 거래량1.5배: {c['거래량']} | 외국인5일: {c['외국인5일']} ({c['외국인순매수']:+,}주)")
            lines.append(f"    코스피추세: {c['코스피추세']}")
            lines.append(f"    손절가: {c['손절가']:,}원 (-7%) | 1차목표: {c['목표가']:,}원 (+18%)")
    else:
        lines.append("  오늘 조건 충족 종목 없음 — 진입 보류")

    lines.append(f"\n{'='*52}")
    return "\n".join(lines)

# ── GitHub 저장 ────────────────────────────────────
def save_to_github(content):
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"국장 데이터 업데이트 — {TODAY_STR}",
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
    print("🔑 KIS 토큰 발급 중...")
    token = get_token()

    print("📡 코스피·코스닥 지수 수집 중...")
    indices = get_index(token)

    print("📡 수급 데이터 수집 중...")
    trading = get_trading(token)

    # 코스피 추세 판단
    kospi_close = indices.get("코스피", {}).get("close", 0)
    kospi_trend = kospi_close > 2400  # 간단 기준, 추후 MA 계산으로 고도화

    print("📡 체크리스트 스크리닝 중...")
    candidates = screen_stocks(token, kospi_trend)
    print(f"  → A/B등급 종목 {len(candidates)}개")

    print("📝 텍스트 생성 중...")
    text = build_text(indices, trading, candidates)
    print(text)

    print("💾 GitHub 저장 중...")
    save_to_github(text)

    print("🎉 완료!")
