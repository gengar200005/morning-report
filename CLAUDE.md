# morning-report

<!-- Last session branch: claude/session-start-nueAo (2026-04-25) -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-25, branch `claude/session-start-nueAo`)

**Phase 4 실전 준비** — 전략 T10/CD60 확정 유지. 리포트 가시성·정확성 사이클 진행 중.

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

#### 1️⃣ ADR-009 후보 — 박스권 조건부 섹터 게이트

ADR-004 기각 후 남은 유일한 유망 방향. 2015-19 박스권에서만 게이트 이득 (+3~+11%p).
시장 regime detection (6M KOSPI return, MA200 slope) 기반으로 박스권 구간만
게이트 활성화. 인프라(`strategy_config.yaml::sector_gate` + `precompute_sector_tiers`)
이미 있음. 성공 조건: 전체 CAGR 유지 or 개선, MDD 악화 없음.

#### 2️⃣ ADR-008 후속 검증 — Section 04 Trend Watch 복귀 반영 확인

cron 06:00 KST 이후 `docs/latest.html` 과 신규 `docs/archive/report_YYYYMMDD.pdf`
의 Section 04 가 Trend Watch 로 표시되는지, 🆕 뱃지가 Top 5 카드 + Remaining
표에만 잔존하는지 확인. Claude Project Files 재업로드: **v3.7 필수 2개** —
`v6_2_template_html.j2`, `render_report.py`.

### 모니터링 대기
- pykrx 인덱스 API 복구 → Weinstein Stage 25점 복원
- `stocks_daily.parquet` 2026-04-30 월말 경계 outlier 재검증

### 후보 작업
- 페이퍼 트레이딩 저널 (실전 착수 전 3-6개월 검증)
- 2025+ 이상치 검증 (+157% CAGR 재현성)
- 2022년 방어 실패 분석 (시장 게이트 개선)
- 생존편향 정량화 (2015 상폐주 리스트)

### 잔존 정리 (UI 수동, sandbox 403)
- 브랜치 삭제: `session-start-hook-Lv8YN`, `session-end-2026-04-24-3`,
  `adr-005-006-007-entry-timing`, `resume-session-progress-8cGdH`,
  `fix-error-handling-riAYS`, `phase3-backtest`

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
- **ADR-001** T10/CD60 재확정 (162종목, T15/CD120 과적합 철회)
- **ADR-002** strategy.py/yaml 단일 소스 아키텍처
- **ADR-003** 섹터 강도 산정 (IBD + Weinstein + Breadth, KOSPI200 11섹터, 164 ticker_overrides)
- **ADR-004** 섹터 게이트 통합 — **기각** (5 variant 전부 baseline 하회)
- **ADR-005** Entry timing — fresh-signal 필터 **기각**, baseline median signal_age=6일
- **ADR-006** streak≤10 walkforward — **기각** (OOS 방향 불일치)
- **ADR-007** UBATP 장중 알림 — **폐기** (장중 RS ≠ 종가 RS, 06:00 단일 채널)
- **ADR-008** Section 04 Entry Candidates — **폐기** (ADR-005 반증 기반), Trend Watch 단일 섹션 복귀

---

## 최근 세션
- **2026-04-25 (web, `claude/session-start-nueAo`)**: ADR-008 — Section 04 Entry Candidates 폐기, Trend Watch 로 §04 복귀. 템플릿 섹션 재번호 (05→04, 05·b→04·b, 06→05, 07→06, 08→07) + `data.new_a_entries` 파생 제거 + Claude Project Instruction v3.6 → v3.7.
- **2026-04-24 (PC, offline, main `339d373`)**: ADR-005/006/007 일괄 결정 + drift 사고 복구 + session-start/end 스킬 git fetch 자동화. PR #16 머지 (`31c07b6`).
- **2026-04-24 #2 (PC web, PR #10 → `ad6666b`)**: Entry Candidates 섹션 + parser 🆕 regex + ACTION 분기 + PDF 카드 보호 CSS + SessionStart hook.
- **2026-04-24 #1 (PC, main `7151030`)**: 체크리스트 라벨-값 버그 fix + PDF 페이지 분할 + Claude Project 지침 v3.5.
- **2026-04-23 #7 (PC)**: ADR-004 섹터 게이트 5 variant 백테 → 기각.
- **2026-04-23 #5-#6 (UZymn → main)**: KOSPI200 11섹터 전환 + plan-004 머지.
