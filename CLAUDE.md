# morning-report

> ## ✅ 2026-04-24 #3 완료 — PR #11/#12/#13 머지 + 워크플로 복구 검증 + US 섹터 12개 확장
>
> 오늘 #2 에서 미머지 상태였던 `session-start-hook-Lv8YN` 을 비롯해 3개 PR
> 순차 머지 완료. (1) **PR #11 `6c9ae79`** kr_indices `+-0.00%` 이중 부호 버그
> (Python `-0.0 + "{:.2f}"` 조합이 `+-0.00%` 출력 → parser regex 매치 실패
> → `StopIteration` → GH Actions HTML 렌더 단계 실패). `kr_report.py` 에서
> `pct + 0.0` negative-zero 정규화 + parser `[+\-−]?` → `[+\-−]*` 방어 강화 +
> 회귀 테스트 추가. (2) **PR #13 `f2ba529`** US 섹터 ETF 7→**12개** 확장
> (GICS 11 Select Sector SPDR + SOXX). `US_SECTOR_META` 딕셔너리 (leaders +
> super_sector Morningstar 3분류) + `_build_us_sector_summary` regime 판정
> (Risk-on/Risk-off/혼조) + multi-arrow regex fix (±1% 이상 섹터가 탈락하던 버그
> 해소). (3) **PR #12 `a1e6c92`** Claude Project 지침 v3.5 → v3.6 (Entry
> Candidates 섹션 + `is_new`/`new_a_entries` 필드 반영).
>
> cron 자동 실행으로 `7bf395e Daily report PDF 2026-04-24 (auto)` 까지
> 파이프라인 완주 → **어제 실패한 전 단계 (HTML/PDF/Drive) 정상 복구 확인**.
>
> **다음 세션 (데스크탑 이어서) 진입점**: (1) GitHub 웹 UI 에서 브랜치 5개
> 수동 삭제 (sandbox 403 으로 CLI 불가). (2) Claude Project Files 재업로드
> 4개 (`CLAUDE_PROJECT_INSTRUCTION.md` + v6_2_template / render_report /
> morning_data_parser). (3) UBATP 알림 시스템 rebase (별도 ancestry) + PC
> E2E 테스트. 상세: `docs/plans/001-alert-system-setup.md`.

<!-- ACTIVE BRANCHES (Last updated: 2026-04-24 #3): -->
<!--   main                                        : 7bf395e — #3 3 PR 머지 + cron 9커밋. -->
<!--   main-legacy-backup                          : bdd3e24 (로컬 전용) — 옛 72커밋 + generate_report.py 보존. 판단 후 삭제 -->
<!--   claude/session-end-2026-04-24-3             : 이 세션 정리 브랜치 (CLAUDE.md 갱신). 머지 후 삭제 -->
<!--   claude/session-start-UBATP                  : 알림 시스템 (미머지, PC E2E 대기, rebase 필요 — main 과 ancestry 끊김) -->
<!--   claude/fix-error-handling-riAYS             : Minervini 노트북 아카이브 (notebooks/ 3개 독점) -->
<!--   phase3-backtest                             : Phase 3 초기 스켈레톤 아카이브 -->
<!--   === 삭제 대상 (UI 수동) === -->
<!--   claude/review-branches-debug-iztcs          : PR #11 머지 완료 -->
<!--   claude/cherry-pick-project-instruction-v36  : PR #12 머지 완료 -->
<!--   claude/us-sectors-12-expansion              : PR #13 머지 완료 -->
<!--   claude/review-session-progress-jvYaw        : 내용 PR #12+#13 에 흡수 (중복) -->
<!--   claude/continue-session-XRwjw               : 내용 PR #13 에 흡수 (중복) -->
<!--   claude/resume-session-progress-8cGdH        : 구 main 상태 7151030 (이미 main 에 포함) -->
<!--   claude/session-start-hook-Lv8YN             : PR #10 ad6666b 로 이미 흡수됨 -->
<!-- /session-end 가 본 포인터 자동 갱신. -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-24 #3, main `7bf395e`)

### 🎯 Phase 4 (실전 준비) — **전략 확정 유지 + 리포트 가시성·정확성 개선** ✅

**오늘 #3 세션 성과** (3 PR main 머지 + cron 자동 9 커밋 복구):

- **PR #11 `6c9ae79` fix(report): kr_indices '+-0.00%' 이중 부호 → StopIteration 해소**
  - Python `-0.0 >= 0 == True` + `f"{-0.0:.2f}" == "-0.00"` 조합으로 `kr_report.py::build_text` 가 `▲ +-0.00%` 출력 → `morning_data_parser::_parse_kr_indices` regex `[+\-−]?` 가 매치 실패 → `kr_indices` 에 KOSPI 누락 → `render_report::_enrich_exec_summary:231` 에서 `StopIteration` → 어제 cron 부터 HTML 렌더 단계 실패.
  - `kr_report.py::build_text` 에 `pct_val = d["pct"] + 0.0` negative-zero 정규화 + 부호/절대값 분리 포맷.
  - `_parse_kr_indices` regex `[+\-−]?` → `[+\-−]*` 방어적 다중 부호 허용.
  - `tests/test_parser.py::test_kr_indices_double_sign_regression` 추가.
- **PR #13 `f2ba529` feat(us-sectors): GICS 11 + SOXX 12섹터 확장**
  - `morning_report.py`: 섹터 ETF 7 → **12** (GICS 11 Select Sector SPDR + SOXX industry ETF). IT/XLK, 커뮤니케이션/XLC, 필수소비재/XLP, 산업재/XLI, 소재/XLB, 부동산/XLRE 추가.
  - `morning_data_parser.py`: `US_SECTOR_META` 딕셔너리 (12 ETF × leaders + Morningstar 3분류 super_sector) + `_build_us_sector_summary` regime 판정 (Risk-on · 민감재 주도 / Risk-off · 방어주 선호 / 혼조) + `_parse_us_sectors` regex `[▲▼]?` → `[▲▼]*` multi-arrow fix (±1% 이상 섹터가 탈락하던 회귀 방지).
  - 템플릿 `v6.2_template.html.j2` 12섹터 테이블 + regime 배너.
  - 테스트 3개 추가 (multi_arrow / 12_etf / summary_regime).
- **PR #12 `a1e6c92` docs(project): Claude Project 지침 v3.5 → v3.6**
  - Entry Candidates 섹션 최상위 승격 (어제 #2 `bdcd4fc`) + `is_new` / `new_a_entries` 필드 반영.
  - Project Files 3개 재업로드 필수 명시 (v6_2_template / render_report / morning_data_parser).

**워크플로 복구 검증**: cron 자동 실행으로 `7bf395e Daily report PDF 2026-04-24 (auto)` 까지 **6/6 단계 완주**. 어제 실패했던 `v6.2 HTML 렌더링 + GitHub Pages 배포` + PDF + Drive 업로드 단계 전부 정상.

**확정 전략**: **T10/CD60** (Trail 10% / Cooldown 60거래일) — 변경 없음
- 백테 CAGR **+29.55%** (11.3년, 162종목), MDD -29.83%
- 실전 기댓값 +15-20% 유지


### ADR-004 섹터 게이트 통합 — **기각** (2026-04-23 #7)

5 variant × 11.3년 백테. 전부 baseline 하회:

| Variant | CAGR | Δ | 2015-19 | 2020-24 | 2025+ |
|---|---:|---:|---:|---:|---:|
| **A baseline (off)** | **+29.55%** | - | -2.05% | +35.26% | +160.96% |
| B 주도 only | +15.66% | -13.89%p | +1.71% | +18.68% | +56.77% |
| C 주도+강세 | +21.43% | -8.12%p | +9.49% | +12.15% | +128.59% |
| D 주도+강세+중립 | +26.56% | -2.99%p | -1.79% | +32.96% | +129.86% |

**근본 가설**: Minervini 8조건 자체가 trend-following 필터라 섹터 추세
게이트와 상관 높음 → 등급 부여 lag 만 비용으로 발생. 박스권에선 개선
되지만 중립/강세장 손실 압도. 상세: `docs/decisions/004-sector-gate-rejection.md`

### 섹터 강도 산식 — **KOSPI200 11섹터 체계로 전환** (2026-04-23 #5)

**외부 리서치 v2026.04 기반 11섹터** (`reports/kospi200_sectors.tsv`):
반도체 / 전력인프라 / 조선 / 방산 / 2차전지 / 자동차 / 바이오 / 금융 / 플랫폼 /
건설 / 소재·유통.

구 18 ETF 산식 **완전 폐기**. `sector_report.py` 전면 재작성 (414 → 226줄).

```
점수 = ((A) IBD 6M 백분위 50 + (C) Breadth 25) × 100/75  → 0-100
등급 임계: 주도 ≥75 / 강세 60-74 / 중립 40-59 / 약세 <40
```

**오늘(2026-04-23) 신 11섹터 결과** (dry-run 검증):
- 🔥 주도: 반도체(5)=100, 건설(8)=90, 방산(5)=88, 전력인프라(10)=75
- 📈 강세: 2차전지(10)=64
- 〰️ 중립: 금융(24)=58, 자동차(9)=57, 조선(5)=52, 소재·유통(66)=44
- 📉 약세: 플랫폼(15)=28, 바이오(7)=11

대비 구 15업종: 전기전자 100 → 반도체 100 + 2차전지 64 로 분해 / 운수장비 79
→ 방산 88 + 자동차 57 + 조선 52 분해. **진입 대상 50% → 23% 집중**.

**데이터 소스** (pykrx 인덱스 API 다운 상태, ADR-005 대기):
- 섹터 매핑: `reports/sector_overrides.yaml` ticker_overrides **164개 전부 명시**
- KSIC auto 매핑 (ksic_to_kospi22) 은 폴백 유지
- parquet 2개: `backtest/data/sector/sector_map.parquet` + `stocks_daily.parquet`
  (plan-003 옵션 2: 주 1회 Colab 수동 갱신)

구현: `sector_breadth.py` + `sector_report.py` 재작성 + `tests/test_sector_breadth.py`.

### ✅ main 반영 완료 (2026-04-23 #6 머지, `4477143`)

- **plan-004**: HTML 렌더/파서 11섹터 전환 (ETF 데이터 없음 버그 해소).
  `_parse_sector_adr003` 신규 / `resolve_sector` 재작성 / 템플릿 키 변경
- **T10/CD60 전략**: 162종목 재백테 +29.29% CAGR / 전략 단일 소스
- **strategy.py/yaml 아키텍처**: 백테 ↔ 라이브 단일화
- **ADR-003 Amendment 3**: KOSPI200 11섹터 체계 + ticker_overrides 164개
- **morning.yml workflow race 수정**: `git reset --hard` 제거, 로컬 render
  + push rebase 재시도 (어제 데이터로 렌더되던 버그 해소)

### 진행중 작업

```
main                                   →  7bf395e (2026-04-24 #3, 3 PR 머지 + cron 9커밋).
claude/session-end-2026-04-24-3        →  이 세션 정리 브랜치 (CLAUDE.md 갱신). PR 후 머지.
claude/session-start-UBATP             →  알림 시스템 (미머지, PC E2E 대기, rebase 필요)
main-legacy-backup                     →  로컬 전용. 옛 72커밋 + generate_report.py 보존
```

**삭제 대상** (GitHub 웹 UI 수동, sandbox HTTP 403 으로 CLI 불가):
- `claude/review-branches-debug-iztcs` / `cherry-pick-project-instruction-v36` / `us-sectors-12-expansion` (PR #11/#12/#13 머지됨)
- `claude/review-session-progress-jvYaw` / `continue-session-XRwjw` (내용 흡수, 중복)
- `claude/resume-session-progress-8cGdH` / `session-start-hook-Lv8YN` (이미 main 에 포함)

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

### ⏭️ 다음 세션 진입점 (데스크탑 이어서)

#### 1️⃣ 브랜치 정리 + Claude Project Files 재업로드 (15분)

**GitHub 웹 UI 브랜치 삭제** (7개): https://github.com/gengar200005/morning-report/branches
- 머지 완료 3개: `review-branches-debug-iztcs`, `cherry-pick-project-instruction-v36`, `us-sectors-12-expansion`
- 중복 2개: `review-session-progress-jvYaw`, `continue-session-XRwjw`
- 이미 main 흡수 2개: `resume-session-progress-8cGdH`, `session-start-hook-Lv8YN`
- **보존**: `session-start-UBATP` (알림), `fix-error-handling-riAYS` (notebooks 아카이브), `phase3-backtest` (아카이브)

**Claude Project (claude.ai) 4개 요소 갱신**:
1. Project **Instructions** 영역: `CLAUDE_PROJECT_INSTRUCTION.md` v3.6 본문
2. Project **Files** 재업로드 3개:
   - `reports/templates/v6.2_template.html.j2` → `v6_2_template_html.j2`
   - `reports/parsers/morning_data_parser.py`
   - `reports/render_report.py`

**검증 포인트** (다음 cron 또는 수동 대화):
- Claude Project 가 🆕 뱃지 / Entry Candidates 섹션 (§04) 정상 인식
- 구조 드리프트 없음 (Drive PDF 와 Claude Project 렌더 결과 일치)
- PDF 에 US 섹터 12개 + Risk-on/off regime 배너 표시

#### 2️⃣ UBATP 알림 시스템 E2E 테스트 (30분, 세션 #3 이월)

⚠️ **ancestry 주의**: `claude/session-start-UBATP` 는 main 과 공통 조상 없음 (force-push 여파).
일반 merge 불가 → **rebase 또는 cherry-pick 전략 필요**.

독점 파일 5개 (main 에 없음): `notifier.py`, `signals_today.py`, `.env.example`,
`scripts/windows/README.md`, `scripts/windows/signals_today_task.xml`.

```bash
git fetch origin claude/session-start-UBATP
git checkout -b feat/alert-system origin/main
git checkout origin/claude/session-start-UBATP -- \
  notifier.py signals_today.py .env.example scripts/windows/
# .env 생성 → python notifier.py signals "테스트" → Task Scheduler 등록
```
상세: `docs/plans/001-alert-system-setup.md`

#### 3️⃣ ADR-005 후보 — 박스권 조건부 섹터 게이트 (1-2시간)

ADR-004 기각 후 남은 유일한 유망 방향. 2015-19 박스권에서만 게이트 이득
나타남 (+3~+11%p). 시장 regime detection (6M KOSPI return, MA200 slope)
기반으로 박스권 구간에만 게이트 활성화.
- 인프라: `strategy_config.yaml::sector_gate` + `precompute_sector_tiers`
  이미 있음. `enabled` 를 regime-flag 로 교체
- 검증: 162종목 × 11.3년 백테 + 기간 분해 vs baseline
- 성공 조건: 전체 CAGR 유지 or 개선, MDD 악화 없음

**또는** 섹터 점수를 filter 대신 랭킹 가점으로 (RS + 섹터점수 가중합).

#### 4️⃣ 모니터링 대기
- **pykrx 인덱스 API 복구** → Weinstein Stage 25점 복원 (ADR-005)
- **`stocks_daily.parquet` 2026-04-30 확보** 후 재검증 (월말 경계 outlier)

#### 5️⃣ 이월
- **`_parse_sector_etf` 구 파서 cleanup** — 후속 커밋에서 제거 판단 (현재는
  안전망으로 존치, 구 fixture 테스트 19개 통과)
- **v3.3 Step 1 `base64.b64decode` 명시 패치 보류** (세션 #8) — Claude
  Project 가 morning_data 로드 시 우회 경로 택해 지연. 오늘은 결과 떴음,
  차 세션 재발 시 반영
- **Morning report Drive MCP → Notion code block 경로 전환 검토** — 구조적
  해결, Actions 워크플로 변경 1-2h 예상. 중장기 이월
- **브랜치 잔여 정리**: `phase3-backtest`, `fix-error-handling-riAYS`.
  워크플로 수정 포함 브랜치 4개는 보존 (action flow 규칙)
- ~~**CLAUDE Project 지침 v3.5 → v3.6 갱신**~~ ✅ **완료** (PR #12, `a1e6c92`)

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
  - **Amendment 3 (2026-04-23 #5)**: KOSPI200 11섹터 체계 전환 — 외부 리서치 v2026.04 기반. `ticker_overrides` 16→164 전면 재작성. 구 18 ETF 산식 폐기.
- [ADR-004] 섹터 게이트를 전략 진입 조건으로 통합 — **기각** — `docs/decisions/004-sector-gate-rejection.md`
  - 5 variant × 11.3년 × 162종목 백테. 전부 baseline +29.55% 하회 (최소 손해 D: -2.99%p, 주도+강세 C: -8.12%p).
  - 교훈: 회귀 알파 ≠ 전략 알파. Minervini 자체가 trend-filter 라 섹터 게이트와 상관되어 lag 만 추가.

## 최근 세션
- **2026-04-24 #3 (PC web → 데스크탑 핸드오프, main `7bf395e`)**: 전 세션 미머지 + 이월 작업 정리. (1) **#2 PR 생성 & 머지 완료** — 브랜치 상태 감사 후 어제 미머지 `session-start-hook-Lv8YN` 을 발견, 추가로 `7bf395e` cron 이 `+-0.00%` 버그로 HTML 렌더 단계 실패한 것 발견. **PR #11 `6c9ae79`** kr_report `-0.0` negative-zero 정규화 + parser 다중 부호 허용 regex fix 로 StopIteration 해소. (2) **PR #13 `f2ba529`** US 섹터 ETF 7→12개 확장 (GICS 11 + SOXX) + `US_SECTOR_META` + `_build_us_sector_summary` regime 판정 + multi-arrow regex fix + 3 테스트 추가. (`claude/continue-session-XRwjw` `da92cb3` 을 데이터파일 제외해 cherry-pick). (3) **PR #12 `a1e6c92`** Claude Project 지침 v3.5 → v3.6 (`claude/review-session-progress-jvYaw` `f8c9689` cherry-pick — parser fix 부분은 PR #13 과 중복이라 제외). 24/24 테스트 PASS. 로컬 main 정리 (`main-legacy-backup` 으로 옛 72커밋 + `generate_report.py` 보존 후 `origin/main` 에 맞춤). cron 자동 실행으로 `7bf395e Daily report PDF 2026-04-24` 까지 파이프라인 완주 → **워크플로 정상 복구 확인**. 남은 작업: (a) GitHub UI 에서 브랜치 7개 수동 삭제 (sandbox 403 제약), (b) Claude Project Files 4개 재업로드 (Instructions + parser + render + template), (c) UBATP 알림 시스템 rebase (별도 ancestry). CLAUDE.md 갱신은 `claude/session-end-2026-04-24-3` 브랜치에 커밋.
- **2026-04-24 #2 (PC web, branch `claude/session-start-hook-Lv8YN` `bdcd4fc`)**: 5 커밋 (main 머지 대기). (1) `92f20fc` SessionStart hook 추가 (web 환경 한정 `pip install -r requirements.txt` 자동화). (2) `ff064f8` parser/ACTION/CSS 3-in-1 fix — `_parse_grade_a` regex `(\d+일|🆕)` 얼터네이션 + `is_new` 필드 + 회귀 테스트 (#1 이월 bug 1건 해소), Executive Summary ACTION 분기 (#1 이월 bug 1건 해소), `.readiness-card` / `.portfolio-main` / `.sector-card` / `.context-col` + 섹션 헤더에 `page-break-*` + `break-*` 병기 (Chrome headless 기준 카드 찢김 방지, 두산에너빌리티 p4→p5 견본 검증). (3) `e16098f` 신규 편입 첫 도입 — `data.new_a_entries` 파생 + 🆕 뱃지 + 04·a 조건부 섹션. (4) `b48c324` preview 정리. (5) `bdcd4fc` **Entry Candidates 최상위 승격** — 백테 진입 규칙 (`entry: open_next_day`) 일치 종목만 강조, Section 04 Entry Candidates 신설 (항상 렌더 + 녹색 boundary + bull-bg-soft 그라디언트 + empty-state 메시지), 기존 04 Top 5 → 05 Trend Watch, 04·b/05/06/07 → 05·b/06/07/08 일괄 재번호. 28/28 테스트 PASS. 다음 cron-job.org 런 또는 manual workflow_dispatch 로 GH Actions Chrome 환경 PDF 검증 후 main 머지 PR.
- **2026-04-24 #1 (PC, main `7151030`)**: 체크리스트 라벨-값 붙음 버그 fix (공백+margin fallback, wkhtmltopdf CSS Grid 미지원 우회), PDF 페이지 분할 규칙 추가 (작은 블록에만 avoid 적용 → 빈 공간 최소화), `docs/.nojekyll` (pages-build-deployment 실패 해소), `morning.yml` schedule 재제거 (UZymn 회귀 복구 + 주석 방지), Claude Project 지침 v3.3 → v3.5 (Drive MCP `download_file_content` + base64 decode canonical path 명시, v3.4 "raw str" 가정 현실화). 6 커밋 main 머지. 다음 세션 이월 bug 2건: parser regex(🆕 이모지 미스매치) + 템플릿 ACTION 고정문구.
- **2026-04-23 #8 (PC, main)**: Claude Project 지침 v3.2 → **v3.3** 갱신 (plan-004 / ADR-003 Amend 3 / T10/CD60 / ADR-004 반영). 진입 게이트 3줄 신설 (Files 신선도 / shim 금지 / 포맷 고정), 필요 파일 5→7개 (sector_mapping / overrides / universe 추가), Step 3 `/tmp/backtest/` 패키지 구성, 절대 금지 4개 추가 (shim·ETF 관련). Claude Project Files 재업로드 후 삼성SDI "ETF 데이터 없음" 해소 확인. 삼성전기 반도체 분류는 2026 증권가 컨센서스와 일치 (iM·교보·하나·대신·Mirae 전부 FC-BGA/AI 기판 밸류체인 커버). Drive MCP base64 경유 병목은 v3.3 Step 1 패치 보류 (결과 떴으므로 차 세션 판단).
- **2026-04-23 #7 (PC, main)**: ADR-004 섹터 게이트 통합 실증 검증 → **기각**. `backtest/01_fetch_data.py` 복원 + 162종목 × 11.3년 pykrx 재수집 (74초), `01b_fetch_kospi_yf.py` 신규 (yfinance), `strategy_config.yaml::sector_gate` + `strategy.py::precompute_sector_tiers/check_sector_gate` 구현, `99_sector_gate_ab.py` + `99_sector_gate_variants.py` 5 variant 스윕. baseline +29.55% vs 최선 variant(D 약세만차단) +26.56% 로 모든 variant 악화. ADR-004 문서화 + CLAUDE.md 갱신.
- **2026-04-23 #6 (PC, UZymn → main)**: plan-004 완료 — sector_mapping 재작성(164 ticker_overrides + universe 역매핑), `_parse_sector_adr003` 신규, render_report 4-way 분기 재작성, 템플릿 sector_etf→sector_adr003. 27 pytest PASS + dry-run + UZymn 수동 트리거 검증. `morning.yml` workflow race 수정. UZymn → main 머지(`4477143`), 브랜치 8개 정리.
- **2026-04-23 #5 (UZymn, 웹)**: 11섹터 전환 — `reports/kospi200_sectors.tsv` 추가, `sector_overrides.yaml` ticker_overrides 164개 전면 재작성, `sector_report.py` 전면 재작성(414→226줄, 18 ETF 완전 폐기), `kr_report.py` import 버그 수정(check_minervini_detailed 누락) + 출력 문자열 T10/CD60/162종목 cleanup. HTML 렌더 재작성은 plan-004 이월.
- (2026-04-23 #4 이전 세션은 `SESSION_LOG.md` 참조)
- 이전 세션 (2026-04-23 #2-#3, 2026-04-22 Phase 3 완료 등) 은 `SESSION_LOG.md` 참조
