import os
import sys
import base64
import json
import requests
import time
import numpy as np
import yfinance as yf
from pathlib import Path
from pykrx import stock as krx
from datetime import datetime, timedelta
import pytz
import holidays as _holidays_lib

# backtest/ 를 import path 에 추가 — strategy 모듈 공유 (single source of truth)
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "backtest"))
from strategy import (  # noqa: E402
    load_config as _load_strategy_config,
    check_minervini_core,
    check_minervini_detailed,
    check_market_gate,
)

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

def _build_kr_market_holidays():
    """KRX 휴장일 = 관공서 공휴일 + 근로자의 날(5/1). 전후 2년 범위."""
    from datetime import date as _date
    year = NOW.year
    years = range(year - 1, year + 3)
    h = _holidays_lib.KR(years=years)
    for y in years:
        h[_date(y, 5, 1)] = "근로자의 날"
    return h

_KR_HOLIDAYS = _build_kr_market_holidays()

def latest_trading_day():
    """장 마감(15:30) 이후면 오늘, 이전이면 전 거래일 반환 (주말·공휴일 제외)"""
    market_close = NOW.replace(hour=15, minute=30, second=0, microsecond=0)
    if NOW >= market_close and NOW.weekday() < 5 and NOW.date() not in _KR_HOLIDAYS:
        d = NOW.date()
    else:
        d = NOW.date() - timedelta(days=1)
        while d.weekday() >= 5 or d in _KR_HOLIDAYS:
            d -= timedelta(days=1)
    return d.strftime("%Y%m%d")

# 하위 호환
def prev_trading_day():
    return latest_trading_day()

# ── 전략 파라미터 (strategy_config.yaml 단일 소스, 2026-04-22 재확정 T10/CD60) ──
STRATEGY_CFG = _load_strategy_config()
STRATEGY_STOP_LOSS   = STRATEGY_CFG["risk"]["stop_loss"]
STRATEGY_TRAIL_STOP  = STRATEGY_CFG["risk"]["trail_stop"]
# 쿨다운: 거래일 → 달력일 환산 (252/365 비율 역적용)
STRATEGY_COOLDOWN_D  = int(round(STRATEGY_CFG["cooldown_days"] * 365 / 252))
STRATEGY_MAX_HOLD    = STRATEGY_CFG["risk"]["max_hold_days"]
STRATEGY_MAX_POS     = STRATEGY_CFG["risk"]["max_positions"]

# ── 스크리닝 state (쿨다운 추적) ────────────────────
STATE_DIR  = Path("reports/state")
STATE_PATH = STATE_DIR / "screening_history.json"

def load_screening_state():
    """이전 실행들의 A/B 등급 이력을 로드.
    Format: {ticker: {"last_high_grade_date": "YYYY-MM-DD",
                        "last_exit_date": "YYYY-MM-DD" or None}}
    """
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [warn] screening state 로드 실패: {e}")
    return {}


def save_screening_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def read_current_holdings(path="holdings_data.txt"):
    """holdings_data.txt 에서 현재 보유 종목코드 set 파싱."""
    import re
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return set(re.findall(r'\((\d{6})\)', content))
    except Exception:
        return set()


def update_screening_state(state, high_grade_today, today_str,
                            held_tickers=None):
    """오늘 A/B 등급 상태 + 실제 보유 이탈을 기반으로 state 갱신.

    Rules:
    - (A/B→out) 이전에 A/B였으나 오늘 빠진 종목: last_exit_date = today
    - (A/B 유지) 오늘 A/B 종목: last_high_grade_date = today
    - (held→not held) 어제 보유였으나 오늘 없는 종목: last_exit_date = today
      (포지션 청산이 등급 이탈보다 먼저 감지될 수 있도록)
    """
    # 포지션 청산 감지: 어제 보유 목록(_held) 과 오늘 실제 보유 비교
    if held_tickers is not None:
        prev_held = set(state.get("_held_tickers", []))
        exited = prev_held - held_tickers
        for tk in exited:
            state.setdefault(tk, {})
            # 이미 더 최근 exit_date 가 있으면 덮어쓰지 않음
            existing = state[tk].get("last_exit_date", "")
            if not existing or existing < today_str:
                state[tk]["last_exit_date"] = today_str
        state["_held_tickers"] = sorted(held_tickers)

    for tk, info in list(state.items()):
        if tk.startswith("_"):
            continue
        if tk in high_grade_today:
            continue
        last_hg = info.get("last_high_grade_date")
        last_ex = info.get("last_exit_date")
        # 마지막 A/B 이후 exit 기록이 없으면 오늘을 exit으로 기록
        if last_hg and (not last_ex or last_hg > last_ex):
            state[tk]["last_exit_date"] = today_str

    for tk in high_grade_today:
        state.setdefault(tk, {})
        state[tk]["last_high_grade_date"] = today_str

    return state


def compute_cooldown_remaining(state, ticker, today_date,
                                threshold=STRATEGY_COOLDOWN_D):
    """쿨다운 잔여 거래일 근사값. 쿨다운 없음이면 None.

    last_exit_date 기준으로만 계산. 등급 복귀 여부로 해제하지 않음 —
    등급(A/B)은 포지션 청산과 무관하게 유지될 수 있어 오탐 원인이 됨.
    """
    info = state.get(ticker, {})
    exit_str = info.get("last_exit_date")
    if not exit_str:
        return None
    try:
        exit_date = datetime.strptime(exit_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    days_since = (today_date - exit_date).days
    if days_since >= threshold:
        return None
    # 잔여 거래일 근사 (달력일 × 252/365)
    remaining_cal = threshold - days_since
    return max(1, int(round(remaining_cal * 252 / 365)))

# UNIVERSE = KOSPI 200 (2026-04-28 KRX 정보데이터시스템 [11006] 다운로드)
# 백테스트 universe (backtest/universe.py 162종목 스냅샷) 와 별개 — 백테는 시점 고정.
UNIVERSE = [
    ("005930", "삼성전자"),                 ("000660", "SK하이닉스"),
    ("373220", "LG에너지솔루션"),             ("005380", "현대차"),
    ("402340", "SK스퀘어"),                ("034020", "두산에너빌리티"),
    ("012450", "한화에어로스페이스"),            ("207940", "삼성바이오로직스"),
    ("329180", "HD현대중공업"),              ("009150", "삼성전기"),
    ("000270", "기아"),                   ("105560", "KB금융"),
    ("006400", "삼성SDI"),                ("028260", "삼성물산"),
    ("032830", "삼성생명"),                 ("055550", "신한지주"),
    ("267260", "HD현대일렉트릭"),             ("068270", "셀트리온"),
    ("010120", "LS ELECTRIC"),          ("042660", "한화오션"),
    ("012330", "현대모비스"),                ("298040", "효성중공업"),
    ("006800", "미래에셋증권"),               ("005490", "POSCO홀딩스"),
    ("010130", "고려아연"),                 ("035420", "NAVER"),
    ("086790", "하나금융지주"),               ("042700", "한미반도체"),
    ("009540", "HD한국조선해양"),             ("034730", "SK"),
    ("010140", "삼성중공업"),                ("015760", "한국전력"),
    ("051910", "LG화학"),                 ("000150", "두산"),
    ("064350", "현대로템"),                 ("316140", "우리금융지주"),
    ("066570", "LG전자"),                 ("003670", "포스코퓨처엠"),
    ("096770", "SK이노베이션"),              ("267250", "HD현대"),
    ("272210", "한화시스템"),                ("035720", "카카오"),
    ("000810", "삼성화재"),                 ("017670", "SK텔레콤"),
    ("079550", "LIG디펜스앤에어로스페이스"),       ("033780", "KT&G"),
    ("011200", "HMM"),                  ("000720", "현대건설"),
    ("138040", "메리츠금융지주"),              ("086280", "현대글로비스"),
    ("024110", "기업은행"),                 ("047810", "한국항공우주"),
    ("278470", "에이피알"),                 ("003550", "LG"),
    ("030200", "KT"),                   ("071050", "한국금융지주"),
    ("047040", "대우건설"),                 ("047050", "포스코인터내셔널"),
    ("0126Z0", "삼성에피스홀딩스"),             ("011070", "LG이노텍"),
    ("006260", "LS"),                   ("259960", "크래프톤"),
    ("018260", "삼성에스디에스"),              ("010950", "S-Oil"),
    ("005940", "NH투자증권"),               ("307950", "현대오토에버"),
    ("443060", "HD현대마린솔루션"),            ("323410", "카카오뱅크"),
    ("039490", "키움증권"),                 ("007660", "이수페타시스"),
    ("005830", "DB손해보험"),               ("028050", "삼성E&A"),
    ("352820", "하이브"),                  ("016360", "삼성증권"),
    ("003230", "삼양식품"),                 ("003490", "대한항공"),
    ("009830", "한화솔루션"),                ("000880", "한화"),
    ("090430", "아모레퍼시픽"),               ("001440", "대한전선"),
    ("066970", "엘앤에프"),                 ("326030", "SK바이오팜"),
    ("078930", "GS"),                   ("052690", "한전기술"),
    ("000100", "유한양행"),                 ("161390", "한국타이어앤테크놀로지"),
    ("180640", "한진칼"),                  ("241560", "두산밥캣"),
    ("377300", "카카오페이"),                ("082740", "한화엔진"),
    ("062040", "산일전기"),                 ("032640", "LG유플러스"),
    ("010060", "OCI홀딩스"),               ("454910", "두산로보틱스"),
    ("034220", "LG디스플레이"),              ("064400", "LG씨엔에스"),
    ("128940", "한미약품"),                 ("001040", "CJ"),
    ("029780", "삼성카드"),                 ("138930", "BNK금융지주"),
    ("036570", "NC"),                   ("450080", "에코프로머티"),
    ("004020", "현대제철"),                 ("021240", "코웨이"),
    ("271560", "오리온"),                  ("022100", "포스코DX"),
    ("175330", "JB금융지주"),               ("002380", "KCC"),
    ("088350", "한화생명"),                 ("011790", "SKC"),
    ("018880", "한온시스템"),                ("004170", "신세계"),
    ("011170", "롯데케미칼"),                ("017800", "현대엘리베이터"),
    ("023530", "롯데쇼핑"),                 ("051900", "LG생활건강"),
    ("251270", "넷마블"),                  ("375500", "DL이앤씨"),
    ("457190", "이수스페셜티케미컬"),            ("006360", "GS건설"),
    ("011780", "금호석유화학"),               ("012750", "에스원"),
    ("014680", "한솔케미칼"),                ("302440", "SK바이오사이언스"),
    ("036460", "한국가스공사"),               ("071970", "HD현대마린엔진"),
    ("097950", "CJ제일제당"),               ("111770", "영원무역"),
    ("035250", "강원랜드"),                 ("004990", "롯데지주"),
    ("005850", "에스엘"),                  ("009970", "영원무역홀딩스"),
    ("028670", "팬오션"),                  ("139480", "이마트"),
    ("103140", "풍산"),                   ("112610", "씨에스윈드"),
    ("120110", "코오롱인더"),                ("139130", "iM금융지주"),
    ("051600", "한전KPS"),                ("000120", "CJ대한통운"),
    ("383220", "F&F"),                  ("001430", "세아베스틸지주"),
    ("001450", "현대해상"),                 ("002790", "아모레퍼시픽홀딩스"),
    ("004370", "농심"),                   ("007340", "DN오토모티브"),
    ("008770", "호텔신라"),                 ("008930", "한미사이언스"),
    ("009420", "한올바이오파마"),              ("011210", "현대위아"),
    ("017960", "한국카본"),                 ("026960", "동서"),
    ("030000", "제일기획"),                 ("069960", "현대백화점"),
    ("192820", "코스맥스"),                 ("204320", "HL만도"),
    ("282330", "BGF리테일"),               ("298020", "효성티앤씨"),
    ("361610", "SK아이이테크놀로지"),           ("000240", "한국앤컴퍼니"),
    ("007070", "GS리테일"),                ("161890", "한국콜마"),
    ("081660", "미스토홀딩스"),               ("073240", "금호타이어"),
    ("000210", "DL"),                   ("001800", "오리온홀딩스"),
    ("003090", "대웅"),                   ("003240", "태광산업"),
    ("004000", "롯데정밀화학"),               ("006040", "동원산업"),
    ("300720", "한일시멘트"),                ("007310", "오뚜기"),
    ("034230", "파라다이스"),                ("069620", "대웅제약"),
    ("093370", "후성"),                   ("192080", "더블유게임즈"),
    ("006280", "녹십자"),                  ("000080", "하이트진로"),
    ("298050", "HS효성첨단소재"),             ("003030", "세아제강지주"),
    ("004490", "세방전지"),                 ("005300", "롯데칠성"),
    ("006650", "대한유화"),                 ("009240", "한샘"),
    ("014820", "동원시스템즈"),               ("069260", "TKG휴켐스"),
    ("071320", "지역난방공사"),               ("137310", "에스디바이오센서"),
    ("185750", "종근당"),                  ("280360", "롯데웰푸드"),
    ("285130", "SK케미칼"),                ("000670", "영풍"),
    ("001680", "대상"),                   ("002030", "아세아"),
    ("002840", "미원상사"),                 ("268280", "미원에스씨"),
    ("005420", "코스모화학"),                ("008730", "율촌화학"),
    ("114090", "GKL"),                  ("005250", "녹십자홀딩스"),
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

# ── KIS API 재시도 래퍼 ───────────────────────────
def kis_get_safe(token, path, tr_id, params, retries=3):
    """kis_get + 429/5xx 자동 재시도 (exponential backoff)"""
    for attempt in range(retries):
        try:
            data = kis_get(token, path, tr_id, params)
            # KIS는 JSON 안에 에러를 넣기도 함
            if isinstance(data, dict) and data.get("rt_cd") == "1":
                msg = data.get("msg1", "")
                if "초과" in msg or "limit" in msg.lower():
                    wait = 2 ** (attempt + 1)
                    print(f"    Rate limit — {wait}초 대기 후 재시도 ({attempt+1}/{retries})")
                    time.sleep(wait)
                    continue
            return data
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    API 오류: {e} — {wait}초 대기 후 재시도")
                time.sleep(wait)
            else:
                raise
    return {}

# ── KIS API 토큰 발급 (파일 캐시 + rate limit 재시도) ───
KIS_TOKEN_CACHE    = Path("/tmp/kis_token.json")
KIS_TOKEN_TTL_SEC  = 23 * 3600  # 24h 유효 중 23h만 사용 (만료 여유)

def get_token():
    """KIS 토큰 발급. /tmp/kis_token.json에 캐싱해 동일 runner 내 step들이 공유.
    rate limit(EGW00133, 1분당 1회) 감지 시 65초 대기 후 1회 재시도."""
    # 1) 캐시 우선
    if KIS_TOKEN_CACHE.exists():
        try:
            cached = json.loads(KIS_TOKEN_CACHE.read_text())
            age = time.time() - float(cached.get("ts", 0))
            if age < KIS_TOKEN_TTL_SEC and cached.get("token"):
                print(f"  ♻️  캐시된 KIS 토큰 재사용 (age={age:.0f}s)")
                return cached["token"]
        except Exception as e:
            print(f"  토큰 캐시 읽기 오류: {e}")

    # 2) 신규 발급 (rate limit 시 65초 대기 후 1회 재시도)
    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }
    for attempt in range(2):
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
        data = r.json()
        if "access_token" in data:
            token = data["access_token"]
            try:
                KIS_TOKEN_CACHE.write_text(
                    json.dumps({"token": token, "ts": time.time()})
                )
            except Exception as e:
                print(f"  토큰 캐시 저장 오류: {e}")
            return token

        if attempt == 0 and data.get("error_code") == "EGW00133":
            print("  ⏳ KIS 토큰 rate limit — 65초 대기 후 재시도")
            time.sleep(65)
            continue

        raise Exception(f"토큰 발급 실패: {data}")

    raise Exception("토큰 발급 실패 (재시도 소진)")

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

# ── Minervini 코어 8조건 체크 (특정 시점 i 기준) ──────
def check_core_at(closes, i):
    """closes[i] 시점에서 코어 8조건 충족 여부 — strategy.py 로 delegate."""
    if i < 0 or i >= len(closes):
        return False
    c_arr = np.asarray(closes, dtype=float)
    return check_minervini_core(c_arr, i, STRATEGY_CFG)

def calc_signal_age(closes):
    """오늘부터 역산하여 코어 통과 연속일수 반환 (최대 20일)"""
    n = len(closes)
    if n < 201:
        return 0
    days = 0
    for d in range(n - 1, max(n - 21, 200), -1):
        if check_core_at(closes, d):
            days += 1
        else:
            break
    return days

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
                if prefix == "kospi" and "kospi_ma60" in ctx:
                    ctx["kospi_above_ma60"] = cur > ctx["kospi_ma60"]
                ma_info = " / ".join([f"MA{n}={'✓' if ctx.get(f'{prefix}_above_ma{n}') else '✗'}" for n in [20,60,120] if f"{prefix}_ma{n}" in ctx])
                print(f"  {ticker}: {cur:,.2f}  {ma_info}")
        except Exception as e:
            print(f"  {ticker} MA 오류: {e}")

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

            row   = rows[-1]  # output2 오름차순(오래된→최신) — 마지막 행이 prev_day
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
        p1    = (NOW - timedelta(days=100)).strftime("%Y%m%d")
        p2    = (NOW - timedelta(days=200)).strftime("%Y%m%d")
        p3    = (NOW - timedelta(days=300)).strftime("%Y%m%d")
        start = (NOW - timedelta(days=400)).strftime("%Y%m%d")

        for s, e in [(start, p3), (p3, p2), (p2, p1), (p1, end)]:
            data = kis_get_safe(token,
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
        data = kis_get_safe(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            }
        )
        out = data.get("output") or data.get("output1") or []
        if isinstance(out, dict):
            out = [out]
        today_str = NOW.strftime("%Y%m%d")
        total, count = 0, 0
        for item in out:
            if item.get("stck_bsop_date") == today_str:
                continue
            frgn = item.get("frgn_ntby_qty", "0") or "0"
            orgn = item.get("orgn_ntby_qty", "0") or "0"
            try:
                total += int(frgn) + int(orgn)
                count += 1
            except ValueError:
                continue
            if count >= 20:
                break
        print(f"    수급20일({code}): {total:+,}주 ({count}일)")
        return total
    except Exception as e:
        print(f"    수급20일({code}) 오류: {e}")
        return 0

# ── 4-A. 종목 가격상세 (PER/PBR/ROE) ─────────────
def get_price_detail(token, code):
    try:
        data = kis_get_safe(token,
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

# ── 5. 스크리닝 (Minervini Trend Template) ────────
def screen_stocks(token, mkt_ctx):
    results  = []
    kospi_ok = mkt_ctx["kospi_above_ma60"]
    vix_ok   = mkt_ctx["vix_ok"]

    # 쿨다운 state 로드 (strategy_config.yaml 기반, T10/CD60)
    state = load_screening_state()
    today_str  = NOW.strftime("%Y-%m-%d")
    today_date = NOW.date()

    # 1단계: 전 종목 OHLCV 수집 + 52주 수익률 (RS 계산용)
    stock_data  = {}   # code -> (name, closes, volumes)
    returns_52w = {}   # code -> 52주 수익률

    for code, name in UNIVERSE:
        try:
            closes, volumes = get_ohlcv(token, code)
            print(f"  {name} 데이터: 종가 {len(closes)}개")
            if len(closes) < 200:
                print(f"  {name} 데이터 부족 스킵 (최소 200개 필요)")
                continue
            stock_data[code] = (name, closes, volumes)
            if len(closes) >= 252:
                returns_52w[code] = closes[-1] / closes[-252] - 1
            else:
                returns_52w[code] = closes[-1] / closes[0] - 1
        except Exception as e:
            print(f"  {name} 데이터 수집 오류: {e}")

    # 2단계: RS percentile 계산
    rs_map = {}
    if returns_52w:
        sorted_rets = sorted(returns_52w.values())
        n = len(sorted_rets)
        for code, ret in returns_52w.items():
            rs_map[code] = sum(1 for v in sorted_rets if v <= ret) / n * 100
        print(f"  RS 계산 완료: {n}종목")

    # 3단계: Minervini 스크리닝 (strategy.py 공유 로직)
    for code, (name, closes, volumes) in stock_data.items():
        try:
            close_now = closes[-1]
            # strategy.check_minervini_detailed 는 numpy 배열 + 인덱스 기준.
            # closes 는 list 일 수 있으므로 변환 후 마지막 인덱스 기준 평가.
            c_arr = np.asarray(closes, dtype=float)
            i = len(c_arr) - 1
            det = check_minervini_detailed(c_arr, i, STRATEGY_CFG)

            ma50, ma150, ma200 = det["ma50"], det["ma150"], det["ma200"]
            ma200_1m = det["ma200_prev"]   # 표시용 alias (백테와 용어 통일)
            hi52, lo52 = det["hi52"], det["lo52"]

            rs_pct = rs_map.get(code, 0)

            # Minervini 8조건 (strategy.py 계산 결과를 분해하여 표시용 변수로)
            core_list = det["conds"]
            c1, c2, c3, c4, c5, c6, c7, c8 = core_list
            core_ok = det["core_ok"]
            aligned = det["aligned"]

            # ── 게이트 ──
            gate_ok = kospi_ok and vix_ok

            # ── 코어/게이트 미통과 → D등급 (수급·가격 API 스킵) ──
            rs_min = STRATEGY_CFG["signal"]["minervini"]["rs_min"]
            rs_ok = rs_pct >= rs_min
            max_score = 12  # 코어8 + 게이트2 + 보조2

            if not (core_ok and gate_ok):
                grade = "D"
                score = sum(core_list) + sum([kospi_ok, vix_ok]) + sum([rs_ok])
                supply_20d = 0
                supply_ok  = False
                detail     = {"per": None, "pbr": None, "roe": None}
                stop       = round(close_now * 0.93, 0)
            else:
                # 코어+게이트 통과 → 수급·가격 API 호출
                supply_20d = get_supply_20d(token, code)
                supply_ok  = supply_20d > 0
                detail = get_price_detail(token, code)
                time.sleep(0.2)
                stop = round(close_now * 0.93, 0)
                score = sum(core_list) + sum([kospi_ok, vix_ok]) + sum([rs_ok, supply_ok])
                aux = sum([rs_ok, supply_ok])
                grade = "A" if aux == 2 else ("B" if aux == 1 else "C")

            # ── 신호 연속일수 (코어 기준) ──
            sig_age = calc_signal_age(closes) if core_ok else 0
            sig_tag = "🆕 신규" if sig_age <= 1 else f"{sig_age}일차"

            # ── 쿨다운 잔여 (strategy_config.yaml cooldown_days 기반) ──
            cooldown_rem = compute_cooldown_remaining(state, code, today_date)

            print(f"  {name} [{grade}] {score}/{max_score}점 [{sig_tag}] — "
                  f"MA정배열:{'✓' if aligned else '✗'} MA200상승:{'✓' if c6 else '✗'} "
                  f"52주:{'✓' if (c7 and c8) else '✗'} RS:{rs_pct:.0f}% "
                  f"수급:{'✓' if supply_ok else '✗'}({supply_20d:+,})"
                  + (f" 쿨다운:⚠ {cooldown_rem}일 남음" if cooldown_rem else ""))

            results.append({
                "종목명":     name,
                "종목코드":   code,
                "신호일수":   sig_age,
                "현재가":     int(close_now),
                "등급":       grade,
                "점수":       score,
                "최대점수":   max_score,
                "MA50":       int(ma50) if ma50 else 0,
                "MA150":      int(ma150) if ma150 else 0,
                "MA200":      int(ma200) if ma200 else 0,
                "MA정배열":   "✓" if aligned else "✗",
                "MA200상승":  "✓" if c6 else "✗",
                "52주고점":   int(hi52),
                "52주저점":   int(lo52),
                "52주고점대비": round((close_now / hi52 - 1) * 100, 1),
                "52주저점대비": round((close_now / lo52 - 1) * 100, 1),
                "RS":         round(rs_pct, 0),
                "수급20일":   "✓" if supply_ok else "✗",
                "수급누적":   supply_20d,
                "코스피MA60": "✓" if kospi_ok else "✗",
                "VIX35이하":  "✓" if vix_ok else "✗",
                "PER":        detail["per"],
                "PBR":        detail["pbr"],
                "ROE":        detail["roe"],
                "손절가":     int(stop),
                "쿨다운잔여":  cooldown_rem,   # 거래일 수 (None이면 없음)
            })

        except Exception as e:
            print(f"  {name} 오류: {e}")
            continue

    results.sort(key=lambda x: ({"A": 0, "B": 1, "C": 2}.get(x["등급"], 3), -x["점수"]))

    # state 업데이트 + 저장 (쿨다운 추적용)
    high_grade_today = {r["종목코드"] for r in results if r["등급"] in ("A", "B")}
    held_tickers = read_current_holdings()
    state = update_screening_state(state, high_grade_today, today_str,
                                   held_tickers=held_tickers or None)
    save_screening_state(state)
    print(f"  screening state 저장: {STATE_PATH}")

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
            pct_val = d["pct"] + 0.0  # -0.0 → 0.0 (avoids "+-0.00%" output)
            sign = "▲" if pct_val >= 0 else "▼"
            prefix = "+" if pct_val >= 0 else "-"
            pct = f"{prefix}{abs(pct_val):.2f}%"
            lines.append(f"  {name:<8} {d['close']:>10,.2f}  {sign} {pct}")

    prev_day = prev_trading_day()
    prev_fmt = f"{prev_day[:4]}.{prev_day[4:6]}.{prev_day[6:]}"

    unit = trading.get("단위", "억원")
    lines.append(f"\n【 수급 (코스피) — {prev_fmt} 기준 / 단위: {unit} 】")
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

    ab_grade  = [c for c in candidates if c["등급"] in ("A", "B")]
    c_grade   = [c for c in candidates if c["등급"] == "C"]
    d_grade   = [c for c in candidates if c["등급"] == "D"]

    lines.append(f"\n【 Minervini 스크리닝 결과 】")
    lines.append(f"  전략: Minervini + 수급 + KOSPI MA60 게이트 + 쿨다운 {STRATEGY_CFG['cooldown_days']}거래일")
    lines.append(f"  리스크: 손절 -{int(STRATEGY_STOP_LOSS*100)}% / 트레일링 -{int(STRATEGY_TRAIL_STOP*100)}% / 최대 {STRATEGY_MAX_POS}종목 / 최대 보유 {STRATEGY_MAX_HOLD}일")
    lines.append(f"  백테(2015~2026, 162종목) CAGR +29.29%, MDD -29.8%, PF 2.22 (실전 기댓값 +15-20%)")
    lines.append(f"  전체 {len(candidates)}종목 — A:{len([c for c in candidates if c['등급']=='A'])} B:{len(ab_grade) - len([c for c in candidates if c['등급']=='A'])} C:{len(c_grade)} D:{len(d_grade)}")

    a_grade = [c for c in ab_grade if c["등급"] == "A"]
    b_grade = [c for c in ab_grade if c["등급"] == "B"]

    if a_grade:
        lines.append(f"\n  ── A등급 ({len(a_grade)}개) — 진입 검토 ──")
        for c in a_grade:
            per_str = f"{c['PER']:.1f}x" if c['PER'] else "N/A"
            pbr_str = f"{c['PBR']:.2f}x" if c['PBR'] else "N/A"
            roe_str = f"{c['ROE']:.1f}%" if c['ROE'] else "N/A"
            sig = c.get("신호일수", 0)
            sig_tag = "🆕" if sig <= 1 else f"{sig}일"
            cd_rem = c.get("쿨다운잔여")
            cd_tag = f" ⚠ 쿨다운 잔여 {cd_rem}거래일" if cd_rem else ""
            lines.append(f"\n  ▶ {c['종목명']} ({c['종목코드']}) [A {c['점수']}/{c['최대점수']}] {sig_tag}{cd_tag}")
            lines.append(f"    {c['현재가']:,}원 | MA50 {c['MA50']:,} / MA150 {c['MA150']:,} / MA200 {c['MA200']:,}")
            lines.append(f"    RS {c['RS']:.0f}% | 수급 {c['수급20일']}({c['수급누적']:+,}주) | 52주고점 {c['52주고점대비']:+.1f}%")
            lines.append(f"    PER {per_str} PBR {pbr_str} ROE {roe_str}")
            lines.append(f"    손절 {c['손절가']:,}원(-7%) | 트레일링(고점-15%)")

    if b_grade:
        lines.append(f"\n  ── B등급 ({len(b_grade)}개) — 조건부 대기 ──")
        lines.append(f"  {'종목명':<10} {'현재가':>10}  RS   수급  신호  쿨다운")
        for c in b_grade:
            sig = c.get("신호일수", 0)
            sig_tag = "🆕" if sig <= 1 else f"{sig}일"
            cd_rem = c.get("쿨다운잔여")
            cd_tag = f"⚠ {cd_rem}일" if cd_rem else "—"
            lines.append(f"  {c['종목명']:<8} {c['현재가']:>10,}원  {c['RS']:.0f}%  {c['수급20일']}  {sig_tag}  {cd_tag}")

    if not a_grade and not b_grade:
        lines.append("  진입 신호 없음 (A/B등급 0개)")

    if c_grade:
        lines.append(f"\n  C등급 {len(c_grade)}개 (코어+게이트 통과, 보조 미충족): "
                      + ", ".join(c["종목명"] for c in c_grade[:10])
                      + (f" 외 {len(c_grade)-10}개" if len(c_grade) > 10 else ""))

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

    print("💾 저장 중...")
    with open(GITHUB_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  로컬 저장 완료 → {GITHUB_FILE}")
    save_to_github(text)
    print("🎉 완료!")
