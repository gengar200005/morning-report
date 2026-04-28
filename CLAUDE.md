# morning-report

<!-- Last session branch: claude/analyze-code-8HvmQ (2026-04-28 #2) -->

한국 모닝리포트 자동 생성 + Phase 3 백테스트 (Minervini+수급+게이트 전략) 프로젝트.

---

## 현재 상태 (2026-04-28)

**Phase 4 실전 준비 — 라이브 universe KOSPI 200 확장 + augmentation 분업 frame
(B) + Claude Code `/analyze` 슬래시 명령 이식**. 페이퍼 트레이딩 인프라 셋업이
여전히 다음 진입점 1순위 (본 세션 우회됨).

**운영**: 매일 06:25 KST `morning.yml` cron 단발 → 데이터 수집 (KIS API 200종목,
~30~40분) → HTML 렌더 → PDF 변환 → Drive 업로드 → Notion publish. **+
augmentation 흐름**: cron 끝 ~07:00 KST 마스터가 Claude Code 세션 → `/analyze`
한 줄 → 7카드 JSON main commit → `claude_render.yml` 자동 트리거 → PDF
재렌더 + Drive + Notion 갱신.

**오늘 (2026-04-28) 핵심 작업**:
- **KOSPI 200 라이브 확장** (162 → 200): `kr_report.py::UNIVERSE` 200 +
  `sector_overrides.yaml::ticker_overrides` 234 (KOSPI 200 100% + stale 34
  보존). 백테 universe (162) 는 시점 고정 스냅샷 유지. workflow_dispatch
  검증 OK — 신규 70종목 (한미반도체/산일전기/대한전선/HD현대일렉트릭/엘앤에프
  등) §04·b Remaining 정상 노출.
- **Claude augmentation 분업 frame (B 채택)**: ADR-009 (04-26 폐기) 부분
  reversal. 룰=자동 / 인간 판단 (매크로/사이즈/심리)=인간 / 7카드=인간 판단
  영역 저널 거울. **마스터 1주 자체 점검 후 NO 면 즉시 A (전면 폐기) 전환**.
- **`/analyze` 슬래시 명령** (`.claude/commands/analyze.md`): web Project 의
  GitHub commit 권한 막힘 우회 + Claude Code 이식. v5.1 instruction 기반,
  로컬 morning_data.txt 직접 읽기 + git push 단순화.
- **결정 인박스 도입** (`docs/decisions/_inbox.md`): 세션 뻗음 mitigation,
  자동 push 예외 허용 (운영 규칙 명문화).
- **v3 entry 카드 패턴**: 산업군 비교 펀더 + WebSearch 5종목 컨센서스 +
  컨센 추월 경계 ⚠️ + 출처 인용. PDF 페이지 8 정상 주입.
- **거래량 기반 종목 선정 / sizing 백테 — ADR-012 기각** (#2 세션):
  `backtest/99_volume_selection.py` 4종 비교 (baseline +30.19% / V1a sel
  거래대금 +19.93% / V1b sel 거래량 +22.11% / V1c sizing 비례 +25.23%) 전부
  FAIL. V1a 박스권 +4.50%p 부산물 → V1c (selection 동일) 박스권 -0.28%p 로
  selection noise 판명. ADR-010 5번째 사례 추가. 알파 추구 자원은 페이퍼
  트레이딩 1순위로 복귀 정당화.

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

#### 1️⃣ ★ 페이퍼 트레이딩 인프라 셋업 (여전히 1순위, 본 세션 우회됨)

알파 추구 4번 연속 기각 (ADR-005/004/001/010) 후 자연스러운 다음 단계.
04-28 세션은 KOSPI 200 universe + augmentation 이식 작업으로 우선순위 양보.
구성 요소:
- Notion DB 1개 생성 (저널: 진입가/청산가/사유/심리 점수 1~5)
- 자동화 미니 모듈 (`backtest/strategy.py` 실시간 모드 → 가상 포지션 추적,
  STOP_LOSS/TRAIL/cooldown 자동 진행)
- 일일 PDF 첫 페이지에 "현재 페이퍼 포지션 / 누적 수익률" 카드 추가 검토
- **운영 모델 선택**: (a) 100% 페이퍼 6개월, (b) 자본 10-15% 실전 + 페이퍼 5종목
  풀 절충 — 마스터 FOMO ("강세장 6개월 안에 끝날까") 감안 시 (b) 권장.
- 통과 기준: 백테 대비 CAGR ±3-5%p / 신호→진입 지연 median ≤ 5일 / 심리 점수 ≥ 3.5

#### 2️⃣ `/analyze` 슬래시 명령 v3 가이드 보강

`.claude/commands/analyze.md` 에 v3 톤 가이드 추가:
- 산업군 비교 펀더 평가 (반도체 ROE 30% vs 유틸리티 ROE 10% 임계 다름)
- WebSearch Top 5 종목 컨센서스 + 출처 인용 의무
- 컨센 추월 경계 ⚠️ 명시
- v5.1 의 "1-3 문장 strict" → Project 톤 (한 문장 진단 + 종목별 비고 +
  액션 환기) 매칭

#### 3️⃣ 본 브랜치 → main PR

`claude/track-kospi-200-stocks-s54c2` 의 KOSPI 200 + /analyze 슬래시 +
_inbox + 운영 규칙 변경 main 머지. 마스터 명시 승인 시.

#### 4️⃣ Claude augmentation B 옵션 1주 자체 점검

"오늘 분석 도움됐나" 매일 1회 자체 점검. NO 면 즉시 A (전면 폐기) 전환.
1주 (~05-04) 후 정식 평가 → ADR-012 정식화 or ADR-009 재확인.

#### 5️⃣ ADR 후보 3건 (마스터 결정)

- ADR-011 결정 인박스 운영 원칙
- ADR-012 augmentation 분업 frame (ADR-009 보완 / 부분 reversal)
- ADR-013 라이브 universe ↔ 백테 스냅샷 분리

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
- ~~**박스권 보호 +10%p 의 다른 채널** (sizing / risk parameter)~~ — 거래대금
  비례 sizing 채널은 ADR-012 로 무효 확정. RS 점수 가중 / stop_loss 완화 채널은
  페이퍼 후 검토 (잔존 후보)

### 기각 / 종료 (ADR 또는 SESSION_LOG 보존)
- ❌ **VCP 자동 필터** (ADR-001, 162 재검증으로 강화 — SESSION_LOG 04-26 #2)
- ❌ **섹터 게이트 무조건** (ADR-004)
- ❌ **fresh-signal entry timing 필터** (ADR-005)
- ❌ **streak≤10 필터** (ADR-006)
- ❌ **UBATP 장중 알림** (ADR-007)
- ❌ **Section 04 Entry Candidates UI** (ADR-008)
- ❌ **Claude augmentation** (ADR-009)
- ❌ **박스권 조건부 게이트** (ADR-010 안에 흡수 — 검증 결과 + 메타 원칙)
- ❌ **거래량 selection / sizing 양 채널** (ADR-012, V1a/V1b/V1c 모두 baseline
  깎음 — 박스권 +4.50%p 부산물은 selection noise 로 판명)
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
- **ADR-012** 거래량 selection / sizing 양 채널 무효 — **채택** (ADR-010 5번째
  사례). V1a (sel 거래대금) / V1b (sel 거래량) / V1c (RS sel + 거래대금 비례
  sizing) 3종 모두 baseline (+30.19%) 깎음 — 전체 -4.96 ~ -10.26%p / V1c MDD
  -11.0%p 악화. V1a 박스권 +4.50%p 부산물은 V1c 동일 종목 진입 (거래 104→104)
  + 박스권 -0.28%p 로 selection noise 판명, 재현성 0. 박스권 보호 sizing 채널
  중 거래대금 가중 항목 종료. RS 점수 가중 / stop_loss 완화는 잔존 후보.

---

## 최근 세션
- **2026-04-28 #2 (web, branch `claude/analyze-code-8HvmQ`)**: 거래량 기반
  종목 선정 / sizing 가설 1회 검증 → ADR-012. `backtest/99_volume_selection.py`
  신규 (self-contained, strategy.py 단일 소스 보존). 4종 비교 (baseline /
  V1a sel 거래대금 / V1b sel 거래량 / V1c RS sel + 거래대금 비례 sizing) 전부
  FAIL. **핵심 발견**: V1a 박스권 +4.50%p 부산물은 V1c (selection 동일, 거래
  104→104) 박스권 -0.28%p 로 selection noise 판명. ADR-010 본문에 미해결로
  남았던 sizing 채널 중 거래대금 가중 항목 검증 종료. 알파 추구 5번째 fail
  사례 + 페이퍼 트레이딩 1순위 복귀 정당화.
- **2026-04-28 (web, branch `claude/track-kospi-200-stocks-s54c2`)**:
  KOSPI 200 라이브 universe 확장 (162 → 200, 백테 162 스냅샷 유지) +
  sector_overrides 234 (신규 70종목 11섹터 매핑) + Claude augmentation 분업
  frame (B 채택, ADR-009 부분 reversal — 7카드=인간 판단 영역 저널 거울,
  1주 자체 점검 후 NO 면 즉시 A 전환) + `/analyze` 슬래시 명령 도입
  (`.claude/commands/analyze.md`, web Project commit 권한 막힘 우회) +
  결정 인박스 (`docs/decisions/_inbox.md`, 자동 push 예외) + v3 entry 카드
  (산업군 펀더 + WebSearch 컨센서스 + 출처). PDF 페이지 8 정상 주입 검증.
- **2026-04-26 #2 (PC CLI worktree `claude/elated-tu-ec63ef`)**: 알파 추구 1차
  종료. VCP 162 재검증 → ADR-001 기각 강화 (-21.35%p). ADR-010 박스권
  조건부 게이트 6 variant → 기각 (강세장 false positive + robustness FAIL).
  ADR-005/004/001/010 4번 연속 "추가 필터 baseline 깎음" 패턴 확정. 코드
  변경 전부 revert.
- **2026-04-26 #1 (PC CLI, `claude/interesting-kapitsa-d40f52`)**: 04-25 web
  사고 fix + Notion CI 자동화 + Instruction v5.0→v5.1 + Claude augmentation
  폐기 (A 옵션) 결정. v5.1 + claude_render 인프라 미래 재시도용 보존.
- **2026-04-25 (web, `claude/v3.9-data-integrity` → main `775ba0b`)**: ADR-008
  Section 04 Entry Candidates 폐기 (Trend Watch §04 복귀, PR #19) +
  Instruction v3.6→v3.9 3사이클 (Step 0 날짜 고정 + Step 1 무결성 가드 +
  ALERT 11 + 데이터 무결성 섹션, PR #20).
- **2026-04-24 (PC, offline, main `339d373`)**: ADR-005/006/007 일괄 결정 +
  drift 사고 복구 + session-start/end 스킬 git fetch 자동화. PR #16 머지.
