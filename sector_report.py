#!/usr/bin/env python3
"""
sector_report.py — 국내 섹터 ETF 주도섹터 분석
RS(50) + 추세(30) + 자금(20) 100점 산식 | 중기 추세추종 전략
"""
import os, json, base64, requests, time
import numpy as np
from datetime import datetime
import pytz
import yfinance as yf

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]
STATE_FILE   = "sector_state.json"
OUTPUT_FILE  = "sector_data.txt"

# ── 유니버스 (시총 500억+ 업종 ETF, 테마 ETF 제외) ──────────────
UNIVERSE = [
    ("091160.KS", "KODEX 반도체"),
    ("381170.KS", "TIGER 반도체TOP10"),
    ("305720.KS", "KODEX 2차전지산업"),
    ("305540.KS", "TIGER 2차전지테마"),
    ("091180.KS", "KODEX 자동차"),
    ("143860.KS", "KODEX 바이오"),
    ("091170.KS", "KODEX 금융"),
    ("091220.KS", "KODEX 은행"),
    ("140700.KS", "KODEX 증권"),
    ("140710.KS", "KODEX 보험"),
    ("139220.KS", "KODEX IT"),
    ("117460.KS", "KODEX 에너지화학"),
    ("117480.KS", "KODEX 철강"),
    ("117490.KS", "KODEX 건설"),
    ("130720.KS", "KODEX 조선"),
    ("273130.KS", "KODEX K-방산"),
    ("227550.KS", "TIGER 미디어컨텐츠"),
    ("214980.KS", "KODEX 게임산업"),
]

# ── 데이터 수집 ──────────────────────────────────────────────────
def fetch_data():
    print("📡 KOSPI 기준 데이터 수집...")
    kospi = yf.Ticker("^KS11").history(period="300d")["Close"].dropna()
    if len(kospi) < 120:
        raise Exception(f"KOSPI 데이터 부족: {len(kospi)}일")
    print(f"  KOSPI {len(kospi)}일치")

    print("📡 섹터 ETF 수집 중...")
    etf_data = {}
    for ticker, name in UNIVERSE:
        try:
            hist = yf.Ticker(ticker).history(period="300d")
            closes  = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()
            if len(closes) < 60:
                print(f"  {name} ({ticker}): 데이터 부족 {len(closes)}일 → 제외")
                continue
            etf_data[name] = {"ticker": ticker, "closes": closes, "volumes": volumes}
            print(f"  {name}: {len(closes)}일치 ✓")
            time.sleep(0.15)
        except Exception as e:
            print(f"  {name} ({ticker}): 오류 — {e}")

    if len(etf_data) < 5:
        raise Exception(
            f"섹터 ETF 데이터 수집 실패: {len(etf_data)}개만 수집됨 (최소 5개 필요).\n"
            "yfinance .KS 티커 접속 장애로 판단합니다."
        )

    return kospi, etf_data


# ── 점수 계산 ────────────────────────────────────────────────────
def calc_scores(kospi, etf_data):
    names    = list(etf_data.keys())
    k_arr    = kospi.values

    # ── A. 상대강도(RS) 초과수익률 계산 ──
    rs = {20: {}, 60: {}, 120: {}}
    for name, d in etf_data.items():
        c = d["closes"].values
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
        c   = d["closes"].values
        v   = d["volumes"].values
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
        # 52주 신고가 -10% 이내
        lookback = min(len(c), 252)
        high_52w = float(max(c[-lookback:]))
        if cur >= high_52w * 0.90:
            trend_score += 5
        # MA120 우상향 (현재 MA120 > 20영업일 전 MA120)
        if len(c) >= 140 and ma120:
            ma120_prev = float(np.mean(c[-140:-20]))
            if ma120 > ma120_prev:
                trend_score += 5

        # C. 자금 유입 점수 (20점)
        flow_score = 0
        if len(v) >= 60:
            avg20v = float(np.mean(v[-20:]))
            avg60v = float(np.mean(v[-60:]))
            if avg60v > 0:
                ratio = avg20v / avg60v
                if ratio >= 1.5:
                    flow_score = 20
                elif ratio >= 1.2:
                    flow_score = 10

        # 수익률
        def ret_n(n):
            return round((cur / float(c[-n-1]) - 1) * 100, 1) if len(c) > n else None

        scores[name] = {
            "total":   round(rs_score + trend_score + flow_score, 1),
            "rs":      round(rs_score, 1),
            "trend":   trend_score,
            "flow":    flow_score,
            "ticker":  d["ticker"],
            "cur":     round(cur, 0),
            "ma20":    round(ma20, 0)  if ma20  else None,
            "ma60":    round(ma60, 0)  if ma60  else None,
            "ma120":   round(ma120, 0) if ma120 else None,
            "r1m":     ret_n(20),
            "r3m":     ret_n(60),
            "r6m":     ret_n(120),
            "rs_20d":  round(rs[20][name]*100, 1),
            "rs_60d":  round(rs[60][name]*100, 1),
            "rs_120d": round(rs[120][name]*100, 1),
        }

    return scores


# ── 등급 분류 ────────────────────────────────────────────────────
def classify(total):
    if total >= 80: return "주도"
    if total >= 65: return "강세"
    if total >= 50: return "중립"
    return "약세"


# ── 상태 파일 (GitHub) ────────────────────────────────────────────
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


# ── 변동 감지 ────────────────────────────────────────────────────
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

        delta = s["total"] - prev_score
        if abs(delta) >= 5:
            changes["score_jumps"].append({"name": name, "delta": round(delta, 1)})

    return changes


# ── 텍스트 출력 ──────────────────────────────────────────────────
def build_text(scores, changes):
    lines = []
    lines.append("━" * 48)
    lines.append(f"  📊 주도 섹터 ETF 현황 — {TODAY_STR}")
    lines.append(f"  기준: RS(50) + 추세(30) + 자금유입(20)")
    lines.append("━" * 48)

    sorted_s = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)

    def fmt_r(v):
        if v is None: return "  N/A"
        return f"{'+' if v >= 0 else ''}{v:.1f}%"

    def ma_tag(s):
        cur = s["cur"]
        parts = []
        for n, k in [(20, "ma20"), (60, "ma60"), (120, "ma120")]:
            v = s.get(k)
            if v:
                parts.append(f"MA{n}{'✓' if cur > v else '✗'}")
        return " ".join(parts)

    groups = [
        ("🔥 주도 (80점+)",   lambda s: s["total"] >= 80),
        ("📈 강세 (65~79점)", lambda s: 65 <= s["total"] < 80),
        ("〰️ 중립 (50~64점)", lambda s: 50 <= s["total"] < 65),
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
                f"  (RS {s['rs']:.0f} / 추세 {s['trend']} / 자금 {s['flow']})"
            )
            if s["total"] >= 65:
                lines.append(
                    f"     └ 1M {fmt_r(s['r1m'])} / 3M {fmt_r(s['r3m'])} / 6M {fmt_r(s['r6m'])}"
                    f"  {ma_tag(s)}"
                )

    # 변동 감지
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

    lines.append("━" * 48)
    return "\n".join(lines)


# ── GitHub 파일 저장 ─────────────────────────────────────────────
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


# ── 메인 ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    kospi, etf_data = fetch_data()
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
    save_to_github(OUTPUT_FILE, text)
    print("🎉 섹터 분석 완료!")
