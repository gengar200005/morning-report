# Phase 3 Backtest — Data Source Notes

## 지수 데이터 소스 전환 이력 (2026-04-21)

pykrx의 `get_index_ohlcv_by_date()` 함수가 KRX 엔드포인트 변경 이후
회귀 버그 (`KeyError: '지수명'`, JSON 디코딩 실패) 상태로, 2026-02 이후
upstream 미수정. pykrx 1.2.4 → 1.2.7 업그레이드에도 미해결.

**해결**: 지수 수집을 yfinance로 전환 (종목 OHLCV는 pykrx 유지).

## 데이터 소스 매핑

| 데이터 | 소스 | 티커 |
|---|---|---|
| 종목 OHLCV | pykrx | 6자리 코드 (예: 005930) |
| KOSPI 지수 | yfinance | ^KS11 |
| KOSDAQ 지수 | yfinance | ^KQ11 |

## 데이터 소스 신뢰성 검증 (2026-04-21)

yfinance vs FinanceDataReader 교차 검증 결과 완전 일치 확인.
두 소스 모두 KRX 공식 종가와 일치 (5개 샘플 일자 기준).

| 날짜 | KOSPI (공식=yfinance=FDR) | KOSDAQ (공식=yfinance=FDR) |
|---|---|---|
| 2015-01-02 | 1,926.44 | 553.73 |
| (추가 샘플은 검증 로그 참조) |

향후 yfinance 장애 시 FDR로 swap 가능 (컬럼 rename 필요).

## 알려진 데이터 이슈 (signals 단계에서 처리 예정)

### 이슈 A: 종목-지수 영업일 불일치 (경미)
- 종목 영업일 중 일부가 yfinance 지수에 누락
- KOSPI 결측: 2017-09-22, 2017-12-20, 2022-01-03, 2022-05-09 (4일)
- KOSDAQ 결측: KOSPI 결측 4일 + 추가 1일
- 영향: 전체 2774 영업일 중 0.18%. merge 정책(inner vs left+ffill)은 signals 단계에서 결정.

### 이슈 B: volume=0 캐리오버 행 (경미)
- 지수 Parquet에 volume=0인 행 2건 존재
- 2024-09-12(목): KRX 정상 거래일이나 yfinance에 volume=0
- 2026-04-20(일): 일요일인데 행 존재 (yfinance 버그)
- 영향: 수익률 계산에 2건의 0% 수익률 추가. 통계적 영향 무시 가능.
- 처리: signals 단계 로더에서 `df = df[df.volume > 0]` 필터 또는 영업일 달력 reindex.

### 이슈 C: 거래대금(value) 컬럼 누락
- pykrx가 현재 버전에서 `거래대금` 컬럼 미반환
- 종목·지수 Parquet 모두 6컬럼: open, high, low, close, volume, change_pct
- Minervini 전략 MVP에는 value 불필요. 필요 시 close × volume으로 근사 가능.

## 2026-04-21 스모크 테스트 결과

- 종목 2개 (삼성전자, SK하이닉스) OHLCV: 각 2,774행 정상
- 삼성전자 2018-05-04 액면분할(50:1) 수정주가 반영 확인
- 지수 2개 (KOSPI, KOSDAQ) OHLCV: 2,770+ 영업일 수집
- tz-naive 일관성, 컬럼 스펙 종목/지수 동일
