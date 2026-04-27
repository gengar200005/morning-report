# morning-report

<!-- Last session branch: claude/json-to-pdf-workflow-7yk63 (2026-04-27) -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-27)

**Phase 4 실전 준비 — 알파 추구 1차 종료, 페이퍼 트레이딩 단계 진입 임박**.
전략 T10/CD60 확정 유지. baseline PDF 자동 운영. 추가 알파 후보 4번 연속 기각
패턴 (ADR-005 / ADR-004 / ADR-001 / ADR-010) 확정. 다음 단계 = 실전 검증 (페이퍼
트레이딩).

**운영 (투트랙 확정)**:
- **트랙 1 (baseline)**: 매일 06:25 KST `morning.yml` cron → 데이터 수집 → HTML
  → PDF → Drive 업로드 → Notion publish. 마스터 손 0.
- **트랙 2 (Claude 카드, PC 있을 때만)**: PC 에서 `docs/claude_analysis/YYYYMMDD.json`
  push → `claude_render.yml` 자동 트리거 → 7카드 주입 PDF 재발행. 모바일 GitHub
  업로드는 안 됨 (마스터 시도 결과). PC 없는 날은 트랙 1 만 작동.

**오늘 (2026-04-27) 핵심 작업**:
- **morning.yml race condition fix** (PR #25 → main `82285d3`). 04-27 에 cron-job.org
  + 추가 트리거로 morning.yml 이 3회 실행되면서 claude_render 가 만든 카드 PDF
  를 baseline 으로 덮어쓴 사고 fix. `morning.yml` line 88 직전에 "오늘자 JSON
  존재 시 `--claude-analysis` 자동 주입" 분기 추가. 이후 morning.yml 재실행해도
  카드 보존.
- **04-27 카드 PDF 복구**: `claude_render.yml` workflow_dispatch (date=20260427)
  수동 실행 → main `b4ba508`. repo + Drive + Notion 모두 카드 PDF 로 갱신.
- **`.crdownload` 임시파일 정리** (Chrome 다운로드 미완 파일이 같이 업로드됐던 것).

**확정 전략**: T10/CD60 (Trail 10% / Cooldown 60거래일)
- 백테 CAGR **+29.55%** (11.3년, 162종목), MDD -29.83%
- 실전 기댓값 +15-20% (생존편향/슬리피지/세금 차감 후)
- 진입 규칙: `check_signal=True` 인 모든 A등급 종목 RS 순 top-5 (streak 무관,
  median signal_age=6일 — ADR-005)

### 아키텍처 (단일 소스 원칙, 2026-04-22)

```
strategy_config.yaml   ← 파라미터 단일 소스
        ↓
    strategy.py        ← 로직 단일 소스
        ↓                    ↓                    ↓
99_*.py (백테)       kr_report.py         signals_today.py
                    (GH Actions 06:00)    (Task Scheduler 15분)
```

---

## 활성 작업

### ⏭️ 다음 진입점

#### 1️⃣ ★ 페이퍼 트레이딩 인프라 셋업 (1순위, 알파 추구 → 실전 검증 전환)

알파 추구 4번 연속 기각 (ADR-005/004/001/010) 후 자연스러운 다음 단계.
구성 요소:
- Notion DB 1개 생성 (저널: 진입가/청산가/사유/심리 점수 1~5)
- 자동화 미니 모듈 (`backtest/strategy.py` 실시간 모드 → 가상 포지션 추적,
  STOP_LOSS/TRAIL/cooldown 자동 진행)
- 일일 PDF 첫 페이지에 "현재 페이퍼 포지션 / 누적 수익률" 카드 추가 검토
- **운영 모델 선택**: (a) 100% 페이퍼 6개월, (b) 자본 10-15% 실전 + 페이퍼 5종목
  풀 절충 — 마스터 FOMO ("강세장 6개월 안에 끝날까") 감안 시 (b) 권장.
- 통과 기준: 백테 대비 CAGR ±3-5%p / 신호→진입 지연 median ≤ 5일 / 심리 점수 ≥ 3.5

#### 2️⃣ morning.yml fix 검증 (2026-04-28 Tue 06:25 KST)

PR #25 fix 후 첫 cron. 검증 시나리오 2개:
- (a) JSON 없을 때: baseline 정상 생성 (회귀 없음 확인).
- (b) PC 에서 `docs/claude_analysis/20260428.json` push → claude_render 카드 주입
  → 이후 morning.yml 수동 dispatch 재실행 시 카드 보존되는지 (race fix 정확
  검증). 1회만 보면 충분.

#### 3️⃣ ADR-011 후보 — 데이터 무결성 원칙

v3.9 에 구현된 "silent degradation 거부 / damage control canonical 화 금지"
원칙을 ADR 로 승격할지 마스터 판단. 가벼운 정리 작업.

### 모니터링 대기
- pykrx 인덱스 API 복구 → Weinstein Stage 25점 복원 (섹터 점수 표시용 한정,
  진입 결정 영향 X)
- `stocks_daily.parquet` 2026-04-30 월말 경계 outlier 재검증

### 후보 작업 (후순위 / 검증 후 우선순위 재평가)
- **2025+ 이상치 검증** (+157% CAGR 재현성) — 실전 기댓값 신뢰도, 페이퍼 후 검토
- **2022년 방어 실패 분석** (시장 게이트 개선) — A4 와 묶어서 검토. 4번 fail
  패턴상 baseline 깎을 가능성 ↑.
- **생존편향 정량화** (2015 상폐주 리스트) — 실전 기댓값 정확도, 페이퍼 후 검토
- **박스권 보호 +10%p 의 다른 채널 구현** (sizing / risk parameter / 박스권 시
  stop_loss 완화) — ADR-010 부산물, 페이퍼 후 검토

### 기각 / 종료 (ADR 또는 SESSION_LOG 보존)
- ❌ **VCP 자동 필터** (ADR-001, 162 재검증으로 강화 — SESSION_LOG 04-26 #2)
- ❌ **섹터 게이트 무조건** (ADR-004)
- ❌ **fresh-signal entry timing 필터** (ADR-005)
- ❌ **streak≤10 필터** (ADR-006)
- ❌ **UBATP 장중 알림** (ADR-007)
- ❌ **Section 04 Entry Candidates UI** (ADR-008)
- ❌ **Claude augmentation** (ADR-009)
- ❌ **박스권 조건부 게이트** (ADR-010 안에 흡수 — 검증 결과 + 메타 원칙)
- ✅ **메타 원칙** (ADR-010): baseline 외 추가 필터는 사전 검증된 1차 출처 +
  robustness plan 둘 다 통과 시에만 백테 시도

### 잔존 정리 (UI 수동, sandbox 403)
- 브랜치 삭제: `session-start-hook-Lv8YN`, `session-end-2026-04-24-3`,
  `adr-005-006-007-entry-timing`, `resume-session-progress-8cGdH`,
  `fix-error-handling-riAYS`, `phase3-backtest`, `session-start-nueAo`,
  `v3.9-data-integrity`, `session-start-4OzHX` (v4.0 abandoned),
  `session-start-HhsjC`, `waiting-for-instructions-6Xn3W` (v5.0 src),
  `interesting-kapitsa-d40f52`

---

## 프로젝트 구조

```
morning-report/
├── CLAUDE.md / SESSION_LOG.md
├── docs/{decisions,plans}/      ← ADR + 플랜
├── .claude/{commands,hooks}/    ← 슬래시 명령어 + SessionStart hook
│
├── kr_report.py                 ← 라이브 모닝리포트 (GH Actions 06:00 KST)
├── combine_data.py / holdings_report.py / gdrive_upload.py
│
└── backtest/
    ├── strategy_config.yaml     ← 🎯 파라미터 단일 소스 (T10/CD60)
    ├── strategy.py              ← 🎯 로직 단일 소스
    ├── universe.py              ← 164종목 스냅샷
    ├── 01_fetch_data.py / 02_validate_data.py
    ├── 99_minervini_vcp_compare.py / 99_walkforward.py
    └── data/                    ← 원시 데이터 (gitignore, 재생성 가능)
```

---

## 운영 규칙

### 브랜치 / 배포
- **main**: GitHub Actions 전용 (매일 06:00 KST cron). 직접 수정 지양.
- **Push 는 마스터 명시 승인 시에만** (세션 중 자동 push 금지)

### 전략 파라미터 변경
- `backtest/strategy_config.yaml` 한 곳만 수정
- 수정 후 백테 재실행 (`python backtest/strategy.py`) → 회귀 검증 후 커밋

### 실전 매매 규약
- 오늘 아침 리포트 Top 5 → 시장 게이트 통과 확인 → 미보유·쿨다운 해제 종목
  RS 순 → **빈 슬롯 수만큼 균등 가중** → 09:00 시가 근처 매수
- 5일 지연 후 매수해도 OK (필터 엄격, Top 5 day-to-day 안정적, median 6일)
- 차트 판독으로 종목 거르기 ❌ (검증 안 된 추가 필터)
- 단독 종목 집중 ❌ (백테는 5종목 포트폴리오 통계 기반 알파)

### 데이터 인프라
- **한국 지수**: yfinance `^KS11`, `^KQ11` (pykrx index API 깨짐)
- **미국 시장**: NY 마감 확정가만 사용 / **KIS API**: rate limit 주의
- **pykrx**: 백테 수집. 거래정지일 OHLV=0, 라운딩 편차 1~6원 (validation 처리)

### Windows/한글
- Console cp949 기본 → `PYTHONIOENCODING=utf-8` / 파일 경로 공백 시 따옴표

---

## 핵심 지식

### 실전 기댓값 (T10/CD60, 차감 후)
| 시장 환경 | 백테 | 실전 |
|---|---:|---:|
| 박스권 (2015-19) | -2.05% | -5 ~ +3% |
| 중립 (2020-24) | +35.26% | +25-30% |
| 강세장 (2025+) | +157% | +130%+ (재현 의심) |
| **전체** | **+29.55%** | **+20-23%** |

차감 내역: 생존편향 -3~5%p / 슬리피지 -1~2%p / 룩어헤드 -0.2%p / 세금 -1~2%p

### MDD 프레이밍
전략 MDD -29.8% < 코스피 ETF -43.9%. STOP_LOSS 7% + TRAIL 10% + 시장 게이트가
자동 차단. **진짜 리스크는 박스권 언더퍼폼** (2015-19 같은 장에서 손절로 -2~5%)
— "차라리 ETF" 후회 견디는 심리가 관건.

---

## 실전 착수 전 체크리스트
- [ ] 6-12개월 페이퍼 트레이딩 (백테 대비 ±3-5%p 이내)
- [ ] 자본의 30-40%만 배분 (나머지 ETF)
- [ ] 심리 테스트: 박스권 -5% 연속 2년 견딜 수 있나
- [ ] 자동화 최소 (신호 알림 + 예약주문)
- [ ] 저널링 (매 거래, 6개월마다 백테 이탈 확인)
- [ ] 중단 조건: 6개월 롤링 코스피 -5%p 이하 → 재검토

---

## 최근 주요 결정 (ADR)
- **ADR-001** T10/CD60 재확정 (162종목, T15/CD120 과적합 철회). **162 재검증
  04-26 #2**: VCP 자동 필터 추가 시 -21%p 알파 손실 → 기각 강화.
- **ADR-002** strategy.py/yaml 단일 소스 아키텍처
- **ADR-003** 섹터 강도 산정 (IBD + Weinstein + Breadth, KOSPI200 11섹터, 164 ticker_overrides)
- **ADR-004** 섹터 게이트 통합 — **기각** (5 variant 전부 baseline 하회)
- **ADR-005** Entry timing — fresh-signal 필터 **기각**, baseline median signal_age=6일
- **ADR-006** streak≤10 walkforward — **기각** (OOS 방향 불일치)
- **ADR-007** UBATP 장중 알림 — **폐기** (장중 RS ≠ 종가 RS, 06:00 단일 채널)
- **ADR-008** Section 04 Entry Candidates — **폐기** (ADR-005 반증 기반), Trend Watch 단일 섹션 복귀
- **ADR-009** Claude augmentation — **폐기** (알파 기여 0 + narrative 끌림 위험), baseline PDF only 운영. 인프라는 보존.
- **ADR-010** baseline 외 추가 필터 추구 자제 원칙 — **채택 (메타)**. ADR-005/004/001
  + 박스권 조건부 게이트 검증 (04-26 #2) 4 case 공통 fail 패턴 정리. 미래
  추가 필터는 (1) 사전 검증된 1차 출처 + (2) robustness sensitivity plan 둘 다
  통과 시에만 백테 시도. 박스권 보호 +10%p 부산물은 게이트 외 채널 (sizing /
  risk parameter) 로 구현 시 본 원칙 적용 대상 아님.

---

## 최근 세션
- **2026-04-27 (web, `claude/json-to-pdf-workflow-7yk63` → main `82285d3`/`b4ba508`)**:
  Claude 분석 PDF 주입 race fix + 04-27 카드 복구. 04-27 PDF 에 카드 누락 사건 추적 →
  morning.yml 이 cron + 추가 트리거로 3회 실행되며 claude_render 산출물을 baseline
  으로 덮어쓴 race condition 발견. `morning.yml` 의 render_report 호출에 "오늘자
  JSON 존재 시 `--claude-analysis` 자동 주입" 분기 추가 (PR #25). 04-27 PDF 는
  `claude_render.yml` workflow_dispatch 수동 실행으로 복구 (`b4ba508`). 투트랙
  운영 모델 (트랙 1 baseline cron / 트랙 2 PC 에서 JSON push) 명시적으로 확정.
- **2026-04-26 #2 (PC CLI worktree `claude/elated-tu-ec63ef`)**: 알파 추구 1차
  종료. VCP 자동 필터 162 재검증 → ADR-001 기각 강화 (CAGR +29.55% → +8.20%,
  -21.35%p, 거래 -49%). ADR-010 박스권 조건부 게이트 6 variant 그리드 → 기각
  (박스권 보호 +10%p 실재했으나 강세장 false positive -8.93%p + MDD 악화 +
  ±5/15% robustness FAIL). ADR-005/004/001/010 4번 연속 "추가 필터 baseline 깎음"
  패턴 확정. 코드 변경 전부 revert (라이브 영향 0). 다음 단계 = 페이퍼 트레이딩
  (자본 10-15% 실전 + 페이퍼 5종목 풀 절충안 권장).
- **2026-04-26 #1 (PC CLI, branch `claude/interesting-kapitsa-d40f52`)**: 04-25 web
  사고 fix + Notion CI 자동화 완성 + Instruction v5.0→v5.1 갱신 + **Claude
  augmentation 폐기 (A 옵션) 결정**. 처음에는 v5.1 운영 모델 (CLI / web 수동 /
  D cron) 분기로 복잡해졌으나, 마스터의 "단순화 시키려다 더 복잡해졌다" 통찰 +
  알파 분해 냉정 평가 (룰 100% / 자연어 해석 0% + narrative 끌림 위험) 후
  augmentation 폐기 결정. `morning.yml` 끝에 Notion publish step 추가 → baseline
  PDF 매일 06:25 cron 으로 Notion 까지 자동 발행. v5.1 + claude_render 인프라는
  미래 재시도용 보존 (deprecation 메모 추가).
- **2026-04-25 (web, `claude/v3.9-data-integrity` → main `775ba0b`)**: ADR-008
  Section 04 Entry Candidates 폐기 (Trend Watch §04 복귀, PR #19) + Claude
  Project Instruction v3.6→v3.7→v3.8→v3.9 3사이클. v3.8: Step 0 오늘 날짜 고정 +
  Step 1 modifiedTime 최신 선택 (D-1 리포트 사고 fix) + 슬림화 503→419. v3.9:
  Step 1 무결성 가드 (expected_size 검증, 불일치 시 2차 경로 자동 + loss_pct
  강제) + ALERT 11 + 데이터 무결성 금지/체크 섹션 (18% 데이터 손실 사고 fix, PR #20).
- **2026-04-24 (PC, offline, main `339d373`)**: ADR-005/006/007 일괄 결정 + drift
  사고 복구 + session-start/end 스킬 git fetch 자동화. PR #16 머지 (`31c07b6`).
