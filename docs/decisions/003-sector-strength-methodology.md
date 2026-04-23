# ADR-003: 섹터 강도 산정 방법론 (IBD + Weinstein + Breadth)

**날짜**: 2026-04-23
**상태**: 채택 (구현 대기)
**관련**: ADR-002 (strategy 모듈), `sector_report.py`, `reports/sector_mapping.py`

## 배경

현재 섹터 분석(`sector_report.py`)은 **18개 섹터 ETF 가격**을 입력으로
RS(50) + 추세(30) + 자금(20) = 100점 산식을 사용. 다음 한계 발견:

1. **유니버스 불일치**: ETF 바스켓은 운용사가 정의한 종목 구성. 우리가 실제로
   거래하는 백테 162종목과 무관. "KODEX 반도체가 강하다" ≠ "내가 거래할
   반도체 종목들이 강하다".
2. **ETF 중복/누락**:
   - 중복: 반도체(KODEX, TIGER), 2차전지(KODEX, TIGER), 금융 위계 모호
     (금융/은행/증권/보험 동일 레벨), IT vs 반도체 사실상 중복
   - 누락: 헬스케어/제약, 통신, 인터넷·플랫폼, 음식료, 유통, 화장품 등
3. **산식 정당성 부재**:
   - 가중치 50/30/20 근거 없음 (ADR 부재)
   - 임계값 80/65/50 임의값
   - 자금 점수 이산화 (1.5/1.2 컷) 거칠음
4. **종목→섹터 매핑 수동 부담**: `reports/sector_mapping.py`에 28종목만 dict
   로 매핑. A등급 종목 늘어나면 수동 추가 필요.

## 결정

**bottom-up 섹터 강도 산정으로 전환**. 우리 유니버스 종목들을 KRX 22개 1차
업종으로 분류 후, **3가지 업계 표준 지표를 100점 합성**.

### 산식

```
섹터 점수 (0-100) =
  (A) IBD 6M 백분위 순위         40점
  (B) Weinstein Stage 2          30점
  (C) Breadth (% above MA50)     30점

등급:
  ≥ 75점  → 주도 (Leading)
  60-74점 → 강세 (Strong)
  40-59점 → 중립 (Neutral)
  < 40점  → 약세 (Weak)
```

#### (A) IBD 6M 백분위 (40점) — O'Neil/Minervini 표준

- 섹터별 **6개월(126 거래일) 가격 수익률**을 집계 (시총 가중 평균)
- 22개 섹터 중 백분위 순위 산출
- 점수 = `40 × percentile_rank` (0~1)
- 출처: O'Neil *How to Make Money in Stocks* 14장 "Industry Group Strength";
  Minervini *Trade Like a Stock Market Wizard* 4장 "Leading Stocks in
  Leading Industries" — 명시적으로 IBD Industry Group Rank Top 40 (상위
  20%) 권장

#### (B) Weinstein Stage 2 (30점) — Stan Weinstein 표준

KRX 업종지수의 **주봉 MA30 (30주 = 약 7개월)** 기준 4단계 분류:

```
Stage 2 Uptrend  : 30점  (가격 > MA30W AND MA30W 상승)
Stage 1 Base     : 20점  (가격 ≈ MA30W 횡보)
Stage 4 Down     :  0점  (가격 < MA30W AND MA30W 하락)
Stage 3 Top      : 10점  (가격 > MA30W AND MA30W 평탄/하락 시작)
```

- 출처: Weinstein *Secrets for Profiting in Bull and Bear Markets* 2장;
  Minervini의 "Stage 2 진입" 개념의 원조

#### (C) Breadth — % above MA50 (30점)

- **섹터 내 우리 유니버스 종목 중 종가가 MA50 이상인 비율**
- 점수 = `30 × pct_above_ma50` (0~1)
- 표본 부족 보정: 섹터 내 유니버스 종목 < 5개면 점수 0 처리
  (코스피 22개 업종 중 일부 섹터는 우리 백테 162종목에서 표본 적음)
- 출처: Murphy *Technical Analysis of the Financial Markets* 6장 Market
  Breadth; Zweig *Winning on Wall Street* — 섹터 단위 적용은 StockCharts
  /FinViz 표준 시각화

### 데이터 소스

| 데이터 | 출처 | 비용 |
|---|---|---|
| 종목 → 섹터 매핑 | `pykrx.stock.get_market_sector_classifications()` | 무료 |
| KRX 22 업종지수 OHLCV | `pykrx.stock.get_index_ohlcv()` | 무료 |
| 종목별 OHLCV | pykrx (이미 백테에서 사용) | 무료 |

**자동 매핑 + 수동 오버라이드 dict 보조**:
- 1차: pykrx 자동 분류
- 2차: 분류 변경/모호 종목용 `reports/sector_overrides.yaml` (소수)

### 유니버스 적용

- **백테/검증**: `backtest/universe.py` 162종목 — 안정 표본
- **라이브**: 추후 동적 유니버스 적용 가능 (구조 동일)

## 대안

### ❌ 현재 ETF 기반 산식 유지

- 유니버스 괴리 문제 미해결
- 누락 섹터(헬스케어, 통신 등) 보강 어려움 (한국 ETF 시장 한계)
- 산식 정당성 근거 여전히 부재

### ❌ Relative Rotation Graph (RRG, de Kempenaer)

- Bloomberg 표준이지만 산식 복잡 (RS-Ratio + RS-Momentum 정규화)
- 4분면 분류는 직관적이나 단일 점수로 환산 시 정보 손실
- 1차 도입 후 향후 v2 시각화로 검토 가능

### ❌ Jegadeesh-Titman 12-1 Momentum

- 학술 표준이지만 12개월 lookback은 코스피 변동성 대비 너무 김
- 6개월(IBD)이 한국 시장에 더 적합 (역사적으로 회전 빠름)

### ❌ WICS 세분류 (10섹터 → 24산업그룹 → 69산업)

- FnGuide 유료 또는 스크래핑 필요 → 인프라 부담
- KRX 22 업종으로 충분 (우리 162종목 분포 시 산업그룹 단위는 표본 부족)

### ❌ 시총 가중 vs 동등 가중

- IBD 원문은 시총 가중 (시장 영향력 반영)
- 동등 가중은 소형주 영향 과대
- **시총 가중 채택** (IBD 원문 따름, 한국 대형주 집중도 반영)

## 결과

### 긍정적 (예상)

- 유니버스와 직결: "주도섹터" 판정이 실제 거래 종목들의 강도 반영
- 학술/실무 표준 차용으로 산식 정당성 확보 (ADR 자체가 근거 문서)
- 누락 섹터 자동 보강 (KRX 22개 → 헬스케어=의약품, 통신=통신업 등 자동
  포함)
- 종목 매핑 수동 부담 제거 (pykrx 자동)
- Minervini 전략과 논리적 일관성 (IBD + Weinstein 둘 다 Minervini 직접
  인용)

### 부정적 / 리스크

- 표본 부족 섹터 (예: 의료정밀, 종이목재 등) 점수 신뢰도 낮음
  → breadth 0 처리로 부분 완화
- KRX 분류와 시장 인식 차이 (예: NAVER가 "서비스업"으로 분류) 수동
  오버라이드 필요
- 6M lookback은 추세 전환 후 인식 지연 (Stage 2 단독 30점이 최신성 보완)
- 백테 검증 미완료 (구현 후 회귀 검증 필요)

### 검증 계획

1. **회귀 검증**: 최근 1년 월별로 새 산식 → "주도" 판정 섹터의 실제 다음
   1개월 수익률 ≥ 코스피 기준선이면 유효
2. **현재 ETF 산식과 병행 출력**: 같은 일자에 두 점수가 어느 정도 일치
   /괴리하는지 확인. 60-70% 일치 예상 (대분류 공통, 세부 다름).
3. **strategy.py 진입조건 통합 시점**: 검증 통과 후 별도 ADR (ADR-004)
   에서 결정. 현 ADR은 "표시용 점수 산정"까지만 결정.

### 후속 작업

- ⏳ `sector_breadth.py` 신규 모듈 구현 (전략 모듈과 독립, 표시 전용)
- ⏳ `reports/sector_overrides.yaml` 신규 (수동 오버라이드 dict)
- ⏳ `sector_report.py` 출력에 신/구 점수 병행 표시 (검증용)
- ⏳ 1-2개월 병행 운영 후 ETF 점수 폐기 또는 보조 유지 결정
- ⏳ 검증 통과 시 ADR-004 로 strategy 진입조건 통합 결정
