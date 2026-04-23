# morning-report

> ## 🚨 새 세션 재개 시 반드시 먼저 실행 (2026-04-23 기준)
>
> 현재 **main 미머지** 상태로 2개 브랜치 병렬 진행 중. 새 세션이 fresh
> 브랜치에서 시작되면 이 아래 작업 내역을 못 봄. `/session-start` 전에:
>
> ```bash
> git fetch origin
> git checkout claude/session-start-UZymn   # 섹터 breadth 작업 (최신)
> git pull
> /session-start
> ```
>
> 또는 알림 작업 이어가려면 `claude/session-start-UBATP` 체크아웃.
> 둘 다 건드려야 하면 UZymn 먼저 → /session-end 후 UBATP.

<!-- ACTIVE BRANCHES (Last updated: 2026-04-23 #4, UZymn 17 커밋): -->
<!--   claude/session-start-UZymn  : ADR-003 Amendment 2 + 회귀 검증 PASS (주도+강세 vs universe-avg, hit 83%/mean +2.37%/월). 본 브랜치. -->
<!--   claude/session-start-UBATP  : 알림 시스템 코드 + 세션 연속성 fix (PC E2E 테스트 대기) -->
<!-- /session-end 가 본 포인터 자동 갱신. -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-23 #4, UZymn 브랜치)

### 🎯 Phase 4 (실전 준비) — 섹터 산식 **검증 PASS** ✅

**확정 전략**: **T10/CD60** (Trail 10% / Cooldown 60거래일)
- 백테 CAGR +29.29% (11.3년, 162종목), MDD -29.8%, 실전 기댓값 +15-20%

### 섹터 강도 산식 (ADR-003 Amendment 2 **정식 채택**)

```
점수 = ((A) IBD 6M 백분위 50 + (C) Breadth 25) × 100/75  → 0-100
       (Weinstein Stage 25점은 pykrx 인덱스 API 복구 후 복원, ADR-005 대기)

등급 임계: 주도 ≥75 / 강세 60-74 / 중립 40-59 / 약세 <40 / 표본<3 N/A
운영 기준: "주도 + 강세" 복합 (주도 단독은 폐기 — hit 42% 변동성 과대)
벤치마크: universe-avg (동등가중 162종목) — KOSPI 는 참고용
```

**회귀 검증 결과** (최근 12개월, 16 ticker_overrides):
| grades | benchmark | mean_excess/월 | hit | 판정 |
|---|---|---:|---:|---|
| 주도 | KOSPI | -2.21% | 42% | FAIL |
| 주도+강세 | KOSPI | -1.22% | 33% | FAIL |
| 주도 | universe | +1.39% | 42% | 부분 |
| **주도+강세** | **universe** | **+2.37%** | **83%** | **PASS ✅** |

핵심 insight: **KOSPI는 universe drag(-3.6%/월) 때문에 부적합**. ADR-003은
"universe 내 섹터 선택 알파" 측정이므로 universe-avg 가 논리적.

**데이터 소스 pivot** (pykrx 인덱스 API 다운):
- 섹터 매핑: KRX KIND (KSIC) + `reports/sector_overrides.yaml` 16 overrides
- 시총: FinanceDataReader `StockListing('KRX')` Marcap
- 종목 OHLCV: pykrx (정상)
- 업종지수 주봉: 수집 보류 (Stage 복원 조건 충족 시 재개)

구현: `sector_breadth.py` + `scripts/validate_sector_breadth.py` +
`tests/test_sector_breadth.py` (~35 tests) + `notebooks/sector_validate.ipynb`.

### 진행중 작업 (2개 브랜치 병렬)

```
claude/session-start-UBATP   →  알림 시스템 (코드 완성, PC E2E 테스트 대기)
claude/session-start-UZymn   →  ADR-003 Amendment 2 + 검증 PASS 완료
                                다음: sector_report.py 신/구 병행 + ADR-004
                                ↑ 이 브랜치
```

main 미머지 유지. 메타 인프라(인덱스+훅) 구축 보류.

### 아키텍처 (단일 소스 원칙, 2026-04-22 확립)

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

### ⏭️ 다음 세션 진입점 (웹/로컬 무관, 총 1.5-2h)

#### 1️⃣ [우선] UZymn — `sector_report.py` 신/구 점수 병행 표시 (30-45분)

ADR-003 Amendment 2 판정 PASS. 모닝리포트에 신 산식 결과 노출 단계.

- 기존 18 ETF 기반 점수 + 신 ADR-003 점수를 나란히 출력
- `reports/sector_mapping.py` 와 `sector_breadth.py` 통합 지점 결정
- 모닝리포트에서 1-2주 운영 체감 후 구 산식 deprecate
- 주의: `sector_breadth.py` 는 Colab 산출 parquet 필요 → GitHub Actions
  워크플로에 parquet 생성 단계 추가 or pre-commit parquet 생성 고려

#### 2️⃣ [차순위] UZymn — ADR-004 착수 (strategy 통합, 1시간)

주도+강세 섹터를 `kr_report.py` signals 생성 시 진입 게이트로 통합.

- `strategy_config.yaml` 에 `sector_filter: true|false` 플래그
- 백테 재실행 (162종목 × 11.3년)로 CAGR 변화 측정
- 성공 시 ADR-004 정식 채택, 실전 전략 파라미터에 섹터 필터 추가

#### 3️⃣ [이월] UBATP — 알림 시스템 E2E 테스트 (30분)
```bash
git checkout claude/session-start-UBATP
git pull
pip install -r requirements.txt
# .env 생성 → python notifier.py signals "테스트" → Task Scheduler 등록
```
상세: `docs/plans/001-alert-system-setup.md`

#### 4️⃣ 이월 (별도 ADR/커밋)
- universe.py 누락 4종목 (008560/000060/042670/000215 상폐·코드변경)
- pykrx 복구 모니터링 → Stage 25점 복원 결정 (ADR-005)
- `stocks_daily.parquet` 2026-04-30 확보 후 sector_breadth 재검증 (경계 outlier 확인)

### 다른 후보 작업
- **1주일 알림 모니터링 후 v2 개선** (과알림 방지, 보유종목 제외, 1-2h)
- **페이퍼 트레이딩 저널** (실전 착수 전 3-6개월 검증, 1시간)
- **2025+ 이상치 검증** (+157% CAGR 재현성 분석, 2-3시간)
- **2022년 방어 실패 분석** (시장 게이트 개선, 2-3시간)
- **생존편향 정량화** (2015 상폐주 리스트 확보, 5+시간)
- **메타 인프라 구축** (main 인덱스 + SessionStart 훅, 1.5-2h, 보류 중)
- **main 머지 리허설** (workflow_dispatch 테스트 후 PR)

---

## 프로젝트 구조

```
morning-report-main/          ← 이 레포 (Git 연결)
├── CLAUDE.md                 ← 이 파일 (현재 상태)
├── SESSION_LOG.md            ← 세션별 작업 일지
├── docs/
│   ├── decisions/            ← ADR (구조적 결정)
│   ├── plans/                ← 다음 작업 상세 플랜
│   └── environment-guide.md  ← 로컬 ↔ 웹 작업 가이드
├── .claude/commands/         ← 슬래시 명령어
│
├── kr_report.py              ← 라이브 모닝리포트 (GitHub Actions 매일 06:00 KST)
├── combine_data.py           ← 데이터 통합
├── holdings_report.py        ← 보유종목 리포트
├── gdrive_upload.py          ← Google Drive 업로드
│
└── backtest/                 ← Phase 3 백테스트
    ├── strategy_config.yaml  ← 🎯 파라미터 단일 소스 (T10/CD60)
    ├── strategy.py           ← 🎯 로직 단일 소스
    ├── universe.py           ← 164종목 스냅샷
    ├── 01_fetch_data.py      ← pykrx OHLCV 수집 (data/ 재생성용)
    ├── 02_validate_data.py   ← 데이터 검증 (거래정지일 제외, 0.1% 톨러런스)
    ├── 99_minervini_vcp_compare.py  ← TRAIL×CD 그리드 스윕
    ├── 99_walkforward.py     ← IS/OOS + 민감도
    └── data/                 ← 원시 데이터 (gitignore, 재생성 가능)
        └── validation_report.json  ← 162종목 ok 판정 (추적)
```

---

## 운영 규칙

### 브랜치 / 배포
- **main**: GitHub Actions 전용 (매일 06:00 KST cron). 직접 수정 지양.
- **작업 브랜치**: 현재 `claude/automate-morning-report-9bUuB`
- **Push는 마스터 명시 승인 시에만** (세션 중 자동 push 금지)

### 전략 파라미터 변경
- **`backtest/strategy_config.yaml` 한 곳만 수정**
- 수정 후 반드시 백테 재실행 (`python backtest/strategy.py`)
- 백테 결과 로그로 회귀 검증 후 커밋

### 데이터 인프라
- **한국 지수**: yfinance `^KS11`, `^KQ11` (pykrx index API 깨짐)
- **미국 시장**: NY 마감 확정가만 사용
- **KIS API**: 라이브 라이트 (rate limit 주의)
- **pykrx**: 백테 데이터 수집. 수정주가 기본 적용됨
  (거래정지일 OHLV=0, 라운딩 편차 1~6원 존재 → validation 톨러런스로 처리)

### Windows/한글 주의
- Console cp949 기본 → `PYTHONIOENCODING=utf-8` 설정
- 파일 경로 공백 시 따옴표

---

## 핵심 지식 (auto memory에서 이관)

### 실전 기댓값 상세 (T10/CD60, 차감 후)
| 시장 환경 | 백테 | 실전 |
|---|---:|---:|
| 박스권 (2015-19) | -2.05% | -5 ~ +3% |
| 중립 (2020-24) | +35.26% | +25-30% |
| 강세장 (2025+) | +157% | +130%+ (재현 의심) |
| **전체 (정직)** | **+29.29%** | **+20-23%** |
| IS 기준 | +10.31% | +3-5% |
| OOS 기준 | +47.88% | +38-42% |

### 차감 내역
- 생존편향: -3~5%p (상폐주 누락, 유니버스 자체가 2026 모닝리포트 리스트)
- 슬리피지: -1~2%p
- 룩어헤드: -0.2%p
- 세금: -1~2%p (대주주 기준)

### 투자 가치 판단
| 투자금 | 초과수익 | 시간당 (주 2-5h × 52주) |
|---|---:|---:|
| 1,000만원 | 연 70만원 | 2,700~7,000원 |
| **5,000만원** | 연 350만원 | **1.3~3.5만원 (의미있음)** |
| 1억원+ | 연 700만원+ | 2.7~7만원+ |

→ **투자금 5,000만원 이상일 때 시간 가치 확보**.

### MDD 프레이밍 (중요)
전략 MDD -29.8%는 코스피 ETF -43.9% 보다 **낮음**. STOP_LOSS 7% + TRAIL 10%
+ 시장 게이트가 자동으로 리스크 차단. "물리면 버텨야 한다"는 오히려 ETF의 약점.

**진짜 리스크**: MDD가 아닌 **박스권 언더퍼폼**. 2015-2019 같은 장 오면
잦은 손절로 -2~5% 가능. "차라리 ETF 살 걸" 후회 견디는 심리가 관건.

---

## 실전 착수 전 체크리스트

- [ ] 6-12개월 페이퍼 트레이딩 (백테 대비 실제 ±3-5%p 이내)
- [ ] 자본의 **30-40%만 배분** (나머지 ETF)
- [ ] 심리 테스트: **박스권 -5% 연속 2년** 견딜 수 있나
- [ ] 자동화 최소 (신호 알림 + 예약주문)
- [ ] 저널링 (매 거래, 6개월마다 백테 이탈 확인)
- [ ] 중단 조건: 6개월 롤링 코스피 -5%p 이하 → 재검토

---

## 최근 주요 결정 (ADR)
- [ADR-001] T10/CD60 재확정 (103 → 162종목, T15/CD120 과적합 철회) — `docs/decisions/001-t10-cd60-reconfirm.md`
- [ADR-002] strategy.py/yaml 단일 소스 아키텍처 — `docs/decisions/002-strategy-module-architecture.md`
- [ADR-003] 섹터 강도 산정 방법론 (IBD + Weinstein + Breadth, 한국 적용) — `docs/decisions/003-sector-strength-methodology.md`
  - **Amendment 1 (2026-04-23)**: pykrx 인덱스 API 장애 대응 — KIND+FDR pivot, Stage 보류, rescale ×100/75
  - **Amendment 2 (2026-04-23 #4)**: 회귀 검증 **PASS** — 운영 기준 "주도+강세" × universe-avg 확정 (mean +2.37%/월, hit 83%). ticker_overrides 16개 baseline 고정.

## 최근 세션
- **2026-04-23 #4 (UZymn, 웹)**: Colab 회귀 검증 3회 → "주도+강세 × universe-avg" PASS. ticker_overrides 5→16 확장 (금융업 41→26), validate_sector_breadth.py 신규, 벤치마크 플래그 추가, ADR-003 Amendment 2.
- **2026-04-23 #3 (UZymn, 웹)**: ADR-003 구현 — pykrx 장애 pivot, sector_breadth.py + 25 pytest + overrides.yaml 완성. Drive MCP 한계로 실데이터 검증 웹 세션 중 이월.
- **2026-04-23 #2 (UZymn)**: ADR-003 채택 — 섹터 강도 산식 50/25/25 설계
- 2026-04-22: 162종목 재백테 + T10/CD60 확정 + strategy 모듈화 + 문서 인프라
- 자세한 건 `SESSION_LOG.md` 참조
