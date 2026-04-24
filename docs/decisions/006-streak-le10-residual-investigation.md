# ADR-006: signal_days ≤ 10 잔여 효과 조사 — Walkforward 검증 계획

- Status: **Proposed** (초안, 실험 미착수)
- Date: 2026-04-24
- Context session: 2026-04-24 #1
- Parent: ADR-005 §5 후속 과제
- Related: ADR-001 (T10/CD60), ADR-005 (entry timing)

## 1. 배경

ADR-005 실험 C (fresh-signal only, streak ≤ N) 에서 모든 변형이 baseline
하회하여 **signal_days 필터는 기각**. 그러나 `N=10` 변형만 **특이한 프로파일**
을 보여 잔여 조사 대상으로 분리.

### 1.1 실험 C 전체 결과 재게재

| max_streak | CAGR | MDD | 승률 | PF | 2015-19 | 2020-24 | 2025+ |
|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (무필터) | **+29.55%** | **-29.83%** | 42.3% | 2.21 | -2.05% | +35.26% | **+157%** |
| ≤ 1 | +18.72% | -41.96% | 35.5% | 1.79 | -3.69% | +19.78% | +119.35% |
| ≤ 2 | +22.54% | -41.01% | 39.0% | 1.97 | +0.54% | +26.39% | +101.11% |
| ≤ 3 | +18.75% | -54.30% | 36.3% | 1.79 | -8.78% | +26.05% | +112.67% |
| ≤ 5 | +25.84% | -43.21% | 38.1% | 2.15 | -6.89% | +41.93% | +100.27% |
| **≤ 10** | **+25.24%** | **-31.48%** | 40.8% | 2.09 | -4.25% | +25.62% | **+183.80%** |

### 1.2 ≤10 변형의 3가지 특이점

1. **MDD 방어**: -31.48% 로 baseline (-29.83%) 과 거의 동일. 다른 streak
   필터들은 -41 ~ -54% 로 평균 -12 ~ -24%p 악화되는데 **≤10 만 예외**.

2. **강세장 아웃퍼폼**: 2025+ 구간에서 +183.80% 로 **baseline +157% 초과**
   (+26%p). 다른 streak 변형은 모두 baseline 하회.

3. **전체 CAGR 차이 -4.3%p**: 대부분 박스권(2015-19)·중립(2020-24) 악화에서
   발생. 박스권은 -2.2%p, 중립은 -9.6%p 악화. 반면 2025+ 는 +26%p 개선 →
   **기간별 효과 방향이 다름**.

### 1.3 가능한 해석

| 가설 | 내용 |
|---|---|
| H1 통계적 우연 | 2025+ 아웃퍼폼이 특정 종목 1-2개 이상치 기여 |
| H2 regime-dependent alpha | 강세장에선 "신호 신선도 ≤10" 가 climax top 회피 효과 |
| H3 MDD 방어 메커니즘 | ≤10 필터가 "막판 추격 매수" 제한 → 최악의 drawdown 회피 |
| H4 Overfitting | 백테 기간 특이성. OOS 에선 재현 안 될 것 |

**본 ADR 의 목적**: H1~H4 중 어느 것이 참인지 실증하여, **signal_days ≤ 10
필터 채택 여부** 최종 결정.

## 2. 검증 계획

### 2.1 실험 E — Walkforward IS/OOS 분해

**목적**: 2025+ 아웃퍼폼이 데이터 snooping 인지 재현 가능한 알파인지 판별.

**설계**:
- 기간 분할:
  - Train window 1: 2015-2019 (5년)
  - Test window 1: 2020-2022 (3년)
  - Train window 2: 2015-2022 (rolling)
  - Test window 2: 2023-2025 (3년)
- 각 window 에서 baseline vs ≤10 variant CAGR/MDD 비교
- OOS 가 IS 와 일관된 방향이면 재현 알파, 불일치면 overfitting

**수용 기준**:
- 모든 OOS window 에서 ≤10 가 baseline CAGR 대비 **-3%p 이내** 유지
- 모든 OOS window 에서 MDD 가 baseline 대비 **-2%p 이내** (악화 허용폭)
- 최소 1개 OOS 에서 ≤10 가 baseline 을 **유의하게 개선**

### 2.2 실험 F — Bootstrap 재표집 (2025+ 구간)

**목적**: 2025+ +183.80% 의 분산 구조 파악. 1-2개 대박 종목 기여인지 광범위
알파인지.

**설계**:
- 2025-01-01 ~ 2026-04-23 의 ≤10 trade log 확보 (실험 C 로 이미 생성됨)
- Bootstrap 1000회 재표집 (sample with replacement):
  - 각 재표집에서 CAGR 재계산
  - 95% 신뢰구간 측정
  - trade 상위 n% 제외 시 CAGR 민감도

**수용 기준**:
- CAGR 95% CI 하한 > baseline 2025+ CAGR → 통계적 우위 인정
- 상위 5 trade 제외 시에도 baseline 초과 → 광범위 알파
- 1-2 종목 기여가 지배적 → H1 (우연) 로 수렴

### 2.3 실험 G — 민감도 확장 (N=7,8,9,10,11,12)

**목적**: ≤10 이 유일한 sweet spot 인지 smooth plateau 인지 파악.

**설계**: 실험 C 와 동일 엔진, max_streak 를 {7,8,9,10,11,12} 로 확장.

**예상 결과 해석**:
- plateau (≤9~12 모두 유사): 재현 가능 알파 가능성 ↑
- ≤10 만 단독 spike: overfitting / local anomaly

### 2.4 실험 H — MDD 기여 trade 분해

**목적**: ≤10 이 MDD 를 방어하는 기전이 무엇인지 확인.

**설계**:
- baseline trade log 에서 최대 drawdown 발생 기간 (예: 2022년) 식별
- 해당 기간 baseline vs ≤10 의 포지션 구성 비교
- signal_age ≥ 11 인 종목이 실제로 draw down 주범인지 검증

## 3. 의사결정 트리

```
실험 E (walkforward)
├── OOS 모든 window 에서 수용 기준 충족
│   └── 실험 F (bootstrap) 로 분산 확인
│       ├── 95% CI 하한 > baseline
│       │   └── ★ ADR-006 Accepted: ≤10 채택
│       │       (strategy_config.yaml 에 max_streak 옵션 추가)
│       └── CI 하한 < baseline
│           └── 실험 G 로 plateau 검증
│               ├── plateau 확인 → Accepted
│               └── spike 단독 → Rejected (H1 수렴)
└── OOS window 중 1개라도 수용 기준 미달
    └── Rejected — ADR-005 최종 결론 확정
```

## 4. 검토한 대안

### 4.1 즉시 채택 (실험 없이)
- 실험 C 단독 샘플만으로 채택: 통계적 근거 부족. **기각**.

### 4.2 regime-dependent 변형 (시장 국면 판정 후 ≤10 토글)
- 박스권·중립: ≤10 미적용 / 강세장: ≤10 적용
- ADR-005 후속 §5 에 이미 "ADR-005 후보 — 박스권 조건부 섹터 게이트" 와
  유사한 regime 기반 접근
- **실험 E/F 결과에 따라 ADR-009 후보로 분리** (본 ADR 범위 밖)

### 4.3 ≤10 을 signal age cap 이 아닌 RS 페널티로 변환
- signal_age > 10 인 candidate 의 RS 점수를 N%p 할인 → 완전 차단이 아닌
  부드러운 후순위화
- 본 ADR 범위 밖 (별도 ADR 후보)

## 5. 구현 범위 (실행 시)

- `backtest/experiments/exp_e_walkforward_streak10.py` — 실험 E
- `backtest/experiments/exp_f_bootstrap_2025.py` — 실험 F
- `backtest/experiments/exp_g_streak_sensitivity.py` — 실험 G
- `backtest/experiments/exp_h_mdd_attribution.py` — 실험 H
- 공통 엔진: 기존 `backtest/experiments/engine.py` 재사용
- 결과 통합: `results/adr006_summary.csv`

## 6. 작업 시간 추정

| 실험 | 예상 시간 |
|---|---:|
| E walkforward | 1.5h (코드 1h + 실행 30m) |
| F bootstrap | 0.5h (trade log 기반 재계산) |
| G sensitivity | 0.5h (엔진 재활용) |
| H MDD 분해 | 1h (분석 중심) |
| 종합 + ADR 업데이트 | 0.5h |
| **합계** | **~4h** |

우선순위: E → F → G → H 순. E 에서 Rejected 판정 나면 나머지 단계 건너뛰고
ADR 마무리 가능 (최단 1.5h).

## 7. 현재 단계 (2026-04-24)

- [x] 문제 정의 (본 문서)
- [ ] 실험 E/F/G/H 구현 + 실행 (차 세션)
- [ ] 결과 기반 Status 업데이트 (Accepted / Rejected)
- [ ] 채택 시 `strategy_config.yaml` 변경 + Instructions v3.6 반영

## 8. 참조

- `backtest/experiments/exp_c_fresh_signal_only.py` — 실험 C 원본 (≤10 trade log 재사용)
- `backtest/experiments/results/exp_c_sensitivity.csv` — 실험 C 통합 결과
- `docs/decisions/005-entry-timing-diagnosis.md` §5 후속 과제 4번
