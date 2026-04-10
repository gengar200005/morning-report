import os
import json
import base64
import requests
import time
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
    data = r.json()
    if "access_token" not in data:
        raise Exception(f"토큰 발급 실패: {data}")
    return data["access_token"]

# ── KIS API 헬퍼 ──────────────────────────────────
def kis_get(token, path, tr_id, params):
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    r = requests.get(
        f"{KIS_BASE_URL}{path}",
        headers=headers,
        params=params,
        timeout=15,
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
            chg   = float(out.get("bstp_nmix_prdy_vrss", 0))
            pct   = float(out.get("bstp_nmix_prdy_ctrt", 0))
            result[name] = {"close": round(close, 2), "chg": round(chg, 2), "pct": round(pct, 2)}
            print(f"  {name}: {close:,.2f} ({pct:+.2f}%)")
        except Exception as e:
            print(f"  {name} 지수 오류: {e}")
            result[name] = {"close": None, "chg": None, "pct": None}
        time.sleep(0.3)
    return result

# ── 2. 외국인·기관·개인 수급 (코스피 전체) ────────
def get_trading(token):
    result = {"외국인": 0, "기관": 0, "개인": 0}
    try:
        # 투자자별 매매동향 조회
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": "0001",  # 코스피
            }
        )
        print(f"  수급 API 응답 키: {list(data.keys())}")
        out = data.get("output", [])
        if isinstance(out, list) and len(out) > 0:
            row = out[0]
            print(f"  수급 첫 번째 row 키: {list(row.keys())[:10]}")
            # 외국인
            for key in ["frgn_ntby_qty", "frgn_ntby_tr_pbmn"]:
                if key in row:
                    result["외국인"] = int(row[key])
                    break
            # 기관
            for key in ["orgn_ntby_qty", "orgn_ntby_tr_pbmn"]:
                if key in row:
                    result["기관"] = int(row[key])
                    break
            # 개인
            for key in ["indv_ntby_qty", "indv_ntby_tr_pbmn"]:
                if key in row:
                    result["개인"] = int(row[key])
                    break
        elif isinstance(out, dict):
            print(f"  수급 dict 키: {list(out.keys())[:10]}")
    except Exception as e:
        print(f"  수급 오류: {e}")
    return result

# ── 3. 종목 일봉 데이터 (100건씩 2회 호출) ────────
def get_ohlcv(token, code):
    closes  = []
    volumes = []
    try:
        end   = NOW.strftime("%Y%m%d")
        # 1차: 최근 100일
        mid = (NOW - timedelta(days=105)).strftime("%Y%m%d")
        # 2차: 그 이전 100일
        start = (NOW - timedelta(days=210)).strftime("%Y%m%d")

        for s, e in [(start, mid), (mid, end)]:
            data = kis_get(token,
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "FHKST03010100",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": s,
                    "FID_INPUT_DATE_2": e,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "0",
                }
            )
            items = data.get("output2", [])
            if not items:
                items = data.get("output1", [])
            for item in reversed(items):
                try:
                    c = float(item.get("stck_clpr", 0))
                    v = int(item.get("acml_vol", 0))
                    if c > 0:
                        closes.append(c)
                        volumes.append(v)
                except:
                    continue
            time.sleep(0.3)

    except Exception as e:
        print(f"  {code} 일봉 오류: {e}")

    return closes, volumes

# ── 4. 외국인 5일 순매수 (종목별) ─────────────────
def get_foreign_5d(token, code):
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": (NOW - timedelta(days=14)).strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": NOW.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            }
        )
        items = data.get("output2", [])[:5]
        total = 0
        for item in items:
            # 외국인 순매수량 필드 탐색
            for key in ["frgn_ntby_qty", "frgn_vol"]:
                if key in item:
                    try:
                        total += int(item[key])
                    except:
                        pass
                    break
        return total
    except:
        return 0

# ── 5. 체크리스트 스크리닝 ────────────────────────
def screen_stocks(token, kospi_close):
    results = []

    # 코스피 추세 판단 (간단 기준: 2400 이상)
    kospi_trend = kospi_close > 2400 if kospi_close else False

    for code, name in FCF_UNIVERSE:
        try:
            closes, volumes = get_ohlcv(token, code)
            print(f"  {name} 데이터: 종가 {len(closes)}개, 거래량 {len(volumes)}개")

            if len(closes) < 120 or len(volumes) < 21:
                print(f"  {name} 데이터 부족 스킵")
                continue

            close_now = closes[-1]
            ma20  = calc_ma(closes, 20)
            ma60  = calc_ma(closes, 60)
            ma120 = calc_ma(closes, 120)

            aligned = bool(ma20 and ma60 and ma120 and ma20 > ma60 > ma120)

            vol_now = volumes[-1]
            vol_avg = sum(volumes[-21:-1]) / 20
            vol_ok  = vol_now >= vol_avg * 1.5

            foreign_5d = get_foreign_5d(token, code)
            foreign_ok = foreign_5d > 0

            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

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
            print(f"  {name} [{grade}] ─ MA정배열:{aligned} 거래량:{vol_ok} 외국인:{foreign_ok}")

        except Exception as e:
            print(f"  {name} 오류: {e}")
            continue

    results.sort(key=lambda x: (x["등급"], -x["현재가"]))
    return results, kospi_trend

# ── 텍스트 포맷 ────────────────────────────────────
def build_text(indices, trading, candidates, kospi_trend):
    lines = []
    lines.append(f"{'='*52}")
    lines.append(f"  국장 데이터 브리핑 — {TODAY_STR}")
    lines.append(f"  전일 마감 기준")
    lines.append(f"{'='*52}")

    lines.append(f"\n【 주요 지수 】")
    for name, d in indices.items():
        if d["close"]:
            sign = "▲" if d["pct"] >= 0 else "▼"
            pct  = f"{'+' if d['pct'] >= 0 else ''}{d['pct']:.2f}%"
            lines.append(f"  {name:<8} {d['close']:>10,.2f}  {sign} {pct}")

    lines.append(f"\n【 수급 (코스피) 】")
    for key in ["외국인", "기관", "개인"]:
        val  = trading.get(key, 0)
        sign = "+" if val >= 0 else ""
        lines.append(f"  {key:<6} {sign}{val:,}주")

    lines.append(f"\n【 코스피 추세 】")
    lines.append(f"  {'✓ 상승추세 유지' if kospi_trend else '✗ 추세 이탈 — 진입 보류'}")

    lines.append(f"\n【 체크리스트 스크리닝 결과 】")
    if candidates:
        for c in candidates:
            lines.append(f"\n  ▶ {c['종목명']} ({c['종목코드']}) [{c['등급']}등급]")
            lines.append(f"    현재가: {c['현재가']:,}원")
            lines.append(f"    MA20: {c['MA20']:,} | MA60: {c['MA60']:,} | MA120: {c['MA120']:,}")
            lines.append(f"    이평선정배열: {c['이평선정배열']} | 거래량1.5배: {c['거래량']} | 외국인5일: {c['외국인5일']} ({c['외국인순매수']:+,}주)")
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
    print("✅ 토큰 발급 완료")

    print("📡 코스피·코스닥 지수 수집 중...")
    indices = get_index(token)

    print("📡 수급 데이터 수집 중...")
    trading = get_trading(token)
    print(f"  외국인: {trading['외국인']:,} | 기관: {trading['기관']:,} | 개인: {trading['개인']:,}")

    kospi_close = indices.get("코스피", {}).get("close", 0) or 0

    print("📡 체크리스트 스크리닝 중...")
    candidates, kospi_trend = screen_stocks(token, kospi_close)
    print(f"  → A/B등급 종목 {len(candidates)}개")

    print("📝 텍스트 생성 중...")
    text = build_text(indices, trading, candidates, kospi_trend)
    print(text)

    print("💾 GitHub 저장 중...")
    save_to_github(text)
    print("🎉 완료!")
