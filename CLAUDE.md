# morning-report

<!-- Last session branch: claude/session-start-bGCen (2026-04-29) -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-29)

**Phase 4 실전 준비 — 자동매매 룰 정합화 합의 + EOD tracker 흐름 설계 완료
+ Top 5 MFE 백테 분석으로 trail 10% 적정성 데이터 확립**. 코드 변경 0,
다음 세션부터 stock-automation 레포 작업 + morning-report inherit PR.

**운영**: 매일 06:25 KST `morning.yml` cron 단발 → 데이터 수집 (KIS API 200종목,
~30~40분) → HTML 렌더 → PDF 변환 → Drive 업로드 → Notion publish. **+
augmentation 흐름**: cron 끝 ~07:00 KST 마스터가 Claude Code 세션 → `/analyze`
한 줄 → 7카드 JSON main commit → `claude_render.yml` 자동 트리거 → PDF
재렌더 + Drive + Notion 갱신.

**오늘 (2026-04-29 web `claude/session-start-bGCen`) 핵심 결정**:
- **사용자 자동 trailing 룰 폐기 결정 — 백테 정합 운영 전환**. 사용자
  M-STOCK 자동매도 룰 (`+15% 활성화 → 장중 -10% peak 즉시 시장가`) 이
  백테 룰 (`종가 ≤ peak × 0.90 → 다음날 시초가`) 과 3 곳 다름 (체크
  시점 / peak 정의 / 청산 시점). 장중 노이즈 슬립아웃 → +100% peak
  winner 가짜 트리거. **알파 손실 추정 -10~15%p CAGR**. 자동 trailing
  즉시 폐기, **stop_loss -7% 룰만 유지**.
- **운영 흐름 합의** (백테 가정 100% 정합):
  ```
  D 15:30 장 마감
   ↓ D 19:00 cron (stock-automation 별도 레포) — 자동매도트래커 DB 갱신
   ↓ D+1 06:00 cron (morning-report) — holdings_report inherit + 청산 평가 줄
   ↓ D+1 ~07:00 마스터 /analyze — 7카드 통합
   ↓ D+1 08:30~09:00 동시호가 시장가 예약주문 (매수/매도)
  ```
  Plan 006 마스터 결정 3가지 본 세션 합의: 트리거 (b) 19:00 cron / 구현
  위치 별도 레포 / Notion token GH Secrets.
- **eod_tracker.py + eod_tracker.yml 드롭인 스크립트 작성** (마스터가
  stock-automation 레포에 commit 예정, 본 레포 코드 변경 0). 보유 DB 5
  신규 필드 spec (최고종가 / 트레일선 / 동적손절선 / 청산상태 / 갱신시각).
- **Top 5 MFE 백테 분석** (Colab + KRX 로그인 + pykrx 1.2.7, 335 거래 산출):
  - **(a) MFE Top 5**: 미래에셋증권 +212% / 동국제강 +157% / 삼양식품 +146% /
    포스코인터 +132% / 에코프로 +122% — 시기/산업 분산, 재현성 시그널 ✓
  - **(b) 환불 폭 Top 5**: 포스코인터 -55%p / 에스엠 -55%p / 한화에어로 -42%p /
    동국제강 -38%p / 두산에너빌리티 -37%p (단 5일!)
  - **통계**: peak_ret p90 46.9% / **mfe_to_exit p90 20%p** / 청산 사유
    trailing 65% stop_loss 33%
  - **Trail 10% 환불 메커니즘**: ① 종가 자체가 갭다운 ② 다음날 시초가
    추가 갭다운 ③ 슬리피지 ④ Peak = 종가 정의. 약속 -10%p 가 실제
    median -12.4%p, p90 -20%p.

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

#### 1️⃣ ★ 노션 자동매도트래커 스키마 확인 (마스터, 5분)

다음 세션 시작 시 즉시. eod_tracker.py 의 F_* 상수 매핑 정확히 잡기 위함.

- 자동매도트래커 view 컬럼 헤더 스크린샷 또는 dump 텍스트
- "최고가" 필드 = peak_close 인지 vs 장중 high 인지 vs 52주고점인지 확인
- "TS 활성화" = +15% 자동 vs 마스터 수동 확인
- 현재 갱신 cron 시점 (지금 아침이면 D-1 stale)

#### 2️⃣ stock-automation 레포에 eod_tracker 드롭인 (마스터, ~1시간)

- Notion DB 5 신규 필드 추가 (없으면): 최고종가 / 트레일선 / 동적손절선 /
  청산상태(Select HOLD/TRAIL/STOP) / 갱신시각(Date)
- `eod_tracker.py` (본 세션 작성) + `.github/workflows/eod_tracker.yml`
  drop-in. F_* 상수 실제 컬럼명 매핑.
- GH Secrets 4건 확인: KIS_APP_KEY / KIS_APP_SECRET / NOTION_API_KEY /
  NOTION_HOLDINGS_DS_ID (=`25d578de-8e37-486d-8787-549667cae981`)
- workflow_dispatch 수동 trigger 테스트 → 보유 종목 1건 갱신 확인.

#### 3️⃣ morning-report inherit PR (Claude 작업, ~1시간)

- `holdings_report.py`: 4 필드 inherit + build_text() 에 🎯 청산 평가
  줄 추가
- `.claude/commands/analyze.md`: alert / portfolio 카드 spec 보강
  (trigger 종목 명시 의무 + 자동매도트래커 단일 진실의 원천 명시)

#### 4️⃣ ★ 마스터 1주 운영 평가 (~05-05)

페이퍼 트레이딩 정식화 + 본 세션 흐름 (D 19:00 / D+1 06:00 / D+1 09:00)
부담 측정. 운영 항목:
- **자동매도 즉시 폐기 후 운영** (오늘부터): M-STOCK 5종목 자동 trailing
  룰 삭제 + stop_loss -7% 유지
- **예약 매수 운영** (08:30~09:00 동시호가 시장가) — 갭 회피 자동 차단
- **DB 입력 부담** (한 사이클 6필드)
- **측정**: Days delayed median ≤ 5일 / Entry psychology 평균 ≥ 3.5 /
  CAGR ±3-5%p (6개월 누적 후)
- **운영 모델 결정**: (a) 100% 페이퍼 6개월 vs (b) 자본 10-15% 실전 +
  페이퍼 절충 — 1-2개월 차 결정.
- **CLAUDE.md 차감 update**: 슬리피지 -1~2%p → -2~3%p + 예약 매수 회피
  차단 -3~7%p 효과. "실전 매매 규약" 에 동시호가 예약 매수 + 자동매도
  폐기 + 종가 기반 수동 trail 추가.

#### 5️⃣ Plan 006 책임 #3 자동 매도 예약 자동화 (1주 후 결정)

수동 1분 부담이 누적되면 자동화. 모닝리포트 trigger 알림 → KIS 매도
예약주문 endpoint 자동 등록. 1주 운영 후 부담 측정 → 결정.

#### 6️⃣ Claude augmentation B 옵션 1주 자체 점검 (~05-04)

직전 세션 (04-28 #1) 결정. "오늘 분석 도움됐나" 매일 1회 자체 점검 1주
누적. NO 면 즉시 A (전면 폐기) 전환. ADR-012 정식화 또는 ADR-009 재확인.

#### 7️⃣ ADR 후보 4건 (마스터 결정)

- **ADR-012 자동매매 룰 정합화** (★ 본 세션 결정 기반) — 장중 -10% trail
  폐기, 종가 기반 백테 룰 채택. 되돌리면 알파 -10~15%p 잠재 손실.
  구조적 결정 → ADR 정식화 가치 큼.
- ADR-013 augmentation B 분업 frame (1주 자체 점검 결과 반영)
- ADR-014 라이브 universe ↔ 백테 스냅샷 분리
- ADR-015 페이퍼 트레이딩 운영 모델 (a/b 결정, 1주 운영 후)
- Plan 007 (선택) PDF 첫 페이지 페이퍼 포지션 / 누적 수익률 카드

#### 8️⃣ dry-run row 처리

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
- **2026-04-29 (web `claude/session-start-bGCen`)**: 사용자 자동 trailing
  룰 (장중 -10% peak) ↔ 백테 룰 (종가 → 다음날 시초가) 차이 발견 →
  자동 trailing 즉시 폐기 결정 + stop_loss -7% 유지. EOD tracker 운영
  흐름 합의 (D 19:00 stock-automation cron → D+1 06:00 morning-report
  inherit → D+1 ~07:00 /analyze → D+1 09:00 동시호가 예약). Plan 006
  마스터 결정 3가지 합의 ((b) 19:00 / 별도 레포 / GH Secrets).
  eod_tracker.py + .yml 드롭인 작성 (마스터 stock-automation commit
  대기). Top 5 MFE 백테 분석 (Colab/pykrx, 335 거래) — peak_ret p90
  46.9% / mfe_to_exit p90 20%p / 청산 사유 trailing 65%. 코드 변경 0.
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
