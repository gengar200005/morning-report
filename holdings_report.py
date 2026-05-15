import os
import base64
import requests
import time
import yaml
from datetime import datetime
import pytz

import json
from datetime import timedelta

from kr_report import (
    get_token,
    get_ohlcv,
    get_supply_20d,
    calc_ma,
    get_market_context,
    kis_get,
    prev_trading_day,
)

_cfg_path = os.path.join(os.path.dirname(__file__), "backtest", "strategy_config.yaml")
with open(_cfg_path) as _f:
    _STRATEGY_CFG = yaml.safe_load(_f)
TRAIL_STOP_PCT  = _STRATEGY_CFG["risk"]["trail_stop"]   # 0.10
HARD_STOP_PCT   = _STRATEGY_CFG["risk"]["stop_loss"]    # 0.07

# ── 설정 ──────────────────────────────────────────
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_HOLDINGS_DB_ID = os.environ.get(
    "NOTION_HOLDINGS_DB_ID", "9ff024c9c4964b849a49ec501f6c3622"
)
# 2025-09-03 Notion API 부터 DB 가 container + data_source(s) 로 분리됨.
# query 는 data_source ID 로 호출해야 함 (DB ID 사용 시 deprecated/실패).
NOTION_HOLDINGS_DS_ID = os.environ.get(
    "NOTION_HOLDINGS_DS_ID", "25d578de-8e37-486d-8787-549667cae981"
)

GITHUB_TOKEN = os.environ["MORNINGREPOT"]
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_FILE  = "holdings_data.txt"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")


INDEX_SNAPSHOT_PATH = "index_snapshot.json"


# ── KOSPI/KOSDAQ 종가 스냅샷 ───────────────────────
def save_index_snapshot(token):
    """
    KIS 토큰을 재활용해 KOSPI/KOSDAQ 전일 종가를 취득, index_snapshot.json 저장.
    holdings_report(step 40) → kr_report(step 47) 순서를 이용한 캐시 구조.
    두 가지 KIS 경로를 순서대로 시도하고 둘 다 실패 시 스냅샷 미생성.
    """
    prev_day = prev_trading_day()
    prev_day_dt = datetime.strptime(prev_day, "%Y%m%d")
    date_from = (prev_day_dt - timedelta(days=14)).strftime("%Y%m%d")

    result = {}
    for iscd, name in [("0001", "코스피"), ("1001", "코스닥")]:
        for path, tr_id, mkt in [
            # 1순위: 주식 일봉 경로를 업종코드로 시도 (FHKUP 404 우회)
            ("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
             "FHKST03010100", "U"),
            # 2순위: 업종 일봉 전용 경로 (현재 404 — 엔드포인트 복구 시 자동 복원)
            ("/uapi/domestic-stock/v1/quotations/inquire-index-daily-chartprice",
             "FHKUP03500100", "U"),
        ]:
            try:
                data = kis_get(token, path, tr_id, {
                    "FID_COND_MRKT_DIV_CODE": mkt,
                    "FID_INPUT_ISCD":         iscd,
                    "FID_INPUT_DATE_1":       date_from,
                    "FID_INPUT_DATE_2":       prev_day,
                    "FID_PERIOD_DIV_CODE":    "D",
                    "FID_ORG_ADJ_PRC":        "0",
                })
                rows = data.get("output2") or data.get("output1") or []
                if isinstance(rows, dict):
                    rows = [rows]
                if not rows:
                    raise ValueError(f"빈 응답 rt_cd={data.get('rt_cd')}")
                row = next(
                    (r for r in reversed(rows) if r.get("stck_bsop_date") == prev_day),
                    rows[-1]
                )
                close = float(row.get("bstp_nmix_prpr") or row.get("stck_clpr") or 0)
                if close <= 0:
                    raise ValueError("종가 0")
                pct_raw = str(row.get("bstp_nmix_prdy_ctrt") or row.get("prdy_ctrt") or "")
                if pct_raw and pct_raw not in ("", "0", "0.00"):
                    pct = round(float(pct_raw), 2)
                    chg = round(close * pct / 100, 2)
                else:
                    chg = pct = 0
                result[name] = {"close": round(close, 2), "chg": chg, "pct": pct, "source": tr_id}
                print(f"  [index] {name}: {close:,.2f} ({pct:+.2f}%) [{tr_id}]")
                break
            except Exception as e:
                print(f"  [index] {name} {tr_id} 실패: {e}")

    if result:
        with open(INDEX_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump({"date": prev_day, "indices": result}, f, ensure_ascii=False)
        print(f"  [index] 스냅샷 저장 → {INDEX_SNAPSHOT_PATH}")
    else:
        print("  [index] 스냅샷 미생성 — KIS 업종 API 전부 실패")


# ── 노션 DB 조회 ───────────────────────────────────
def fetch_holdings():
    """상태=In progress & 거래소∈{KRX, KOSDAQ} 필터링하여 보유 종목 조회"""
    url = f"https://api.notion.com/v1/data_sources/{NOTION_HOLDINGS_DS_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2025-09-03",
        "Content-Type": "application/json",
    }
    body = {
        "filter": {
            "and": [
                {"property": "상태", "status": {"equals": "In progress"}},
                {"or": [
                    {"property": "거래소", "select": {"equals": "KRX"}},
                    {"property": "거래소", "select": {"equals": "KOSDAQ"}},
                ]},
            ]
        },
        "page_size": 100,
    }
    r = requests.post(url, headers=headers, json=body, timeout=15)
    if r.status_code != 200:
        raise Exception(f"노션 DB 조회 실패: {r.status_code} {r.text}")

    def get_title(prop):
        return "".join(x.get("plain_text", "") for x in (prop.get("title") or [])).strip()

    def get_rich(prop):
        return "".join(x.get("plain_text", "") for x in (prop.get("rich_text") or [])).strip()

    def get_num(prop):
        return prop.get("number")

    def get_select(prop):
        sel = prop.get("select") or {}
        return sel.get("name")

    def get_date(prop):
        d = prop.get("date") or {}
        return d.get("start")

    def get_check(prop):
        return bool(prop.get("checkbox", False))

    holdings = []
    for page in r.json().get("results", []):
        p = page["properties"]
        holdings.append({
            "page_id":   page["id"],
            "종목명":    get_title(p.get("종목명", {})),
            "종목코드":  get_rich(p.get("종목코드", {})),
            "매수가":    get_num(p.get("매수가", {})),
            "매수일":    get_date(p.get("매수일", {})),
            "거래소":    get_select(p.get("거래소", {})),
            "손절가":    get_num(p.get("손절가", {})),
            "트레일선":  get_num(p.get("트레일선", {})),
            "최고종가":  get_num(p.get("최고종가", {})),
        })
    return holdings


# ── Notion 트레일선 갱신 ────────────────────────────
def update_notion_trailing(page_id, 최고종가, 트레일선, 동적손절선):
    """신고가 갱신 시 Notion 자동매도 트래커 row 업데이트."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2025-09-03",
        "Content-Type": "application/json",
    }
    body = {"properties": {
        "최고종가":   {"number": 최고종가},
        "트레일선":   {"number": 트레일선},
        "동적손절선": {"number": 동적손절선},
        "갱신시각":   {"date": {"start": datetime.now(KST).strftime("%Y-%m-%d")}},
    }}
    r = requests.patch(url, headers=headers, json=body, timeout=15)
    return r.status_code == 200


# ── 종목 분석 (Minervini 지표) ──────────────────────
def analyze_holding(token, h, mkt_ctx):
    code = h["종목코드"]
    name = h["종목명"]
    entry = h.get("매수가") or 0

    if not code or not code.isdigit() or len(code) != 6:
        return {**h, "error": f"종목코드 형식 오류: '{code}'"}

    closes, _ = get_ohlcv(token, code)
    if len(closes) < 200:
        return {**h, "error": f"일봉 데이터 부족 ({len(closes)}개)"}

    close_now = closes[-1]
    ma50  = calc_ma(closes, 50)
    ma150 = calc_ma(closes, 150)
    ma200 = calc_ma(closes, 200)
    ma200_1m = round(sum(closes[-222:-22]) / 200, 0) if len(closes) >= 222 else None

    window = closes[-252:] if len(closes) >= 252 else closes
    hi52 = max(window)
    lo52 = min(window)

    # Minervini 코어 8조건
    c1 = bool(ma50  and close_now > ma50)
    c2 = bool(ma150 and close_now > ma150)
    c3 = bool(ma200 and close_now > ma200)
    c4 = bool(ma50 and ma150 and ma50 > ma150)
    c5 = bool(ma150 and ma200 and ma150 > ma200)
    c6 = bool(ma200 and ma200_1m and ma200 > ma200_1m)
    c7 = close_now >= lo52 * 1.25
    c8 = close_now >= hi52 * 0.75
    core_list = [c1, c2, c3, c4, c5, c6, c7, c8]
    core_ok = all(core_list)
    aligned = all([c1, c2, c3, c4, c5])

    gate_ok = mkt_ctx.get("kospi_above_ma60", False) and mkt_ctx.get("vix_ok", False)

    # 수급 (코어+게이트 통과 시에만 API 호출 — kr_report.py와 동일 정책)
    if core_ok and gate_ok:
        supply_20d = get_supply_20d(token, code)
        time.sleep(0.2)
    else:
        supply_20d = 0
    supply_ok = supply_20d > 0

    # 등급 (RS는 전체 시장 필요 → 이 스크립트에선 제외, 보조=수급만)
    if not (core_ok and gate_ok):
        grade = "D"
    else:
        grade = "B" if supply_ok else "C"

    # ── 손절·TS 도달 감지 + 트레일선 갱신 ──────────────
    stop_loss   = h.get("손절가")   or round(entry * (1 - HARD_STOP_PCT))
    trail_now   = h.get("트레일선") or 0
    max_close   = h.get("최고종가") or entry or close_now

    # 신고가(종가) 갱신 시 트레일선 재계산
    high_updated = close_now > max_close
    new_max   = close_now if high_updated else max_close
    new_trail = round(new_max * (1 - TRAIL_STOP_PCT))
    dyn_stop  = max(stop_loss or 0, new_trail or 0)

    # 전일 종가 기준 도달 여부
    breach_stop  = bool(stop_loss  and close_now < stop_loss)
    breach_trail = bool(trail_now  and close_now < trail_now)

    # ── Hard Gate 간이 판정 ──
    h4 = (close_now >= entry * 1.05) if entry else False
    h5 = (close_now >= stop_loss * 1.05) if stop_loss else False
    hard_ok = core_ok and gate_ok and h4 and h5

    if hard_ok:
        signal = "⭐ 추매 조건 일부 충족 — 추가 판단 필요"
    else:
        fails = []
        if not core_ok:
            fails.append(f"코어 {sum(core_list)}/8")
        if not gate_ok:
            fails.append("시장 게이트")
        if entry and not h4:
            fails.append(f"매수가+5% 미달({(close_now/entry-1)*100:+.1f}%)")
        if stop_loss and not h5:
            fails.append("손절가+5% 미달")
        signal = "❌ 추매 금지 (" + ", ".join(fails) + ")"

    pnl_pct = (close_now / entry - 1) * 100 if entry else 0
    hi52_pct = (close_now / hi52 - 1) * 100

    return {
        **h,
        "현재가":       int(close_now),
        "MA50":         int(ma50)  if ma50  else 0,
        "MA150":        int(ma150) if ma150 else 0,
        "MA200":        int(ma200) if ma200 else 0,
        "코어통과":     sum(core_list),
        "MA정배열":     aligned,
        "MA200상승":    c6,
        "52주고점":     int(hi52),
        "52주고점대비": round(hi52_pct, 1),
        "수급20일":     supply_20d,
        "등급":         grade,
        "손익률":       round(pnl_pct, 2),
        "추매시그널":   signal,
        "손절가":       int(stop_loss) if stop_loss else 0,
        "트레일선_new": int(new_trail),
        "최고종가_new": int(new_max),
        "동적손절선":   int(dyn_stop),
        "고점갱신":     high_updated,
        "손절_도달":    breach_stop,
        "TS_도달":      breach_trail,
    }


# ── 텍스트 포맷 ────────────────────────────────────
def build_text(analyses, mkt_ctx):
    lines = []
    lines.append("=" * 52)
    lines.append(f"  보유 종목 현황 — {TODAY_STR}")
    lines.append("=" * 52)

    if not analyses:
        lines.append("\n  보유 종목 없음 (노션 '상태=In progress' 미발견)")
        lines.append("\n" + "=" * 52)
        return "\n".join(lines)

    gate_ok = mkt_ctx.get("kospi_above_ma60", False) and mkt_ctx.get("vix_ok", False)
    vix = mkt_ctx.get("vix")
    vix_str = f"{vix:.2f}" if vix else "N/A"
    lines.append(f"\n【 시장 게이트 】 {'✓ 통과' if gate_ok else '✗ 실패 — 추매 환경 아님'}")
    lines.append(
        f"  VIX {vix_str} ({'✓' if mkt_ctx.get('vix_ok') else '✗'} 35이하) / "
        f"코스피 60MA {'✓ 위' if mkt_ctx.get('kospi_above_ma60') else '✗ 아래'}"
    )

    lines.append(f"\n【 보유 종목 ({len(analyses)}개) 】")
    for h in analyses:
        lines.append("")
        if "error" in h:
            lines.append(f"  ▶ {h['종목명']} ({h['종목코드']}) — ⚠️ {h['error']}")
            continue

        entry = h.get("매수가") or 0
        stop  = h.get("손절가") or 0
        lines.append(f"  ▶ {h['종목명']} ({h['종목코드']}) [{h['등급']}등급]")
        lines.append(
            f"    매수가 {entry:,.0f} → 현재 {h['현재가']:,} ({h['손익률']:+.2f}%)"
        )
        lines.append(
            f"    MA50 {h['MA50']:,} / MA150 {h['MA150']:,} / MA200 {h['MA200']:,}"
        )
        lines.append(
            f"    정배열:{'✓' if h['MA정배열'] else '✗'} "
            f"MA200상승:{'✓' if h['MA200상승'] else '✗'} "
            f"코어 {h['코어통과']}/8"
        )
        lines.append(
            f"    52주고점 {h['52주고점']:,} (대비 {h['52주고점대비']:+.1f}%)"
        )
        trail = h.get("트레일선_new", 0)
        lines.append(
            f"    손절가 {stop:,.0f} | 트레일선 {trail:,.0f} | 수급20일 {h['수급20일']:+,}주"
        )
        if h.get("손절_도달"):
            lines.append(f"    🚨 손절 도달 — 현재 {h['현재가']:,} < 손절가 {stop:,.0f}")
        if h.get("TS_도달"):
            lines.append(f"    🚨 TS 도달 — 현재 {h['현재가']:,} < 트레일선 {trail:,.0f}")
        if h.get("고점갱신"):
            lines.append(f"    ★ 신고가 갱신 → 트레일선 {trail:,.0f}으로 상향")
        lines.append(f"    ⇒ {h['추매시그널']}")

    lines.append("\n" + "=" * 52)
    return "\n".join(lines)


# ── GitHub 저장 ────────────────────────────────────
def save_to_github(content):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"보유 종목 데이터 업데이트 — {TODAY_STR}",
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
    print("📡 노션 DB에서 보유 종목 조회 중...")
    # 노션 API 변경 (2025-09-03 data sources 분리) 등으로 조회 실패해도
    # morning.yml 후속 step (combine_data / render / PDF / Notion publish) 이
    # 진행되도록 fail-soft. 빈 holdings 분기가 graceful exit 처리.
    try:
        holdings = fetch_holdings()
    except Exception as e:
        print(f"⚠️ 노션 DB 조회 실패 — 빈 보유 목록으로 진행: {e}")
        holdings = []
    print(f"  보유 종목 {len(holdings)}개 발견")
    for h in holdings:
        print(f"  - {h['종목명']} ({h['종목코드']}) 매수가={h['매수가']} 매수일={h['매수일']}")

    if not holdings:
        text = build_text([], {})
        print(text)
        with open(GITHUB_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        save_to_github(text)
        print("🎉 완료!")
        exit(0)

    print("\n🔑 KIS 토큰 발급 중...")
    token = get_token()
    print("✅ 토큰 발급 완료")

    print("\n📡 KOSPI/KOSDAQ 지수 스냅샷 저장 중...")
    save_index_snapshot(token)

    print("\n📡 시장 컨텍스트 수집 중 (VIX / 코스피 MA60)...")
    mkt_ctx = get_market_context()

    print("\n📡 각 보유 종목 Minervini 분석 중...")
    analyses = []
    for h in holdings:
        print(f"  → {h['종목명']} ({h['종목코드']}) 분석 중...")
        analyses.append(analyze_holding(token, h, mkt_ctx))

    # 신고가 갱신 종목 → Notion 트레일선 자동 업데이트
    for a in analyses:
        if a.get("고점갱신") and a.get("page_id"):
            ok = update_notion_trailing(
                a["page_id"], a["최고종가_new"], a["트레일선_new"], a["동적손절선"]
            )
            tag = "✅" if ok else "⚠️"
            print(f"  {tag} {a['종목명']} 트레일선 갱신 → {a['트레일선_new']:,}원")

    print("\n📝 텍스트 생성 중...")
    text = build_text(analyses, mkt_ctx)
    print(text)

    print("\n💾 저장 중...")
    with open(GITHUB_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  로컬 저장 완료 → {GITHUB_FILE}")
    save_to_github(text)
    print("🎉 완료!")
