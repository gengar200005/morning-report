# ADR-008: Scrap Section 04 Entry Candidates — Trend Watch 단일 섹션 복귀

- Status: **Accepted**
- Date: 2026-04-25
- Context session: 2026-04-25 (session-start-nueAo)
- Accepted: 2026-04-25 by 마스터 승인 ("1번 관련 section 4 폐기")
- Supersedes: 2026-04-24 #2 Entry Candidates 섹션 신설 (commit `bdcd4fc`)
- Related: ADR-005 (entry-timing 실증), CLAUDE Project Instruction v3.6 → v3.7

## 1. 배경

2026-04-24 #2 세션에서 A등급 중 `is_new=True` 만 모아 Section 04 "Entry
Candidates" 를 신설했다. 명분은 "백테 `entry: open_next_day` 규칙과 일치하는
유일한 실전 매수 후보군" 이었다.

ADR-005 가 이 명분을 실증 **반증**했다:

- baseline 트레이드 333건 중 signal_age=1일 진입은 **19.5%** 뿐. 나머지
  80.5% 는 "extended" 상태에서 선정됨.
- median signal_age = **6일**, mean 9.7일, p75 13일, p90 23일.
- `signal_days ≤ 1` 필터는 CAGR -10.8%p (백테 -4.3%p @ ≤10 까지 전부 하회).
- 알파 분해: **필터(수급+RS≥70) +25.8%p + 체결타이밍 +6.7%p**. "fresh
  신호일만" 은 백테 규칙도, 실전 운용 원칙도 아니다.

결국 Section 04 는 **실제 전략의 1/5 슬라이스만 강조** 해서 사용자를 오도할
위험이 있다. "🆕 첫날만 매수" 라는 잘못된 해석을 유도하고, 남은 80% 슬라이스는
Section 05 Trend Watch 로 밀려 "진입 후보 아님" 으로 오해되기 쉽다.

## 2. 옵션

활성 작업 목록 (CLAUDE.md 기준) 에서 세 안을 검토:

- **(A) 재설계** — "Top 5 RS 순 분산, 빈 슬롯만큼" 으로 의미 재정의. 단점:
  실전 매매 규약을 템플릿에 중복 인코딩. Trend Watch 가 이미 RS 순 Top 5.
- **(B) 문구 정정** — "🆕 우선순위만 강조, 매수는 Top 5 전체" 로 유지. 단점:
  한 섹션 안에 "팩트 테이블 (🆕 only)" + "진입 규칙 (Top 5 전체)" 두 의미가
  섞임. 시각적 강조 (초록 좌측 바, 최상위 배치) 가 계속 🆕 쪽으로만 쏠림.
- **(C) Section 04 폐기** — Trend Watch (구 Section 05) 를 Section 04 로
  승격. 🆕 뱃지는 Trend Watch row 와 Remaining 표 안에서 **힌트** 로만
  유지 (정보 자체는 여전히 유용, single-section 안에 단일 분포로 통합).

## 3. 결정

**Option (C) 채택** — Section 04 Entry Candidates 폐기, Trend Watch 를
Section 04 (Grade A · Top 5) 로 복귀.

### 이유

1. **ADR-005 의 실증 결과와 일관** — median 6일 분포 하에서 "🆕 = 매수 후보
   군" 임을 정당화할 데이터가 없음. 섹션 수준 강조는 실제 확률 분포를
   왜곡한다.
2. **실전 매매 규약과 일관** (CLAUDE.md) — "Top 5 RS 순 → 빈 슬롯만큼 균등
   가중" 이지 "🆕 만 매수" 아님.
3. **정보 손실 없음** — `is_new` 플래그는 parser 에서 계속 생산되고, Trend
   Watch row 의 종목명 옆에 🆕 신규 뱃지 + Remaining 표의 Signal 컬럼 🆕
   로 표시됨. "언제부터 A등급이냐" 라는 맥락 정보는 제공되지만, 섹션 수준의
   시각적 강조는 제거.
4. **템플릿·데이터 파이프 간소화** — `data.new_a_entries` 파생 삭제,
   `.entry-candidates` CSS 블록 삭제. 섹션 번호 재조정 (05→04, 06→05,
   07→06, 08→07).

### 불채택 이유

- (A) 는 실전 매매 규약 (자연어 규칙) 을 템플릿에 재인코딩해서 Trend Watch
  와 중복만 만듬.
- (B) 는 한 섹션에 두 의미를 섞어 시각적 혼란을 남김. 사용자는 초록 강조
  바를 보면 여전히 "🆕 우선" 으로 해석.

## 4. 실행

### 4.1 코드 변경

- `reports/templates/v6.2_template.html.j2`:
  - `.entry-candidates` CSS 블록 제거 (padding/background/border-left)
  - `<!-- SECTION 04: ENTRY CANDIDATES -->` 블록 전체 제거 (~50 줄)
  - Trend Watch 승격: `<div class="section-num">05</div>` → `04`
  - A-Remaining 재번호: `05·b` → `04·b`
  - Portfolio / Macro Calendar / Market Context: 06/07/08 → 05/06/07
- `reports/render_report.py`:
  - `data["new_a_entries"] = [s for s in grade_a_sorted if s.get("is_new")]`
    제거.
- `reports/parsers/morning_data_parser.py`: **무변경**. `is_new` 필드는
  Trend Watch row 뱃지 표시에 그대로 사용.
- `tests/test_parser.py`: **무변경**. parser 측 `is_new` 계약 보존.

### 4.2 Claude Project Instruction 갱신 (v3.6 → v3.7)

- 헤더 banner 에 v3.7 근거 (ADR-008) 명시.
- 진입 게이트 #1 의 "v3.6 지표 3개" 중 `data.new_a_entries` 참조 조건 삭제.
  parser `(\d+일|🆕)` 얼터네이션은 유지 (뱃지 파싱용).
- 진입 게이트 #4 "신규 A등급 인식" 재작성: `is_new` 는 Trend Watch row 뱃지
  힌트용. "별도 매수 후보군" 프레이밍 제거.
- Step 4 claude_analysis 키 테이블: §05 Top5 Trend Watch → **§04 Top5 Trend
  Watch**, §05·b → §04·b, §06/07 → §05/06. §04 Entry Candidates 관련 문단
  전체 삭제.
- ALERT 10 재작성: `🆕 A등급 {N}종목 — §04 Trend Watch Top 5 상단 표시,
  단 median signal_age=6일이므로 "첫날 = 매수" 의미 아님` 로 톤 다운 (또는
  항목 삭제).
- "절대 금지" v3.6 항목 3개 삭제:
  - §04 Entry Candidates claude_analysis 삽입 금지
  - `data.new_a_entries` 재가공 금지
  - 🆕 신규 A등급을 Top5 Trend Watch 코멘트에 혼입 금지 (v3.7 에서는 오히려
    허용 — 단일 섹션이므로 entry 카드에서 "🆕 N종목 포함" 언급 가능)
- 자체 체크리스트 v3.6 항목 3개 (`data.new_a_entries` / §04 / §05 검사) 삭제.

### 4.3 CLAUDE.md

- "활성 작업 > 다음 진입점 1️⃣" (Entry Candidates 설명 텍스트 정정) 제거.
- 2️⃣ (박스권 조건부 섹터 게이트) 를 1️⃣ 로 승격.
- "최근 주요 결정" 에 ADR-008 한 줄 추가.
- "최근 세션" 에 2026-04-25 항목 추가.

## 5. 영향 / 검증

### 5.1 리포트 가시성

- Section 04 헤드라인이 "Entry Candidates · N" (N 가변) 에서 "Grade A ·
  Top 5" (고정) 로 바뀜. 레이아웃은 Top 5 readiness 카드 5장 + Remaining
  표 로 단순화.
- 🆕 뱃지는 Top 5 카드 제목줄과 Remaining 표 Signal 컬럼에 유지.

### 5.2 PDF 분량

- Entry Candidates 0 종목인 날도 빈 섹션 한 장을 할당하고 있었음 → 제거로
  PDF 한 페이지 줄 가능 (특히 Remaining 이 많은 날).

### 5.3 백테·전략 불변

- 이번 변경은 **리포트 표시 계층 전용**. `strategy.py` / `strategy_config.yaml`
  / 백테 CAGR +29.55% 전부 영향 없음.

### 5.4 회귀 리스크

- 낮음. 템플릿 변수 `data.new_a_entries` 를 참조하는 코드는 템플릿 1곳 +
  render_report 파생 1곳 뿐이었고 둘 다 동시 제거. 다른 참조 grep 결과 0건
  (parser·test·sector 모듈 전부 `is_new` 필드만 사용).

## 6. 후속 과제

- 다음 06:00 KST cron 실행 후 `docs/latest.html` 과 `docs/archive/` 신규
  PDF 에서 Section 04 가 Trend Watch 로 표시되는지 확인. Notion 페이지도
  마찬가지.
- Claude Project Files 재업로드: **v3.7 필수 2개** — `v6_2_template_html.j2`,
  `render_report.py`. parser 는 무변경이므로 재업로드 불필요.
