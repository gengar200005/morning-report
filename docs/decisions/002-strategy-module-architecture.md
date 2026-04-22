# ADR-002: strategy.py / yaml 단일 소스 아키텍처 도입

**날짜**: 2026-04-22
**상태**: 채택

## 배경

리팩토링 전 프로젝트 상태:
- `kr_report.py` (라이브 스크리닝): Minervini 8조건을 inline 구현, 파라미터 하드코딩
- `backtest/99_minervini_vcp_compare.py` (백테): 같은 로직을 별도로 재구현
- 두 파일의 파라미터가 **별도로 관리됨**

발견된 drift 사례:
- 2026-04-22 세션 중 확인 결과, **kr_report.py가 구 확정값 T15/CD120을
  하드코딩 그대로 사용 중**이었음:
  - `STRATEGY_TRAIL_STOP = 0.15` (백테 확정은 0.10)
  - `STRATEGY_COOLDOWN_D = 170 달력일` (백테 확정 60거래일 ≈ 87 달력일)
- 사용자는 추천 결과만 봐서 이 불일치를 감지 불가
- 파라미터 변경이 **백테/라이브 양쪽에 동시 반영되지 않는 구조적 취약점**

추가로 시그널 로직 자체에도 미세 차이 존재 가능:
- 52주 윈도우 계산: 백테 `c[max(0, i-252):i]`, 라이브 `closes[-252:]`
- 경계 처리 1일 차이 → 특정 날짜에 다른 종목이 뜰 수 있음

## 결정

**strategy.py / strategy_config.yaml 을 단일 소스로 도입.**

```
backtest/strategy_config.yaml   ← 파라미터 단일 소스
        ↓
backtest/strategy.py            ← 로직 단일 소스
        ↓                              ↓
backtest/99_*.py              kr_report.py
```

### 이관 내용

**`strategy_config.yaml`** — 모든 파라미터:
- 시그널 (Minervini 조건 threshold, RS min, 수급 비율, 시장 게이트 MA)
- 리스크 (stop_loss, trail_stop, max_hold_days, max_positions)
- 쿨다운 (cooldown_days)
- 실행 (cost, entry/exit timing, warmup)

**`strategy.py`** — 모든 로직:
- `load_config()` — yaml 로드
- `check_minervini_detailed(c, i, cfg)` — 8조건 상세 결과 반환
- `check_minervini_core(c, i, cfg)` — 불린만 반환 (내부에서 detailed 호출)
- `check_supply(v, c, i, cfg)` — 수급 프록시 (up/dn volume)
- `check_market_gate(kospi, i, cfg)` — 코스피 MA60
- `check_signal(c, v, i, rs_pct, cfg)` — 전체 시그널 통합
- `run_backtest(dates, stocks, kospi, cfg, ...)` — 포트폴리오 엔진
- `calc_metrics(eq, trades, start, end)` — CAGR/MDD/PF 계산
- CLI 지원 (`python backtest/strategy.py` → 확정 백테 실행)

### 리팩토링

- `99_minervini_vcp_compare.py`: strategy.py delegate, 그리드 스윕/리포트만 유지
- `99_walkforward.py`: 변경 없음 (importlib로 99_*.py 간접 import)
- `kr_report.py`:
  - `STRATEGY_*` 상수를 yaml 로드로 교체
  - Minervini 8조건을 `check_minervini_detailed` 호출로 교체
  - `check_core_at`을 `check_minervini_core` delegate

### 검증

- `python backtest/strategy.py` → CAGR +29.29%, MDD -29.83% 재현 ✅
- `python backtest/99_minervini_vcp_compare.py` → 리팩토링 전 로그와 diff 0바이트 ✅

## 대안

### ❌ 별도 `constants.py` 만 만들고 로직은 그대로
파라미터 drift만 해결하고 로직 drift는 그대로. 52주 계산 1일 차이 같은
미세 bug가 숨을 수 있음. 반쪽짜리 해결.

### ❌ `kr_report.py` 그대로 두고 백테만 모듈화
라이브 ↔ 백테 불일치가 가장 큰 문제. 이걸 해결 못하면 리팩토링 가치 없음.

### ❌ 모든 것을 `backtest/` 밖으로 이동
`backtest/strategy.py`는 기존 디렉터리 구조 존중. 라이브(`kr_report.py`)가
`backtest/`를 import 하는 구조가 다소 어색하지만, 별도 `lib/` 같은 디렉터리
신설은 변경 범위 과도. 현재 상태로 충분.

### ❌ YAML 대신 Python constants 파일
YAML은 사람이 편집하기 좋고 주석 지원. 실험 시 `cp config.yaml config_v2.yaml`
한 줄로 A/B 테스트 가능. Python constants는 import 순서/순환 import 위험.

## 결과

### 긍정적
- **백테 확정 = 라이브 추천** 자동 동기화
- 파라미터 변경 한 곳 (yaml) → 양쪽 자동 반영
- 로직 수정 한 곳 (strategy.py) → 양쪽 자동 반영
- 과거 drift 버그 제거 (kr_report T15 → T10)
- yaml이 곧 문서 (주석 포함) → 신규자 온보딩 쉬움
- 실험 용이: `strategy_config_v2.yaml` 복사 후 수정

### 부정적
- 추상화 1단계 추가 → "yaml 어디 있지?" 한 단계 더 탐색
- yaml 오타 시 런타임 에러 (예: `rs_min` → `rs_mim`)
- `backtest/` 디렉터리를 `kr_report.py`가 import 하는 모양이 다소 어색
  (디렉터리 구조 차후 개선 여지)

### 후속 작업
- ⏳ kr_report의 수급 로직(KIS 외인/기관)과 strategy.check_supply(up/dn vol)
  일관성 검토 — 의도적 차이인지 재확인 필요
- ⏳ 전략 A/B 테스트 프레임워크 (여러 yaml 동시 비교)
- ⏳ yaml 스키마 검증 (pydantic 등)으로 오타 방지
