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

# ── 60일 고점 근접 체크 (보조 조건 ⑤) ───────────────
def check_60d_high(closes):
    """최근 60거래일 고점 대비 현재가 -2% 이내 또는 돌파"""
    if len(closes) < 60:
        return False, None
    high_60d = max(closes[-60:])
    current  = closes[-1]
    return current >= high_60d * 0.98, int(high_60d)

# ── 지수 추세 분석 (1순위/2순위) ─────────────────────
def get_index_trend():
    """KOSPI/KOSDAQ 5일·20일 수익률 + 52주 고저점 대비 위치 + 20일 신고가 여부"""
    result = {}
    for ticker, name in [("^KS11", "코스피"), ("^KQ11", "코스닥")]:
        try:
            hist   = yf.Ticker(ticker).history(period="400d")
            closes = hist["Close"].dropna().values
            if len(closes) < 21:
                continue
            cur = float(closes[-1])

            ret5d  = (cur / float(closes[-6])  - 1) * 100 if len(closes) > 5  else None
            ret20d = (cur / float(closes[-21]) - 1) * 100 if len(closes) > 20 else None

            # 52주 고저 (거래일 기준 252일)
            hi52 = float(closes[-252:].max()) if len(closes) >= 252 else float(closes.max())
            lo52 = float(closes[-252:].min()) if len(closes) >= 252 else float(closes.min())

            # 20일 신고가: 오늘 종가 > 직전 20거래일 최고가
            hi20_prev = float(closes[-21:-1].max())
            new_hi20  = cur > hi20_prev

            result[name] = {
                "ret5d":    round(ret5d, 1)  if ret5d  is not None else None,
                "ret20d":   round(ret20d, 1) if ret20d is not None else None,
                "hi52":     round(hi52, 2),
                "lo52":     round(lo52, 2),
                "pct_hi52": round((cur / hi52 - 1) * 100, 1),
                "pct_lo52": round((cur / lo52 - 1) * 100, 1),
                "new_hi20": new_hi20,
            }
            s5  = f"{'+' if ret5d  >= 0 else ''}{ret5d:.1f}%"  if ret5d  is not None else "N/A"
            s20 = f"{'+' if ret20d >= 0 else ''}{ret20d:.1f}%" if ret20d is not None else "N/A"
            print(f"  {name}: 5D {s5}  20D {s20}  52W고 대비 {cur/hi52*100-100:+.1f}%  {'★신고가' if new_hi20 else ''}")
        except Exception as e:
            print(f"  {name} 추세 오류: {e}")
    return result


def get_market_context():
    ctx = {
        "vix": None, "vix_ok": False,
        "kospi_ma60": None, "kospi_above_ma60": False,
    }
    try:
        hist = yf.Ticker("^VIX").history(period="5d")
        if not hist.empty:
            ctx["vix"]    = round(float(hist["Close"].iloc[-1]), 2)
            ctx["vix_ok"] = ctx["vix"] < 35
            print(f"  VIX: {ctx['vix']} ({'✓' if ctx['vix_ok'] else '✗'} 35이하)")
    except Exception as e:
        print(f"  VIX 오류: {e}")

    for ticker, prefix in [("^KS11", "kospi"), ("^KQ11", "kosdaq")]:
        try:
            hist   = yf.Ticker(ticker).history(period="200d")
            closes = hist["Close"].dropna()
            if len(closes) >= 2:
                cur = round(float(closes.iloc[-1]), 2)
                ctx[f"{prefix}_cur"] = cur
                for n in [20, 60, 120]:
                    if len(closes) >= n:
                        ma = round(float(closes.tail(n).mean()), 2)
                        ctx[f"{prefix}_ma{n}"]       = ma
                        ctx[f"{prefix}_above_ma{n}"] = cur > ma
                # 스크리닝 게이트 조건은 코스피 MA60 기준 유지
                if prefix == "kospi":
                    ctx["kospi_ma60"]       = ctx.get("kospi_ma60", ctx.get("kospi_ma60"))
                    ctx["kospi_above_ma60"] = ctx.get("kospi_above_ma60", False)
                    if "kospi_ma60" in ctx:
                        ctx["kospi_above_ma60"] = cur > ctx["kospi_ma60"]
                ma_info = " / ".join([f"MA{n}={'✓' if ctx.get(f'{prefix}_above_ma{n}') else '✗'}" for n in [20,60,120] if f"{prefix}_ma{n}" in ctx])
                print(f"  {ticker}: {cur:,.2f}  {ma_info}")
        except Exception as e:
            print(f"  {ticker} MA 오류: {e}")

    # 스크리닝 게이트용 kospi_ma60 / kospi_above_ma60 보장
    if "kospi_ma60" not in ctx and "kospi_ma60" in ctx:
        pass
    ctx.setdefault("kospi_ma60", ctx.get("kospi_ma60"))
    ctx.setdefault("kospi_above_ma60", ctx.get("kospi_above_ma60", False))
    # kospi_ma60 / kospi_above_ma60 는 kospi_ma60 키로 통일
    if "kospi_ma60" not in ctx:
        ctx["kospi_ma60"]       = ctx.get("kospi_ma60")
        ctx["kospi_above_ma60"] = ctx.get("kospi_above_ma60", False)

    return ctx

# ── 1. 코스피·코스닥 지수 (KIS 업종 일봉 — 전거래일 시가/종가 직접 조회) ──
def get_index(token):
    result   = {}
    prev_day = prev_trading_day()
    yf_map   = {"코스피": "^KS11", "코스닥": "^KQ11"}

    for iscd, name in [("0001", "코스피"), ("1001", "코스닥")]:
        try:
            data = kis_get(token,
                "/uapi/domestic-stock/v1/quotations/inquire-index-daily-chartprice",
                "FHKUP03500100",
                {
                    "FID_COND_MRKT_DIV_CODE": "U",
                    "FID_INPUT_ISCD":         iscd,
                    "FID_INPUT_DATE_1":        prev_day,
                    "FID_INPUT_DATE_2":        prev_day,
                    "FID_PERIOD_DIV_CODE":     "D",
                    "FID_ORG_ADJ_PRC":        "0",
                }
            )
            rows = data.get("output2") or data.get("output1") or []
            if isinstance(rows, dict):
                rows = [rows]
            if not rows:
                raise ValueError(f"빈 응답 rt_cd={data.get('rt_cd')} msg={data.get('msg1')}")

            row   = rows[0]
            close = float(row.get("bstp_nmix_prpr") or row.get("stck_clpr") or 0)
            open_ = float(row.get("bstp_nmix_oprc") or row.get("stck_oprc") or 0)
            if close <= 0:
                raise ValueError("종가 0 또는 누락")

            # 전일대비율이 있으면 우선(close-to-close), 없으면 시가 대비
            pct_raw = str(row.get("bstp_nmix_prdy_ctrt") or row.get("prdy_ctrt") or "")
            if pct_raw and pct_raw not in ("", "0", "0.00"):
                pct = round(float(pct_raw), 2)
                chg = round(close * pct / 100, 2)
            elif open_ > 0:
                chg = round(close - open_, 2)
                pct = round(chg / open_ * 100, 2)
            else:
                chg = pct = 0

            result[name] = {"close": round(close, 2), "chg": chg, "pct": pct}
            print(f"  {name}: {close:,.2f} ({pct:+.2f}%) [KIS {prev_day}]")

        except Exception as e:
            print(f"  {name} KIS 지수 오류: {e} — yfinance 백업")
            try:
                import yfinance as yf
                hist   = yf.Ticker(yf_map[name]).history(period="30d")
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    prev  = float(closes.iloc[-2])
                    close = float(closes.iloc[-1])
                    chg   = round(close - prev, 2)
                    pct   = round((close - prev) / prev * 100, 2)
                else:
                    close = chg = pct = 0
                result[name] = {"close": round(close, 2), "chg": chg, "pct": pct}
                print(f"  {name}: {close:,.2f} ({pct:+.2f}%) [yfinance 백업]")
            except Exception as e2:
                print(f"  {name} yfinance도 실패: {e2}")
                result[name] = {"close": None, "chg": None, "pct": None}
    return result

# ── 2. 수급 (KIS 시장별 투자자 → pykrx 백업) ──────────────────
def get_trading(token):
    result   = {"외국인": 0, "기관": 0, "개인": 0, "단위": "억원"}
    prev_day = prev_trading_day()

    # 1순위: KIS 시장별 투자자매매동향(일별) [FHPTJ04040000]
    # - KRX 직접 / pykrx 는 해외 IP 차단 → GitHub Actions 불가
    # - KIS 서버는 해외 IP 허용 → Actions·로컬 모두 동작
    # - FID_INPUT_ISCD_2 는 업종분류코드(필수). KOSPI 전체는 "0001".
    # - 응답 단위: 백만원 → ÷100 하여 억원으로 변환
    try:
        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
            "FHPTJ04040000",
            {
                "FID_COND_MRKT_DIV_CODE": "U",      # 업종
                "FID_INPUT_ISCD":         "0001",   # KOSPI 종합
                "FID_INPUT_DATE_1":       prev_day,
                "FID_INPUT_ISCD_1":       "KSP",    # 코스피 시장 식별
                "FID_INPUT_DATE_2":       prev_day,
                "FID_INPUT_ISCD_2":       "0001",   # 업종분류코드(필수, 빈 값이면 0 반환)
            }
        )
        rt  = data.get("rt_cd", "?")
        msg = data.get("msg1", "")
        print(f"  수급(KIS) rt_cd={rt} msg={msg}")
        out = data.get("output", [])
        if isinstance(out, list) and len(out) > 0:
            row = out[0]

            def _raw(key):
                try:
                    return int(str(row.get(key, "0")).replace(",", "").strip() or "0")
                except:
                    return 0

            # API 반환 단위: 백만원 → 100으로 나눠 억원으로 변환
            result["외국인"] = _raw("frgn_ntby_tr_pbmn") // 100
            result["기관"]   = _raw("orgn_ntby_tr_pbmn") // 100
            result["개인"]   = _raw("prsn_ntby_tr_pbmn") // 100
            print(f"  수급(KIS) 외국인={result['외국인']:+,}억 기관={result['기관']:+,}억 개인={result['개인']:+,}억")

            if any(result[k] != 0 for k in ["외국인", "기관", "개인"]):
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

    raise Exception(
        "수급 데이터 수집 완전 실패: KIS API + pykrx 모두 0 반환.\n"
        "잘못된 데이터로 리포트 생성을 차단합니다."
    )

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

# ── 4. 외국인+기관 20거래일 누적 순매수 (보조 조건 ⑥) ──
def get_supply_20d(token, code):
    """외국인+기관 최근 20거래일 누적 순매수 수량 합산"""
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
                total += int(item.get("orgn_ntby_qty", 0))
                count += 1
            except:
                pass
            if count >= 20:
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

            supply_20d = get_supply_20d(token, code)
            supply_ok  = supply_20d > 0

            detail = get_price_detail(token, code)
            time.sleep(0.2)

            near_high, high_60d = check_60d_high(closes)

            stop   = round(close_now * 0.93, 0)
            target = round(close_now * 1.18, 0)

            # 코어(①②) + 게이트(③④) 모두 충족이 전제 — 하나라도 미충족 시 D
            core_ok = aligned and vol_ok
            gate_ok = kospi_ok and vix_ok
            max_score = 6

            if not (core_ok and gate_ok):
                grade = "D"
                score = sum([aligned, vol_ok, kospi_ok, vix_ok, near_high, supply_ok])
            else:
                aux = sum([near_high, supply_ok])
                score = 4 + aux
                grade = "A" if aux == 2 else ("B" if aux == 1 else "C")

            high_str = f"✓ {high_60d:,}원" if near_high else "✗"
            print(f"  {name} [{grade}] {score}/{max_score}점 — MA:{aligned} 거래량:{vol_ok} 코스피:{kospi_ok} VIX:{vix_ok} 60D고점:{near_high} 수급20일:{supply_ok}({supply_20d:+,})")

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
                "수급20일":     "✓" if supply_ok else "✗",
                "수급누적":     supply_20d,
                "코스피MA60":   "✓" if kospi_ok else "✗",
                "VIX35이하":    "✓" if vix_ok else "✗",
                "60일고점":     high_str,
                "PER":          detail["per"],
                "PBR":          detail["pbr"],
                "ROE":          detail["roe"],
                "손절가":       int(stop),
                "목표가":       int(target),
            })

        except Exception as e:
            print(f"  {name} 오류: {e}")
            continue

    results.sort(key=lambda x: ({"A": 0, "B": 1, "C": 2}.get(x["등급"], 3), -x["점수"]))
    return results

# ── 텍스트 포맷 ────────────────────────────────────
def build_text(indices, trading, candidates, mkt_ctx, trend=None):
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
    lines.append(f"  VIX         {vix_str:>8}  {'✓ 35이하 — 패닉 환경 아님' if mkt_ctx['vix_ok'] else '✗ 35초과 — 패닉 환경, 진입 불가'}")
    for n in [20, 60, 120]:
        key = f"kospi_ma{n}"
        if key in mkt_ctx and mkt_ctx[key]:
            val = f"{mkt_ctx[key]:,.2f}"
            above = mkt_ctx.get(f"kospi_above_ma{n}", False)
            gate  = " ← 게이트 조건" if n == 60 else ""
            lines.append(f"  코스피 MA{n:<3} {val:>10}  {'✓ 위' if above else '✗ 아래'}{gate}")
    for n in [20, 60, 120]:
        key = f"kosdaq_ma{n}"
        if key in mkt_ctx and mkt_ctx[key]:
            val = f"{mkt_ctx[key]:,.2f}"
            above = mkt_ctx.get(f"kosdaq_above_ma{n}", False)
            lines.append(f"  코스닥 MA{n:<3} {val:>10}  {'✓ 위' if above else '✗ 아래'}")

    if trend:
        lines.append(f"\n【 지수 추세 분석 】")
        for name, t in trend.items():
            s5  = f"{'+' if t['ret5d']  >= 0 else ''}{t['ret5d']:.1f}%"  if t['ret5d']  is not None else "N/A"
            s20 = f"{'+' if t['ret20d'] >= 0 else ''}{t['ret20d']:.1f}%" if t['ret20d'] is not None else "N/A"
            hi_flag = "  ★ 20일 신고가" if t['new_hi20'] else ""
            lines.append(f"  {name}  |  5일 {s5}  /  20일 {s20}{hi_flag}")
            lines.append(f"    52주 고점 {t['hi52']:,.0f}  대비 {t['pct_hi52']:+.1f}%")
            lines.append(f"    52주 저점 {t['lo52']:,.0f}  대비 +{t['pct_lo52']:.1f}%")

    passing  = [c for c in candidates if c["등급"] in ("A", "B", "C")]
    watching = [c for c in candidates if c["등급"] == "D"]

    lines.append(f"\n【 체크리스트 스크리닝 결과 】")
    if passing:
        for c in passing:
            per_str = f"{c['PER']:.1f}x" if c['PER'] else "N/A"
            pbr_str = f"{c['PBR']:.2f}x" if c['PBR'] else "N/A"
            roe_str = f"{c['ROE']:.1f}%" if c['ROE'] else "N/A"
            lines.append(f"\n  ▶ {c['종목명']} ({c['종목코드']}) [{c['등급']}등급 {c['점수']}/{c['최대점수']}점]")
            lines.append(f"    현재가: {c['현재가']:,}원")
            lines.append(f"    MA20: {c['MA20']:,} | MA60: {c['MA60']:,} | MA120: {c['MA120']:,}")
            lines.append(f"    이평선정배열: {c['이평선정배열']} | 거래량1.5배: {c['거래량']} | 코스피MA60: {c['코스피MA60']} | VIX35이하: {c['VIX35이하']}")
            lines.append(f"    수급20일(외국인+기관): {c['수급20일']} ({c['수급누적']:+,}주) | 60일고점근접: {c['60일고점']}")
            lines.append(f"    PER: {per_str} | PBR: {pbr_str} | ROE: {roe_str}")
            lines.append(f"    손절가: {c['손절가']:,}원 (-7%) | 1차목표: {c['목표가']:,}원 (+18%)")
    else:
        lines.append("  진입 신호 없음")

    if watching:
        lines.append(f"\n【 종목별 조건 현황 (D등급 — {len(watching)}개) 】")
        lines.append(f"  {'종목명':<10} {'점수':>4}  정배열  거래량  수급20일  60일고점  현재가")
        lines.append(f"  {'-'*62}")
        for c in watching:
            hi = "✓" if "✓" in c['60일고점'] else "✗"
            lines.append(
                f"  {c['종목명']:<8}  {c['점수']}/{c['최대점수']}점"
                f"  정배열{c['이평선정배열']}  거래량{c['거래량']}"
                f"  수급{c['수급20일']}  60일고점{hi}"
                f"  {c['현재가']:,}원"
            )
            lines.append(
                f"    └ MA20 {c['MA20']:,} / MA60 {c['MA60']:,} / MA120 {c['MA120']:,}"
            )

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

    print("📡 지수 추세 분석 중 (5일·20일 수익률 / 52주 고저)...")
    trend = get_index_trend()

    print("📡 코스피·코스닥 지수 수집 중...")
    indices = get_index(token)

    print("📡 수급 데이터 수집 중...")
    trading = get_trading(token)
    print(f"  외국인: {trading['외국인']:,} | 기관: {trading['기관']:,} | 개인: {trading['개인']:,}")

    print("📡 체크리스트 스크리닝 중...")
    candidates = screen_stocks(token, mkt_ctx)
    print(f"  → A/B등급 종목 {len(candidates)}개")

    print("📝 텍스트 생성 중...")
    text = build_text(indices, trading, candidates, mkt_ctx, trend)
    print(text)

    print("💾 GitHub 저장 중...")
    save_to_github(text)
    print("🎉 완료!")
