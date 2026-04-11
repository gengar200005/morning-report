import os
import base64
import requests
import time
import yfinance as yf
from pykrx import stock as krx
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

def prev_trading_day():
    d = NOW.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")

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

SECTOR_ETF = {
    "005930": ("091160", "KODEX반도체"),
    "000660": ("091160", "KODEX반도체"),
    "005380": ("091180", "KODEX자동차"),
    "035420": None,
    "051910": None,
    "068270": None,
    "028260": None,
    "105560": ("091170", "KODEX은행"),
    "055550": ("091170", "KODEX은행"),
    "012330": ("091180", "KODEX자동차"),
}

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

# ── 섹터 ETF 60MA 체크 ────────────────────────────
def get_etf_ma60(etf_info):
    if not etf_info:
        return None, "N/A"
    etf_code, etf_name = etf_info
    try:
        end   = NOW.strftime("%Y%m%d")
        start = (NOW - timedelta(days=100)).strftime("%Y%m%d")
        df = krx.get_etf_ohlcv_by_date(start, end, etf_code)
        if len(df) < 60:
            return None, etf_name
        for col in ["종가", "Close", "close", "NAV"]:
            if col in df.columns:
                prices = df[col].dropna()
                if len(prices) >= 60:
                    ma60  = float(prices.tail(60).mean())
                    cur   = float(prices.iloc[-1])
                    above = cur > ma60
                    print(f"    ETF {etf_name}: {cur:,.0f} vs MA60 {ma60:,.0f} ({'✓' if above else '✗'})")
                    return above, etf_name
    except Exception as e:
        print(f"    ETF {etf_name} 오류: {e}")
    return None, etf_name

# ── 저항→지지 전환 체크 ───────────────────────────
def check_sr(closes, window=5, tolerance=0.04):
    if len(closes) < 40:
        return False, None
    current = closes[-1]
    search  = closes[-80:-10] if len(closes) >= 90 else closes[:-10]
    swing_highs = []
    for i in range(window, len(search) - window):
        if (all(search[i] >= search[i-j] for j in range(1, window+1)) and
                all(search[i] >= search[i+j] for j in range(1, window+1))):
            swing_highs.append(search[i])
    for high in sorted(swing_highs, key=lambda x: abs(x - current)):
        if high * (1 - tolerance) <= current <= high * (1 + tolerance):
            return True, int(high)
    return False, None

# ── 0. VIX & 코스피 60MA ──────────────────────────
def get_market_context():
    ctx = {
        "vix": None, "vix_ok": False,
        "kospi_ma60": None, "kospi_above_ma60": False,
    }
    try:
        hist = yf.Ticker("^VIX").history(period="5d")
        if not hist.empty:
            ctx["vix"]    = round(float(hist["Close"].iloc[-1]), 2)
            ctx["vix_ok"] = ctx["vix"] < 20
            print(f"  VIX: {ctx['vix']} ({'✓' if ctx['vix_ok'] else '✗'})")
    except Exception as e:
        print(f"  VIX 오류: {e}")

    try:
        hist = yf.Ticker("^KS11").history(period="100d")
        if len(hist) >= 60:
            ma60 = round(float(hist["Close"].tail(60).mean()), 2)
            cur  = round(float(hist["Close"].iloc[-1]), 2)
            ctx["kospi_ma60"]       = ma60
            ctx["kospi_above_ma60"] = cur > ma60
            print(f"  코스피 {cur:,.2f} vs MA60 {ma60:,.2f} ({'✓' if ctx['kospi_above_ma60'] else '✗'})")
    except Exception as e:
        print(f"  코스피 MA60 오류: {e}")

    return ctx

# ── 1. 코스피·코스닥 지수 ─────────────────────────
def get_index(token):
    result = {}
    for code, name in [("0001", "코스피"), ("1001", "코스닥")]:
        try:
            data  = kis_get(token,
                "/uapi/domestic-stock/v1/quotations/inquire-index-price",
                "FHPUP02100000",
                {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code}
            )
            out   = data.get("output", {})
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

# ── 2. 수급 (KIS 시장별 투자자 → pykrx 백업) ──────────────────
def get_trading(token):
    result   = {"외국인": 0, "기관": 0, "개인": 0, "단위": "억원"}
    prev_day = prev_trading_day()

    # 1순위: KIS 시장별 투자자매매동향 (FHPTJ04040000)
    # - KRX direct / pykrx 는 해외 IP 차단으로 GitHub Actions 에서 불가
    # - 이 endpoint 는 KIS 서버에서 직접 제공 → 해외 IP 무관
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
            "FHPTJ04040000",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD":         "0001",
                "FID_INPUT_DATE_1":       prev_day,
                "FID_INPUT_DATE_2":       prev_day,
                "FID_INPUT_ISCD_1":       "KSP",
                "FID_INPUT_ISCD_2":       "",
            }
        )
        rt  = data.get("rt_cd", "?")
        msg = data.get("msg1", "")
        print(f"  수급(KIS) rt_cd={rt} msg={msg}")
        out = data.get("output", [])
        if isinstance(out, list) and len(out) > 0:
            row = out[0]
            print(f"  수급(KIS) row keys={list(row.keys())[:10]}")
            def _parse(key_pbmn, key_qty):
                v = row.get(key_pbmn) or row.get(key_qty, "0")
                try:
                    raw = int(str(v).replace(",", "") or "0")
                    # pbmn(거래대금)은 원 단위 → 억원 변환; qty(수량)는 그대로
                    if key_pbmn in row and abs(raw) >= 100_000_000:
                        return raw // 100_000_000
                    return raw
                except:
                    return 0
            result["외국인"] = _parse("frgn_ntby_tr_pbmn", "frgn_ntby_qty")
            result["기관"]   = _parse("orgn_ntby_tr_pbmn", "orgn_ntby_qty")
            result["개인"]   = _parse("prsn_ntby_tr_pbmn", "prsn_ntby_qty")
            print(f"  수급(KIS) raw: 외국인={result['외국인']:,} 기관={result['기관']:,} 개인={result['개인']:,}")
            if any(result[k] != 0 for k in ["외국인", "기관", "개인"]):
                print(f"  수급(KIS) 성공: 외국인={result['외국인']:,}억 기관={result['기관']:,}억")
                return result
        print("  수급(KIS) 값 모두 0 — pykrx 백업 시도")
    except Exception as e:
        print(f"  수급(KIS) 오류: {e}")

    # 2순위: pykrx (로컬 전용 — GitHub Actions 에서는 KRX IP 차단으로 실패)
    try:
        df = krx.get_market_trading_value_by_investor(prev_day, prev_day, "KOSPI")
        print(f"  수급(pykrx) shape={df.shape} index={list(df.index)} cols={list(df.columns)}")

        if df.empty:
            raise ValueError("빈 DataFrame")

        # 순매수 컬럼 탐색 ─ MultiIndex·단순 인덱스 모두 대응
        net_col = None
        cols = list(df.columns)
        for col in cols:
            s = str(col)
            if "순매수" in s and "거래대금" in s:
                net_col = col; break
        if net_col is None:
            for col in cols:
                if "순매수" in str(col): net_col = col; break
        if net_col is None:
            for col in cols:
                if col in ("순매수금액", "net", "Net"): net_col = col; break
        if net_col is None and len(cols) >= 3:
            net_col = cols[-1]
            print(f"  순매수 컬럼 최후 추정: '{net_col}'")

        print(f"  사용 순매수 컬럼: '{net_col}'")

        if net_col is not None:
            for label, key in [
                ("외국인합계", "외국인"), ("외국인",  "외국인"),
                ("기관합계",   "기관"),   ("기관",    "기관"),
                ("개인",       "개인"),
            ]:
                if label in df.index and result[key] == 0:
                    raw_val = int(df.loc[label, net_col])
                    print(f"  raw [{label}] = {raw_val:,}")
                    if abs(raw_val) < 100_000_000:
                        result[key] = raw_val
                    else:
                        result[key] = raw_val // 100_000_000
            if any(result[k] != 0 for k in ["외국인", "기관", "개인"]):
                print(f"  수급(pykrx) 성공: 외국인={result['외국인']:,}억 기관={result['기관']:,}억")
                return result
        print("  수급(pykrx) 값 모두 0")
    except Exception as e:
        print(f"  수급(pykrx) 오류: {e}")

    print("  ⚠️ 수급 데이터 수집 실패 — 0으로 처리")
    return result

# ── 3. 종목 일봉 데이터 ───────────────────────────
def get_ohlcv(token, code):
    closes  = []
    volumes = []
    try:
        end   = NOW.strftime("%Y%m%d")
        mid   = (NOW - timedelta(days=105)).strftime("%Y%m%d")
        start = (NOW - timedelta(days=210)).strftime("%Y%m%d")

        for s, e in [(start, mid), (mid, end)]:
            data = kis_get(token,
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "FHKST03010100",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD":      code,
                    "FID_INPUT_DATE_1":    s,
                    "FID_INPUT_DATE_2":    e,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC":    "0",
                }
            )
            items = data.get("output2", []) or data.get("output1", [])
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

# ── 4. 외국인 5일 순매수 ──────────────────────────
def get_foreign_5d(token, code):
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            }
        )
        out = data.get("output1", [])
        if isinstance(out, dict):
            out = [out]
        today_str = NOW.strftime("%Y%m%d")
        total, count = 0, 0
        for item in out:
            if item.get("stck_bsop_date") == today_str:
                continue
            try:
                total += int(item.get("frgn_ntby_qty", 0))
                count += 1
            except:
                pass
            if count >= 5:
                break
        return total
    except:
        return 0

# ── 4-A. 종목 가격상세 (PER/PBR/ROE) ─────────────
def get_price_detail(token, code):
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            }
        )
        out = data.get("output", {})
        def sf(v):
            try:
                f = float(v)
                return round(f, 2) if f != 0 else None
            except:
                return None
        per = sf(out.get("per"))
        pbr = sf(out.get("pbr"))
        eps = sf(out.get("eps"))
        bps = sf(out.get("bps"))
        roe = round(eps / bps * 100, 2) if eps and bps else None
        return {"per": per, "pbr": pbr, "roe": roe}
    except Exception as e:
        print(f"  {code} 가격상세 오류: {e}")
        return {"per": None, "pbr": None, "roe": None}

# ── 5. 스크리닝 ───────────────────────────────────
def screen_stocks(token, mkt_ctx):
    results  = []
    kospi_ok = mkt_ctx["kospi_above_ma60"]
    vix_ok   = mkt_ctx["vix_ok"]

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

            detail = get_price_detail(token, code)
            time.sleep(0.2)

            etf_ok, etf_name = get_etf_ma60(SECTOR_ETF.get(code))
            sr_ok, sr_level  = check_sr(closes)

            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

            score     = sum([aligned, vol_ok, foreign_ok, kospi_ok, vix_ok])
            if etf_ok is True:  score += 1
            if sr_ok:           score += 1
            max_score = 5 + (1 if etf_ok is not None else 0) + 1

            if score >= max_score - 1 and aligned:
                grade = "A"
            elif score >= max_score - 2:
                grade = "B"
            else:
                grade = "C"

            etf_str = f"✓ {etf_name}" if etf_ok is True else (f"✗ {etf_name}" if etf_ok is False else "N/A")
            sr_str  = f"✓ {sr_level:,}원" if sr_ok else "✗"
            print(f"  {name} [{grade}] {score}/{max_score}점 — MA:{aligned} 거래량:{vol_ok} 외국인:{foreign_ok} 코스피:{kospi_ok} VIX:{vix_ok} ETF:{etf_str} SR:{sr_str}")

            if grade in ("A", "B"):
                results.append({
                    "종목명":       name,
                    "종목코드":     code,
                    "현재가":       int(close_now),
                    "등급":         grade,
                    "점수":         score,
                    "최대점수":     max_score,
                    "MA20":         int(ma20) if ma20 else 0,
                    "MA60":         int(ma60) if ma60 else 0,
                    "MA120":        int(ma120) if ma120 else 0,
                    "이평선정배열": "✓" if aligned else "✗",
                    "거래량":       "✓" if vol_ok else "✗",
                    "외국인5일":    "✓" if foreign_ok else "✗",
                    "외국인순매수": foreign_5d,
                    "코스피MA60":   "✓" if kospi_ok else "✗",
                    "VIX20이하":    "✓" if vix_ok else "✗",
                    "섹터ETF":      etf_str,
                    "저항지지":     sr_str,
                    "PER":          detail["per"],
                    "PBR":          detail["pbr"],
                    "ROE":          detail["roe"],
                    "손절가":       int(stop),
                    "목표가":       int(target),
                })

        except Exception as e:
            print(f"  {name} 오류: {e}")
            continue

    results.sort(key=lambda x: (x["등급"], -x["점수"]))
    return results

# ── 텍스트 포맷 ────────────────────────────────────
def build_text(indices, trading, candidates, mkt_ctx):
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

    unit = trading.get("단위", "억원")
    lines.append(f"\n【 수급 (코스피) — 단위: {unit} 】")
    for key in ["외국인", "기관", "개인"]:
        val  = trading.get(key, 0)
        sign = "+" if val >= 0 else ""
        lines.append(f"  {key:<6} {sign}{val:,}{unit}")

    lines.append(f"\n【 시장 컨텍스트 】")
    vix  = mkt_ctx.get("vix")
    ma60 = mkt_ctx.get("kospi_ma60")
    vix_str  = f"{vix:.2f}"    if vix  else "N/A"
    ma60_str = f"{ma60:,.2f}"  if ma60 else "N/A"
    lines.append(f"  VIX         {vix_str:>8}  {'✓ 20이하 — 변동성 안정' if mkt_ctx['vix_ok'] else '✗ 20초과 — 변동성 경계'}")
    lines.append(f"  코스피 MA60 {ma60_str:>10}  {'✓ MA60 위 — 상승추세 유지' if mkt_ctx['kospi_above_ma60'] else '✗ MA60 아래 — 진입 보류'}")

    lines.append(f"\n【 체크리스트 스크리닝 결과 】")
    if candidates:
        for c in candidates:
            per_str = f"{c['PER']:.1f}x" if c['PER'] else "N/A"
            pbr_str = f"{c['PBR']:.2f}x" if c['PBR'] else "N/A"
            roe_str = f"{c['ROE']:.1f}%" if c['ROE'] else "N/A"
            lines.append(f"\n  ▶ {c['종목명']} ({c['종목코드']}) [{c['등급']}등급 {c['점수']}/{c['최대점수']}점]")
            lines.append(f"    현재가: {c['현재가']:,}원")
            lines.append(f"    MA20: {c['MA20']:,} | MA60: {c['MA60']:,} | MA120: {c['MA120']:,}")
            lines.append(f"    이평선정배열: {c['이평선정배열']} | 거래량1.5배: {c['거래량']} | 외국인5일: {c['외국인5일']} ({c['외국인순매수']:+,}주)")
            lines.append(f"    코스피MA60: {c['코스피MA60']} | VIX20이하: {c['VIX20이하']}")
            lines.append(f"    섹터ETF60MA: {c['섹터ETF']} | 저항→지지: {c['저항지지']}")
            lines.append(f"    PER: {per_str} | PBR: {pbr_str} | ROE: {roe_str}")
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

    print("📡 시장 컨텍스트 수집 중 (VIX / 코스피 MA60)...")
    mkt_ctx = get_market_context()

    print("📡 코스피·코스닥 지수 수집 중...")
    indices = get_index(token)

    print("📡 수급 데이터 수집 중...")
    trading = get_trading(token)
    print(f"  외국인: {trading['외국인']:,} | 기관: {trading['기관']:,} | 개인: {trading['개인']:,}")

    print("📡 체크리스트 스크리닝 중...")
    candidates = screen_stocks(token, mkt_ctx)
    print(f"  → A/B등급 종목 {len(candidates)}개")

    print("📝 텍스트 생성 중...")
    text = build_text(indices, trading, candidates, mkt_ctx)
    print(text)

    print("💾 GitHub 저장 중...")
    save_to_github(text)
    print("🎉 완료!")
