# ADR-012: 거래량 selection / sizing 양 채널 무효 — 박스권 부산물은 selection noise

**날짜**: 2026-04-28
**상태**: 채택 (ADR-010 메타 원칙 5번째 사례 + 강화)
**관련**: ADR-010 (baseline 외 추가 필터 자제), ADR-001 (T10/CD60 baseline)

## 배경

마스터 가설: *"A등급 통과 (Minervini 8조건 + 수급 + RS) 종목 중 3일 거래량 상위 5개를 매수하면 baseline (RS 정렬 Top 5) 보다 알파 있을까?"*

가설 메커니즘 후보:
- 거래량 spike = 단기 catalyst proxy (Minervini breakout volume ×1.3 룰의 selection 버전)
- 유동성 큰 종목 = 슬리피지 보호 → 백테 ↔ 실전 갭 축소
- ADR-010 본문에서 박스권 보호 부산물의 sizing 채널 미해결 항목 명시 →
  검증 가치 있음

ADR-010 메타 원칙 사전 게이트:
- **사전 검증된 1차 출처** ✗ — Minervini 본인은 거래량을 *timing confirmation*
  으로 쓰지 *selection* 으로 안 씀. 학술 1차 출처도 부재.
- **Robustness sensitivity plan** ✗ — 3/5/10일 lookback × cap 그리드 미정의

두 게이트 모두 미통과지만 마스터 의사 + 30분 비용 + 데이터 산출 가치 (ADR-010
사례 보강) 로 1회 한정 검증 진행. **사전 기댓값은 FAIL** (ADR-005/004/001/010
4번 연속 패턴 + chase entry 위험).

## 검증 설계

`backtest/99_volume_selection.py` (4종 백테, baseline 포함):

| 변형 | sort_mode | size_mode | 의미 |
|---|---|---|---|
| baseline | rs | equal | RS percentile desc Top 5, 균등 가중 |
| V1a | vol3d_value | equal | 3일 (close × volume) desc Top 5 |
| V1b | vol3d_shares | equal | 3일 volume desc Top 5 |
| V1c | rs | vol3d_value_proportional | RS Top 5 + 거래대금 비례 가중 |

V1c 가 핵심 — selection 변경 시 발생 가능한 noise 와 sizing 효과 분리.
strategy.py 의 run_backtest 를 self-contained 로 복사 + sort/size 키만
매개변수화 (단일 소스 원칙 보존).

데이터: 162종목 × 2774영업일 (2015-01-01 ~ 2026-04-28). baseline 재현성
검증 통과 (CAGR +30.19%, MDD -29.83% 일치).

## 결과

### 4종 비교 (162종목, 11.3년)

| 변형 | 전체 CAGR | MDD | 박스권 (15-19) | 중립 (20-24) | 강세 (25+) |
|---|---:|---:|---:|---:|---:|
| baseline | +30.19% | -29.8% | -2.05% | +35.26% | +169.27% |
| V1a sel 거래대금 | +19.93% | -35.5% | +2.45% ⭐ | +18.67% | +103.20% |
| V1b sel 거래량 | +22.11% | -34.1% | -0.56% | +29.94% | +81.13% |
| V1c sizing 비례 | +25.23% | -40.8% | -2.33% | +24.41% | +172.04% |

### Δ vs baseline

| 변형 | Δ 전체 | Δ MDD | Δ 박스권 | Δ 중립 | Δ 강세 |
|---|---:|---:|---:|---:|---:|
| V1a | -10.26%p | -5.7%p | **+4.50%p** | -16.59%p | -66.08%p |
| V1b | -8.09%p | -4.3%p | +1.49%p | -5.32%p | -88.15%p |
| V1c | -4.96%p | **-11.0%p** | -0.28%p | -10.85%p | +2.77%p |

### Pass 기준 (사전 정의) 결과

| 기준 | V1a | V1b | V1c |
|---|---|---|---|
| 전체 CAGR ≥ baseline +0%p | ✗ | ✗ | ✗ |
| 전체 MDD ≤ baseline +3%p | ✗ | ✗ | ✗ |
| 박스권 CAGR ≥ baseline -2%p | ✓ | ✓ | ✓ |
| **종합** | **FAIL** | **FAIL** | **FAIL** |

## 결정

**거래량 (3일 거래대금/거래량) 기반 selection 및 sizing 양 채널 모두 무효
확정.** ADR-010 메타 원칙 5번째 사례 추가. baseline (RS percentile desc Top 5,
균등 가중) 유지.

## 근거

### 1. 박스권 부산물은 selection noise, 재현성 0

V1a 의 박스권 +4.50%p 가 가장 흥미로운 수치였으나, **V1c (sizing 만 변경,
selection baseline 동일) 검증으로 재현성 부재 증명**:

- V1c 박스권 거래 수 = baseline 과 정확히 **104건 동일** (V1a 는 90건)
- V1c 박스권 CAGR = -2.33% ≈ baseline -2.05% (Δ -0.28%p, 사실상 동등)
- → V1a 의 박스권 +4.50%p 는 sizing 효과가 아니라 **거래대금 정렬로 다른
  종목 (RS Top 인데 거래대금 작은 종목 — 펌프 위험주?) 이 빠지면서 우연히
  손실 회수**. 다른 시점/유니버스에서 재현 보장 0.

### 2. Sizing 차등은 위험 가중 잘못된 방향

V1c 의 강세장 +2.77%p 는 noise. 그러나 명확한 손상:
- **MDD -29.8% → -40.8% (-11.0%p 악화)**
- 중립장 -10.85%p 손실

거래대금 큰 종목 (대형주) 에 가중 집중 → 변동성·drawdown 악화. Position
sizing 의 일반 원칙 (분산화) 와 정반대 방향. ADR-010 본문에서 sizing 채널을
"검토 가능" 항목으로 남겨뒀으나, **거래대금 비례 sizing 은 명백한 음의 방향**.

### 3. Chase entry 페널티 (V1a/V1b 강세장 -66 ~ -88%p)

V1a 강세장 -66.08%p, V1b 강세장 -88.15%p. 거래량 spike = 이미 breakout 한참
진행 후 → RS 모멘텀 강자 (계속 상승 중인 종목) 대신 **이미 늦은 종목** 진입.
강세장에서 모멘텀 따라가기의 본질적 알파를 정면으로 파괴.

### 4. ADR-005/004/001/010 패턴 재현

baseline 알파 (+30.19%) = `RS 모멘텀 × Minervini × 수급 × 시장 게이트`. 추가/
대체 필터를 얹거나 정렬 키를 바꾸면:

| 효과 | V1 case |
|---|---|
| 진입 정밀도 부분 ↑ | V1a 박스권 +4.50%p (selection noise) |
| 진입 횟수 / 종목 분포 변경 | -1~5% 거래 수 변화 |
| **알파 큰 추세 진입 차단 / 변경** | **강세장 -66~88%p (V1a/V1b)** |
| **위험 가중 악화** | **V1c MDD -11.0%p** |

→ 부분 개선 < 전체 손실. 5번째 ADR-010 사례.

## 결과 (Consequences)

### 긍정적

- **ADR-010 메타 원칙 강화**: 5번째 fail 사례. 미래 6번째 추가 필터 후보 시
  본 ADR + ADR-001/004/005/010 함께 인용 → 검증 자체 자제 정당화.
- **박스권 보호 sizing 채널 검증 종료**: ADR-010 본문에서 미해결 후순위로
  남았던 항목 (`sizing 차등 (RS 점수 가중 / 거래대금 가중)`) 중 거래대금
  가중은 명확히 무효. RS 점수 가중은 별개 가설로 남으나, 본 ADR 의
  *sizing 차등 = MDD 악화* 패턴이 사전 경계 신호로 작용.
- **페이퍼 트레이딩 1순위 복귀 정당화**: 알파 추구 자원 양보 정당화 데이터
  추가.

### 부정적

- ADR-010 사전 게이트 미통과 가설을 1회 검증 한 선례. 다만 본 검증 자체가
  *데이터로 게이트 정당화* 효과 → 균형.
- V1 코드 (`backtest/99_volume_selection.py`) **폐기** — 작업 브랜치
  `claude/analyze-code-8HvmQ` 와 함께 삭제. 재현 필요 시 본 ADR 의 4종 비교
  표 + Pass 기준 기록만으로 strategy.py 의 sort_mode/size_mode 매개변수화
  재구성 가능.

## 미래 폐기 조건

다음 중 하나라도 발생 시 본 ADR 재검토:

1. **학술 / 1차 출처 발견** — 학술 논문 또는 Minervini/Weinstein/O'Neil/Asness
   원전에서 "거래량 기반 selection / sizing 알파" 가 사전 검증 + robust
   sensitivity 통과 데이터 포함하여 등장 시.
2. **시장 구조 변화** — KOSPI 호가 단위 / 거래시간 / ETF 비중 등이 거래량
   신호의 의미를 바꿀 정도로 변동 시.
3. **본 검증 자체의 결함 발견** — V1c 의 MDD -11%p 가 거래대금 비례가 아닌
   다른 sizing 방식 (예: log-volume normalize, max weight cap 30%) 에서
   회수된다는 증거 발생 시 sensitivity 추가 검증 가능.
