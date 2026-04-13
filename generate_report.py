import os
import re
import requests
from datetime import datetime
import pytz

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")
TODAY_ISO = NOW.strftime("%Y-%m-%d")

ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY        = os.environ["NOTION_API_KEY"]
NOTION_PARENT_PAGE_ID = os.environ.get(
    "NOTION_PARENT_PAGE_ID", "33f14f343a5681a0bf2dd9920d69303f"
)
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]


# ── GitHub 데이터 읽기 ────────────────────────────────
def read_github_file(filename):
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
    r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=10)
    if r.status_code == 200:
        return r.text
    raise Exception(f"{filename} 읽기 실패: {r.status_code}")


# ── Claude API 호출 ───────────────────────────────────
def call_claude(us_data, kr_data, loc_data="", sector_data=""):
    # kr_data에서 A/B등급 종목 추출 → 프롬프트에 직접 명시해 생략 방지
    must_include = []
    for line in kr_data.split("\n"):
        m = re.search(r"▶\s+(\S+)\s+\(\d+\)\s+\[([ABC])등급", line)
        if m:
            must_include.append(f"{m.group(1)}({m.group(2)}등급)")
    if must_include:
        must_warning = (
            f"\n🚨 ⑤ 스크리닝 섹션 필수 포함 종목 {len(must_include)}개: "
            + ", ".join(must_include)
            + "\n   → 위 종목 전부를 빠짐없이 작성할 것. 한 종목이라도 누락 시 잘못된 리포트.\n"
        )
    else:
        must_warning = ""

    prompt = f"""당신은 서울 이촌동 거주 소화기내과 봉직의의 전담 모닝리포트 작성 AI입니다.
오늘({TODAY_STR}) 데이터를 분석해 노션 모바일 앱에서 한눈에 보기 좋은 모닝리포트를 작성하세요.

═══════════════════════════════════════
[투자 전략 — 체크리스트 기반 추세추종 v2]
═══════════════════════════════════════
- 유니버스: 대형주 FCF 흑자 10종목 이내
- 손절 -7% 또는 60MA 이탈 | 1차 목표 +18%
- 1종목 포트 20~25% | 분할진입 1차 50%

■ 코어 조건 (①② 모두 충족 필수)
  ① 이평선 정배열: MA20 > MA60 > MA120
  ② 거래량: 20일 평균 대비 1.5배 이상

■ 시장 환경 게이트 (③④ 모두 충족 필수)
  ③ 코스피 60MA 위
  ④ VIX 35 이하 (패닉 환경 회피)

■ 보조 조건 (⑤⑥ 충족 개수로 등급 결정)
  ⑤ 60거래일 고점 대비 현재가 -2% 이내 또는 돌파
  ⑥ 외국인+기관 최근 20거래일 누적 순매수 양(+)

■ 등급 산정
  코어(①②) + 게이트(③④) 4개 모두 충족이 전제.
  미충족 시 D등급 — 편입 부적합, 코멘트 불필요.
  A등급: 4개 충족 + 보조 2개 = 6/6 → 진입 검토
  B등급: 4개 충족 + 보조 1개 = 5/6 → 조건부 대기
  C등급: 4개 충족 + 보조 0개 = 4/6 → 진입 가능, 확신도 낮음

═══════════════════════════════════════
[분석 규칙 — 반드시 준수]
═══════════════════════════════════════

<분석 순서>
모든 종목/시장 분석은 아래 순서를 엄격히 따른다:
1단계: 정량 채점 — 체크리스트 6항목 O/X 판정 + 등급(A/B/C) 확정
2단계: 정성 해석 — 1단계 등급에 따른 제한된 코멘트만 허용
  - A등급: 진입 시나리오 + 리스크 요인 1개 + 모니터링 지표 1개
  - B등급: 미충족 조건 나열 + 충족 시나리오 + 모니터링 지표 1개
  - C등급: "편입 부적합" + 사유 1줄. 추가 코멘트 불필요
정량 등급과 모순되는 정성 코멘트는 금지.
예: B등급이면서 "적극 매수 검토", "모멘텀 우호적" 등 진입 유도 표현 불가.
</분석 순서>

<미-한 섹터 연동 규칙>
미국 섹터 ETF 등락을 한국 개별종목의 호재/부담 요인으로 연결할 때,
반드시 아래 전이 메커니즘 중 하나를 명시해야 한다:
(1) 공급망 연결 — 동일 밸류체인 (예: SOXX → SK하이닉스)
(2) 금리/환율 동조 — 미국 금리 변동 → 원화 → 외국인 수급 경로
(3) 글로벌 수급 경로 — 동일 EM펀드/글로벌 섹터 펀드의 동시 리밸런싱
메커니즘을 특정할 수 없으면 ⑤ 스크리닝 코멘트에서 해당 미국 섹터를
한국 종목 판단 근거로 사용하지 말 것. ② 시장 보드 참고 정보로만 기재.
"같은 섹터 이름"만으로 연결하는 것은 분석 오류로 간주.
</미-한 섹터 연동 규칙>

<스크리닝 코멘트 구조>
각 종목의 📌 진입 전략 코멘트는 아래 4항목만 순서대로 작성:
1. [등급] X등급 (N/6) — 미충족 항목: ②거래량, ③외국인 등 구체적 나열
2. [국내 요인] 해당 종목/섹터의 한국 내 모멘텀만 기술
   (밸류업 현황, 실적 컨센서스, 배당수익률, 자사주소각, 수급, 정책)
3. [글로벌 연동] 위 <미-한 섹터 연동 규칙>에 따라 작성.
   전이 메커니즘이 없으면 "해당 없음" 한 줄로 종결.
4. [모니터링] "이 조건이 깨지면 시나리오 무효" 1가지 명시.
위 4항목 외의 자유 코멘트, 감상적 표현, 수사적 문구 금지.
</스크리닝 코멘트 구조>

<확증편향 방지>
- 각 종목에 Bull 1줄 / Bear 1줄을 반드시 병기.
- Bull만 있고 Bear가 없는 코멘트는 불완전한 분석으로 간주.
- Bear 요인 없이 진입을 권고하거나 "매력적"으로 표현하는 것은 금지.
- ⑥ 핵심 포인트의 🚦 액션은 반드시 체크리스트 등급(A/B/C)에 근거.
  등급과 무관한 매크로 해석이나 섹터 분위기로 액션을 결정하지 말 것.
- 액션 유형은 4가지로 제한:
  ✅ 진입 검토 (A등급 — 6/6)
  ⏳ 조건부 대기 (B등급 — 5/6) — 미충족 보조 조건 명시
  ⚠️ 확신도 낮음 (C등급 — 4/6) — 보조 조건 2개 모두 미충족
  ❌ 편입 부적합 (D등급 — 코어/게이트 미충족)
</확증편향 방지>

<추세 판단 규칙>
us_data.txt의 지수·섹터 ETF에는 MA20·MA60·MA120 데이터가 포함된다.
kr_data.txt의 코스피·코스닥 지수에도 MA20·MA60·MA120이 포함된다.
kr_data.txt의 개별 종목에는 MA20·MA60·MA120이 포함된다.

MA 데이터가 있으면 반드시 단기(MA20)·중기(MA60)·장기(MA120) 3단계 추세를 판단하고 표기할 것:
  MA20위+MA60위+MA120위 → "단기·중기·장기 상승추세 (정배열)"
  MA20위+MA60위+MA120아래 → "단기·중기 상승, 장기 추세 회복 중"
  MA20위+MA60아래+MA120아래 → "단기 반등, 중기·장기 하락추세"
  MA20아래+MA60위+MA120위 → "단기 조정, 중기·장기 상승추세 유지"
  MA20아래+MA60아래+MA120위 → "단기·중기 하락, 장기 추세 훼손 경계"
  MA20아래+MA60아래+MA120아래 → "단기·중기·장기 하락추세 (역배열)"

"추세 판단 불가"는 MA 데이터가 아예 없는 항목에만 사용. 하나라도 있으면 있는 것으로 판단.
1일 등락폭 ±2% 이내는 "보합" 또는 "소폭 변동"으로 기술. 1일 등락만으로 추세 결론 내리지 말 것.
1일 등락폭 ±5% 초과: 이벤트 기반 해석 허용, 단 이벤트명 필수 명시.
"급등/급락/폭등/폭락" 용어는 ±5% 초과 시에만 사용.
"강세/약세 주도" 표현은 섹터 ETF 기준 ±2% 초과 시에만 사용.
</추세 판단 규칙>

<데이터 품질 규칙>
- 모든 수치에 출처 + 기준 시점 명시.
  예: "PER 10.5x (네이버금융, 4/10 종가 기준)"
- us_data.txt 수치와 웹 서치 수치가 충돌 시: 둘 다 병기 + 채택 근거 1줄.
- 수치를 찾을 수 없는 항목: "데이터 미확인"으로 표기. 추정치 생성 금지.
- 이평선(MA20/60/120) 수치는 반드시 실제 데이터 기반. 추정/계산 금지.
</데이터 품질 규칙>

<금융주 전용 규칙>
한국 금융지주(KB, 신한, 하나, 우리) 분석 시:
- 필수 참조 지표: 밸류업 공시 현황, 총주주환원율, CET1 비율,
  배당수익률, 실적 발표 일정
- 미국 XLF 등락은 ② 시장 보드 참고 정보로만 표기.
  ⑤ 스크리닝 코멘트에서 XLF를 한국 금융주 판단 근거로 사용 금지.
- 한국 금융주의 구동 요인은 밸류업/배당/자사주/한은 금리 방향이며,
  이를 [국내 요인]에서 분석할 것.
</금융주 전용 규칙>

<반도체 섹터 규칙>
한국 반도체(삼성전자, SK하이닉스) 분석 시:
- 미국 반도체(SOXX, 엔비디아, AMD, TSMC) 동향은
  전이 메커니즘 (1)공급망 연결에 해당하므로 [글로벌 연동]에 기술 가능.
- 단, 미국 반도체 1일 등락을 그대로 한국 반도체 추세로 전이하지 말 것.
  "미국 반도체 훈풍" 같은 표현은 ±3% 초과 + 3일 이상 연속 시에만 허용.
</반도체 섹터 규칙>

═══════════════════════════════════════
[데이터]
═══════════════════════════════════════

=== 미장 데이터 ===
{us_data}

=== 국장 데이터 ===
{kr_data}

=== 섹터 ETF 주도 분석 데이터 ===
{sector_data}

=== 개원입지 분석 데이터 ===
{loc_data}

═══════════════════════════════════════
[출력 형식]
═══════════════════════════════════════
출근길 5분 내 독해 가능하도록 작성. 노션 모바일 앱 최적화.

## ☀️ ① 이촌동 날씨
표 + 한줄 코멘트 (우산/복장 준비 여부)

## 📊 ② 시장 보드
코스피/코스닥/S&P500/나스닥/다우/VIX/달러원/WTI/금/미10Y 표
총평 1줄 (사실 기반, 해석 최소화)

## 🇺🇸 ③ 미국 시장
섹터 ETF 표 (SOXX/XLK/XLE/XLF/XLV/XLY/XLU) + M7·반도체 개별주 표
코멘트: 당일 주도 테마 1줄 + 특이 이벤트 있으면 1줄

## 🇰🇷 ④ 국내 시장
지수 표 + 수급 표 (외국인/기관/개인)
해석: 외국인/기관/개인 수급 방향 + 추세 판단 (5일 이상 데이터 기반)

## 🔍 ⑤ 스크리닝 결과
{must_warning}
⚠️ 국장 데이터 【체크리스트 스크리닝 결과】의 A/B/C등급 종목 전부 포함. 누락·등급 재평가·추가 금지.
⚠️ C등급도 A/B등급과 동일하게 반드시 포함.

A/B/C등급 없을 때: ✋ **오늘 진입 보류** — 조건 미충족

A/B/C등급 있으면 종목별로:
### 🅐/🅑/🅒 종목명 (종목코드)
체크리스트 표 (현재가/MA20·MA60·MA120/이평선정배열/거래량1.5배/외국인+기관20일수급/코스피60MA/VIX35이하/60일고점/PER·PBR·ROE/손절가/목표가)
📌 진입 전략: <스크리닝 코멘트 구조> 4항목 순서대로

## ⚡ ⑥ 오늘의 핵심 포인트
🎯 시장: 1줄 팩트 요약
📌 종목: 가장 주목할 1종목 + 핵심 관전 포인트
🚦 액션: 체크리스트 등급 기반 (✅진입검토/⏳조건부대기/❌편입부적합)

## 📊 ⑧ 주도 섹터 ETF
섹터 ETF 데이터 없으면 섹션 전체 생략.
있으면:
- 주도(80+)/강세(65~79) 섹터 목록: 점수 + RS/추세/자금 분해 + 1M/3M/6M 수익률
- 주도 이탈/신규 진입 섹터 변동 요약
- ⑤ 스크리닝 종목 중 주도·강세 섹터와 일치하는 종목 1줄 연결 (없으면 "해당 없음")

## 🏥 ⑦ 개원입지 분석
개원입지 데이터 없으면 섹션 전체 생략.
있으면: 인구/경쟁/점수 표 + 종합평가 2줄 + 전략 1줄 + 리스크 1줄 + 내일 예정"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
        timeout=180,
    )
    if r.status_code != 200:
        raise Exception(f"Claude API 오류: {r.status_code} {r.text}")
    return r.json()["content"][0]["text"]


# ── Markdown → Notion 블록 변환 ──────────────────────
def parse_rich_text(text):
    if "**" not in text:
        return [{"type": "text", "text": {"content": text}}]
    parts = []
    for i, seg in enumerate(re.split(r'\*\*', text)):
        if not seg:
            continue
        part = {"type": "text", "text": {"content": seg}}
        if i % 2 == 1:
            part["annotations"] = {"bold": True}
        parts.append(part)
    return parts or [{"type": "text", "text": {"content": text}}]


def is_table_line(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) > 2


def is_separator_line(line):
    s = line.strip()
    return is_table_line(line) and all(c in "|-: " for c in s[1:-1])


def parse_cells(line):
    s = line.strip()[1:-1]
    return [c.strip() for c in s.split("|")]


def build_table_block(rows_raw):
    data_rows = []
    has_header = False
    for row in rows_raw:
        if is_separator_line(row):
            has_header = True
        else:
            data_rows.append(parse_cells(row))
    if not data_rows:
        return None
    num_cols = max(len(r) for r in data_rows)
    table_rows = []
    for row in data_rows:
        cells = [parse_rich_text(c) for c in (row + [""] * num_cols)[:num_cols]]
        table_rows.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": num_cols,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": table_rows,
        },
    }


def to_notion_blocks(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": []}})
            i += 1
            continue

        if re.match(r'^[-=]{3,}$', s):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        if s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": parse_rich_text(s[3:])}})
            i += 1
            continue

        if s.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                           "heading_3": {"rich_text": parse_rich_text(s[4:])}})
            i += 1
            continue

        if s.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": parse_rich_text(s[2:])}})
            i += 1
            continue

        if s.startswith("> "):
            blocks.append({"object": "block", "type": "quote",
                           "quote": {"rich_text": parse_rich_text(s[2:])}})
            i += 1
            continue

        if is_table_line(line):
            table_raw = []
            while i < len(lines) and (is_table_line(lines[i]) or is_separator_line(lines[i])):
                table_raw.append(lines[i])
                i += 1
            block = build_table_block(table_raw)
            if block:
                blocks.append(block)
            continue

        blocks.append({"object": "block", "type": "paragraph",
                       "paragraph": {"rich_text": parse_rich_text(s)}})
        i += 1

    return blocks


# ── 노션 저장 (100블록 초과 시 자동 분할) ─────────────
def save_to_notion(report_text):
    notion_headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    all_blocks = to_notion_blocks(report_text)
    first_batch, remaining = all_blocks[:100], all_blocks[100:]

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=notion_headers,
        json={
            "parent": {"page_id": NOTION_PARENT_PAGE_ID},
            "properties": {
                "title": {"title": [{"text": {"content": f"📋 모닝리포트 {TODAY_STR}"}}]}
            },
            "children": first_batch,
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise Exception(f"노션 저장 실패: {r.status_code} {r.text}")

    page_id  = r.json()["id"]
    page_url = r.json().get("url", "")

    while remaining:
        batch, remaining = remaining[:100], remaining[100:]
        r2 = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=notion_headers,
            json={"children": batch},
            timeout=30,
        )
        if r2.status_code not in (200, 201):
            print(f"⚠️ 추가 블록 저장 실패: {r2.status_code}")

    print(f"✅ 노션 저장 완료 ({len(all_blocks)}블록) → {page_url}")


# ── 메인 ─────────────────────────────────────────────
if __name__ == "__main__":
    print("📥 데이터 파일 읽는 중...")
    us_data = read_github_file("us_data.txt")
    kr_data = read_github_file("kr_data.txt")
    try:
        sector_data = read_github_file("sector_data.txt")
        print("✅ 섹터 ETF 데이터 로드 완료")
    except Exception as e:
        print(f"⚠️ 섹터 ETF 데이터 없음 (섹션 ⑧ 생략): {e}")
        sector_data = ""
    try:
        loc_data = read_github_file("location_data.txt")
        print("✅ 개원입지 데이터 로드 완료")
    except Exception as e:
        print(f"⚠️ 개원입지 데이터 없음 (섹션 ⑦ 생략): {e}")
        loc_data = ""
    print("✅ 데이터 로드 완료")

    print("🤖 Claude API 리포트 생성 중...")
    report = call_claude(us_data, kr_data, loc_data, sector_data)
    print("✅ 리포트 생성 완료")
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    print("📝 노션 저장 중...")
    save_to_notion(report)
    print("🎉 모닝리포트 완료!")
