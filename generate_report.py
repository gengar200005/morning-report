import os
import re
import json
import base64
import requests
from datetime import datetime
import pytz

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")
TODAY_ISO = NOW.strftime("%Y-%m-%d")

ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
NOTION_API_KEY       = os.environ["NOTION_API_KEY"]
# 📊 모닝리포트 폴더 page_id (URL의 32자리 hex)
NOTION_PARENT_PAGE_ID = os.environ.get(
    "NOTION_PARENT_PAGE_ID", "33e14f343a568158a76fcf91d4bb4de8"
)

GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]

# ── GitHub에서 데이터 파일 읽기 ─────────────────────
def read_github_file(filename):
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        return r.text
    raise Exception(f"{filename} 읽기 실패: {r.status_code}")

# ── Claude API 호출 ──────────────────────────────────
def call_claude(us_data, kr_data):
    prompt = f"""당신은 서울 이촌동 거주 소화기내과 봉직의의 전담 투자 어시스턴트입니다.
아래 미장·국장 데이터를 바탕으로 오늘({TODAY_STR}) 모닝리포트를 작성해주세요.

투자 전략: 대형주 추세추종 (FCF 흑자 유니버스 10종목 대상)
핵심 원칙:
- 손절 -7% 또는 60MA 이탈
- 1차 목표 +18%, 트레일링 고점 대비 -10%
- 1종목 포트폴리오 20~25% 이내
- 분할 진입 (1차 50% → 확인 후 추가)

=== 미장 데이터 ===
{us_data}

=== 국장 데이터 ===
{kr_data}

위 데이터를 분석하여 아래 형식으로 모닝리포트를 작성하세요:

① 시장 보드 요약 (코스피/코스닥/미장 핵심 수치 + 환율/WTI/금)
② 미국 시장 분석 (섹터별 흐름 + 반도체·M7 동향 + 1~2줄 코멘트)
③ 국내 시장 분석 (코스피/코스닥 마감 + 수급 해석 + 추세 판단)
④ 스크리닝 결과 해석 (A/B등급 종목 진입 전략 — 없으면 "진입 보류" 명시)
⑤ 오늘의 핵심 포인트 (3줄 이내, 행동 가이드)

간결하고 실용적으로 작성하세요. 출근길 5분 안에 읽을 수 있어야 합니다."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 2048,
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

# ── 텍스트를 노션 블록 리스트로 변환 ────────────────
def to_notion_blocks(text):
    blocks = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": []}})
            continue
        # ①②③④⑤ 로 시작하는 섹션 헤더
        if re.match(r"^[①②③④⑤]", stripped):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": stripped}}]
                },
            })
        # --- 구분선
        elif set(stripped) <= set("-="):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": stripped}}]
                },
            })
    return blocks[:100]  # Notion API 1회 한도 100블록

# ── 노션에 서브페이지 저장 ───────────────────────────
def save_to_notion(report_text):
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {
        "parent": {"page_id": NOTION_PARENT_PAGE_ID},
        "properties": {
            "title": {
                "title": [{"text": {"content": f"📋 모닝리포트 {TODAY_STR}"}}]
            }
        },
        "children": to_notion_blocks(report_text),
    }
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if r.status_code in (200, 201):
        page_url = r.json().get("url", "")
        print(f"✅ 노션 저장 완료 → {page_url}")
    else:
        raise Exception(f"노션 저장 실패: {r.status_code} {r.text}")

# ── 메인 ────────────────────────────────────────────
if __name__ == "__main__":
    print("📥 데이터 파일 읽는 중...")
    us_data = read_github_file("us_data.txt")
    kr_data = read_github_file("kr_data.txt")
    print("✅ 데이터 로드 완료")

    print("🤖 Claude API 리포트 생성 중...")
    report = call_claude(us_data, kr_data)
    print("✅ 리포트 생성 완료")
    print("\n" + "="*52)
    print(report)
    print("="*52 + "\n")

    print("📝 노션 저장 중...")
    save_to_notion(report)
    print("🎉 모닝리포트 완료!")
