#!/usr/bin/env python3
"""
sector_report.py — 국내 섹터 ETF 주도섹터 분석
RS(50) + 추세(30) + 자금(20) 100점 산식 | 중기 추세추종 전략
데이터: KIS API (OHLCV·거래량) + yfinance (KOSPI 기준선)
"""
import os, json, base64, requests, time
import numpy as np
from datetime import datetime, timedelta
import pytz
import yfinance as yf

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]
KIS_APP_KEY    = os.environ["KIS_APP_KEY"]
KIS_APP_SECRET = os.environ["KIS_APP_SECRET"]
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"
STATE_FILE   = "sector_state.json"
OUTPUT_FILE  = "sector_data.txt"

# ── 유니버스 (KIS 6자리 코드, 시총 500억+ 업종 ETF) ─────────────────
UNIVERSE = [
    ("091160", "KODEX 반도체"),
    ("381170", "TIGER 반도체TOP10"),
    ("305720", "KODEX 2차전지산업"),
    ("305540", "TIGER 2차전지테마"),
    ("091180", "KODEX 자동차"),
    ("143860", "KODEX 바이오"),
    ("091170", "KODEX 금융"),
    ("091220", "KODEX 은행"),
    ("140700", "KODEX 증권"),
    ("140710", "KODEX 보험"),
    ("139220", "KODEX IT"),
    ("117460", "KODEX 에너지화학"),
    ("117480", "KODEX 철강"),
    ("117490", "KODEX 건설"),
    ("130720", "KODEX 조선"),
    ("273130", "KODEX K-방산"),
    ("227550", "TIGER 미디어컨텐츠"),
    ("214980", "KODEX 게임산업"),
]

# ── KIS API ──────────────────────────────────────────────────────────
def get_token():
    r = requests.post(
        f"{KIS_BASE_URL}/oauth2/tokenP",
        headers={"Content-Type": "application/json"},
        json={"grant_type": "client_credentials",
              "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET},
        timeout=10,
    )
    data = r.json()
    if "access_token" not in data:
        raise Exception(f"KIS 토큰 발급 실패: {data}")
    return data["access_token"]


def kis_get(token, path, tr_id, params):
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    r = requests.get(f"{KIS_BASE_URL}{path}", headers=headers,
                     params=params, timeout=15)
    return r.json()


# ── 데이터 수집 ──────────────────────────────────────────────────────
def fetch_data(token):
    # KOSPI 기준선: yfinance (RS 계산용, 동일 날짜 기준 필요)
    print("📡 KOSPI 기준 데이터 수집 (yfinance)...")
    kospi = yf.Ticker("^KS11").history(period="400d")["Close"].dropna()
    if len(kospi) < 120:
        raise Exception(f"KOSPI 데이터 부족: {len(kospi)}일")
    print(f"  KOSPI {len(kospi)}일치")

    # ETF OHLCV: KIS API (거래량 정확도 확보)
    print("📡 섹터 ETF 수집 중 (KIS API)...")
    etf_data = {}
    today = NOW.strftime("%Y%m%d")
    mid   = (NOW - timedelta(days=210)).strftime("%Y%m%d")
    start = (NOW - timedelta(days=420)).strftime("%Y%m%d")

    for code, name in UNIVERSE:
        try:
            closes, volumes = [], []
            for s, e in [(start, mid), (mid, today)]:
                data = kis_get(token,
                    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                    "FHKST03010100",
                    {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                     "FID_INPUT_DATE_1": s, "FID_INPUT_DATE_2": e,
                     "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"},
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
                time.sleep(0.2)

            if len(closes) < 60:
                print(f"  {name} ({code}): 데이터 부족 {len(closes)}일 → 제외")
                continue

            # 전일 대비 등락률
            cur  = closes[-1]
            prev = closes[-2] if len(closes) >= 2 else cur
            chg_pct = round((cur / prev - 1) * 100, 2) if prev > 0 else 0.0

            etf_data[name] = {
                "code":    code,
                "closes":  closes,
                "volumes": volumes,
                "chg_pct": chg_pct,
            }
            print(f"  {name}: {len(closes)}일치 ✓  {chg_pct:+.2f}%")
        except Exception as e:
            print(f"  {name} ({code}): 오류 — {e}")

    if len(etf_data) < 5:
        raise Exception(
            f"섹터 ETF 데이터 수집 실패: {len(etf_data)}개만 수집됨 (최소 5개 필요)."
        )

    return kospi, etf_data


# ── 점수 계산 ────────────────────────────────────────────────────────
def calc_scores(kospi, etf_data):
    k_arr = kospi.values

    # A. 상대강도(RS) 초과수익률
    rs = {20: {}, 60: {}, 120: {}}
    for name, d in etf_data.items():
        c = np.array(d["closes"])
        min_len = min(len(c), len(k_arr))
        c_t = c[-min_len:]
        k_t = k_arr[-min_len:]
        for n in [20, 60, 120]:
            if min_len > n:
                rs[n][name] = float(c_t[-1]/c_t[-n-1]) - float(k_t[-1]/k_t[-n-1])
            else:
                rs[n][name] = 0.0

    def rank_pct(d):
        vals = list(d.values())
        return {name: sum(1 for x in vals if x <= v) / len(vals) for name, v in d.items()}

    rp = {n: rank_pct(rs[n]) for n in [20, 60, 120]}

    scores = {}
    for name, d in etf_data.items():
        c   = np.array(d["closes"])
        v   = np.array(d["volumes"])
        cur = float(c[-1])

        # A. 상대강도 점수 (50점)
        rs_score = 50 * (0.2*rp[20][name] + 0.5*rp[60][name] + 0.3*rp[120][name])

        # B. 추세 품질 점수 (30점)
        ma20  = float(np.mean(c[-20:]))  if len(c) >= 20  else None
        ma60  = float(np.mean(c[-60:]))  if len(c) >= 60  else None
        ma120 = float(np.mean(c[-120:])) if len(c) >= 120 else None
        trend_score = 0
        if ma20  and cur > ma20:  trend_score += 5
        if ma60  and cur > ma60:  trend_score += 5
        if ma20 and ma60 and ma120 and ma20 > ma60 > ma120:
            trend_score += 10
        lookback = min(len(c), 252)
        if cur >= float(max(c[-lookback:])) * 0.90:
            trend_score += 5
        if len(c) >= 140 and ma120:
            if ma120 > float(np.mean(c[-140:-20])):
                trend_score += 5

        # C. 자금 유입 점수 (20점) — KIS 거래량 기반
        flow_score = 0
        if len(v) >= 60:
            avg20v = float(np.mean(v[-20:]))
            avg60v = float(np.mean(v[-60:]))
            if avg60v > 0:
                ratio = avg20v / avg60v
                if ratio >= 1.5:   flow_score = 20
                elif ratio >= 1.2: flow_score = 10

        def ret_n(n):
            return round((cur / float(c[-n-1]) - 1) * 100, 1) if len(c) > n else None

        scores[name] = {
            "total":   round(rs_score + trend_score + flow_score, 1),
            "rs":      round(rs_score, 1),
            "trend":   trend_score,
            "flow":    flow_score,
            "code":    d["code"],
            "chg_pct": d.get("chg_pct", 0.0),
            "cur":     round(cur, 0),
            "ma20":    round(ma20, 0)  if ma20  else None,
            "ma60":    round(ma60, 0)  if ma60  else None,
            "ma120":   round(ma120, 0) if ma120 else None,
            "r1m":     ret_n(20),
            "r3m":     ret_n(60),
            "r6m":     ret_n(120),
        }

    return scores


# ── 등급 분류 ────────────────────────────────────────────────────────
def classify(total):
    if total >= 80: return "주도"
    if total >= 65: return "강세"
    if total >= 50: return "중립"
    return "약세"


# ── 상태 파일 (GitHub) ────────────────────────────────────────────────
def load_state():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        try:
            return json.loads(base64.b64decode(r.json()["content"]).decode()), r.json()["sha"]
        except Exception:
            pass
    return {}, None


def save_state(state, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"섹터 상태 업데이트 — {TODAY_STR}",
        "content": base64.b64encode(
            json.dumps(state, ensure_ascii=False, indent=2).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"✅ {STATE_FILE} 저장 완료")
    else:
        print(f"❌ {STATE_FILE} 저장 실패: {r.status_code}")


# ── 변동 감지 ────────────────────────────────────────────────────────
def detect_changes(current, prev_state):
    changes = {"new_leaders": [], "demoted": [], "score_jumps": []}
    prev = prev_state.get("scores", {})

    for name, s in current.items():
        cur_grade  = classify(s["total"])
        prev_score = prev.get(name, {}).get("total", 0) if prev else 0
        prev_grade = classify(prev_score) if prev_score else None

        if cur_grade == "주도" and prev_grade != "주도":
            changes["new_leaders"].append(name)
        elif prev_grade == "주도" and cur_grade != "주도":
            changes["demoted"].append(f"{name}({cur_grade})")

        if abs(s["total"] - prev_score) >= 5:
            changes["score_jumps"].append({"name": name, "delta": round(s["total"] - prev_score, 1)})

    return changes


# ── 텍스트 출력 ──────────────────────────────────────────────────────
def build_text(scores, changes):
    lines = []
    lines.append("━" * 52)
    lines.append(f"  📊 주도 섹터 ETF 현황 — {TODAY_STR}")
    lines.append(f"  기준: RS(50) + 추세(30) + 자금유입(20)")
    lines.append("━" * 52)

    sorted_s = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)

    def fmt_r(v):
        if v is None: return "  N/A"
        return f"{'+' if v >= 0 else ''}{v:.1f}%"

    def fmt_chg(pct):
        if pct is None: return "  —  "
        sign = "▲" if pct >= 0 else "▼"
        return f"{sign}{abs(pct):.2f}%"

    def ma_tag(s):
        cur, parts = s["cur"], []
        for n, k in [(20, "ma20"), (60, "ma60"), (120, "ma120")]:
            v = s.get(k)
            if v:
                parts.append(f"MA{n}{'✓' if cur > v else '✗'}")
        return " ".join(parts)

    groups = [
        ("🔥 주도 (80점+)",    lambda s: s["total"] >= 80),
        ("📈 강세 (65~79점)",  lambda s: 65 <= s["total"] < 80),
        ("〰️ 중립 (50~64점)",  lambda s: 50 <= s["total"] < 65),
        ("📉 약세 (50점 미만)", lambda s: s["total"] < 50),
    ]

    for label, cond in groups:
        bucket = [(n, s) for n, s in sorted_s if cond(s)]
        if not bucket:
            continue
        lines.append(f"\n{label}")
        for i, (name, s) in enumerate(bucket, 1):
            prefix = f"  {i}." if s["total"] >= 65 else "  •"
            lines.append(
                f"{prefix} {name:<22} {s['total']:>5.1f}점"
                f"  {fmt_chg(s['chg_pct'])}"
                f"  (RS {s['rs']:.0f} / 추세 {s['trend']} / 자금 {s['flow']})"
            )
            if s["total"] >= 65:
                lines.append(
                    f"     └ 1M {fmt_r(s['r1m'])} / 3M {fmt_r(s['r3m'])} / 6M {fmt_r(s['r6m'])}"
                    f"  {ma_tag(s)}"
                )

    lines.append("\n⚡ 주간 변동 (전주 대비)")
    has = any([changes["new_leaders"], changes["demoted"], changes["score_jumps"]])
    if not has:
        lines.append("  변동 없음")
    else:
        if changes["new_leaders"]:
            lines.append(f"  🆕 신규 주도 진입: {', '.join(changes['new_leaders'])}")
        if changes["demoted"]:
            lines.append(f"  ⬇️  주도 이탈: {', '.join(changes['demoted'])}")
        if changes["score_jumps"]:
            jumps = [
                f"{c['name']} ({'+' if c['delta'] >= 0 else ''}{c['delta']}점)"
                for c in sorted(changes["score_jumps"], key=lambda x: abs(x["delta"]), reverse=True)
            ]
            lines.append(f"  📊 점수 급변: {', '.join(jumps)}")

    lines.append("━" * 52)
    return "\n".join(lines)


# ── GitHub 파일 저장 ──────────────────────────────────────────────────
def save_to_github(filename, content):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": f"섹터 ETF 분석 — {TODAY_STR}",
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    r2 = requests.put(url, headers=headers, json=payload)
    if r2.status_code in (200, 201):
        print(f"✅ {filename} 저장 완료")
    else:
        print(f"❌ {filename} 저장 실패: {r2.status_code} {r2.text[:100]}")


# ── 메인 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🔑 KIS 토큰 발급 중...")
    token = get_token()
    print("✅ 토큰 발급 완료")

    kospi, etf_data = fetch_data(token)
    print(f"✅ {len(etf_data)}개 ETF 데이터 수집 완료\n")

    print("📊 점수 계산 중...")
    scores = calc_scores(kospi, etf_data)

    if not scores or max(s["total"] for s in scores.values()) == 0:
        raise Exception(
            "섹터 ETF 점수 계산 실패: 모든 ETF 점수가 0.\n"
            "KOSPI 기준 데이터 또는 RS 계산에 오류가 있습니다."
        )

    print("📂 이전 상태 로드...")
    prev_state, state_sha = load_state()
    changes = detect_changes(scores, prev_state)

    text = build_text(scores, changes)
    print("\n" + text)

    print("\n💾 저장 중...")
    new_state = {
        "date": TODAY_STR,
        "scores": {
            n: {"total": s["total"], "grade": classify(s["total"])}
            for n, s in scores.items()
        },
    }
    save_state(new_state, state_sha)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  로컬 저장 완료 → {OUTPUT_FILE}")
    save_to_github(OUTPUT_FILE, text)
    print("🎉 섹터 분석 완료!")
