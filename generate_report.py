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
    "NOTION_PARENT_PAGE_ID", "33e14f343a568158a76fcf91d4bb4de8"
)
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]


# ── GitHub 데이터 읽기 ────────────────────────────────
def read_github_file(filename):
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        return r.text
    raise Exception(f"{filename} 읽기 실패: {r.status_code}")


# ── Claude API 호출 ───────────────────────────────────
def call_claude(us_data, kr_data):
    prompt = f"""당신은 서울 이촌동 거주 소화기내과 봉직의의 전담 모닝리포트 작성 AI입니다.
오늘({TODAY_STR}) 데이터를 분석해 노션 모바일 앱에서 한눈에 보기 좋은 모닝리포트를 작성하세요.

[투자 전략]
- 대형주 추세추종, FCF 흑자 유니버스 10종목
- 손절 -7% 또는 60MA 이탈 | 1차 목표 +18% | 1종목 포트 20~25% | 분할진입 1차 50%

=== 미장 데이터 ===
{us_data}

=== 국장 데이터 ===
{kr_data}

아래 형식을 정확히 따라 작성하세요. 출근길 5분 내 독해 가능해야 합니다.

---

## 📊 ① 시장 보드

| 구분 | 수치 | 등락 | 신호 |
|------|------|------|------|
| 코스피 | 실제값 | ▲/▼ +X.XX% | 🟢/🔴 |
| 코스닥 | 실제값 | ▲/▼ +X.XX% | 🟢/🔴 |
| S&P500 | 실제값 | ▲/▼ +X.XX% | 🟢/🔴 |
| 나스닥 | 실제값 | ▲/▼ +X.XX% | 🟢/🔴 |
| 다우 | 실제값 | ▲/▼ +X.XX% | 🟢/🔴 |
| VIX | 실제값 | ▲/▼ | 😊안정/😰경계/🚨위험 |
| 달러/원 | 실제값 | ▲/▼ | |
| WTI | 실제값 | ▲/▼ | |
| 금 | 실제값 | ▲/▼ | |
| 미 10Y | 실제값 | ▲/▼ | 장단기차 표기 |

> 💬 **총평:** 오늘 장세 성격 한 줄 요약

---

## 🇺🇸 ② 미국 시장

### 섹터 성과

| 섹터 ETF | 등락 | 평가 |
|----------|------|------|
| 반도체 SOXX | 실제값 | 💪강세/😐보합/😞약세 |
| IT XLK | 실제값 | |
| 에너지 XLE | 실제값 | |
| 금융 XLF | 실제값 | |
| 헬스케어 XLV | 실제값 | |
| 소비재 XLY | 실제값 | |
| 유틸리티 XLU | 실제값 | |

### 반도체·M7 개별주

| 종목 | 등락 | 비고 |
|------|------|------|
| 엔비디아 | 실제값 | |
| TSMC | 실제값 | |
| ASML | 실제값 | |
| AMD | 실제값 | |
| 인텔 | 실제값 | |
| 삼성ADR | 실제값 | |
| 애플 | 실제값 | |
| 마이크로소프트 | 실제값 | |
| 알파벳 | 실제값 | |
| 아마존 | 실제값 | |
| 메타 | 실제값 | |
| 테슬라 | 실제값 | |
| 엔비디아(중복제거) | | |

> 💬 **코멘트:** 미장 핵심 흐름 1~2줄

---

## 🇰🇷 ③ 국내 시장

| 지수 | 종가 | 등락 | 추세 |
|------|------|------|------|
| 코스피 | 실제값 | ▲/▼ +X.XX% | ✅상승추세/⚠️이탈 |
| 코스닥 | 실제값 | ▲/▼ +X.XX% | ✅/⚠️ |

### 수급 (코스피)

| 주체 | 순매수 | 방향 |
|------|--------|------|
| 외국인 | 실제값 | 🟢매수/🔴매도/⬜중립 |
| 기관 | 실제값 | 🟢/🔴/⬜ |
| 개인 | 실제값 | 🟢/🔴/⬜ |

> 💬 **해석:** 수급·추세 종합 판단 1~2줄

---

## 🔍 ④ 스크리닝 결과

A/B등급 종목이 없으면 아래 한 줄만 작성:
✋ **오늘 진입 보류** — A/B등급 조건 미충족

A/B등급 종목이 있으면 종목별로 아래 형식 반복:

### 🅐 종목명 (종목코드)

| 항목 | 내용 |
|------|------|
| 현재가 | 000,000원 |
| MA20 / MA60 / MA120 | 000,000 / 000,000 / 000,000 |
| 이평선 정배열 | ✅ MA20>MA60>MA120 / ❌ |
| 거래량 1.5배 돌파 | ✅ / ❌ |
| 외국인 5일 순매수 | ✅ +0,000주 / ❌ |
| 손절가 | 000,000원 (-7%) |
| 1차 목표가 | 000,000원 (+18%) |

> 📌 **진입 전략:** 조건 충족 시 구체적 행동 지침 1~2줄

---

## ⚡ ⑤ 오늘의 핵심 포인트

- 🎯 **시장:** 오늘 장세 판단 한 줄
- 📌 **종목:** 주시할 종목·충족 조건 한 줄
- 🚦 **액션:** 매수 진입 / 관망 / 보류 중 하나를 명확히"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
        timeout=60,
    )
    if r.status_code != 200:
        raise Exception(f"Claude API 오류: {r.status_code} {r.text}")
    return r.json()["content"][0]["text"]


# ── Markdown → Notion 블록 변환 ──────────────────────
def parse_rich_text(text):
    """**bold** 파싱 → Notion rich_text 포맷"""
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
    s = line.strip()[1:-1]  # 양쪽 | 제거
    return [c.strip() for c in s.split("|")]


def build_table_block(rows_raw):
    """markdown table rows → Notion table block"""
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
        },
        "children": table_rows,
    }


def to_notion_blocks(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # 빈 줄
        if not s:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": []}})
            i += 1
            continue

        # 구분선
        if re.match(r'^[-=]{3,}$', s):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # heading_2 (##)
        if s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": parse_rich_text(s[3:])}})
            i += 1
            continue

        # heading_3 (###)
        if s.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                           "heading_3": {"rich_text": parse_rich_text(s[4:])}})
            i += 1
            continue

        # bullet list
        if s.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": parse_rich_text(s[2:])}})
            i += 1
            continue

        # quote / callout
        if s.startswith("> "):
            blocks.append({"object": "block", "type": "quote",
                           "quote": {"rich_text": parse_rich_text(s[2:])}})
            i += 1
            continue

        # 테이블 (연속 | 라인 수집)
        if is_table_line(line):
            table_raw = []
            while i < len(lines) and (is_table_line(lines[i]) or is_separator_line(lines[i])):
                table_raw.append(lines[i])
                i += 1
            block = build_table_block(table_raw)
            if block:
                blocks.append(block)
            continue

        # 일반 단락
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

    # 페이지 생성
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

    # 나머지 블록 추가 (100개씩)
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
    print("✅ 데이터 로드 완료")

    print("🤖 Claude API 리포트 생성 중...")
    report = call_claude(us_data, kr_data)
    print("✅ 리포트 생성 완료")
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    print("📝 노션 저장 중...")
    save_to_notion(report)
    print("🎉 모닝리포트 완료!")
