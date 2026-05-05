# ADR-015: 스크리닝 state 갱신 시점 — 두 layer 의존 명문화

**날짜**: 2026-05-05 (Layer 1) · 2026-05-06 확장 (Layer 2)
**상태**: 채택
**관련**: `morning.yml`, `kr_report.py::screen_stocks` /
`update_screening_state_holdings` / `update_screening_state_grades`,
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

## Layer 2 — `screen_stocks` 내부 cooldown 계산 시점 (2026-05-06 추가)

PR #34 의 step swap 만으로도 1일 lag 이 잔존함이 5/6 cron 검증에서 드러남:

5/6 cron 결과:
- `state.047040.last_exit_date = "2026-05-06"` 자동 기록 (1일 lag 으로 잡힘)
- 그러나 **`morning_data.txt` 의 minervini A등급 list 에 047040 쿨다운 표시 X**

원인은 `kr_report.py::screen_stocks` 의 흐름:

```python
state = load_screening_state()                  # ① 어제 cron 끝 state
for code in UNIVERSE:
    cooldown_rem = compute_cooldown_remaining(state, code, today_date)  # ② ① 시점 state 기준
    results.append({"쿨다운잔여": cooldown_rem})
held_tickers = read_current_holdings()
state = update_screening_state(state, ..., held_tickers=...)            # ③ state update
save_screening_state(state)
```

② 가 ③ 보다 먼저 실행 — cooldown 은 update **이전** state 로 계산됨. 따라서:

- `morning_data.txt` 의 cooldown 표시는 어제 cron 끝의 state 를 기준 → 1일 lag.
- `screening_history.json` 은 today's update 결과 → 다음 cron 부터만 정상 표시.

step swap (Layer 1) 은 ③ 의 입력 (held_tickers) 을 fresh 로 만들 뿐, ② 와의
순서는 그대로. → **Layer 1 만으로는 same-day 표시 보장 불가**.

## 결정

### 1. `morning.yml` step 순서 의무 (Layer 1)

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

### 2. `screen_stocks` 내부 호출 순서 의무 (Layer 2)

`update_screening_state` 를 두 함수로 분리:
- `update_screening_state_holdings(state, today_str, held_tickers)` — 청산 감지
- `update_screening_state_grades(state, high_grade_today, today_str)` — 등급 갱신

`screen_stocks` 흐름:

```python
state = load_screening_state()
held_tickers_today = read_current_holdings()
state = update_screening_state_holdings(state, today_str, held_tickers_today or None)
                                                      # ↑ cooldown 계산 전 의무

for code in UNIVERSE:
    cooldown_rem = compute_cooldown_remaining(state, code, today_date)
                                              # ↑ 갱신된 state 사용 → same-day 표시
    ...

high_grade_today = {... for r in results if r["등급"] in ("A", "B")}
state = update_screening_state_grades(state, high_grade_today, today_str)
                                              # ↑ 등급 fallback 은 results 후 적용
save_screening_state(state)
```

기존 `update_screening_state(state, high_grade, today, held_tickers=...)` 는
레거시 wrapper 로 보존 (외부 호출자 / 회귀 테스트 동치성 검증).

### 3. 회귀 방지 테스트 의무

`tests/test_screening_state_lag.py`:
- Layer 1: fresh holdings 정상 / stale holdings 실패 documented / held=None 스킵 /
  등급 이탈 fallback / 무변동 종목 보존
- Layer 2: holdings update 후 cooldown 계산 시 잔여 표시 / cooldown 계산이
  holdings update 전이면 잔여 미표시 (위반 패턴) / 분리 함수 vs 레거시
  wrapper 동치성

### 4. 인프라 변경 시 점검 의무

`morning.yml` 또는 `screen_stocks` 수정 시 본 ADR 을 reference 로 참고:
- `read_current_holdings()` 호출 step 이 `holdings_report.py` 뒤에 있는가 (Layer 1)
- `update_screening_state_holdings` 가 cooldown 계산 (`compute_cooldown_remaining`)
  보다 먼저 호출되는가 (Layer 2)
- 다른 state 갱신 script 에서도 동일 시점 의존 위반이 없는가

## 결과

- `morning.yml` step 2-4 순서 swap (holdings_report 우선) — Layer 1.
- `kr_report.py` 의 `update_screening_state` 분리 (`_holdings` / `_grades`)
  + `screen_stocks` 흐름 재구성 (cooldown 계산 전 holdings update) — Layer 2.
- `screening_history.json` 수동 보정: `047040.last_exit_date = "2026-05-05"`,
  `_held_tickers` 에서 047040 제거.
- `tests/test_screening_state_lag.py` 신설 (8케이스, Layer 1·2 모두 검증).
- 다음 cron (2026-05-07 06:25) 부터 same-day 쿨다운 표시 정상 작동 확인.

## 회귀 사고 trigger 조건 (운영 모니터링)

다음 패턴 발견 시 본 ADR 위반 의심:
- `screening_history.json` 의 `_held_tickers` 가 어제값 그대로 → Layer 1 위반
- 어제 보유였다가 오늘 빠진 종목이 **same-day** morning_data.txt 의 minervini
  list 에 쿨다운 표시 없이 등장 → Layer 2 위반
- 특히 **A/B 등급 유지된 채 보유에서 빠진 종목** 의 다음날 진입 후보 재등장
