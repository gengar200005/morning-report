# morning-report

<!-- Last session branch: claude/condescending-roentgen-c7ae37 (2026-04-28 #2) -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-28 #2)

**Phase 4 실전 준비 — 페이퍼 트레이딩 인프라 첫 단계 진입 (Plan 005/006 + Notion DB) + `/analyze` v3 가이드 정식화 + 백테 가정 한계 발견**. 1주 운영 후 정식화 (CLAUDE.md 차감 / 운영 모델 / 자동 모듈 구현).

**운영**: 매일 06:25 KST `morning.yml` cron 단발 → 데이터 수집 (KIS API 200종목,
~30~40분) → HTML 렌더 → PDF 변환 → Drive 업로드 → Notion publish. **+
augmentation 흐름**: cron 끝 ~07:00 KST 마스터가 Claude Code 세션 → `/analyze`
한 줄 → 7카드 JSON main commit → `claude_render.yml` 자동 트리거 → PDF
재렌더 + Drive + Notion 갱신.

**오늘 #2 (2026-04-28 PC CLI worktree) 핵심 작업**:
- **`/analyze` v3 가이드 정식화** (PR #27 머지). `.claude/commands/analyze.md`
  에 entry 카드 v3 의무 4개 (산업군 임계 분리 / WebSearch Top 5 / 컨센 추월
  ⚠️ +10%/+50% / 출처) sub-section + entry 외 6카드 환기 사항 분리 + 금지
  사항 4건 + 예시 섹션 (2026-04-28 reference). 다음 cron 06:25 부터 자동
  동일 quality.
- **페이퍼 트레이딩 인프라 첫 단계** (PR #28 머지). Plan 005 (DB 스키마
  24필드 spec) + Plan 006 (자동 모듈 spec) + Notion DB 자동 생성 (📊 모닝
  리포트 → 페이퍼 트레이딩 저널 → Positions). **Data source ID
  `d02501fe-58a4-4ba1-9bed-0478ebb3e3be`** (Plan 006 영구 reference).
  Views 3개 + dry-run row 1개.
- **백테 +29.55% 가정 한계 정량화** (대화 분석, 코드 미변경). `strategy.py:320`
  `entry_price = o[i] × (1 + 0.15%)` — 시초가 무조건 100% 체결 가정.
  거래량 / 호가창 / 상한가 갭 / 인간 회피 전부 미반영. 슬리피지 -1~2%p →
  -2~3%p 보정 필요 + 인간 회피/지연 -3~7%p 미반영.
- **예약 매수 회피 차단 발견**. 한국 증시 동시호가 (08:30~09:00) 시장가
  매수 예약 → 09:00 단일가 체결, 갭상이라도 시초가 매수 가능. **인간
  회피/지연 자동 차단 장치**. 운영 시 실전 +22~25% 가능 (백테 가정 거의
  살아있음). 망설임 + 5일 지연 시 +12~17%. 1주 운영 검증.

**확정 전략**: T10/CD60 (Trail 10% / Cooldown 60거래일)
- 백테 CAGR **+29.55%** (11.3년, 162종목), MDD -29.83%
- 실전 기댓값 +15-20% (생존편향/슬리피지/세금 차감 후)
- 진입 규칙: `check_signal=True` 인 모든 A등급 종목 RS 순 top-5 (streak 무관,
  median signal_age=6일 — ADR-005)
- 라이브 universe 200 / 백테 universe 162 분리 (라이브 = 신규 종목 노출,
  백테 = 시점 고정 알파 측정)

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

#### 1️⃣ ★ 마스터 1주 운영 후 페이퍼 트레이딩 정식화 (~05-05)

본 세션에서 인프라 첫 단계 (Plan 005/006 + Notion DB) 완료. 1주 운영 후
ADR-014 + Plan 007/008 정식화. 운영 항목:
- **예약 매수 운영** (08:30~09:00 동시호가 시장가) — 갭 회피 자동 차단
  장치, 백테 가정 거의 그대로 실현 가능 가설 검증
- **DB 입력 부담** (한 사이클 6필드: Entry date/price/note/psychology +
  Exit note/psychology) — 5종목 동시 운영 부담 적정성
- **측정**: Days delayed median ≤ 5일 / Entry psychology 평균 ≥ 3.5 /
  CAGR ±3-5%p (6개월 누적 후)
- **운영 모델 결정**: (a) 100% 페이퍼 6개월 디폴트 vs (b) 자본 10-15% 실전
  + 페이퍼 5종목 절충 — 1-2개월 차에 결정.
- **CLAUDE.md 차감 update**: 슬리피지 -1~2%p → -2~3%p 보정 + 예약 매수
  회피 차단 -3~7%p 효과 반영. "실전 매매 규약" 에 동시호가 예약 매수 추가.

#### 2️⃣ Plan 006 자동 모듈 마스터 결정 3가지

`docs/plans/006-paper-trading-auto-module.md` spec 만 main, 미구현. 결정 후
구현:
- **트리거**: (a) `morning.yml` cron 끝 06:25 vs (b) 별도 cron 19:00 vs
  (c) PC Task Scheduler — 추천 (b) 종가 정확 + market gate 정확
- **구현 위치**: `backtest/strategy.py` 실시간 모드 추가 vs `paper_trading.py`
  신규 모듈
- **Notion API token 위치**: `.env` 로컬 vs GH Secrets vs Task Scheduler env

#### 3️⃣ Claude augmentation B 옵션 1주 자체 점검 (~05-04)

직전 세션 (04-28 #1) 결정. "오늘 분석 도움됐나" 매일 1회 자체 점검 1주
누적. NO 면 즉시 A (전면 폐기) 전환. 정식 평가 후 ADR-012 정식화 또는
ADR-009 재확인.

#### 4️⃣ ADR 후보 4건 (마스터 결정)

- ADR-012 augmentation B 분업 frame (1주 자체 점검 결과 반영)
- ADR-013 라이브 universe ↔ 백테 스냅샷 분리
- ADR-014 페이퍼 트레이딩 운영 모델 (a/b 결정, 1주 운영 후)
- Plan 007 (선택) PDF 첫 페이지 페이퍼 포지션 / 누적 수익률 카드

#### 5️⃣ dry-run row 처리

[SK하이닉스 [DRY RUN]](https://www.notion.so/35014f343a5681f0ad86fe7c22185b37)
1개 — 마스터 사용감 확인 후 삭제 또는 첫 정식 row 활성화. Entry note
1자 깨짐 ("컨센→컴센") 같이 처리.

### 모니터링 대기
- pykrx 인덱스 API 복구 → Weinstein Stage 25점 복원
- `stocks_daily.parquet` 2026-04-30 월말 경계 outlier 재검증
- **KIS API 200종목 호출 시간** (~30~40분) — pykrx 마이그레이션 (KRX_ID/PW
  환경변수 셋업) 검토. 페이퍼 트레이딩 들어가기 전.

### 후보 작업 (후순위)
- **v6.2 template Top 5 자동 READINESS 코멘트 부정확** ("ROE 22% 펀더멘털
  취약" 같은 기계적 분류) — ROE 임계 분리 + 산업군 인식. 알파 0, 별 이슈.
- **KOSPI 200 외 stale tickers cleanup**: 293490 (옛 카카오뱅크) → 323410 /
  000215 → 375500 / 298000 → 298020 / 005870 → 088350. 라이브 영향 0.
- **2025+ 이상치 검증** (+157% CAGR 재현성) — 페이퍼 후 검토
- **2022년 방어 실패 분석** — 페이퍼 후 검토
- **생존편향 정량화** (2015 상폐주 리스트) — 페이퍼 후 검토
- **박스권 보호 +10%p 의 다른 채널** (sizing / risk parameter) — 페이퍼 후

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
  `interesting-kapitsa-d40f52`, `elated-tu-ec63ef`, `claude-pub`,
  `claude-pub-v3` (04-28 임시 publish 브랜치)

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
- **예외**: `docs/decisions/_inbox.md` 만 자동 commit + push 허용

### 결정 인박스 (`docs/decisions/_inbox.md`)
세션 중 "해보자" 가 굳어지는 순간 1~3줄 즉시 기록 + 즉시 push (코드 변경 0
이어도 OK). 세션이 도중에 뻗어도 다음 세션이 컨텍스트 회복. 다음 세션 시작
시 회수 → 정식 문서 흡수 → 해당 entry 삭제.

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
- **ADR-011** 결정 인박스 (`_inbox.md`) 운영 원칙 — **채택**. 세션 뻗음 →
  컨텍스트 손실 4번 연속 패턴 mitigation. "해보자" 결정 1~3줄 즉시 commit +
  push (자동 push 예외 1건 신설), 다음 세션 회수 → 정식 문서 흡수 → entry
  삭제. 3개월 운영 후 활용도 0 또는 자동 push 사고 시 폐기.

---

## 최근 세션
- **2026-04-28 #2 (PC CLI worktree `claude/condescending-roentgen-c7ae37`)**:
  `/analyze` v3 가이드 정식화 (PR #27, `d881bf8` — entry 카드 v3 의무 4개
  sub-section + 6카드 환기 분리 + 금지 4건 + 예시 섹션) + 페이퍼 트레이딩
  인프라 첫 단계 (PR #28, `39727d5` — Plan 005/006 spec + Notion DB
  자동 생성, data_source_id `d02501fe-58a4-4ba1-9bed-0478ebb3e3be`,
  Views 3개 + dry-run row 1개) + 백테 가정 한계 정량화 (시초가 무조건 체결
  가정, cost 0.15% + 인간 회피 -3~7%p 미반영) + 예약 매수 회피 차단 발견
  (08:30~09:00 동시호가 시장가, 1주 운영 검증 대기).
- **2026-04-28 #1 (web, branch `claude/track-kospi-200-stocks-s54c2`)**:
  KOSPI 200 라이브 universe 확장 (162 → 200, 백테 162 스냅샷 유지) +
  sector_overrides 234 (신규 70종목 11섹터 매핑) + Claude augmentation 분업
  frame (B 채택, ADR-009 부분 reversal) + `/analyze` 슬래시 명령 도입 +
  결정 인박스 (`_inbox.md`, 자동 push 예외) + v3 entry 카드 패턴 도입.
- **2026-04-26 #2 (PC CLI worktree `claude/elated-tu-ec63ef`)**: 알파 추구 1차
  종료. VCP 162 재검증 → ADR-001 기각 강화 (-21.35%p). ADR-010 박스권
  조건부 게이트 6 variant → 기각. ADR-005/004/001/010 4번 연속 "추가 필터
  baseline 깎음" 패턴 확정.
- **2026-04-26 #1 (PC CLI, `claude/interesting-kapitsa-d40f52`)**: 04-25 web
  사고 fix + Notion CI 자동화 + Instruction v5.0→v5.1 + Claude augmentation
  폐기 (A 옵션) 결정. v5.1 + claude_render 인프라 미래 재시도용 보존.
- **2026-04-25 (web, `claude/v3.9-data-integrity` → main `775ba0b`)**: ADR-008
  Section 04 Entry Candidates 폐기 (Trend Watch §04 복귀, PR #19) +
  Instruction v3.6→v3.9 3사이클 (PR #20).
