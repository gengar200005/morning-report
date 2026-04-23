# morning-report

<!-- ACTIVE BRANCHES (2026-04-23, main 미머지 상태로 병렬 진행 중): -->
<!--   claude/session-start-UZymn  : ADR-003 섹터 강도 산식 + 응급 패치 (최신, 본 브랜치) -->
<!--   claude/session-start-UBATP  : 알림 시스템 코드 + 세션 연속성 fix (PC E2E 테스트 대기) -->
<!-- 다음 세션은 /session-start 의 "0. 브랜치 누락 체크" 자동 실행으로 양쪽 모두 인지. -->
<!-- /session-end 가 본 포인터 자동 갱신. -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-23, UZymn 브랜치)

### 🎯 Phase 4 (실전 준비) — 알림 시스템 + 섹터 산식 개편 병행

**확정 전략**: **T10/CD60** (Trail 10% / Cooldown 60거래일)
- 백테 CAGR +29.29% (11.3년, 162종목), MDD -29.8%, 실전 기댓값 +15-20%

### 진행중 작업 (2개 브랜치 병렬)

```
claude/session-start-UBATP   →  알림 시스템 (코드 완성, PC E2E 테스트 대기)
claude/session-start-UZymn   →  섹터 강도 새 산식 (ADR-003 채택, 구현 대기)
                                ↑ 이 브랜치
```

**다음 PC 세션에서 두 작업 모두 처리 필요** — main 미머지 상태로 양쪽
브랜치 따로 체크아웃하며 진행. 메타 인프라(인덱스+훅) 구축 보류.

### 섹터 강도 새 산식 (ADR-003)

```
ETF top-down (현재) → 유니버스 bottom-up (새)
  KODEX 반도체 가격     →  우리 162종목 → KRX 22업종 분류 → 3요소 점수
                              IBD 6M(50) + Weinstein Stage(25) + Breadth(25)
                              시총 가중 + 단일 종목 25% cap
                              임계: 75 주도 / 60 강세 / 40 중립 / <40 약세
```
근거: O'Neil/Minervini 직접 인용 + 한국 시장 변동성/시총 집중 보정.
구현은 다음 PC 세션, 검증 후 strategy 통합은 별도 ADR-004 로 결정.

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

### ⏭️ 다음 세션 진입점 (PC 환경 권장, 총 1.5-2h)

**두 브랜치 묶음 처리 필요** (main 미머지로 인해):

#### 1️⃣ UBATP 브랜치 — 알림 시스템 E2E 테스트 (30분, 이월)
```bash
git checkout claude/session-start-UBATP
git pull
pip install -r requirements.txt        # PyYAML/python-dotenv/pandas 추가됨
# .env 생성 (디스코드 webhook 4개 + KIS 키 + MORNINGREPOT)
python notifier.py signals "테스트"     # 디스코드 수신 확인
python signals_today.py --force --dry-run
# scripts/windows/signals_today_task.xml 의 WorkingDirectory 수정 → Task Scheduler 등록
```
상세: `docs/plans/001-alert-system-setup.md`

#### 2️⃣ UZymn 브랜치 — sector_breadth 실데이터 검증 (45-60분)

**진행 상태**: 코드 + 데이터 + 테스트 완료, 실데이터 실행만 남음.

상세 runbook: [`docs/plans/002-sector-breadth-pc-execution.md`](docs/plans/002-sector-breadth-pc-execution.md)

핵심 변경 (2026-04-23 웹 세션):
- **pykrx 인덱스 API 전면 다운 확인** → KRX KIND + FDR 로 pivot
- **Weinstein Stage 25점 보류** → rescale ×100/75, 임계 75/60/40 유지
- `sector_breadth.py` + `sector_overrides.yaml` + 25 pytest 완성
- Colab 에서 parquet 2개 Drive 저장됨: `MyDrive/morning-report/sector_data/`

PC 에서 할 것:
1. `pytest tests/test_sector_breadth.py -v` (뼈대 검증)
2. Drive parquet 2개 로컬 복사 → `backtest/data/sector/`
3. `python sector_breadth.py --sector-map ... --stocks-daily ...`
4. 회귀 검증 스크립트 작성 + 실행 (최근 12개월 월별)
5. 지주회사 29개 재분류 오버라이드 추가

#### 이월 (별도 ADR/커밋)
- universe.py 누락 4종목 (008560/000060/042670/000215 상폐·코드변경)
- pykrx 복구 모니터링 → Stage 복원 결정 (ADR-005)

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

## 최근 세션
- **2026-04-23 #3 (UZymn, 웹)**: ADR-003 구현 착수 — Colab 노트북 작성→실행 중 pykrx 인덱스 API 전면 다운 발견 → KRX KIND + FDR 로 pivot, Weinstein Stage 보류 (ADR amendment). sector_breadth.py + 25 pytest + overrides.yaml 완성. 실데이터 검증은 PC 세션 이월 (Drive MCP 권한 부족).
- **2026-04-23 (UZymn)**: ADR-003 채택 — 섹터 강도 산식 50/25/25 설계
- 2026-04-22: 162종목 재백테 + T10/CD60 확정 + strategy 모듈화 + 문서 인프라
- 자세한 건 `SESSION_LOG.md` 참조
