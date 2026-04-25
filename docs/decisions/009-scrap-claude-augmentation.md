# ADR-009: Scrap Claude augmentation — baseline PDF only operation

- Status: **Accepted**
- Date: 2026-04-26
- Context session: 2026-04-26 (interesting-kapitsa-d40f52)
- Accepted: 2026-04-26 by 마스터 승인 ("그렇게 정리하게 필요한 부분들 수정해줄래?")
- Supersedes: v5.0 (2026-04-25 PR #22, commit `5a3c76d`) + v5.1 (2026-04-26
  commit `1e47104`) 의 매일 augmentation 운영 가정
- Related: ADR-005 (entry-timing 실증, "추가 필터 baseline 하회"), ADR-008
  (Section 04 narrative 강조 폐기)

## 1. 배경

v5.0 zero-base (2026-04-25) 는 Claude 가 매일 7카드 (alert / gate_flow /
sector / entry / agrade / portfolio / macro) 작성 → `docs/claude_analysis/YYYYMMDD.json`
commit → `claude_render.yml` 가 7카드 주입된 augmented PDF + Drive + Notion
publish 까지 자동 처리하는 흐름을 도입했다.

2026-04-26 세션에서 v5.1 갱신 (Notion publish CI 이전, Project Files 4개
슬림화) 까지 진행했으나, 운영 모델이 다음 셋으로 분기되며 복잡도가 증가:

- **claude.ai/projects (web)**: GitHub commit 자동화 도구 (write MCP) 가
  marketplace 미제공 → 마스터가 매일 다운로드 → GitHub UI 수동 commit (1분).
- **Claude Code CLI**: git CLI 보유 → 자동 commit. 단 매일 CLI 띄움 (3분).
- **cron + Anthropic API (옵션 D)**: GitHub Actions runner 가 직접 호출.
  마스터 손 0, 단 월 ~$2-20 + 안전 필터 false-positive 위험.

마스터의 통찰: **"단순화시키려다 더 복잡해졌다."** — v5.0 zero-base 의 본
의도가 단순화였으나 운영 채널이 셋으로 갈라지며 매일 액션이 명확하지 않은
상태가 됨.

본질로 돌아가서 알파 분해를 냉정 평가하면:

- 백테 CAGR **+29.55%** 의 알파 분해 (ADR-005 결과):
  - 필터 (수급 + RS≥70) + 시장 게이트: **+25.8%p**
  - 체결 타이밍 (5일 지연 OK): **+6.7%p**
  - 합: 100% 가 룰에서 옴.
- 자연어 해석 / narrative 의 알파 기여: **0%p** (측정 안 됨, 가설일 뿐).
- ADR-005 가 이미 실증: "추가 필터 (fresh-signal / streak≤10 등) baseline
  하회" — 룰 외 직관 거름은 알파 잠식.
- Claude 7카드의 narrative (sector "leaders 변동" / agrade "신고가 클러스터" /
  macro "FOMC D-N" 등) 는 마스터의 직관 필터를 자극 → 백테 외 판단 유인 →
  ADR-005 의 결과와 정확히 같은 결의 위험.

추가로 모델 일관성 편차도 확인:

- 2026-04-26 Sonnet 4 시도: 섹터명 OCR-스러운 오류 ("보호 100점" ← 반도체,
  "방송 87.4" ← 방산), Top 5 에 RS 73 신한지주 등장 (정렬 기준 어긋남).
- 2026-04-26 Opus 4.7 시도: 안전 필터 false-positive (Drive + JSON + GitHub
  도구 조합에서 가끔 트리거).
- cron 자동화 시 무검증 발행 → 마스터가 잘못된 narrative 에 끌릴 위험.

baseline PDF (`reports/templates/v6.2_template.html.j2`) 가 이미 의사결정에
필요한 데이터를 충분히 제공:

- Top 5 RS 정렬 + signal_age + stop_price
- Holdings verdict (HOLD/ADD/CUT)
- 시장 게이트 통과 boolean (VIX, KOSPI MA60)
- 매크로 캘린더 (D-day + impact)
- 섹터 강도 점수

→ Claude 의 자연어 해석은 가독성 가치만 있고 알파 기여 0. 가독성 가치 <
narrative 노이즈 위험.

## 2. 옵션

- **(A) Claude augmentation 폐기, baseline PDF only 운영**. 매일 06:25 KST
  `morning.yml` cron → baseline PDF + Drive + Notion 자동 publish. 마스터
  손 0, 비용 0. augmentation 인프라 (claude_render.yml + publish_to_notion.py +
  notion_page_template.json) 는 보존, JSON commit 만 하면 즉시 작동.
- **(B) v5.1 유지 — claude.ai 호출 + 마스터 1분 수동 commit**. 가독성 유지.
  단 매일 액션 + narrative 끌림 위험 + 모델 편차 노출.
- **(C) cron + Anthropic API 자동화 (옵션 D)**. 손 0, 단 월 ~$2-20 + 안전
  필터 false-positive 시 fallback 처리 + 모델 편차 무검증 발행 위험.
- **(D) 예전 방식 복원 — Claude 가 PDF 직접 편집 + Notion publish**. 도구
  의존, 안전성 ↓ (Claude 실패 시 PDF 자체 안 나옴), v5.x 의 baseline 안전망
  포기.

## 3. 결정

**Option (A) 채택** — Claude augmentation 폐기, baseline PDF only 운영.

### 이유

1. **알파 분해 결과 일관** — 백테 알파 100% 가 룰에서 옴. 자연어 해석은
   알파 기여 0. ADR-005 의 "추가 필터 baseline 하회" 와 같은 결.
2. **narrative 끌림 위험** — Claude 의 자연어 해석 (특히 sector / agrade /
   macro 카드) 이 마스터 직관 필터를 자극 → 백테 외 판단 유인. 매매 전략의
   명시 원칙 ("차트 판독 ❌, 단독 종목 ❌") 과 같은 결로 차단해야 함.
3. **모델 일관성 위험** — Sonnet 4 OCR 오류 / Opus 안전 필터 false-positive
   는 일회성 사고가 아니라 구조적 편차. cron 자동화 시 무검증 발행 → 마스터
   손해 가능. 매번 검증하려면 자동화 의미 ↓.
4. **baseline 충분성** — v6.2 template 이 이미 의사결정 데이터 (RS / verdict /
   게이트 / 매크로) 충분 제공. augmentation 의 가독성 가치 < narrative 위험.
5. **운영 단순화** — 매일 06:25 KST cron 1회 → 결과 자동 발행 → 마스터는
   Notion 페이지 확인만. PC/모바일 무관, 손 0, 비용 0.

### 불채택 이유

- **(B) v5.1 유지** — narrative 위험 + 매일 1분 손. 위험-가치 trade-off 에서
  가독성이 narrative 노이즈를 정당화 못 함.
- **(C) cron + API 자동화** — 손은 0이지만 narrative 위험은 동일. 모델 편차
  가 무검증 발행 → 알파 잠식 위험. 비용 자체 ($2-20/월) 는 사소하나 위험-가치
  trade-off 가 (B) 보다 더 나쁨.
- **(D) 예전 방식 복원** — Claude 실패 시 PDF 자체 안 나옴. v5.x 의 baseline
  안전망 (CI 가 매일 baseline PDF 보장) 포기. 안전성 측면에서 명백히 열위.

## 4. 실행

### 4.1 코드 변경

- `.github/workflows/morning.yml`: HTML→PDF + Drive 업로드 step 뒤에 **Notion
  publish step 신규 추가**. 매일 06:25 KST cron-job.org workflow_dispatch
  트리거에서 baseline PDF 가 Drive + Notion 까지 자동 발행 (commit `7b4e71e`).
- `.github/workflows/claude_render.yml`: **무변경** (보존). `docs/claude_analysis/*.json`
  push 트리거 + Notion publish step 그대로. 미래 augmentation 재시도 시
  JSON commit 만 하면 즉시 작동.
- `reports/publish_to_notion.py`: **무변경** (보존, 양 workflow 공통 사용).
- `notion_page_template.json`: **무변경** (보존).

### 4.2 Claude Project Instruction 갱신 (v5.0 → v5.1 → deprecated)

- v5.0 → v5.1 (commit `1e47104`): §0 4단계 → 3단계, §3 압축, §6 Notion 도구
  행 제거, Project Files 7 → 5 → 4.
- v5.1 deprecated (commit `7b4e71e`): 본문 첫 줄에 deprecation 메모 추가
  ("현재 운영 X, 미래 augmentation 재시도용 보존"). 본문 자체는 보존하여
  미래 재시도 시 즉시 가용.

### 4.3 CLAUDE.md

- "현재 상태" 섹션을 "Claude augmentation 폐기, baseline PDF 자동 운영" 으로
  덮어쓰기 (commit `7b4e71e`).
- "활성 작업 → 다음 진입점 1️⃣" 을 "baseline 자동 운영 1차 검증 (2026-04-27
  Mon 06:25 KST)" 으로 갱신.
- "최근 주요 결정" 에 ADR-009 한 줄 추가 (다음 commit).
- "최근 세션" 에 2026-04-26 항목 추가 (commit `7b4e71e` + 본 commit).

## 5. 영향 / 검증

### 5.1 매일 운영

- **매일 06:25 KST**: `morning.yml` cron → 데이터 수집 → HTML → PDF → Drive
  업로드 → **Notion publish** (자식 페이지 + PDF embed). 마스터 손 0.
- **매일 07:00 경**: 마스터가 출근길 모바일에서 Notion 부모 페이지 → 새
  자식 페이지 ("모닝리포트 YYYY-MM-DD (요일)") 확인 → 매매 결정 인풋.

### 5.2 augmentation 재시도 (선택적, 폐기 결정 후 사실상 발생 안 함)

- 마스터가 특정 날 augmentation 원할 시: claude.ai 호출 → 7카드 JSON 다운로드
  → GitHub UI 에 `docs/claude_analysis/YYYYMMDD.json` 업로드 → claude_render.yml
  자동 트리거 → augmented PDF + Drive 덮어쓰기 + Notion 새 자식 페이지 발행.
- **알려진 한계**: `publish_to_notion.py` 가 매번 새 페이지 생성 (idempotent
  X) → 그날 Notion 에 baseline + augmented 두 페이지 공존. 미래 재시도 시
  idempotent 처리 (같은 날짜 페이지 덮어쓰기) 추가 필요.

### 5.3 백테·전략 불변

- 본 결정은 **표시 계층 + 운영 모델 전용**. `strategy.py` / `strategy_config.yaml`
  / 백테 CAGR +29.55% / T10/CD60 룰 전부 영향 없음.

### 5.4 회귀 리스크

- 낮음. `morning.yml` 의 새 step 은 `publish_to_notion.py` (이미 dispatch
  검증 1m6s SUCCESS, run 24933790231) 재사용. 실패 시 cron 끝의 step 만
  fail, baseline PDF + Drive 업로드는 이미 완료된 상태.
- augmentation 인프라 보존이라 향후 재시도 비용 0 (코드 작성 X, 운영 결정만
  뒤집으면 됨).

### 5.5 1차 검증

- 2026-04-27 Mon 06:25 KST cron-job.org 자연 트리거 → `morning.yml` 의 새
  Notion publish step 정상 작동 확인. 자고 일어나서 Notion 부모 페이지에
  04-27 자식 페이지 + PDF embed 자동 생성 확인.

## 6. 후속 과제

- 04-27 검증 후 운영 안정 단계 진입. 별도 모니터링 불필요.
- 미래 augmentation 재시도 결정 시 본 ADR 의 "narrative 끌림 위험 + 모델
  일관성 편차 + baseline 충분성" 근거 재평가 필요. 단순한 "가독성 좋다"
  유혹은 ADR-009 위반.
- ADR-010 (박스권 조건부 섹터 게이트) / ADR-011 (데이터 무결성 원칙) 후보
  결정은 별개 진행.
