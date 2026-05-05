# ADR-015: 스크리닝 state 갱신 시점 — `holdings_report.py` 우선 실행 의무

**날짜**: 2026-05-05
**상태**: 채택
**관련**: `morning.yml`, `kr_report.py::update_screening_state`,
`tests/test_screening_state_lag.py`, ADR-001 (T10/CD60 재확정)

## 배경

T10/CD60 전략의 **쿨다운 60거래일** 룰은 청산된 종목이 다음 cron 시점에
다시 진입 후보로 올라오지 않도록 보장하는 핵심 안전장치다. 그러나 동일 패턴의
쿨다운 누락 사고가 **2회 반복**:

| 일자 | 종목 | 패턴 | 결과 |
|---|---|---|---|
| 2026-04-30 | APR (278470) | stop loss + A 등급 유지 | `last_exit_date` 미기록, 다음 cron 에서 진입 후보로 재등장 |
| 2026-05-05 | 대우건설 (047040) | 매도 + A 등급 유지 | 동일. `_held_tickers` 도 어제값 그대로 |

첫 번째 사고 후 **fix commit `10e6c16`** (2026-05-01) 가 두 가지 패치:
1. `compute_cooldown_remaining` 의 "A/B 등급 복귀 시 쿨다운 해제" 로직 제거
2. `read_current_holdings()` 추가 + `update_screening_state` 에 `held_tickers`
   파라미터 추가 → 어제 보유→오늘 미보유 감지

그러나 **root cause 미해결** → 4일 만에 동일 패턴 재발.

## Root Cause

`morning.yml` step 순서:

```
Step 2: kr_report.py        ← screening + state 갱신 (read_current_holdings 호출)
Step 3: sector_report.py
Step 4: holdings_report.py  ← holdings_data.txt 갱신 (실제 오늘 보유)
Step 5: combine_data.py
```

**`kr_report.py` (Step 2) 가 `holdings_report.py` (Step 4) 보다 먼저 실행됨.**

GH Actions runner 는 매 run 마다 fresh checkout 으로 시작 — Step 2 시점에
`holdings_data.txt` 는 **어제 cron 결과**. 따라서 `read_current_holdings()` 가
읽는 것은 어제 보유 종목 set.

`update_screening_state` 의 청산 감지 로직:

```python
prev_held = set(state.get("_held_tickers", []))      # 어제 cron 끝의 _held_tickers
exited = prev_held - held_tickers                     # held_tickers = 어제 holdings_data.txt
# → 동일한 어제 데이터 비교 → exited = ∅ → 청산 감지 무용지물
```

오늘 실제 보유 (3종목) 와 어제 _held_tickers (4종목) 의 차이 = 047040 — 이걸
잡는 logic 자체가 시점 미스매치로 **never reachable**.

### 왜 등급 이탈 fallback 이 안 잡았나

`update_screening_state` 의 두 번째 loop:

```python
if last_hg and (not last_ex or last_hg > last_ex):
    state[tk]["last_exit_date"] = today_str
```

이건 **A/B → C/D 등급 하락** 시에만 작동. 청산된 종목이 A/B 등급 유지 중이면
fallback 도 미작동. NH(005940) 같은 "보유 빠짐 + 등급 이탈" 동시 발생 케이스는
fallback 으로 잡혔지만, APR/대우건설 같은 "보유 빠짐 + A 등급 유지" 케이스는
양쪽 모두 미작동 → 누락.

### 왜 10e6c16 fix 가 못 막았나

10e6c16 는 `update_screening_state` 의 **logic** 만 추가했고, 데이터 입력 시점
(= `morning.yml` step 순서) 은 그대로. 추가된 logic 에 **stale 한 어제 파일이
입력**되므로 새 logic 도 무용지물. 수동 state 보정으로 즉시 증상은 해소했으나
시스템적 root cause 미발견 → 반복.

## 결정

### 1. `morning.yml` step 순서 의무

`holdings_report.py` 는 `kr_report.py` **보다 반드시 먼저 실행**한다.
의존 관계: `kr_report.py::read_current_holdings()` → `holdings_data.txt` →
`holdings_report.py` 의 출력.

```
Step 1: morning_report.py     (미장)
Step 2: holdings_report.py    ← 먼저 실행, holdings_data.txt 갱신
Step 3: kr_report.py          ← 갱신된 holdings_data.txt 읽음
Step 4: sector_report.py
Step 5: combine_data.py
```

### 2. 회귀 방지 테스트 의무

`tests/test_screening_state_lag.py` 추가:
- "보유 빠짐 + A 등급 유지" 패턴 mock 입력 시 `last_exit_date` 정상 기록 검증
- 동일 입력에서 `_held_tickers` 정상 갱신 검증
- step 순서 위반을 시뮬레이트한 stale-input 케이스에서 **누락 재현** → 운영
  step 순서 의존을 명시적으로 문서화

### 3. 인프라 변경 시 점검 의무

`morning.yml` 수정 시 본 ADR 을 reference 로 참고. step 순서 변경이 필요하면
다음 항목을 사전 검토:
- `read_current_holdings()` 호출 step 이 `holdings_report.py` 뒤에 있는가
- 다른 state 갱신 script 에서도 동일 시점 의존 위반이 없는가

## 결과

- `morning.yml` step 2-4 순서 swap (holdings_report 우선).
- `screening_history.json` 수동 보정: `047040.last_exit_date = "2026-05-05"`,
  `_held_tickers` 에서 047040 제거.
- `tests/test_screening_state_lag.py` 신설.
- 다음 cron (2026-05-06 06:25) 부터 정상 동작 확인.

## 회귀 사고 trigger 조건 (운영 모니터링)

다음 패턴 발견 시 본 ADR 위반 의심:
- `screening_history.json` 의 `_held_tickers` 가 어제값 그대로
- 어제 보유 종목이 모닝 리포트 A/B 등급 list 에 쿨다운 표시 없이 등장
- 특히 **A/B 등급 유지된 채 보유에서 빠진 종목** 의 다음날 진입 후보 재등장
