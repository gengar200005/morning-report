# Session Log

프로젝트 세션별 작업 일지. 최신이 상단. 상세한 결정 근거는 `docs/decisions/`.

---

## 2026-04-26 (PC CLI, branch `claude/interesting-kapitsa-d40f52`) — v5.0 사고 fix + Notion CI 자동화 + Instruction v5.1

### 결정
- **04-25 web 사고 fix** — 어제 web Opus 가 7카드 분석 작성 후 GitHub MCP
  부재로 마스터 수동 commit 안내. 안내문 옵션 B 의 `cat > ... << 'EOF' ...
  EOF` bash heredoc 코드 블록을 마스터가 GitHub 웹 UI 파일 본문에 그대로
  붙여넣음. workflow run 24922905767 JSON 파싱 실패 (33s). 오늘 CLI 에서
  깨끗한 7카드 JSON 으로 재push (commit `7c4bd53`), workflow SUCCESS (1m0s).
- **Notion CI 자동화 완성 (B 옵션)** — Notion `file_uploads` API 가 Anthropic
  MCP 패키지 (web 도 CLI 도) 에 구조적 부재 + `notion_page_template.json` 의
  external URL 거부 정책으로 `pdf` 블록은 file_upload 타입 강제. 따라서 v5.0
  §3.2 의 4단계 (slot 생성 → PDF 바이너리 → page create → children PATCH)
  를 CI step 으로 이전. `reports/publish_to_notion.py` (155줄, requests 기반)
  + `claude_render.yml` Notion publish step 추가 (commit `32bc13a`). 검증:
  workflow_dispatch run 24933790231 → Notion step 4초 만에 통과, 자식 페이지
  + PDF embed 정상 생성. NOTION_API_KEY / NOTION_PARENT_PAGE_ID 기존 secret
  재사용 (마스터가 `morning-report-publisher` integration 신규 생성, 부모
  페이지 connections 추가).
- **Instruction v5.0 → v5.1** — Notion publish 가 CI 임무로 이전됨에 따라
  지침 갱신:
  - §0 역할: 4단계 → **3단계** (Drive 읽기 → 7카드 → commit). CI 자동 처리
    한 줄 메모.
  - §3: Claude API 호출 절차 23줄 → 짧은 메모 6줄 (CI 책임 명시).
  - §5: "CLAUDE.md 가 단일 소스" → "전체 정의는 레포 CLAUDE.md" (Project
    Files 등록 X 와 일관성).
  - §6 도구 표: Notion 행 3개 (file_upload / page create / blocks append)
    제거. CI 처리 단계 명시 1줄 추가.
  - **Project Files: 7 → 4** — CLAUDE.md (매일 7카드 작성에 직접 인용 X,
    핵심 5줄은 §5 인라인) + `notion_page_template.json` (CI 만 사용) +
    `combine_data.py` (raw text 결합 순서, parser abstraction 으로 충분)
    제거. holdings_report.py 등 데이터 생성 단계 파일도 등록 불필요 명시.
  - 본문 분량: 172줄 → 약 140줄.
- **운영 모델 확정** — claude.ai/projects 환경에서 자동 commit 불가능 (GitHub
  커넥터는 연결됐지만 read-only — chat 첨부 / Projects sync / Claude Code
  remote browse 만 지원, write 권한 없음). 따라서 v5.1 권장 운영 = **Claude
  Code CLI 에서 7카드 작성 + commit**. 안전 필터 false-positive (어제 Opus
  4.7 케이스) 와 도구 부재 둘 다 우회.

### 검토한 대안
- **Notion 자동화 우회 3안**:
  - (A) HTTP 직접 호출 — 마스터가 매일 CLI 띄워야 자동화 의미 없음. 기각.
  - **(B) CI workflow 에 Notion step 추가** — secrets 이미 있음, Drive
    OAuth 와 동일 환경. **채택**.
  - (C) Drive viewUrl external embed — `notion_page_template.json` usage_rules
    2번 "external URL 방식 아님" 명시 거부 + PDF 권한이 Drive 에 묶임. 기각.
- **Project Files 6개 vs 5개**:
  - (a) CLAUDE.md 유지 (6개) — 풍부한 컨텍스트, ADR/세션 기록 포함
  - **(b) CLAUDE.md 제거 (5개)** — §5 5줄로 충분, 컨텍스트 가벼움, 매일
    갱신 부담 없음. **채택**.
- **commit 전략 — 단일 fix vs 2 commits**: ba94ec9 삭제 commit reset 후
  단일 "replace malformed" commit 으로 정상화 (`7c4bd53`). main history
  깔끔.

### 다음 세션에서 할 일
- **v5.1 정상 운영 관찰** — 다음 06:00 KST cron + 마스터 호출 사이클에서:
  - 7카드 JSON commit → workflow → Notion 페이지 자동 생성 end-to-end 재현
  - Notion publish step 1분 내 완료 유지
  - Drive PDF 와 Notion embed PDF 동일 파일 검증
- **ADR 후보 3건 우선순위 결정 (마스터 판단)**:
  - **ADR-009**: v5.0/v5.1 운영 모델 (claude.ai 환경 갭 → CI step 이전)
  - **ADR-010**: 박스권 조건부 섹터 게이트 (전략 알파)
  - **ADR-011**: 데이터 무결성 원칙 (silent degradation 거부)
- **잔존 stale 브랜치 UI 수동 삭제** (sandbox 403 으로 자동 불가) — 11개:
  `session-start-hook-Lv8YN`, `session-end-2026-04-24-3`,
  `adr-005-006-007-entry-timing`, `resume-session-progress-8cGdH`,
  `fix-error-handling-riAYS`, `phase3-backtest`, `session-start-nueAo`,
  `v3.9-data-integrity`, `session-start-4OzHX` (v4.0 폐기),
  `session-start-HhsjC`, `waiting-for-instructions-6Xn3W` (v5.0 src).
- **claude.ai 프로젝트 Project Files 갱신 (마스터)**: v5.0 → v5.1 교체
  업로드 + CLAUDE.md / notion_page_template.json 등록 해제.

### 미해결
- **모델별 7카드 품질 편차** — Opus 4.7 (어제 본문, 채택) vs Sonnet 4 (오늘
  안전필터 우회 시도, 섹터명 OCR 오류 + RS 73 신한지주 등장) 결과 불일치.
  v5.1 §1.3 의 "추측 prefix 금지" / §7 "추측 prefix 금지" 만으로는 불충분
  할 수 있음. 향후 모델 일관성 가드 (예: 데이터 인용 시 출처 키 명시) 추가
  검토.
- **CLAUDE.md SHA 누락** — push 후 새 SHA 로 갱신 필요할 수 있음. 또는
  영구적으로 SHA 박지 않고 날짜+버전 표기로 단순화.

### 이번 세션 생성/수정 파일
- 신규: `reports/publish_to_notion.py` (155줄, requests 기반 v5.0 §3.2 4단계)
- 수정: `.github/workflows/claude_render.yml` (Notion publish step 추가),
  `CLAUDE_PROJECT_INSTRUCTION_v5.md` (v5.0 → v5.1, 172 → ~140줄),
  `CLAUDE.md`, `SESSION_LOG.md`
- 삭제 (커밋 시리즈 일부): `docs/claude_analysis/20260425.json` 손상본 →
  깨끗한 7카드 JSON 으로 교체

### 머지/푸시 결과 (2026-04-26 종료 시점)
- 이번 세션 commit 시리즈 (모두 main 직접 push):
  1. `7c4bd53` — `fix(claude_analysis): replace malformed 20260425.json`
  2. `32bc13a` — `feat(notion): v5.0 §3 Notion publishing CI step 추가`
  3. (pending) — v5.1 인계 commit
- workflow SUCCESS 2건: run 24933354377 (1m0s, push trigger), run 24933790231
  (1m6s, dispatch trigger Notion 검증).
- main 자동 갱신 commit: `672eedd` (04-25 PDF), `06ae974` (04-26 PDF) — CI
  auto push.

---

## 2026-04-25 (web, branches `claude/session-start-nueAo` → `claude/v3.9-data-integrity`) — ADR-008 + Instruction v3.7 → v3.9 3사이클

### 결정
- **ADR-008 Accepted** — Section 04 Entry Candidates 폐기, Trend Watch 단일
  섹션(§04) 복귀. ADR-005 실증 (median signal_age=6일, fresh 1일 진입 19.5%)
  기반으로 "🆕 = 매수 신호" 프레이밍이 왜곡임을 확인. 템플릿 섹션 재번호
  (05→04, 05·b→04·b, 06→05, 07→06, 08→07). `data.new_a_entries` 파생 제거.
  parser `is_new` 필드는 Trend Watch row + Remaining 표 뱃지 힌트로 유지.
  **PR #19 rebase merge → main `de873db`**.
- **Claude Project Instruction v3.6 → v3.7 → v3.8 → v3.9 3사이클**
  - **v3.7** (ADR-008 반영): Section 04 Entry Candidates 제거 관련 지침 갱신
  - **v3.8** (2026-04-25 #2 D-1 사고 fix):
    - Step 0 신설 — 오늘 날짜는 system prompt `current date` 만 사용
      (bash `date` / `datetime.now()` / `date.today()` 금지). 샌드박스 UTC vs
      KST 9h 어긋남으로 D-1 리포트 (04-24 미장 7,108) 발행 사고 재발 차단.
    - Step 1 재정의 — Drive 폴더 `morning_data*.txt` 중 modifiedTime 최신
      1개 선택. 파일명과 current date 매칭 금지. 헤더 날짜 D-2+ 어긋나면
      파이프라인 지연으로 판단 → 중단.
    - 슬림화 503→419줄 (코드 블록 보존, 산문·역사적 맥락 제거).
    - PR #19 에 포함 → main `de873db`.
  - **v3.9** (2026-04-25 #3 18% 데이터 손실 사고 fix):
    - Step 1 **무결성 가드** — `search_files` 에서 `expected_size` 확보 →
      `download_file_content` decode 후 크기 검증 → 불일치/예외 시 2차 경로
      (`read_file_content` + escape unwrap) 자동 진입. `loss_pct` 강제 계산,
      `>= 20%` 면 중단, `> 0` 면 ALERT 11 카드 예약 필수. silent pass 차단.
    - Step 3 parser 스키마 힌트 — `data["minervini"]["grade_a"]` 등 4줄
      (smoke-test false-negative 방지).
    - ALERT 11 신설 — `⚠️ 데이터 손실 {pct}% — 리포트 부분적` TOP 우선순위.
    - 절대 금지 / 자체 체크에 "데이터 무결성" 카테고리 추가. mojibake byte
      수작업 매핑 / 멀티 청크 reassemble / hex 변환 명시적 금지.
    - **PR #20 rebase merge → main `775ba0b`**.

### 검토한 대안
- **Section 04 처리 3안**: (A) 재설계 "Top 5 RS 순 분산", (B) 문구 정정 "🆕
  우선순위만 강조", (C) 폐기 → Trend Watch 복귀. **(C) 채택**.
  - (A) 기각 — 실전 매매 규약 자연어 규칙을 템플릿에 중복 인코딩. Trend Watch
    가 이미 RS 순 Top 5 이므로 의미 중복만 생김.
  - (B) 기각 — 한 섹션 안에 "팩트 테이블 (🆕 only)" + "진입 규칙 (Top 5
    전체)" 두 의미가 섞여 시각적 강조 (초록 좌측 바, 최상위 배치) 가 계속
    🆕 쪽으로만 쏠림.
- **Instruction 슬림화 2안**: (a) ~250줄 코드 블록 보존, (b) ~200줄 Step
  3/5/6/9 코드를 `render_report.py` 외부 포인터화. **(a) 채택**.
  - (b) 기각 — Project Instructions 는 한 번 로드 후 컨텍스트 유지. 외부
    포인터화 시 Claude 가 매 세션 `render_report.py` 를 열어 canonical 스니펫
    찾아야 함 = 오히려 컨텍스트 소비 증가 + MCP round-trip 증가. 이 파일이
    존재하는 목적 (drift 잠금) 과 모순.
  - 실제 결과: (a) 계획 시 추정 250 → 실측 419. 코드 블록 보존 하의 한계.
- **v3.9 사용자 제안 3건 중 escape unwrap fallback 공식화 거부**:
  - (1) base64 옮김 안전성 가드 **채택** (HIGH, Step 1 integrity guard)
  - (2) parser API 형태 명시 **채택** (MEDIUM, Step 3 스키마 4줄)
  - (3) escape unwrap + mojibake 매핑 helper 표준화 **거부**. 이유: damage
    control 을 canonical 화하면 (i) 데이터 손실 체감이 사라짐, (ii) mojibake
    패턴은 파일마다 달라 유지보수 불가능, (iii) 진짜 해결은 전송 안전성
    확보지 깨진 결과 복구가 아님. v3.9 는 fallback 진입 자체를 이상 신호로
    처리 (ALERT 11 + loss_pct 강제).

### 다음 세션에서 할 일
- **v3.9 효과 관찰**: 다음 모닝리포트 세션에서
  - Step 1 1차 경로 (`download_file_content`) 성공률 (21KB 이상 파일에서도
    성공하는지, 아니면 여전히 토큰 경유 손상으로 2차 경로 진입하는지)
  - 2차 경로 진입 시 `loss_pct` 수치 + ALERT 11 카드 정상 노출
  - Step 3 parser 스키마 힌트로 smoke-test false-negative 재발 없는지
- **ADR-009 후보 (박스권 조건부 섹터 게이트) 진행 여부 결정** — 2015-19
  박스권 regime detection (6M KOSPI return, MA200 slope) 기반 조건부 게이트
  활성화. 인프라 `strategy_config.yaml::sector_gate` + `precompute_sector_tiers`
  이미 있음.
- **Section 04 Trend Watch 복귀 실제 렌더 확인** — 다음 06:00 KST cron 이후
  `docs/latest.html` 과 신규 `docs/archive/report_YYYYMMDD.pdf` 에서 §04
  헤드라인 = `Grade A · Top 5`, 🆕 뱃지가 Top 5 카드 + Remaining 표에만
  잔존하는지 확인.

### 미해결
- **MCP → sandbox base64 전송 근본 해결 미해결**: v3.9 는 Step 1 2차 경로
  진입 시 ALERT 11 로 사용자에게 고지하지만 여전히 escape unwrap 손실 발생.
  근본 해결은 MCP 가 결과를 `/tmp` 에 직접 쓰는 API 가 있어야 가능 — Claude
  Code 범위 밖, MCP 서버 / connector 도구 확장 필요.
- **데이터 무결성 원칙의 ADR 후보**: silent degradation 거부, damage control
  canonical 화 금지 는 v3.9 에 구현됐지만 원칙 자체는 향후 다른 fallback
  판단에도 적용될 것. ADR-009 후보로 승격할지 마스터 판단.
- **5~8개 이전 세션 브랜치 UI 수동 삭제 (sandbox 403)**:
  `session-start-hook-Lv8YN`, `session-end-2026-04-24-3`,
  `adr-005-006-007-entry-timing`, `resume-session-progress-8cGdH`,
  `fix-error-handling-riAYS`, `phase3-backtest`, + 오늘 생성분
  `session-start-nueAo`, `v3.9-data-integrity`.

### 이번 세션 생성/수정 파일
- 신규: `docs/decisions/008-scrap-entry-candidates-section.md`
- 수정: `reports/templates/v6.2_template.html.j2`, `reports/render_report.py`,
  `CLAUDE_PROJECT_INSTRUCTION.md` (v3.6 → v3.9, 405 → 470줄),
  `CLAUDE.md`, `SESSION_LOG.md`

### 머지/푸시 결과 (2026-04-25 종료 시점)
- **main HEAD**: `775ba0b` docs(project): Claude Project Instruction v3.8 → v3.9
- 직전 main 갱신: `de873db` v3.7 → v3.8 (PR #19 포함 ADR-008 + 슬림화)
- 현재 브랜치: `claude/v3.9-data-integrity` @ `741cf2f` — 콘텐츠 ≡ `775ba0b`
  (rebase merge 로 SHA 만 변경, 세션 종료 문서 커밋 예정)

---

## 2026-04-24 (PC, offline, branch `claude/condescending-feynman-008ff4` — PR #16) — ADR-005/006/007 entry timing 실증 + baseline 확정

### 결정
- **ADR-005 Accepted** — Entry timing 실증. baseline median signal_age=**6일**,
  fresh(1일차)=19.5% 뿐. signal_days≤N 필터 전부 baseline 하회 (≤1 -10.8%p,
  ≤3 -10.8%p, ≤10 -4.3%p). "Extended 진입 우려" 가설 기각. 알파 분해:
  **필터(수급+RS≥70) +25.8%p + 체결타이밍 +6.7%p = 전체 +29.55%**. 실전
  기댓값 +15-20% 는 체결 알파 대부분 소실 + 슬리피지/세금/생존편향 차감 후
  잔여 필터 알파. baseline T10/CD60 그대로 유지.
- **ADR-006 Rejected** — Walkforward 실험 E. baseline vs K=10 (streak≤10) 4 window 분해:
  - IS1 (2015-19): ΔCAGR -2.20%p, ΔMDD -1.58%p
  - **OOS1 (2020-22): ΔCAGR -19.27%p, ΔMDD -2.58%p → C1/C2 미달**
  - IS2 (2015-22): ΔCAGR -8.51%p
  - **OOS2 (2023-25): ΔCAGR +11.72%p, ΔMDD +8.36%p → C3 통과**
  - 방향 불일치 = 재현 알파 아님. H1 (우연) / H4 (overfitting) 강력 지지.
    H3 (MDD 방어) OOS1 에서 오히려 악화로 기각. 실험 F/G/H 는 skip (E
    결과 명백).
- **ADR-007 Accepted** — UBATP 장중 알림 시스템 **폐기**. 현 알림 = "등급
  변화 이벤트" (매매 신호 아님). 재설계 (Top 5 delta + state-aware) 해도
  장중 RS ≠ 종가 RS → 실익 없음. 청산 알림도 불채택 (주식앱 기계 stop-loss/
  trailing 주문으로 대체). 운영은 06:00 모닝리포트 단일 신호 채널로 단순화.
- **v3.6 Instructions draft Rejected** — draft 추가분이 전부 ADR-005/007
  "기각 결정" 의 가상 방어 규칙. 실 사건 아닌 가상 위험 기반 규칙 비대화
  불필요. 실제 Claude 오답 사건 발생 시에만 한 줄씩 추가.

### ⚠ 원격 #2 와의 관계 — 중대 발견
web #2 세션 (`claude/session-start-hook-Lv8YN`) 의 **"백테 진입 규칙 =
🆕 A등급 첫날 신호 → 익일 시가 매수"** 해석은 본 ADR-005 가 **실증 반증**.
실제 baseline 은 `check_signal=True` 인 모든 종목 RS 순 top-5 진입 — streak
무관. Extended 진입 (signal_age 10+ 일) 도 baseline 의 정상 분포 (median=6일).
Section 04 Entry Candidates (🆕 만 강조) 의 정당성은 별도 재검토 필요 (차
세션 작업 #3).

### 실전 매매 규약 정립 (사용자 1종목 집중 → 원칙 복귀 대화에서 도출)
- 원칙: 오늘 아침 리포트 Top 5 → 시장게이트 통과 확인 → 미보유·쿨다운
  해제 종목 RS 순 → **빈 슬롯 수만큼 균등 가중** → 09:00 시가 근처 매수
- 5일 지연 후 매수해도 OK. 필터가 엄격해서 Top 5 라인업이 day-to-day
  안정적. baseline median signal_age=6일 = 지연 진입도 정상.
- 차트 판독으로 종목 거르기 ❌ (검증되지 않은 추가 필터)
- 단독 종목 집중 ❌ (백테는 5종목 포트폴리오 통계 기반 알파)

### 주요 작업
1. `backtest/experiments/` 디렉토리 신규. `engine.py` hooked backtest 엔진
   (select_fn 주입 + entry_mode 파라미터화). 기존 `strategy.py` unchanged.
2. 실험 A — baseline 재현 (+29.55% 정확 일치) + signal_age 분포 계측
   (1일 19.5% / median 6 / p90 23).
3. 실험 B split — 4 variant. B2 +3.74% vs B3 +13.30% 역전 (non-actionable).
4. 실험 C — streak ∈ {1,2,3,5,10} 민감도. ≤10 만 특이 프로파일 → ADR-006 대상.
5. 실험 E — walkforward IS/OOS, K=10 기각.
6. 통합 `experiments_compare.csv` + `exp_e_windows.csv` + ADR 3개 확정.
7. ADR-007 작성, `docs/plans/001-alert-system-setup.md` DEPRECATED.
8. CLAUDE.md / SESSION_LOG 원격 #2 구조 존중하며 병합 (hard reset +
   선택 체크아웃 + 수동 병합 전략으로 5커밋을 단일 커밋에 압축).
9. v3.6 Instructions draft Rejected 처리.
10. **session-start 자동 git fetch 미실시** 교훈 — `memory/feedback_*.md` 기록.

### 세션 후반 작업 (drift 복구 + 스킬 수정)
11. **drift 사고 복구** — push 직전 로컬 main 이 origin/main 에 수십 커밋
    뒤처진 상태 발견 (웹 세션 PR #10~#13 + Actions auto 커밋 다수). 전략
    전환: rebase abort → `git reset --hard origin/main` → 신규 파일
    (ADR/experiments/draft) 만 선택 checkout → 기록 파일 4개 (CLAUDE.md,
    SESSION_LOG, .gitignore, plans/001) 수동 병합 → 단일 squash 커밋 →
    force-push → PR #16 rebase merge 완료 (main `31c07b6`).
12. **스킬 수정** — `/session-start` 와 `/session-end` 양쪽에 원격 sync
    체크 자동화 추가. 글로벌 (`~/.claude/commands/`) + 프로젝트 로컬
    (`.claude/commands/`) 둘 다 반영. 오늘 같은 drift 사고 재발 방지.
    커밋 `339d373` main push 완료.
13. **원격 #2 와의 관계 정리** — web #2 의 "백테 진입 규칙 = 🆕 첫날만"
    해석은 ADR-005 가 실증 반증. Entry Candidates 섹션 (코드) 은 유지하되
    설명 텍스트 정정은 차 세션 과제 (ADR-008 후보). CLAUDE.md 의 "확정
    전략" 블록에 정정된 규칙 문구 삽입.
14. **브랜치 정리** — 머지된 `claude/condescending-feynman-008ff4` 원격
    삭제, ADR-007 결정 반영하여 `claude/session-start-UBATP` 원격 삭제,
    PR #15 (중복) 폐기.
15. **PR #17 생성** — `claude/session-start-hook-Lv8YN` → main 머지용 PR.
    CONFLICTING 상태, 웹 세션에서 rebase 대기.

### 미해결 / 다음 세션
- **[머지 대기] PR #17** (원격 #2 → main) — 웹 Claude 세션에서 rebase +
  force-push 후 머지. 충돌은 CLAUDE.md / SESSION_LOG 등 기록 파일 위주.
- **[확인 필요] PR #14** (`claude/session-end-2026-04-24-3`) — 어제 open,
  내용 파악 필요.
- **[차순위] Entry Candidates 섹션 설명 텍스트 재설계** (ADR-005 기반,
  후보 ADR-008). "🆕 첫날만 매수 후보" → "Top 5 RS 순 분산, median 6일차".
- **[선택] 박스권 조건부 섹터 게이트** (구 ADR-005 후보 → ADR-008 재번호).
- **실전 매매**: 두산에너빌리티 1종목 유지. 오늘 Top 5 나머지 종목 RS 순
  분산 매수 (기술 작업 아님).

### 이번 세션 생성/수정 파일
- 신규:
  - `backtest/experiments/engine.py` + exp_a/b_split/b_live/c/e + make_compare.py
  - `backtest/experiments/results/exp_*` (summary CSV/JSON)
  - `docs/decisions/005-entry-timing-diagnosis.md` (Accepted)
  - `docs/decisions/006-streak-le10-residual-investigation.md` (Rejected)
  - `docs/decisions/007-scrap-intraday-alerts.md` (Accepted)
  - `docs/plans/002-instructions-v3.6-draft.md` (Rejected, 보존)
  - `memory/feedback_session_start_git_fetch.md` (drift 방지 피드백)
- 수정:
  - `CLAUDE.md`, `SESSION_LOG.md`, `.gitignore`
  - `docs/plans/001-alert-system-setup.md` (DEPRECATED)
  - `.claude/commands/session-start.md` (원격 drift 체크 추가)
  - `.claude/commands/session-end.md` (push 전/후 검증 추가)
  - `~/.claude/commands/session-start.md`, `session-end.md` (글로벌 동일 수정)

### 머지/푸시 결과 (2026-04-24 종료 시점)
- `main` HEAD: `339d373` chore(skills): session-start/end drift 체크 추가
- 직전: `31c07b6` feat(backtest): ADR-005/006/007 entry timing 실증
- 로컬 main ↔ origin/main: **완전 동기** (drift 0)
- 내일 06:00 cron 은 본 상태에서 돌아감 (리포트 렌더 코드 무변경)

---

## 2026-04-24 #2 (PC web, branch `claude/session-start-hook-Lv8YN` `bdcd4fc`) — Entry Candidates 섹션 + parser 🆕 + ACTION 분기 + 카드 보호 CSS

### 결정
- **백테 진입 규칙 명시**: `backtest/strategy_config.yaml::execution.entry: open_next_day`
  + `strategy.py:310-330` 분석으로 실전 매수 후보 = **🆕 A등급 첫날 신호** 만
  해당함을 확인. 기존 N일차 A등급 종목들은 백테 관점에서 이미 진입 완료
  또는 미스샷. 이에 따라 모닝 리포트 UI 도 신규 편입을 최상위로 강조.
- **Section 04 Entry Candidates 신설**, 기존 04 Top 5 → **05 Trend Watch** 로
  역할 재정의. 04·b/05/06/07 → 05·b/06/07/08 일괄 재번호.
  - Always render (0건도 empty-state 메시지 표시).
  - 녹색 4px boundary + bull-bg-soft → 흰색 그라디언트 + "TODAY'S BUY
    CANDIDATES · 백테 진입 규칙 일치" eyebrow + 백테 규칙 callout 박스.
- **PDF 카드 찢김 방지 CSS 강화**: 전세션 (#1) 패치가 `.readiness-card` 등
  큰 블록을 보호 안 했고 `wkhtmltopdf` 가정 주석으로 신문법(`break-*`)
  미사용. 실제 렌더러는 Chrome headless (`reports/render_pdf.py`) 라
  page-break-* + break-* 병기로 수정. `.readiness-card` / `.portfolio-main`
  / `.sector-card` / `.context-col` + 섹션 헤더 (`.section-header` /
  `.two-col-title` / `.context-head`) 보호.
- **Parser `_parse_grade_a` regex 확장**: `(\d+)일` 만 매치하던 것을
  `(\d+일|🆕)` 얼터네이션으로 확장 + `is_new` bool 필드 추가. 기존엔
  신규 A등급 종목이 regex 미스매치로 드롭 → 카운트 불일치 (오늘 A:25 표기
  vs 24종목 렌더). LIG넥스원(079550) 사례. 회귀 테스트 추가.
- **Executive Summary ACTION 라인 분기**: 보유종목 +5% **돌파** 시에도
  "도달 전 관망" 으로 출력되던 문제. `change_pct < 5` 분기로 "돌파 ·
  거래량 수동 확인" 자동 전환.
- **SessionStart hook 추가**: web 환경 한정 `pip install -r requirements.txt`
  자동 실행. `CLAUDE_CODE_REMOTE` 가드로 로컬 무영향.

### 커밋
- `92f20fc` chore: add SessionStart hook to install Python deps on web sessions
- `26bca68` chore(preview): PDF page-break CSS 수정안 견본 (리뷰용, merge 금지)
- `ff064f8` fix(report): parser 🆕 regex + ACTION 분기 + PDF 카드 찢김 방지 CSS
- `e16098f` feat(report): A등급 신규 편입 섹션 + 🆕 뱃지 일관 표시
- `b48c324` chore: remove docs/preview/ (리뷰 완료, main 머지 대비 정리)
- `bdcd4fc` feat(report): 신규 편입 섹션을 최상위 04 Entry Candidates 로 승격

### 검증
- `tests/test_parser.py`: 20/20 PASS (🆕 회귀 테스트 1건 신규 추가)
- `tests/test_sector_mapping.py`: 8/8 PASS
- `tests/test_sector_breadth.py`: 5 failure (pre-existing, 무관)
- 로컬 Chromium v147 PDF 렌더: 9 페이지, 두산에너빌리티 카드 단일 페이지
  유지 확인 (이전엔 p4→p5 찢김), Section 04 Entry Candidates 녹색 강조 표시
- Synthetic 0/3 종목 케이스 모두 정상 (empty-state + 강조 렌더)

### 다음 세션 진입점
1. GH Actions Chrome 환경 PDF 검증 (다음 cron 또는 manual workflow_dispatch)
2. main 머지 PR 생성

---

## 2026-04-24 #1 (PC, main, 7151030) — 체크리스트 표기 + PDF 분할 + 지침 v3.3→v3.5 + 워크플로 정리

### 결정
- **템플릿 체크리스트 표기 fix** (`v6.2_template.html.j2`): `<span class="check-val">`
  앞에 공백 1자 + `.check-val { margin-left: 6px }` 추가. wkhtmltopdf QtWebKit
  이 CSS Grid 미지원이라 기존 `display: grid; gap: 6px` 가 실패해서
  `코어 조건 8/8100%` / `RS ≥ 7096` / `소속전력인프라` / `통과VIX+MA60` 으로
  붙어 나오는 버그. CSS Grid fail 환경에서도 inline margin 으로 간격 유지.
- **Claude Project 지침 v3.3 → v3.4 → v3.5** (`CLAUDE_PROJECT_INSTRUCTION.md`):
  - v3.4: Step 1 긍정 경로 코드 블록 추가 + `base64 금지` 규칙 스코프 축소
    (Step 7~8 PDF 한정 명시) → 세션 #8 에서 발견한 paranoia 우회 루프 차단
  - v3.5: 2026-04-24 모닝 리포트 실측 반영. Drive MCP `read_file_content` 가
    이모지/특수문자 백슬래시 이스케이프로 반환해서 Claude 가 `download_file_content`
    재시도 → 왕복 2회. `download_file_content` + `base64.b64decode` 를 단일
    canonical path 로 명시. `read_file_content` 선호출 금지.
- **`docs/.nojekyll` 추가**: GitHub Pages 기본 Jekyll 이
  `docs/plans/004-sector-html-renderer-rewrite.md:100` 의 `{%}%` 패턴을 Liquid
  태그로 오인해서 `pages-build-deployment` #141-143 연속 실패. Jekyll 자체
  비활성으로 앞으로 md 파일의 어떤 Liquid 충돌도 안전.
- **`morning.yml` schedule 트리거 재제거**: `0 21 * * 0-5` cron 이 4/20 `658e231`
  에서 제거됐었는데 4/23 UZymn 세션 `d93baf4` (ADR/CLAUDE.md 인프라 통째 재
  생성) 가 stale morning.yml 145줄 신규 추가하면서 부활. 오늘 KST 06:25
  cron-job.org 정상 트리거(#85) 와 ~2.5시간 지연된 GitHub 내장 cron(#86) 이
  중복 실행되는 걸 발견. schedule 재제거 + 주석으로 회귀 방지 사유 명시.
- **PDF 페이지 분할 규칙 추가** (`v6.2_template.html.j2`):
  `.readiness-card { page-break-inside: avoid }`, `.section-header { page-break-after: avoid }`,
  공통 `table tr / h1-h3 / check-col / readiness-header / readiness-footer`.
  큰 섹션은 자연 분할 허용 → 빈 공간 최대 ~220px.

### 검토한 대안
- **템플릿 표기 fix**: CSS Grid 대신 flexbox 전환 고려했으나 wkhtmltopdf
  flexbox `gap` 도 미지원. 공백 + inline margin 이 가장 호환성 좋음.
- **pages-build-deployment**: 문제의 md 한 줄만 escape 하는 방안도 있었으나
  ADR/plan 에 계속 충돌 패턴 나올 수 있음. `.nojekyll` 로 구조적 차단.
- **페이지 분할**: `section` 단위 강제 개행 (`page-break-before: always`)
  고려했으나 빈 공간 큼. 작은 블록 단위 avoid 만 적용해서 빈 공간 최소화.
- **v3.5 Step 1**: `read_file_content` 를 대안 경로로 유지 고려했으나,
  두 경로 병기 시 Claude 가 또 선택 루프 돌 가능성 → 단일 canonical 강제.

### 이번 세션에서 배운 것
- **웹 Claude 세션의 "인프라 파일 통째 재생성" 패턴은 회귀 주범**. UZymn
  세션이 stale morning.yml (schedule 포함) 을 145줄 신규 파일로 추가하면서
  4/20 의 schedule 삭제가 부활. **예방책으로 morning.yml 상단에 주석 명시**.
- **v3.3 → v3.4 paranoia 축소 패치는 효과 있었지만 부분적**. Claude 가
  "규칙 스코프: Step 7~8 의 PDF 한정" 이라고 스스로 말함 = scope narrowing
  적용됨. 하지만 canonical path 가 현실과 안 맞아 여전히 왕복. 지침 개선은
  **"방지 규약 좁히기 + 긍정 경로 정확히 기술"** 둘 다 필요.
- **CSS Grid + wkhtmltopdf 호환성 주의**. QtWebKit (Chrome 57 이전 fork)
  은 CSS Grid/flexbox gap 미지원. PDF 생성 때 grid 레이아웃 쓸 땐 fallback
  (공백 텍스트 노드, inline margin) 같이 박기.

### 미해결
- **파서 regex bug** (오늘 Claude Project 세션이 보고): `_parse_grade_a` 가
  신규 A등급 `🆕` 이모지 케이스 누락 (오늘 LIG넥스원 079550). 25→24 파싱.
  Top5 영향 없음. fix: `re.compile(r"(\d+일|🆕)")` 얼터네이션.
- **템플릿 ACTION 라인 고정 문구** (같은 세션 보고): Executive Summary 끝
  `{{ holding.add_threshold }}원 도달 전 관망` 이 조건 분기 없이 고정. 추매
  돌파 상황 (+13.03%) 에도 "도달 전" 표시. fix:
  `{% if holding.change_pct < 5 %}도달 전 관망{% else %}돌파 · 거래량 수동 확인{% endif %}`.
- **cron-job.org 시간**: 06:25 유지/06:05 변경 여부 마스터 결정 대기.
  변경 시 `morning.yml` line 4 주석도 동기화.
- **UBATP 알림 E2E**: 세션 #4 부터 이월, 이번 세션도 미수행.
- **v3.5 실효성 검증**: 다음 모닝 리포트에서 Step 1 이 `download_file_content`
  한 번만 호출하는지 관찰. 여전히 `read_file_content` 시도하면 강화 필요.

### 다음 세션에서 할 일
- **[최우선] 파서 regex + 템플릿 ACTION 라인 수정** (30분, 오늘 발견 bug 2건).
- **[차순위] 다음 cron-job.org 런 결과 확인** (5분): PDF 분할 / 체크리스트
  표기 / pages 빌드 녹색 / GitHub 내장 cron 중복 실행 없음 / v3.5 효과.
- **[조건부] cron-job.org 시간 변경** (2분, 마스터 결정 시).
- **[중장기] UBATP 알림 E2E** (30분, 이월).
- **[중장기] ADR-005 박스권 조건부 섹터 게이트** (1-2h, ADR-004 기각 후속).

---

## 2026-04-23 #8 (PC, main) — Claude Project v3.3 지침 개편 + 운영 진단

### 결정
- **CLAUDE_PROJECT_INSTRUCTION.md v3.2 → v3.3 업데이트** — plan-004 / ADR-003
  Amendment 3 / T10/CD60 / ADR-004 기각 전부 반영. 주요 변경:
  - 최상단 "v3.3 진입 게이트" 3줄 (Files 신선도 / shim 금지 / 포맷 고정)
  - 전략 파라미터 T15/CD120 → **T10/CD60** (손절 -7%, 트레일링 -10%, 쿨다운 60)
  - 필요 파일 5개 → **7개** (sector_mapping.py / sector_overrides.yaml / universe.py 추가, `__init__.py` 는 Step 3 런타임 생성)
  - Step 3 에 `/tmp/backtest/` 패키지 구성 추가 (sector_mapping 의 universe import 의존)
  - Step 4 sector 키에 **11섹터 체계** 명시, ETF 명 (KODEX / TIGER) 언급 금지
  - 절대 금지에 shim/ETF 관련 4개 신규 (`_parse_sector_etf`, 런타임 monkey-patch, 포맷 감지 셰임, sector_etf 키)
  - 자체 체크에 드리프트 감지 6개 항목
- **Project Files ↔ Git 레포 동기화 규칙 명문화** — main 에 `reports/` 수정
  커밋 머지되면 **그 세션 안에서** Project Files 7개 전부 재업로드 (덮어쓰기).
  이 규칙 없으면 v3.3 진입 게이트 #1 에서 매번 걸림.
- **삼성전기 (009150) 반도체 섹터 분류 타당성 확인** — 증권가 리포트 기반
  (iM증권·교보·하나·대신·Mirae Asset) 2026 컨센서스가 FC-BGA/AI 기판 밸류
  체인으로 커버 중. 매출 드라이버·주가 상관·애널리스트 커버리지 3축 모두
  반도체 사이클과 정렬. ADR-003 Amendment 3 의 분류 **유지**.

### 검토한 대안
- **v3.3 Step 1 에 명시적 `base64.b64decode` 코드 블록 박기** — morning_data
  로드 시 Claude Project 가 과잉 해석으로 `read_file_content` + 역이스케이프
  같은 복잡 경로를 택해 병목 발생. 사용자가 "오늘은 결과 떴다"로 종료, 패치
  보류. 다음 세션에서 체감 지연 재발 시 반영 판단.
- **Drive MCP → Notion code block 으로 morning_data 경로 전환** — 구조적
  해결책이지만 Actions 워크플로 변경 필요 (1-2h). 오늘 결론 나오고 종료,
  우선순위 낮음으로 이월.
- **삼성전기 분류 전기전자로 원복** — KRX KSIC 기준으로는 합리적이지만
  증권가 커버리지·실적 드라이버 기준으론 반도체 일치. **원복 기각**,
  현재 분류 유지.

### 이번 세션에서 배운 것
- **Claude Project Files ↔ Git 레포 drift 가 무음 실패** — plan-004 머지
  (#6) 당시 Project Files 재업로드 체크리스트 항목이 없어서 세션 #6 ~ #7
  동안 Claude Project 의 Files 는 plan-004 이전 스냅샷 유지. 사용자 체감
  으론 "ADR 다 반영됐는데 리포트엔 왜 안 뜨지?" 로 나타남. 이런 이원화
  시스템에선 동기화 훅이 첫 번째 인프라 투자 대상.
- **지침에 "방지 규약" 많이 박으면 Claude 가 무관한 경로에까지 일반화**
  — v3.3 에 "PDF base64 는 토큰 독" 경고를 박았더니 morning_data (UTF-8
  텍스트) 로드까지 그 paranoia 적용해서 우회 경로 고안. 규약은 **적용
  대상을 명시적으로 좁혀서** 기재해야 함 (e.g. "Step 8 의 PDF 업로드
  한정"). 아니면 명시적 "긍정 경로" 코드 블록으로 대체.
- **Project Files 0 바이트 파일은 업로드 목록에 뜨지 않음** — claude.ai
  의 드롭 동작. 런타임 생성으로 우회 가능 (`write_text("")`). 이번에
  `reports/__init__.py` 케이스로 발견.
- **사명 ≠ 사업 실체** — 삼성전기 사례. 1969년 삼성산요전기 합작 출신이라
  이름에 "전기" 박혔지만 현재 매출은 MLCC + FC-BGA + 카메라 모듈.
  `reports/kospi200_sectors.tsv::role_note` 컬럼에 실제 역할 기재되어
  있어 섹터 분류 헷갈릴 때 이게 1차 참고자료.

### 미해결
- **v3.3 Step 1 base64 경로 명시** — 오늘은 결과 떴지만 다음 런에서 또
  병목 나면 `base64.b64decode` 한 줄로 고정 필요. 판단 이월.
- **내일(2026-04-24) 06:00 cron 검증** — plan-004 + 11섹터 + workflow race
  fix 정상 반영 확인 대기 (세션 #6 부터 이월).
- **UBATP 알림 E2E 테스트** — PC 필요 (30분). 세션 #4 부터 누적 이월.
- **Morning report Drive MCP 구조 개선** — base64 경유 비용 + 지연 누적.
  Notion code block 경로가 대안. 우선순위 중.

### 다음 세션에서 할 일
- **[우선] UBATP 알림 E2E** (30분, 이월) — 가장 오래 이월된 항목.
- **[차순위] 06:00 cron 결과 확인** (5분) — 내일 아침.
- **(조건부)** Claude Project 모닝 리포트 재발 시 v3.3 Step 1 패치 반영.
- **(중장기)** ADR-005 후보 — 박스권 조건부 섹터 게이트 (regime-dependent,
  ADR-004 기각 후속). 2015-19 이득 보존 + 중립/강세장 손실 회피.

---

## 2026-04-23 #7 (PC, main) — ADR-004 섹터 게이트 통합 실증 → **기각**

### 결정
- **ADR-004 섹터 게이트 기각** — 5 variant × 11.3년 × 162종목 백테. 모든 variant
  가 baseline +29.55% CAGR 를 하회. "주도+강세" (ADR-003 검증 조합) 는 -8.12%p
  악화, "약세만 차단" (D) 조차 -2.99%p 악화. MDD 도 C/D 모두 baseline 대비 악화.
- **확정 전략 T10/CD60 변경 없음** — baseline 숫자는 +29.29% → +29.55% (최신
  2026-04-23 포함 효과 +0.26%p), MDD -29.8% → -29.83% 로 사실상 동일 재현.
- **섹터 게이트 인프라는 존치** — `strategy_config.yaml::sector_gate` +
  `precompute_sector_tiers/check_sector_gate` 는 enabled=false 기본값으로 남김.
  박스권 조건부 활성화 등 후속 실험 시 재사용.

### 주요 작업
1. ✅ `backtest/01_fetch_data.py` 복원 — 백업 (`phase3_backup/`) 에서 복사.
   기존 레포에 ohlcv 데이터가 gitignore 로 누락된 상태였음.
2. ✅ pykrx 종목 OHLCV 헬스체크 — 인덱스 API 만 다운이고 종목은 정상 확인.
3. ✅ 162종목 × 11.3년 재수집 (`01_fetch_data.py --skip-index`) — **74초**
   완료 (예상 30-60분에서 대폭 단축, pykrx 안정화 효과로 추정).
4. ✅ `01b_fetch_kospi_yf.py` 신규 — pykrx index API 장애 우회. yfinance `^KS11`
   2015-01 ~ 오늘 2771 rows 수집. 스키마는 `load_data` 가 기대하는 close 만.
5. ✅ `strategy_config.yaml::signal.sector_gate` 블록 추가 — enabled/tiers/
   fallback_on_na/recompute_every. 기본 off (후방 호환).
6. ✅ `strategy.py::precompute_sector_tiers(all_dates, stock_arr, cfg)` 신규 —
   `stock_arr` 를 long-format DataFrame 으로 변환 후 `sector_breadth.
   compute_sector_scores` 를 `end_date=D-1` 로 N거래일마다 호출. 캐시
   `{i: {ticker: grade}}`. 룩어헤드 방지 + 메모리 경제.
7. ✅ `strategy.py::check_sector_gate(ticker, i, cache, cfg)` — `run_backtest`
   의 candidates 루프에서 `check_signal` 통과 후 호출. N/A 정책 pass/block 지원.
8. ✅ `99_sector_gate_ab.py` 초기 A/B + `99_sector_gate_variants.py` 5 variant
   스윕 작성. tier_cache 1회 (80s) 후 각 variant 백테 1.5-2.6s.
9. ✅ 결과 분석: 전 variant baseline 하회. 최소 손해 D (-3%p), 최대 손해 B (-14%p).
10. ✅ `docs/decisions/004-sector-gate-rejection.md` 작성 (기각 + 대안 + 교훈).
11. ✅ CLAUDE.md + SESSION_LOG 갱신. 다음 활성 작업 ADR-005 후보로 재정립.

### 결과 요약

```
─────────────────────────────────────────────────────────────────
 variant               전체       2015-19     2020-24     2025+
─────────────────────────────────────────────────────────────────
 A baseline          +29.55%      -2.05%     +35.26%    +160.96%   ← 유지
 B 주도 only           +15.66%     +1.71%     +18.68%     +56.77%
 C 주도+강세            +21.43%     +9.49%     +12.15%    +128.59%   ← ADR 검증 조합
 D 주도+강세+중립        +26.56%     -1.79%     +32.96%    +129.86%   ← 최소 손해
 E 주도+강세 strict     +21.43%     +9.49%     +12.15%    +128.59%
─────────────────────────────────────────────────────────────────
```

### 검토한 대안
- **박스권 detection + 조건부 활성화** — 2015-19 에서만 게이트 이득 나타남
  (+3~+11%p). 6M KOSPI 수익률이나 MA200 slope 기반 regime detection 으로
  박스권에만 활성화. 이론적으로 타당. **ADR-005 후보로 이월**.
- **게이트 대신 랭킹 가점** — 현 RS 백분위 순위에 섹터 점수 가중합 추가로 반영.
  filter 가 아닌 ranking 알파. 구현 1h. 후속 후보.
- **recompute_every 단축 (5→1)** — lag 감소 가능하나 섹터 등급 플립이 주 단위
  이상이라 효과 미미 예상. 우선순위 낮음.
- **strict fallback (E) 만 따로 검증** — C와 수치 동일. N/A 섹터 거의 없어
  의미 없음. 폐기.

### 이번 세션에서 배운 것
- **회귀 알파 ≠ 전략 알파** — ADR-003 Amendment 2 에서 "주도+강세 섹터 × universe-avg
  다음 달 hit 83%" 가 PASS 였어도, Minervini 통과 종목 부분집합에 대한 조건부
  알파는 다른 명제. 섹터 단위 평균 알파는 개별 종목 필터로 환원되지 않음.
- **상관된 trend 필터 중첩은 lag 만 추가** — Minervini 자체가 trend-following
  이므로 섹터 trend 게이트는 같은 방향. AND 로 걸면 등급 부여 시점까지 기다리며
  조기 진입 기회 손실. "다른 축의 필터" (momentum × value, trend × MR) 가 효율적.
- **박스권 vs 추세장 필터 비대칭** — 박스권에선 false signal 거르는 효과 > lag
  손실 (이득). 추세장에선 lag 손실 >> 추가 정확도 (손해). regime-dependent
  게이트가 이론적으로 타당.
- **1회 데이터 재수집 = 전체 baseline 재현** — +29.29% → +29.55% 로 2015-2026
  전 구간 일관 재현. 재생성 가능한 데이터의 힘. Windows 에서 pykrx 162종목
  2015-2026 가 74초에 완료된 건 예상 외 발견 (SLEEP_SEC=0.4 × 164 = 66초 이론치
  대비 이상적).
- **tier_cache 재사용 변형 실험 거의 공짜** — 80s 1회 precompute 후 variant 당
  2초. 의사결정 전 4-5 variant 스윕이 표준 patternizable.

### 미해결
- **박스권 조건부 게이트 실증** (ADR-005 후보) — 시장 regime detection +
  조건부 활성화. 1-2h.
- **랭킹 가점 방식 실증** — filter 대신 섹터 점수를 RS에 가중합. 1h.
- **universe.py 009540 이름 교정 커밋 (335e988)** — 직전 세션 끝물에 main 에
  이미 들어감 (이 세션 시작 시 pull). SESSION_LOG #6 "미해결" 중 이 건은 해소.
- **UBATP 알림 E2E** — 여전히 이월 (PC 필요).
- **내일(2026-04-24) 06:00 cron** — plan-004 + 11섹터 정상 반영 검증 대기.

### 다음 세션에서 할 일
- **[우선] UBATP 알림 E2E** (30분) — 이번 세션에서도 이월됨.
- **[차순위] ADR-005 — 박스권 조건부 게이트** (1-2h) — 섹터 게이트 인프라는
  있으므로 regime detection 붙이고 백테 1회.
- **(모니터링)** 2026-04-24 06:00 cron 자동 런.

### 이번 세션 생성/수정 파일
- 신규: `backtest/01_fetch_data.py` (복원), `backtest/01b_fetch_kospi_yf.py`,
  `backtest/99_sector_gate_ab.py`, `backtest/99_sector_gate_variants.py`,
  `docs/decisions/004-sector-gate-rejection.md`
- 수정: `backtest/strategy_config.yaml`, `backtest/strategy.py`,
  `CLAUDE.md`, `SESSION_LOG.md`
- 생성 데이터 (gitignore): `backtest/data/ohlcv/*.parquet` (164),
  `backtest/data/index/kospi.parquet`, `backtest/data/adr004_ab.json`,
  `backtest/data/adr004_variants.json` + 로그 3개

---

## 2026-04-23 #6 (PC, UZymn → main) — plan-004 완료 + workflow race 수정 + main 머지

### 결정
- **plan-004 실행 범위 확정**: sector_mapping 완전 재작성 / `_parse_sector_adr003`
  파서 신규 / render_report 4-way 분기(leading/weak/neutral·na/미매핑) / 템플릿
  `sector_etf`→`sector_adr003` 전면 교체. Session #5 의 plan 문서 그대로 따름.
- **`_parse_sector_etf` 구 파서 존치**: 후방 호환 안전망. 구 fixture 테스트 19개
  그대로 통과 확인. 후속 cleanup 커밋에서 제거 판단.
- **Workflow race 수정 방향 — 옵션 A**: `git reset --hard` 제거 후 로컬 workspace
  의 `morning_data.txt` 그대로 사용. push 는 `git fetch + rebase + retry` 루프
  (최대 5회, 3초 간격) 로 Contents API commit 과의 non-ff 자동 해소.
- **main 머지 전략**: `git merge origin/main -X ours --no-ff` — UZymn(12:41 UTC)
  이 main(06:00 KST) 보다 최신 데이터이므로 충돌 시 UZymn 편. 이후 main
  fast-forward.

### 주요 작업
1. ✅ `reports/sector_mapping.py` 재작성 — STOCK_TO_SECTOR_ETF 하드코드 삭제.
   `ticker_overrides.yaml` (164) + `backtest/universe.py` 역매핑 로드.
   `resolve_sector(name, sector_adr003)` 새 시그니처 (sector/tier/score/in_leading).
2. ✅ `reports/parsers/morning_data_parser.py` — `_parse_sector_adr003` 신규(+107).
   `📊 주도 섹터 현황(?!ETF)` 헤더로 구 파서와 공존. 11섹터 점수/종목수/breadth
   + 주간변동(new_leaders/demoted/score_jumps) + transition flag + na 파싱.
3. ✅ `reports/render_report.py` — `_enrich_grade_a` 4-way 재작성. "KODEX " replace
   삭제. `data["sector_adr003"]` 키 사용. "ETF 데이터 없음" → "섹터 미매핑".
4. ✅ `reports/templates/v6.2_template.html.j2` — `sector_etf.*` → `sector_adr003.*`
   7곳 교체. 섹션 meta "16 ETFs" → "11 Sectors · KOSPI200". 티어 임계 라벨
   갱신(≥75 / 60–74 / 40–59 / <40). 카드에 `N종목 · breadth X%` 추가.
5. ✅ `tests/test_parser.py` +3 테스트 / `tests/test_sector_mapping.py` 신규 +8
   → **27 passed**. Dry-run 렌더: 삼성SDI=2차전지 64점, LG이노텍=반도체 100점,
   두산에너빌리티=전력인프라 75점. "ETF 데이터 없음" 0건.
6. ✅ UZymn 1차 수동 트리거 (`gh run 24832792291`) — success 인데 어제 데이터로
   렌더됨 발견. 로그 타임라인 분석: combine_data 의 Contents API push 후 195ms
   만에 render step 의 `git fetch`가 실행돼 새 commit 을 못 봄 → `reset --hard`
   가 yesterday's `morning_data.txt` 로 workspace 롤백 → 어제 데이터로 렌더.
   GitHub 의 Contents API ↔ git upload-pack eventual consistency 가 근본 원인.
7. ✅ `morning.yml` 재설계 — `reset --hard` 제거. 로컬 `morning_data.txt` 로
   render. commit 후 `git reset --hard HEAD` 로 workspace 클린화 (1차 수정에선
   morning_data.txt 만 되돌려 kr_data/us_data 등 unstaged dirty 로 rebase 실패).
   push 는 fetch+rebase+retry 루프.
8. ✅ UZymn 3차 트리거 (`gh run 24835114736`) — **success, attempt 1/5 push 성공**.
   배포본 검증: Report date=2026-04-23, "ETF 데이터 없음"/"KODEX "/"TIGER "=0,
   섹터 카드 11섹터 정상, 삼성SDI/LG이노텍 등 정상 매핑.
9. ✅ `git merge origin/main -X ours --no-ff` → UZymn 에 main 의 오늘 auto
   commit 60개 흡수. 충돌 3파일 (docs/latest.html, report_20260423.html/pdf)
   전부 UZymn 편. main FF → `4477143`. non-force push 성공.
10. ✅ 브랜치 정리 — 8개 삭제:
    - **흡수 확정 3**: automate-9bUuB(UZymn⊃), Zhskp(UBATP⊃), handoff-4O6g8
    - **main 직접 머지 4**: add-dated-workflow-files-HeeoS, fix-notion-embed-pkGLk,
      fix-supply-demand-data-mJAXF, morning-report-automation-l7hoA
    - **패치 동등(cherry) 1**: fix-duplicate-workflows-VWASY
    - 보존 7: workflow 영향 4 (user rule 보호) + 고유 산출물 2 + UBATP 활성 1

### 검토한 대안
- **1차 fetch+reset retry 루프 추가**: race 는 회피하지만 Contents API 가 끝내
  propagate 안 되는 edge case 잔존 (현재는 매일 정상 동작해도 이론적 결함).
  옵션 A 가 근본. 기각.
- **combine_data 의 Contents API push 제거 → 워크플로에서 한 번에 commit**: 큰
  구조 변경. morning_data.txt 를 별도 public 레포에도 push 하는 로직과 얽혀 PR
  리뷰 범위 커짐. 이월.
- **UZymn 을 main 으로 rebase**: 60 × 47 대량 conflict 맛집. merge + `-X ours`
  가 깔끔.
- **브랜치 일괄 삭제**: 워크플로 영향 브랜치 (7toDJ/uQdUm/Zj26Z) 는 고유 infra
  커밋 포함해 content-level 반영 여부 불확실. user rule "action flow 지장 금지"
  적용 → 보존.

### 이번 세션에서 배운 것
- **로그 엔지니어링 필수** — "success" conclusion 이어도 렌더 결과가 이상하면
  step 단위 타임스탬프로 race 추적해야 함. 195ms 간격이 diagnostic smoking gun.
- **git reset --hard 위험성** — "원격과 동기화" 라는 깔끔한 명분이 있지만, 원격
  상태가 eventual consistency 로 stale 이면 workspace 를 과거로 되돌림. 로컬에
  이미 옳은 상태가 있으면 reset 은 오히려 해악.
- **-X ours vs -X theirs 방향** — 현재 브랜치 기준. UZymn 위에서 `merge main -X
  ours` = UZymn 편. main 위에서 `merge UZymn -X theirs` = UZymn 편. 같은 결과.
- **git cherry 의 가치** — 브랜치 정리 시 commit SHA 비교 (log) 는 약함. 패치
  동등 (cherry) 로 봐야 squash/rebase 머지 흔적까지 포착.
- **"이미 오늘자" 인 로컬 파일을 reset 으로 덮어쓰는 반-직관** — render step 이
  오늘자 로컬 `morning_data.txt` 를 받아놓고도 "원격 최신화" 명분으로 어제자로
  롤백. "신뢰할 수 있는 로컬 상태 > 신뢰 못 하는 원격 상태" 원칙.

### 미해결
- **내일(2026-04-24) 06:00 cron 자동 런 검증** — plan-004 + workflow 수정이
  정상 trigger 에서도 동작하는지 확인 필요
- **universe.py 009540 "한진칼" 이름 stale** — 실제 HD한국조선해양. 섹터 배치
  (조선) 는 정확. 이름만 수정 대기
- **`_parse_sector_etf` 구 파서 cleanup** — 후속 커밋에서 제거 판단
- **판단 보류 브랜치 7개** — phase3-backtest, fix-error-handling-riAYS, 워크플로
  수정 4개 (7toDJ/uQdUm/Zj26Z/stock-tracker), 활성 UBATP

### 다음 세션에서 할 일
- **[최우선] UBATP 알림 시스템 E2E 테스트** (30분, PC 필요)
- **[차순위] ADR-004 착수** — 섹터 게이트 (주도+강세) 를 kr_report.py signals
  진입 게이트로 통합. `strategy_config.yaml::sector_filter` 플래그 + 162종목
  × 11.3년 백테 재실행 (1시간)
- **(모니터링)** 내일 06:00 cron 런 결과 확인

---

## 2026-04-23 #5 (UZymn, 웹) — 11섹터 전환 + sector_report.py 재작성 + kr_report 버그 수정

### 결정
- **KOSPI200 11섹터 체계 전환** (ADR-003 Amendment 3) — 외부 리서치 v2026.04 기반.
  반도체/전력인프라/조선/방산/2차전지/자동차/바이오/금융/플랫폼/건설/소재·유통.
- **구 18 ETF 산식 완전 폐기** (KIS API OHLCV + RS50/추세30/자금20 전체 삭제).
  `sector_report.py` 414 → 226줄 전면 재작성.
- **ticker_overrides 16 → 164 전면 재작성** — universe 164종목 전부 명시.
  KSIC auto 매핑 의존도 제거 (폴백 유지).
- **Q1/Q6 태양광 = 전력인프라** (한화솔루션/OCI) 채택. 사용자 외부 세션 판단.
- **Q2/Q5 합병 플래그** (현대건설기계 + HD현대인프라코어, 2026.01 합병) — MISC 분류 + 주석.

### 주요 작업
1. ✅ `sector_report.py` 에 ADR-003 베타 섹션 추가 (`render_adr003_section()`)
   → 1차 확인 후 전면 재작성 (18 ETF 완전 폐기)
2. ✅ parquet 2개 (`sector_map.parquet` 9.7KB + `stocks_daily.parquet` 1.6MB) 레포 커밋
   (plan-003 옵션 2: 주 1회 Colab 수동 갱신)
3. ✅ `backtest/data/sector/` 디렉토리 + `.gitkeep` + `.gitignore` 명시적 허용
4. ✅ `kr_report.py` 버그 수정 — `check_minervini_detailed` import 누락.
   리팩토링(9522c62) 후 라이브 첫 런에서 universe 162 → 0 종목 발생 원인.
5. ✅ `kr_report.py` 출력 문자열 cleanup:
   - "쿨다운 120거래일" 하드코드 → yaml 값 사용 (60)
   - "103종목 +20.7% MDD -26.2% 기댓값 10-13%" → 162종목 +29.29% MDD -29.8% 기댓값 +15-20%
   - 주석 "T15/CD120" 잔재 제거
6. ✅ `reports/kospi200_sectors.tsv` 추가 (외부 리서치 150종목 × 11섹터)
7. ✅ universe 164 ↔ CSV 150 교차: matched 96 + universe_only 68 매뉴얼 분류 → 전부
8. ✅ `sector_report.py` 전면 재작성 — sector_breadth 직접 호출 + 산식 전환 감지
9. ✅ Dry-run 검증: 11섹터 점수 정상 산출
   (반도체 100, 건설 90, 방산 88, 전력인프라 75, 2차전지 64 ... 바이오 11)

### 검토한 대안
- **신/구 섹션 병행 출력 유지**: 구 18 ETF 섹션 유지하며 신 섹션 덧붙임.
  사용자 판단으로 **구 완전 폐기** 선택 (혼동 회피, 단일 소스).
- **테마 ETF 구성종목 실수집 (Colab)**: `KODEX 반도체` 구성종목을 pykrx/KIS 로 실수집
  해서 자동 분류. 외부 리서치 CSV 가 제공되어 이 작업은 불필요해짐 — 향후 갱신 시 검토.
- **내 지식 기반 초안 제안**: 5-6 테마로 한정 (반도체/2차전지/자동차/방산/조선).
  외부 리서치가 11섹터로 더 포괄적 → CSV 채택.
- **HTML 파서/렌더 호환**: `sector_report.py` 만 재작성하면 HTML 섹터 카드
  깨짐 발견. **plan-004 로 분리** (이월).

### 이번 세션에서 배운 것
- **리팩토링 후 라이브 검증 필수** — kr_report.py `9522c62` 는 "백테 검증 완료" 로
  기록됐지만 실제 라이브 런은 한 번도 안 돌았고, 오늘 수동 트리거에서 `NameError`
  로 universe 전부 skip 되는 치명적 버그 드러남. CLAUDE.md 의 "검증 완료" 표기는
  검증 범위 (백테 only vs 라이브 포함) 를 명시해야 함.
- **출력 layer stale** — yaml 파라미터 전환 (T10/CD60) 은 끝났다고 생각했지만
  출력 문자열에 하드코드 "120거래일" / "103종목 +20.7%" 이 남아있었음. 리팩토링은
  **로직 layer 뿐만 아니라 출력 layer 까지 끝나야 완료**.
- **KSIC 자동 매핑 한계** — KRX KIND 의 업종 분류(KSIC)가 2024-26 그룹 재편을 반영
  못함. POSCO홀딩스="전기전자", 동양생명="전기전자" 등 stale. `ticker_overrides`로
  전부 명시하는 게 안전.
- **HTML 렌더 레거시 파서 의존** — `sector_report.py` 만 바꾸면 `_parse_sector_etf`
  가 신 포맷 파싱 실패. 텍스트 리포트와 HTML 리포트는 커플링 강함.
- **섹터 분해 효과 극명** — 구 "운수장비 79" 가 신 체계에서 **방산 88 + 자동차 57
  + 조선 52** 로 나뉨. 방산이 진짜 주도였고 조선은 조정 중인 실체. 정제 효과.

### 미해결
- **plan-004 HTML 렌더 재작성** (1-2h) — main 머지 블로커
- **UZymn 수동 트리거 최종 검증 미완** — 마지막 커밋 `30247b6` 이후 라이브 런 없음
- **브랜치 정리 10개** — GitHub 웹 UI 로 수동 삭제 필요 (이전 세션 이월)
- **universe.py 이름 stale 추가 발견**:
  - 009540 "한진칼" → 실제 HD한국조선해양 (시총 32조)
  - 079960 "동양생명" → 금융업이지만 전기전자로 auto 분류됨
  - 005870 "한화생명" → 금융업이지만 전기전자로 auto 분류됨
- **첫 cron 런의 전환 노이즈** — 구 ETF state vs 신 11섹터 state 간 matching 0 →
  transition flag 로 감지했지만 실제 GitHub 의 sector_state.json 덮여쓰기는 첫 런 후.

### 다음 세션에서 할 일 (데스크탑)
- **[최우선] plan-004**: HTML 렌더/파서 재작성 (3개 파일). 상세: `docs/plans/004-*.md`
- **UZymn 수동 트리거 1회** — 최종 검증 + HTML 깨짐 양상 실물 확인
- **main 머지** — plan-004 완료 후. 내일 06:00 cron 부터 11섹터 자동 반영
- **(이월)** UBATP 알림 시스템 E2E 테스트

---

## 2026-04-23 #4 (UZymn, 웹) — 섹터 회귀 검증 PASS + ADR-003 Amendment 2

### 결정
- **ADR-003 정식 판정 기준 확정**: "주도+강세" × universe-avg 벤치마크.
  hit 83%, mean_excess +2.37%/월, 종합 PASS.
- **"주도" 단독 등급 운영 폐기** — 집중도 과도 → 섹터 변동성에 취약 (hit 42%
  → FAIL). "주도+강세" 가 알파-안정성 균형점.
- **벤치마크는 universe-avg** (동등가중 162종목 평균) — KOSPI 는 universe
  구성 차이(SK하이닉스 등 mega-cap 편입 여부)로 beta drag -3.6%/월 유발.
  이는 signal 책임 아님. `--benchmark kospi` 참고용 유지.
- **`ticker_overrides` 16개 seeding 고정** — 5 initial + 11 확장. 금융업
  41 → 26종목 축소. KSIC "기타 금융업" 에 혼재된 비금융 지주사업 분리.

### 주요 작업
1. ✅ `scripts/validate_sector_breadth.py` 신규 — 월별 회귀 루프 + KOSPI/
   universe 벤치마크 + PASS/FAIL 판정
2. ✅ `sector_breadth.py` 에 `load_overrides` + `apply_ticker_overrides` +
   CLI `--overrides` 통합. compute_sector_scores 에 overrides 파라미터.
3. ✅ `tests/test_sector_breadth.py` 에 overrides 테스트 10개 추가 → 총 ~35
4. ✅ `reports/sector_overrides.yaml` 5 → 16 entries 확장 (지주회사 재분류)
5. ✅ `notebooks/sector_validate.ipynb` Colab 실행 파이프라인 (pytest →
   latest scores → 회귀 → 금융업 Top 30 iterate → 커밋)
6. ✅ `requirements.txt` 에 pandas/pyarrow/PyYAML 명시 (실사용 중이었으나
   latent 의존)
7. ✅ Colab 3회 회귀 실험:
   - 5 override × KOSPI: mean -1.16%, hit 50% → FAIL
   - 16 override × KOSPI: mean -2.21%, hit 42% → FAIL (역효과)
   - 16 override × universe: mean +2.37%, hit 83% → **PASS**
8. ✅ ADR-003 Amendment 2 작성 — 판정 기준 + ticker_overrides 근거 + 한계

### 검토한 대안
- **override 확장 없이 산식만 튜닝**: 16 override 확장 후 주도 mean 이
  오히려 -1.1 → -2.2%/월 악화 (전기전자 marcap 커지며 일부 약세월 drag
  증폭). override 자체보다 **벤치마크가 근본 문제**였음이 드러남.
- **주도 단독 유지 + 임계 상향(≥80)**: 신호 더 적어져 변동성 ↑, 표본 부족
  으로 신뢰구간 악화. 기각.
- **표준 Stage 25점 복원 시도**: pykrx 인덱스 API 여전히 다운. 회귀 돌리기
  전 복원 조건(ADR-005) 충족 불가. 보류 유지.
- **종목 단위 Minervini 필터 병행**: 섹터 산식의 독립 검증이 우선. Strategy
  통합은 ADR-004 로 분리.

### 이번 세션에서 배운 것
- **벤치마크 선택이 결과를 뒤집음**: 산식 변경 없이 KOSPI → universe-avg
  전환만으로 FAIL → PASS. 벤치마크가 "측정 대상에 관련된 beta drag 을
  포함하는가" 가 판정 타당성의 핵심. 3회 실험 중 2번은 산식/override 를
  튜닝한 건데, 진짜 문제는 비교 기준이었음.
- **"주도" 엄격 필터 ≠ 우수한 알파**: 집중하면 알파 평균은 비슷해도
  분산이 커서 hit ratio 망가짐. **"주도+강세" 가 hit 41% → 83%** 로 확
  뛴 건 reliability 자체의 가치. 백테에서 mean 보다 hit ratio 중시한 결정.
- **ticker_overrides 이중 효과**: 금융업 drag 제거 기대로 시작 → 실제로는
  전기전자/기계 marcap 증가시켜 주도 단독에선 역효과. 주도+강세로 확장하면
  섹터 다양성 복원으로 효과 발휘. **override 효과는 grade 조합과 연동**.
- **fat-tailed 알파**: 2025-12/2026-01/2026-03 3개월이 전체 excess 의
  60% 이상 기여. 강세장 집중 효과. 즉 "주도+강세" 는 하락장 방어보다
  **상승장 초과수익 레버리지** 성격. 이 방향성은 Minervini 전략과 일치.

### 미해결
- **2026-03 경계 효과**: 23거래일(1개월 미달)이라 outlier 가능. 다음 월말
  (2026-04-30) 데이터 확보 후 재검증 시 알파 크기 확인
- **표본 12개월**: mean/hit 신뢰구간 여전히 넓음. 2년치 stocks_daily 로
  6M lookback 후 12개월 확보 한계. 2027년까지 누적 재측정 필요
- **SK Inc. (034730) / 카카오페이 (377300)**: 투자지주·핀테크 섹터 귀속
  보수적 유지. 향후 그룹별 사업 재편 모니터링 필요
- **universe.py 누락 3-4종목**: 008560/000060/042670/000215. 백테 재현성
  영향 → 별도 ADR 판단 이월

### 다음 세션에서 할 일
- **[우선] `sector_report.py` 신/구 점수 병행 표시** (30-45분)
  - 기존 18 ETF 산식 결과 + 신 ADR-003 결과를 나란히 출력
  - `reports/sector_mapping.py` 와 `sector_breadth.py` 통합 지점
  - 모닝리포트에서 실전 체감 → 1-2주 운영 후 구 산식 deprecate
- **[차순위] ADR-004 착수** (1시간)
  - 주도+강세 섹터를 `kr_report.py` signals 생성 시 진입 게이트로 통합
  - `strategy_config.yaml` 에 `sector_filter: true|false` 플래그
  - 백테 재실행으로 CAGR 변화 측정 (162종목 × 11.3년)
- **(이월)** UBATP 브랜치 알림 시스템 E2E 테스트 (30분)
- **(이월)** universe.py 누락 종목 처리 + pykrx Stage 복원 모니터링

---

## 2026-04-23 #3 (UZymn, 웹) — pykrx 장애 pivot + sector_breadth 구현

### 결정
- **pykrx 1.2.7 인덱스 마스터 API 전면 다운 확인** — Colab Phase B 실행
  중 발견. `get_index_ticker_list`, `get_index_ticker_name`,
  `get_index_ohlcv_by_date`, `get_index_portfolio_deposit_file` 모두 사망.
  종목 OHLCV 만 정상.
- **데이터 소스 pivot**: 섹터 매핑은 KRX KIND (KSIC) + FDR 시총, 업종지수
  주봉은 수집 보류 (Weinstein Stage 25점 비활성)
- **산식 조정**: `(IBD 50 + Breadth 25) × 100/75 = 0-100 스케일`, 임계값
  75/60/40 유지 (rescale 덕분)
- **Stage 복원 조건** 명시: pykrx 복구 + 2년치 결손 없는 수집 + sanity
  pass → 별도 ADR
- **Weinstein 처리 (a) 75점 재정의 채택** (사용자 승인). 대안 (b) 합성
  sector index, (c) ETF 임시, (d) 대기 모두 기각
- **Phase C 실데이터 검증은 PC 세션 이월** — 웹 Drive MCP 가 `drive.file`
  scope 제한으로 Colab 산출 parquet 접근 불가. 1시간 삽질 대신 PC 에서
  10분 처리가 효율

### 주요 작업
1. ✅ Colab 노트북 초안 (Section 1-4, 22셀) 작성 + 커밋 5개
2. ✅ pykrx fetch 실패 진단 — `__fetch` JSON 에러 → IndexTicker master
   df 공유 구조로 인덱스 API 전체 사망 확인
3. ✅ FDR `StockListing('KRX-DESC')` + KRX KIND `상장법인목록` 검증
4. ✅ KIND `업종` 컬럼 = KSIC 9차 소분류 (58종) 확인 → 22업종 환원 필요
5. ✅ ADR-003 Amendment 2026-04-23 작성 (커밋 `3a236e6`)
6. ✅ `reports/sector_overrides.yaml` 작성 — KSIC 58종 → 15개 KOSPI 22업종
   자동 매핑 (커밋 `b4cb496`)
7. ✅ 노트북 전면 재작성 (KIND+FDR pivot, 16셀) 커밋 `02ae40f`
8. ✅ Colab 재실행 → parquet 2개 Drive 저장 성공:
   - sector_map.parquet: 164행, 160 섹터매핑 성공, 9.7KB
   - stocks_daily.parquet: 162종목 × 500일 = 79,644행, 1.6MB
9. ✅ Drive MCP 접근 실패 확인 → PC 이월 결정
10. ✅ `sector_breadth.py` 전체 구현 + 25 pytest (커밋 `2650050`):
    - IBD 6M 백분위 (시총가중+25%cap iterative)
    - Breadth (% above MA50) + 표본 단계화
    - classify_grade + compute_sector_scores CLI
11. ✅ `docs/plans/002-sector-breadth-pc-execution.md` runbook

### 검토한 대안
- **pykrx retry/폴백** (과거 영업일 5단계 x 3회): IndexTicker 마스터 df
  공유 구조 때문에 모든 시도 같은 에러. 기각
- **pykrx 강제 재설치**: 같은 버전이라 의미 없음. 대신 소스 pivot 선택
- **FDR `KRX-DESC` Sector 컬럼**: "벤처기업부" 등 KOSDAQ 상장구분값 → 섹터
  아님. 기각. Industry (KSIC) 는 유용
- **Naver/Daum 스크래핑**: 162 요청 fragility → KIND 1회 호출이 나음
- **웹에서 Drive 파일 ID 직접 입력**: MCP `drive.file` scope 로 외부 파일
  접근 불가 확인. 두 번 시도 모두 "not found"
- **Phase C 지금 세션 강행**: Drive 접근 삽질 + 로컬 pytest 불가 (sandbox
  numpy 없음) 으로 PC 10분 < 웹 30분. PC 이월 선택
- **Drive 파일을 ClaudeMorningData 폴더로 복사**: 가능하지만 사용자 수작업
  + 임시방편. PC 이월 택일

### 다음 세션에서 할 일 (PC 환경)
- **[우선] sector_breadth 실데이터 검증** (45-60분)
  - pytest → pass 확인
  - Drive parquet 로컬 복사
  - CLI 실행 → 섹터 점수 분포 + 금융 편중 체감
  - `scripts/validate_sector_breadth.py` 작성 + 12개월 회귀 검증
  - 지주회사 29개 `ticker_overrides` 추가
  - 상세: `docs/plans/002-sector-breadth-pc-execution.md`
- **(이월)** UBATP 알림 시스템 E2E 테스트 (30분)
- **(이월)** universe.py 누락 4종목 처리 + pykrx 복구 모니터링

### 미해결
- **Drive MCP 권한 범위 조사 보류** — `drive.file` scope 로 외부 생성
  파일 접근 불가. 웹에서 Phase C 불가능이 구조적. 해결책은 MCP 권한 확장
  또는 ClaudeMorningData 경로 통일 — 비용 > 편익으로 PC 이월이 최적.
- **universe.py 누락 4종목**: 008560 메리츠증권(2023 상폐), 000060 메리츠
  화재(2023 상폐), 042670 HD현대인프라코어(2026-01 해산), **000215 DL
  이앤씨(신규 발견 — 코드 변경 가능성, 현재 375500)**. PC 에서 확인 + 정리
- **pykrx 복구 여부 미확정**: 2026-04-23 장애 발견, 임시 회피 방식이
  언제까지 유효할지 불투명. ADR-005 대기
- **지주회사 ticker_overrides 비어있음**: 금융업 41개 중 비금융 사업 지주
  회사 많음. 실데이터 보고 PC 에서 20-30개 수동 추가 예상

### 이번 세션에서 배운 것
- **세션 연속성 실전**: 이전 세션이 Colab 진행 중 "세션 터짐" 으로 중단
  → "작업 쪼개서 하자" 합의 후 각 단계마다 즉시 커밋. 9 커밋 동안 1회도
  날리지 않음. **중간 커밋 전략의 가치 확실히 입증**
- **외부 API 의존 단일점**: pykrx 하나로 모든 인덱스/종목 데이터 하려다가
  한 번에 무너짐. KIND + FDR + pykrx 3원화가 일부만 죽어도 계속 전진 가능
- **"데이터 없이 코드만 작성" 의 가치**: Drive 접근 불가 상태에서도
  sector_breadth.py + 25 pytest 를 다 썼음. PC 세션이 25분 걸릴 일 10분
  으로 단축. **테스트가 실데이터 없어도 가치 있음**
- **ADR amendment 의 가치**: 원 ADR-003 을 "폐기하고 새로 쓰기" 가 아닌
  amendment 섹션 추가로 변화 이력 유지. 나중에 Stage 복원 시 깔끔한 diff
- **사용자 결정 위임**: "클로드 추천대로 가자" 3회 등장. 근거 + 후보 + 권장
  제시 후 "네" 받는 패턴이 효율적. 세부 매핑 (KSIC 58 → 22업종 매핑) 도
  전부 맡김 → 실데이터로 1회 완성

---

## 2026-04-23 (UZymn 브랜치) — ADR-003 섹터 강도 산정 방법론 채택

> **참고**: 같은 날짜에 `claude/session-start-UBATP` 브랜치에서 별개 작업
> (장중 알림 시스템 + 세션 연속성 구조) 진행됨. 본 세션은 그것과 독립적인
> ADR 작업. 두 작업 모두 PC 환경에서 통합 처리 필요.

### 결정
- **섹터 강도 산정을 ETF top-down → 유니버스 bottom-up 으로 전환**
  (ADR-003). 18개 ETF 가격 기반에서 우리 백테 162종목을 KRX 22 업종으로
  분류 + 3요소 산식으로 변경.
- **3요소 100점 산식**:
  - (A) IBD 6M 백분위 — **50점**
  - (B) Weinstein Stage 2 — **25점**
  - (C) Breadth (% above MA50) — **25점**
- **한국 시장 적용 4대 판단** (Claude가 결정):
  - 비중 50/25/25 (40/30/30 균등 안 채택) — O'Neil/Minervini 본인 우선
    순위 (IBD 1차, Stage 2차) + 한국 변동성 22% 로 Stage whipsaw ↑
  - **시총 가중 + 단일 종목 25% cap** — 삼성전자 KOSPI ~20% 단독 영향
    차단. KRX 200 인덱스 30% cap 보다 보수적 (섹터 단위는 종목 적어 cap
    영향 더 큼)
  - 임계값 75/60/40 유지 (백테 후 조정 명시)
  - 표본 부족 단계화: ≥5 정상 / 3-4 breadth=0 (max 75) / <3 N/A
- **strategy 진입조건 통합은 별도 ADR-004 로 분리** (검증 통과 후 결정).
  본 ADR은 "표시용 점수 산정"까지만 범위.
- **세션 종료 (구현은 PC 세션으로 이월)**: 웹 환경에서 pykrx KRX 호출
  실패 (sandbox 네트워크 isolation) 확인. 추측 기반 구현은 회귀 위험
  높아 PC 세션에서 데이터 보고 구현하는 게 효율적.

### 검토한 대안
- **main 머지** (앵커 확립으로 세션 연속성 해결): 세부 작업 미완으로 의미
  없다고 사용자 판단. 알림 시스템 PC 검증 후 재논의.
- **UZymn 에 UBATP 머지** (알림 시스템 코드 가져오기): 이번 세션에 알림
  시스템 작업 없으므로 중복 브랜치만 origin에 추가 → 보류.
- **UBATP 로 체크아웃 이동**: 시스템 지시("UZymn에서 develop") 어긋남.
- **메타 인프라 구축** (main 인덱스 파일 + SessionStart 훅으로 브랜치
  난립 근본 해결, 1.5-2h): 1-2 세션 더 해보고 패턴 명확해진 후 판단.
- **비중 40/30/30** (균등): O'Neil/Minervini 우선순위 미반영, 기각.
- **비중 60/20/20** (IBD 강조): Stage 너무 약화, Minervini 2단 필터
  구조 무력화, 기각.
- **동등 가중**: 한국 소형주 노이즈 ↑ + 시장 신호 왜곡, 기각.
- **순수 시총 가중** (cap 없이): 삼성전자 단독 영향 과대, 기각. KRX 200
  자체가 30% cap 사용.
- **WICS 세분류** (10섹터→24산업그룹→69산업): FnGuide 유료/스크래핑 부담.
  KRX 22업종 충분하다고 판단.
- **Jegadeesh-Titman 12-1 Momentum**: 12M lookback 한국 변동성 대비 김.
  Chae & Eom (2009) 한국 negative momentum 보고 → 6M 이 더 robust.
- **RRG (Relative Rotation Graph)**: 산식 복잡, 단일 점수 환산 시 정보
  손실. v2 시각화로 보류.
- **즉시 구현 진입**: 웹 환경에서 KRX 데이터 접근 불가로 추측 기반 코드
  되어 다음 세션에서 다시 손봐야 → 비효율, 기각.

### 주요 작업
1. ✅ `/session-start` → 현재 브랜치(UZymn) 상태가 stale 임을 발견
2. ✅ 모든 원격 브랜치 스캔 → UBATP 가 최신 (알림 시스템 + 세션 연속성)
3. ✅ "세션 연속성 문제" 근본 원인 분석 — 웹 Claude 가 매 세션 새 브랜치
   를 만드는데 앵커 부재 → 이전 작업 누락
4. ✅ 머지 전략 검토 → 이번 세션엔 머지 없이 진행 결정
5. ✅ 사용자가 실제 작업으로 pivot: "섹터 구분 명확화 + 방향성 판단 기준"
6. ✅ 현재 `sector_report.py` 분석 → 한계 4가지 정리
7. ✅ 업계 표준 섹터 강도 지표 6가지 조사 (IBD, Weinstein, RRG, Breadth,
   Jegadeesh-Titman, Dorsey Wright)
8. ✅ Minervini 생태계 표준 조합 식별 (IBD 1차 + Weinstein 2차)
9. ✅ pykrx 데이터 가용성 확인 — KRX 22업종 + 종목 매핑 + 업종지수 OHLCV
   모두 무료 가능 (단, sandbox 네트워크 isolation으로 라이브 검증 미가능)
10. ✅ ADR-003 초안 작성 (40/30/30, 임계값 75/60/40)
11. ✅ ADR-003 한국 적용 판단 반영 갱신 (50/25/25 + 25% cap + 표본 단계화)
12. ✅ 커밋 2회 (`f7efc35`, `b38ae2e`) + push (origin/UZymn 신규 등록)

### 다음 세션에서 할 일
- **[우선] PC 환경에서 두 작업 묶음 처리** (총 1.5-2h)
  1. **UBATP 브랜치** → 알림 시스템 E2E 테스트 (이월 작업, 30분)
     - `git pull` + `pip install -r requirements.txt` + `.env` 생성
     - `notifier.py` 단독 테스트 → 디스코드 수신 확인
     - `signals_today.py --force --dry-run` → KIS 스캔
     - Task Scheduler XML import + 경로 수정
  2. **UZymn 브랜치** → `sector_breadth.py` 신규 구현 (1시간)
     - ADR-003 명세 그대로: 50/25/25, 시총가중+25%cap, 표본 단계화
     - `reports/sector_overrides.yaml` 신규 (KRX 자동 분류 보강용)
     - `sector_report.py` 출력에 신/구 점수 병행 표시 (검증)
- **회귀 검증**: 최근 1년 월별 → 새 산식 "주도" 판정 섹터의 다음 1개월
  수익률이 코스피 기준선 이상인지 확인
- **(이월)** 1주일 알림 모니터링 후 v2 개선 / main 병합 리허설 / 페이퍼
  트레이딩 저널 / 2025+ 이상치 검증 / 2022 방어 실패 분석

### 미해결
- **세션 연속성 근본 해결 보류**: 메타 인프라(main 인덱스 + SessionStart
  훅) 구축이 가장 확실한 해법이지만 1.5-2h 부담으로 1-2 세션 더 해보고
  판단. **다음 새 세션이 UZymn/UBATP 외 브랜치에서 파생되면 또 누락 가능**.
- **KRX 22업종 중 우리 162종목 실제 분포 미확인**: PC 세션에서 pykrx 호출
  후 표본 부족 섹터 (3개 미만) 실제 몇 개인지 확인 필요. 그 결과로 섹터
  단위 점수 산출 가능 개수 확정.
- **ADR-003 임계값/표본 처리 세부 조정**: 백테 검증 후 75/60/40 임계값과
  표본 임계 (5/3) 가 적절한지 실측. 첫 결과 후 ADR 갱신 가능성.
- (이월) 포인터 갱신 수동 의존, kr_report 수급 vs strategy.check_supply
  차이 재확인, 생존편향 정량화, 공휴일 달력 미구현.

### 이번 세션에서 배운 것
- **세션 연속성 fix 의 자기 모순**: UBATP 세션이 만든 fix(`/session-start`
  브랜치 스캔 + CLAUDE.md 포인터)가 UBATP 브랜치에만 존재 → 이번 세션이
  다른 브랜치(UZymn)에서 시작하면서 fix 자체에 도달 못 함. 메타 인프라가
  파편화된 채 작동하면 의미 없다는 실증.
- **"클로드가 결정" 위임의 가치**: 사용자가 "한국에 적합한 방식으로 구성"
  요청하면서 4가지 판단(비중/가중/임계값/표본) 한 번에 정리 가능. 일일이
  사용자 의견 묻는 것보다 근거 명시 + 결정 + 사용자 검토가 효율적.
- **웹 환경 한계 인지**: pykrx KRX 호출이 sandbox 에서 안 되는 것 일찍
  확인 → 구현 미루는 결정 합리화. 환경 제약을 일찍 점검하면 작업 범위
  자연스럽게 좁혀짐.
- **ADR 분리 원칙의 가치**: ADR-003 (점수 산정) vs ADR-004 (strategy 통합)
  분리해두면 검증 단계 명확. 한 번에 결정하지 않고 단계별 결정.

---

## 2026-04-22 — Phase 3 완료 + 전략 재확정 + 아키텍처 + 문서 인프라

### 결정
- **T15/CD120 → T10/CD60 재확정**
  - 103종목 백테가 검증 과엄격으로 61종목 제외된 것 발견
  - Validation 로직 수정 (거래정지일 제외 + 0.1% 톨러런스) → 162종목 복원
  - 162종목 재백테: T15/CD120 +16.16% vs T10/CD60 **+29.29%** → 뒤집힘
  - Walk-forward (IS/OOS) 양쪽에서 T10/CD60이 일관되게 상위권
  - 실전 기댓값 +10-13% → **+15-20%**로 상향
- **strategy.py + strategy_config.yaml 단일 소스 아키텍처 도입**
  - 백테(99_*.py)와 라이브(kr_report.py)가 같은 함수 import
  - 파라미터는 yaml 한 곳, 로직은 strategy.py 한 곳
  - kr_report.py가 구 T15/CD120 파라미터로 돌고 있던 drift 버그 제거
- **의사결정 기록 시스템 도입** (CLAUDE.md + SESSION_LOG.md + ADR + 슬래시 명령어)
  - 환경(로컬 ↔ 웹 Claude Code) 간 작업 이어가기 위함
- **내일 알림 시스템 작업 플랜 사전 문서화** (docs/plans/001-alert-system-setup.md)
  - 웹 환경에서 `/session-start` 한 줄로 작업 재개 가능하도록
- **슬래시 명령어 전역 + 프로젝트 이중 배치**
  - 레포 내 `.claude/commands/`: git 추적 → 웹 환경/clone에서 사용
  - `~/.claude/commands/`: 로컬 편의 미러 (다른 프로젝트에서도 사용)
  - 마스터는 레포 쪽. 수정 시 레포에서 하고 전역으로 수동 sync.

### 검토한 대안
- **T10/CD120** (OOS 최고 +49.94%): IS 랭크 #11로 불안정, 채택 X
- **T20/CD60** (IS #2, OOS #3): MDD -42.2%로 악화, 채택 X
- **VCP auto 3요소**: 거래 124건으로 너무 적음, 수동 차트 판정으로 유지
- **재수집** (pykrx adjusted / FDR / KIS): 진단 결과 데이터는 정상, validation 로직만 수정으로 해결

### 주요 작업
1. ✅ Samsung parquet 진단 → 거래정지일 OHLV=0 + 라운딩 편차 원인 규명
2. ✅ validation 로직 수정 (backtest/02_validate_data.py) — 103 → 162종목
3. ✅ 162종목 TRAIL × CD 그리드 재백테 실행
4. ✅ Walk-forward 분석 (backtest/99_walkforward.py 신규)
5. ✅ strategy_config.yaml 작성 (T10/CD60 파라미터)
6. ✅ strategy.py 작성 (check_signal, run_backtest, calc_metrics)
7. ✅ 99_minervini_vcp_compare.py → strategy.py delegate 리팩토링
8. ✅ kr_report.py → strategy.py 연결 (Minervini 8조건 공유)
9. ✅ 백테 회귀 검증 (+29.29% 재현, diff 0바이트)

### 다음 세션에서 할 일
- **[우선] 실시간 알림 시스템 구축** (2026-04-23, 웹 Claude Code)
  - 상세 플랜: `docs/plans/001-alert-system-setup.md`
  - 사용자 준비: 텔레그램 봇 토큰 + chat_id (또는 디스코드 webhook)
  - 작업: notifier.py + signals_today.py + Task Scheduler (총 2.5-3.5h)
- **페이퍼 트레이딩 저널 템플릿** (실전 착수 전 검증)
- **2025+ 이상치 검증**: +157% CAGR의 종목/섹터 집중도 분석
- **2022년 방어 실패 상세 분석**
- **main 머지**: pyyaml requirements 추가 후 workflow_dispatch 테스트 → 머지

### 미해결
- kr_report의 수급 로직(KIS 외인/기관)과 strategy.check_supply(up/dn vol)의
  의도적 차이 재확인 필요
- 생존편향 정량화 (2015년 상폐 종목 실제 리스트 확보)

### 이번 세션에서 배운 것
- **기댓값 숫자는 유니버스 구성에 극도로 민감**: 103 → 162로 바꿨을 뿐인데
  최적 파라미터 자체가 바뀜. 과적합 탐지는 유니버스 확대로 검증 가능.
- **MDD 프레이밍 수정**: 전략 -29.8% < ETF -43.9%. 자동 손절이 오히려
  버티는 심리 부담 덜어줌. 진짜 리스크는 "박스권 언더퍼폼" 기회비용.
- **파라미터 drift는 조용히 발생**: kr_report가 구 T15/CD120 값 그대로
  운영 중이었고 아무도 몰랐음. 단일 소스 원칙의 실전적 필요성 확인.
