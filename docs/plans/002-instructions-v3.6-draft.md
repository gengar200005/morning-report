# Instructions v3.6 변경사항 제안 초안

- Source: ADR-005 결과 반영
- Status: **Proposed** (마스터 승인 대기)
- Date: 2026-04-24

## 변경 의도

v3.5 (가상)까지는 "백테 +29.29% CAGR / 실전 기댓값 +15-20%" 수치만 명시되어
있었고, **백테↔실전 괴리의 원천** 에 대한 설명이 없었음. v3.6 은 실험 결과를
반영해:

1. 실전 기댓값 산출 근거 (체결 타이밍 손실 -6.7%p 명시)
2. "Extended 진입은 정상" 규정 추가 (운영 규약에 fresh-only 자체 규칙 금지)
3. signal_age 관련 해석 가이드 (리포트 Top 5 에 signal_age 10+ 종목이 섞이는
   것은 정상이며, baseline 이 같은 분포로 알파 생성)

## v3.3 → v3.6 Diff 제안

### 추가: 진입 게이트 #4 (새로 생성)

```
#4. Extended 진입 우려 응답 금지
  - 사용자가 "리포트의 RS Top 5 가 이미 signal_age 10일 넘어간 종목들인데
    괜찮은가?" 류 질문 시, **ADR-005 실증으로 정상** 임을 알림.
  - baseline median signal_age = 6일, p90 = 23일. Fresh-only 필터 강제 시
    CAGR -10.8%p, MDD -24.5%p 악화됨 (실험 C 결과).
  - "signal_days ≤ N 필터 도입" 같은 우회 제안도 금지. ADR-005 §4.3 참조.
```

### 수정: 확정 전략 파라미터 블록

**v3.3 원문**:

```
[리스크 파라미터]
- stop_loss 7% / trail_stop 10% / cooldown 60d / max_pos 5
- 백테 CAGR +29.29% / MDD -29.8% / 실전 기댓값 +15-20%
```

**v3.6 제안**:

```
[리스크 파라미터]
- stop_loss 7% / trail_stop 10% / cooldown 60d / max_pos 5
- 백테 CAGR +29.55% (익일 시가 체결, 162종목 × 11.3년, 2026-04-23 재수집)
  - 당일 종가 체결로 현실화 시 +22.85% (ADR-005 B1)
  - 추가 슬리피지·세금·생존편향 -3~7%p → 실전 기댓값 +15-20%
- MDD -29.8%
- 알파 분해: 필터(Minervini+수급+RS≥70) +25.8%p / 체결 타이밍 +6.7%p
  - 체결 알파는 실전화 시 소실, 필터 알파가 실전 알파의 본체
```

### 수정: 절대 금지 (v3.3 4개 → v3.6 5개)

기존 4개 유지 + 1개 추가:

```
5. 자체 재량으로 "signal_age ≤ N" 필터 또는 "fresh signal only" 규칙을
   전략·리포트 어느 쪽에도 도입 금지. ADR-005 에서 모든 변형이 baseline
   하회 실증됨. 도입 제안은 반드시 마스터 승인 후 별도 ADR 로.
```

### 추가: 자체 체크 항목 (v3.3 6개 → v3.6 8개)

기존 6개 유지 + 2개 추가:

```
7. 리포트 Top 5 의 signal_age 분포 언급 시, "baseline median 6일 / p90 23일"
   기준 대비 정상 여부 판정. 10-20일차 종목 다수 = 정상.
8. 실전 기댓값 수치 언급 시, "체결 타이밍 현실화 손실 -6.7%p + 필터 알파 유지"
   두 축으로 분해 설명 가능해야 함 (ADR-005).
```

### 추가: 참고 문서 목록

```
- docs/decisions/005-entry-timing-diagnosis.md — 진입 타이밍 실증
- backtest/experiments/results/experiments_compare.csv — 실험 결과 통합표
```

## 반영 범위

- `CLAUDE_PROJECT_INSTRUCTION.md` 에 위 diff 적용 → v3.6 릴리스
- Claude Project Files 재업로드 체크리스트 (v3.3 동기화 규칙 적용)
- `CLAUDE.md::최근 주요 결정` 에 ADR-005 항목 추가
- `SESSION_LOG.md` 에 2026-04-24 #1 엔트리로 실험 결과 기록

## 반영 전 확인 필요

1. **CLAUDE_PROJECT_INSTRUCTION.md 실제 구조**에 맞춘 diff 재작성 여부
   (현재는 섹션명 추정으로 작성됨)
2. **B2 vs B3 역전 현상**의 원인 규명 후 v3.6 확정 — 본 초안은 후속 과제로
   분리. 확정 전 반영 여부 마스터 판단.
3. **"실전 기댓값 +15-20%"** 숫자 자체의 유효성 재검토 — B1 의 +22.85% 에서
   어떤 차감을 어느 수준으로 적용할지 명시적 분해표 필요할 수도.

## 반영 안 함 (기각)

- `strategy_config.yaml` 에 `entry_mode` 옵션 추가해 실전 모드 토글 노출 —
  ADR-005 §5 후속 과제로 분리. v3.6 진입 게이트의 "shim 금지" 정신 위반 우려.
