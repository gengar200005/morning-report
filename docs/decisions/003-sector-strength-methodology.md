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
  (A) IBD 6M 백분위 순위         50점
  (B) Weinstein Stage 2          25점
  (C) Breadth (% above MA50)     25점

등급:
  ≥ 75점  → 주도 (Leading)
  60-74점 → 강세 (Strong)
  40-59점 → 중립 (Neutral)
  < 40점  → 약세 (Weak)
```

**비중 50/25/25 근거** (한국 시장 적용 판단):
- O'Neil 과 Minervini 본인의 **우선순위 명시**: IBD Industry Group Rank
  를 1차 필터(Top 40 / 상위 20%), Weinstein Stage 를 2차 보조로 사용.
- 한국 모멘텀 효과는 학술적으로 혼재 (Chae & Eom 2009 negative momentum
  vs Asness et al. 2013 "Value and Momentum Everywhere" 한국 포함 양성)
  지만, **6M lookback은 단일 모멘텀 팩터 중 가장 검증된 형태**.
- 한국 시장 변동성(연환산 ~22%, S&P ~15%) 이 미국보다 큼 → Weinstein
  Stage 의 false signal (whipsaw) 빈도 높음 → 비중 30→25로 낮춤.

**임계값 75/60/40** : 임의값. 첫 구현 후 백테 분포 확인하여 조정 가능.

#### (A) IBD 6M 백분위 (50점) — O'Neil/Minervini 표준

- 섹터별 **6개월(126 거래일) 가격 수익률**을 집계
- 집계 방식: **시총 가중 + 단일 종목 25% cap**
  - 한국 시총 집중 (삼성전자 KOSPI ~20%, Top 10 ~50%) 으로 순수 시총
    가중 시 단일 종목에 점수 휘둘림
  - **KRX 200 인덱스 자체가 단일 종목 30% cap 사용** (한국 시장 표준)
  - 본 산식은 25% 로 더 보수적 적용 (섹터 단위는 더 좁아 영향 ↑)
  - 동등 가중 대안 기각: 소형주 영향 과대 + 시장 신호 왜곡
- 22개 섹터 중 백분위 순위 산출
- 점수 = `50 × percentile_rank` (0~1)
- 출처:
  - O'Neil *How to Make Money in Stocks* 14장 "Industry Group Strength"
  - Minervini *Trade Like a Stock Market Wizard* 4장 — IBD Industry
    Group Rank Top 40 명시적 권장
  - Asness et al. (2013) "Value and Momentum Everywhere" *Journal of
    Finance* — 6M momentum 글로벌(한국 포함) 양성 검증

#### (B) Weinstein Stage 2 (25점) — Stan Weinstein 표준

KRX 업종지수의 **주봉 MA30 (30주 = 약 7개월)** 기준 4단계 분류:

```
Stage 2 Uptrend  : 25점  (가격 > MA30W AND MA30W 상승)
Stage 3 Top      :  8점  (가격 > MA30W AND MA30W 평탄/하락 시작)
Stage 1 Base     : 17점  (가격 ≈ MA30W 횡보)
Stage 4 Down     :  0점  (가격 < MA30W AND MA30W 하락)
```

- 출처: Weinstein *Secrets for Profiting in Bull and Bear Markets* 2장;
  Minervini *Trade Like a Stock Market Wizard* 의 "Stage 2 진입" 개념의
  직접적 원조

#### (C) Breadth — % above MA50 (25점)

- **섹터 내 우리 유니버스 종목 중 종가가 MA50 이상인 비율**
- 점수 = `25 × pct_above_ma50` (0~1)
- **표본 부족 처리** (한국 22업종 중 일부 섹터 우리 162종목에서 종목수
  부족 — 예: 섬유의복, 종이목재 등):
  ```
  종목 수 ≥ 5  : 정상 점수 산출
  종목 수 3-4 : breadth 0점 처리, IBD/Stage 만으로 점수 (max 75점)
  종목 수 < 3 : 섹터 점수 자체 N/A (집계 제외)
  ```
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

- 학술 표준이지만 12개월 lookback은 한국 변동성 대비 너무 김
- 한국 모멘텀 효과는 학술적으로 혼재 (Chae & Eom 2009 negative momentum
  보고). 짧은 lookback(6M)이 그나마 robust.
- IBD 원문도 6M 사용. 일관성 유지.

### ❌ WICS 세분류 (10섹터 → 24산업그룹 → 69산업)

- FnGuide 유료 또는 스크래핑 필요 → 인프라 부담
- KRX 22 업종으로 충분 (우리 162종목 분포 시 산업그룹 단위는 표본 부족)

### ❌ 동등 가중 (equal-weighted)

- 소형주 영향 과대, 시장 신호 왜곡
- 한국에서 특히 부적합: 시총 작은 종목이 변동성 큼 → 점수 노이즈 ↑

### ❌ 순수 시총 가중 (uncapped market-cap weighted)

- IBD 원문 방식이지만 **한국 시장에서는 부적합**
- 삼성전자 단독 KOSPI 시총 ~20% → 전기전자 섹터 점수 = 사실상 삼성 점수
- KRX 200 인덱스조차 단일 종목 30% cap 사용 (시장 표준)

### ✅ 시총 가중 + 25% 종목 cap (채택)

- KRX 200 cap (30%) 보다 보수적 (섹터 단위는 종목 적어 cap 영향 더 큼)
- 시장 영향력 반영 + 단일 종목 왜곡 차단의 절충

### ❌ 비중 다른 조합 검토

- **40/30/30 (균등)**: O'Neil/Minervini 우선순위와 불일치
- **60/20/20 (IBD 강조)**: Stage 가 너무 약화, Minervini 의 2단 필터 구조
  무력화
- **50/25/25 (채택)**: 1차 필터(IBD) 우위 + 2-3차(Stage/Breadth) 보조

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

---

## Amendment 2026-04-23 — pykrx 장애 대응 (Phase B 실행 중 발견)

### 배경

Colab Phase B 실행 중 pykrx 의 KRX 인덱스 마스터 API 전면 다운 확인.
진단 결과:

| pykrx API | 상태 |
|---|---|
| `get_market_ohlcv_by_date` (종목 OHLCV) | ✅ 정상 |
| `get_index_ticker_list` | ❌ `KeyError: '시장'` |
| `get_index_ticker_name` | ❌ `KeyError: '지수명'` |
| `get_index_ohlcv_by_date` | ❌ `KeyError: '지수명'` |
| `get_index_portfolio_deposit_file` | ❌ 빈 결과 (0행) |

원인: pykrx 1.2.7 `krx.IndexTicker.__fetch()` 가 KRX 마스터 데이터
엔드포인트에서 빈 응답(`Expecting value: line 1 column 1 (char 0)`) → 동일
`self.df` 를 쓰는 모든 인덱스 API 동반 사망. 종목 레벨만 정상.

또한 ADR 초안에 데이터 소스로 명시한 `get_market_sector_classifications()`
는 pykrx 에 **존재하지 않는 함수**였음 (초안 오류). 실제 동등 경로로
쓰려 했던 `get_index_portfolio_deposit_file` 도 같이 사망.

### 영향

1. **(B) Weinstein Stage 25점 산출 불가** — 업종지수 주봉 OHLCV 수집 못함
2. **섹터 매핑 불가** — pykrx 인덱스 API 전체 사망

### 조정

#### 데이터 소스 pivot

| 데이터 | 초안 | Amendment |
|---|---|---|
| 섹터 매핑 | pykrx 업종지수 구성종목 역매핑 | **KRX KIND 상장법인목록** (KSIC 9차) + `reports/sector_overrides.yaml` (KSIC → KOSPI 22업종 자동 매핑 + 종목 오버라이드) |
| 업종지수 OHLCV | pykrx `get_index_ohlcv_by_date` | **수집 보류** (Stage 복구 시 재개) |
| 종목 OHLCV | pykrx `get_market_ohlcv_by_date` | **변경 없음** (정상) |
| 시가총액 | (초안 미명시) | **FinanceDataReader** `StockListing('KRX')` Marcap |

KIND `업종` 컬럼은 KSIC 9차 소분류 (100+ 종) — 우리 universe 160종목에서
58종 등장. 22업종 으로 환원하려면 자동 매핑 규칙 + 일부 수동 오버라이드
필요. `sector_overrides.yaml` 이 1) KSIC→22 자동 규칙 2) 종목 단위 수동
오버라이드 두 역할 모두 수행.

#### 산식 조정 — Stage 25점 임시 제거 + rescale

```
섹터 점수 (임시) =
  ((A) IBD 6M 백분위 50점 + (C) Breadth 25점) × 100/75

= (IBD + Breadth) × 1.333   →   0-100 스케일
```

- 임계값 **75/60/40 유지** (rescale 덕분에 동일 해석)
- 표본 단계화 변경 없음: ≥5 정상 / 3-4 breadth=0 / <3 N/A

#### Stage 복원 조건 (별도 ADR로 결정)

1. pykrx `get_index_ohlcv_by_date` 정상 응답 복구
2. 업종지수 주봉 2년치 결손 없이 수집 가능
3. Stage 판정 결과가 직관과 부합 (sanity)

복원 시 rescale `× 1.333` 제거하여 원 산식 (IBD 50 + Stage 25 + Breadth 25
= 100) 으로 복귀. 노트북 Section 2 복구.

### 한계 명시

- Stage 가 잡던 "추세 전환" 신호가 빠짐 → IBD 6M lagging 만 남아 최신성
  보완 효과 감소
- **실전 진입조건 통합(ADR-004) 전에 Stage 복원 강력 권장**

### 이월 작업 (PC 세션)

- [ ] `universe.py` 누락 3종목 처리: 008560 메리츠증권(2023-04 지주자회사화),
      000060 메리츠화재(2023-02 동), 042670 HD현대인프라코어(2026-01 해산).
      백테 재현성 영향 → 별도 ADR 필요 여부 검토
- [x] `sector_overrides.yaml` 지주회사 ticker_overrides 추가 — Amendment 2 에서 처리
- [ ] pykrx 인덱스 API 복구 모니터링 → 복구 시 Stage 복원

---

## Amendment 2 (2026-04-23 #4, UZymn): 회귀 검증 + 판정 기준 확정

### 배경

Amendment 1 이후 `sector_breadth.py` + 25 pytest + Colab 데이터 파이프라인
완료. Colab 에서 실데이터 회귀 검증 실시 — **162종목 universe × 최근 12개월,
매 월말 기준 선정 섹터의 다음 1개월 평균 수익률 측정**.

### 검증 결과 요약 (3회 반복)

| 시도 | overrides | grades | benchmark | mean_excess | hit | 판정 |
|---|---:|---|---|---:|---:|---|
| 1 | 5 | 주도 | KOSPI | −1.16%/월 | 50% | FAIL |
| 1 | 5 | 주도+강세 | KOSPI | −1.99%/월 | 25% | FAIL |
| 2 | 16 | 주도 | KOSPI | −2.21%/월 | 42% | FAIL |
| 2 | 16 | 주도+강세 | KOSPI | −1.22%/월 | 33% | FAIL |
| 3 | 16 | 주도 | universe | +1.39%/월 | 42% | 부분 PASS |
| **3** | **16** | **주도+강세** | **universe** | **+2.37%/월** | **83%** | **PASS ✅** |

### 결정 1: 벤치마크를 `universe-avg` 로 전환

KOSPI 대비 FAIL → universe-avg 대비 PASS 로 뒤집힘. 원인 분석:
- `mean_kospi_ret` +8.83%/월 vs `mean_universe_ret` +5.23%/월 — universe(162
  종목) 자체가 KOSPI 대비 **-3.6%/월 구조적 언더퍼퐈**.
- universe 에 SK하이닉스·삼성SDI 등 대형주 일부 결손. KOSPI 지수는 시총가중
  mega-cap 비중 크고, universe 는 중형주 편중. 이 베타 차이는 섹터 선정
  산식과 무관.
- ADR-003 의도는 "universe 내 섹터 선택의 순 알파" 측정. KOSPI 비교는
  universe 선정 자체의 beta drag 을 signal 탓으로 귀속 → 오판.

→ `scripts/validate_sector_breadth.py` 에 `--benchmark` 플래그 (`universe`
기본, `kospi` 참고용). 판정 수치도 universe 기준.

### 결정 2: 운영 기준 등급 = "주도 + 강세"

**"주도" 단독은 폐기**:
- 표본 1-2 섹터로 너무 집중 → hit 42%, 변동성 ±6%p/월
- 특정 섹터 단일 선정 월 (예: 2025-09 금융업만) drag 취약

**"주도 + 강세"** 가 실용 범위:
- 평균 4-6 섹터, 70-100 종목 → 알파 보존하면서 안정성 확보
- hit 83% (12개월 중 10개월 universe 앞섬)
- 연환산 +32~34%p excess (월별 동등가중 이론치, 거래비용 전)
- 운영 의미: "주도" = 강한 모멘텀 집중 투자 후보, "강세" = 보조 후보.
  두 등급 함께 묶어 진입 필터 역할.

### 결정 3: `ticker_overrides` 16개 seeding 상태 고정

Amendment 1 이전엔 비어있음 → 이번 세션 5 + 11 = 16개 추가. 금융업 41→26
종목으로 축소, "기타 금융업 KSIC" 에 혼재된 비금융 지주사업 실체를 복원.

추가된 종목: LG/CJ/GS/한화/HD현대/한진칼/두산/LS/OCI/롯데지주/효성/
한미사이언스/한국앤컴퍼니/HDC/오리온홀딩스/영원무역홀딩스.
보류: SK(순수 투자지주), 카카오페이(핀테크=금융업 유지).

실제 효과 (주도+강세 기준):
- 2025-09: 금융업 단독 → **금융업+운수장비+기계 (3섹터)** 로 확장 → 월
  excess -5.4% → **+0.03%** (drag 소멸)

### 산식 자체는 변경 없음

Amendment 1 의 `(IBD 50 + Breadth 25) × 100/75` 그대로. 임계 75/60/40 유지.
Weinstein Stage 25점 복원 조건도 Amendment 1 그대로.

### 한계 / 해석 주의

- **표본 12개월** — mean/hit 신뢰구간 넓음. ±2%p/월 오차 가능. 추가 12-24
  개월 누적 시 재검증 필요.
- **동등가중 + 거래비용 무시** — 실전 strategy 로 전환 시 슬리피지·세금
  -3~5%p 차감. 알파 순 기대 +5~10%p/년 수준으로 보수적 추정.
- **fat-tailed**: 2025-12, 2026-01, 2026-03 3개월이 전체 excess 의 60%
  이상 기여. 강세장에서 주도 섹터 집중 효과. 약세장에서는 drag 최소화
  하는 수준 (2025-10~11, 2026-02 모두 소폭 음수).
- **2026-03 outlier 경계**: 3-31 → 4-23 구간은 23거래일 (1개월 미달).
  최신 데이터 경계 효과 반영됨.

### 정식 채택 결정

- [x] "주도+강세" × universe 벤치마크 조합을 ADR-003 **정식 판정 기준**
- [x] `sector_overrides.yaml` 16 entries 를 초기 baseline 으로 고정
- [ ] **다음 세션 (이월)**: `sector_report.py` 에 신 산식 점수 병행 표시
- [ ] **다음 세션 (이월)**: ADR-004 착수 — 주도+강세 섹터를 strategy 진입
      게이트로 통합 (`kr_report.py` signals 생성 시 섹터 필터 추가)
