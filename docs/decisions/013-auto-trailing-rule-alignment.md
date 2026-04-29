# ADR-013: 자동매매 룰 정합화 — 장중 trailing 폐기, 종가 기반 백테 룰 채택

**날짜**: 2026-04-29
**상태**: 채택
**관련**: ADR-001 (T10/CD60 baseline), Plan 006 (페이퍼 트레이딩 자동 모듈)

## 배경

본 ADR 은 04-29 web 세션 (`claude/session-start-bGCen`) 에서 합의된 자동매매
룰 정합화 결정을 정식화. 페이퍼 트레이딩 인프라 첫 단계 (Plan 005/006, ADR
직전 04-28 #2) 후 실전 운영 흐름 점검 중 **사용자 자동매매 룰과 백테 룰의
3 곳 불일치** 발견.

### 사용자 룰 (M-STOCK 자동매도, 폐기 대상)

```
+15% 수익 도달 시 트레일링 활성화 → 장중 -10% peak 기준 즉시 시장가 매도
```

- **체크 시점**: 장중 (실시간)
- **peak 정의**: 장중 high (스파이크 포함)
- **청산 시점**: 트리거 즉시 시장가

### 백테 룰 (`backtest/strategy.py`, ADR-001 baseline)

```
종가 ≤ peak_close × 0.90 트리거 → 다음날 시초가 시장가 매도
```

- **체크 시점**: 종가 확정 후 (D 15:30 이후)
- **peak 정의**: 진입일~D 종가 max (장중 high 무시)
- **청산 시점**: D+1 시초가

## 알파 손실 추정

3 곳 불일치 → 동일 종목에서 결과 다름. 핵심 손상 메커니즘:

### 1. 장중 노이즈 슬립아웃 (가장 큼)

장중 -10% trail 은 +100% peak winner 들이 +30~70% 수준에서 **가짜 트리거**
에 일찍 잡힘. 백테는 종가 기준이라 장중 스파이크/스윙 무시.

Top 5 MFE 백테 분석 (335 거래, 162종목 11.3년):
- peak_ret p90 **46.9%** (상위 10% trade 가 +47% 이상 도달)
- mfe_to_exit median **12.4%p** / p90 **20.0%p**
- MFE Top 5: 미래에셋증권 +212% / 동국제강 +157% / 삼양식품 +146% /
  포스코인터 +132% / 에코프로 +122%
- 환불 폭 Top 5: 포스코인터 -55%p / 에스엠 -55%p / 한화에어로 -42%p /
  동국제강 -38%p / 두산에너빌리티 -37%p (단 5일!)

장중 trail 시 위 winner 들이 +50~80% 수준에서 가짜 트리거 잡힐 가능성 큼.
시기/산업 분산 (2020/21/23/24/25-26) 이라 winner 5건 = 백테 알파의 큰 부분.

### 2. Peak 정의 차이

장중 high = 종가 보다 평균 1-3% 높음 (intraday volatility). trail level
도 함께 1-3% 높아져 트리거 빈도 증가. 거래 수 증가 → 슬리피지·세금 누적
손상.

### 3. 청산 시점 차이

즉시 시장가 vs D+1 시초가. 보통 D+1 시초가 가 종가 대비 0~1% 갭다운,
즉시 시장가 보다 평균 -0.5%p 손해. 그러나 **갭상 종목** 의 경우 D+1 시초
체결로 +2-3%p 이득 케이스도 있음 — 평균은 wash 에 가까움.

### Net 추정

- (1) winner 보호 손실 **-10~15%p CAGR**
- (2) 거래 수 증가 손상 -1~2%p
- (3) 청산 시점 wash ±0%p

**총 -10~17%p CAGR 손실 추정**. 백테 +29.55% → 사용자 룰 운영 시 +12~19%
로 침식. 실전 기댓값 차감 후 (-3~5%p 생존편향 / -2~3%p 슬리피지 / -1~2%p
세금) 으로 +5~12% 까지 떨어짐 — KOSPI ETF 와 무차별.

## 결정

**장중 trailing 룰 즉시 폐기, 종가 기반 백테 룰 채택.**

- M-STOCK 자동매도 룰 5종목 삭제 (마스터 즉시 운영 변경)
- **stop_loss -7% 룰만 유지** (백테 STOP_LOSS 와 정합, 기본 안전망)
- Trailing 청산은 **EOD tracker (별도 stock-automation 레포 D 19:00 KST
  cron)** 가 단일 진실의 원천:
  - `peak_close = max(close[entry:D])`
  - `trail_level = peak_close × 0.90`
  - `stop_level = entry_price × 0.93`
  - `청산상태 = HOLD / TRAIL / STOP` (close vs trail/stop 비교)
- D+1 morning-report (`holdings_report.py`) 가 4 필드 inherit + 🎯 청산
  평가 줄로 마스터에게 전달
- 마스터는 D+1 08:30~09:00 동시호가 시장가 매도 예약 (TRAIL/STOP 시)

## 운영 흐름 (백테 가정 100% 정합)

```
D 15:30 장 마감
 ↓ D 19:00 KST cron (stock-automation 별도 레포)
 │  ├ KIS API 일봉 페이지 분할 (진입일~D)
 │  ├ peak_close / trail_level / stop_level / 청산상태 계산
 │  └ Notion 보유 DB 5 필드 갱신 (4 + 갱신시각)
 ↓ D+1 06:25 KST cron (morning-report)
 │  ├ holdings_report.py 4 필드 inherit
 │  ├ 🎯 청산 평가 줄 (HOLD / TRAIL / STOP / STALE)
 │  └ build_text → PDF + Notion publish
 ↓ D+1 ~07:00 마스터 /analyze
 │  └ 7카드 — alert / portfolio 카드에 trigger 종목 명시
 ↓ D+1 08:30~09:00 동시호가 시장가 예약주문
    ├ 매수: T10/CD60 진입 후보 (Top 5 RS 순)
    └ 매도: 청산상태 ∈ {TRAIL, STOP} 종목
```

## 근거

### 1. 백테 가정 살아있는 운영 = 백테 알파 그대로 실현 가능

직전 세션 (04-28 #3, NDX 필터 종결) 에서 **백테 시가 100% 체결 가정**
의 알파 부풀림 우려가 부정됨 (시그널 종목 평균 갭 +0.17%, n=333). 본
세션 운영 흐름은 동시호가 예약주문 (08:30~09:00) 으로 시초가 체결 가정도
거의 그대로 실현 가능. **인간 회피/지연 자동 차단 장치**.

### 2. EOD tracker 단일 진실의 원천 = Claude augmentation 임의 판단 차단

`/analyze` Claude 가 alert/portfolio 카드에 임의로 trail/stop 재계산하면
**EOD tracker 와 불일치**. 마스터 혼선 + ADR-009 narrative 끌림 위험
재현. ADR-013 의 부산물 — analyze.md spec 에 "자동매도트래커가 단일 진실의
원천, Claude 임의 재계산 ❌" 명시.

### 3. ADR-001 baseline 정합 = 알파 추구 자원 페이퍼 1순위 복귀 정당화

자동매매 룰 정합화는 *추가 필터* 가 아니라 *baseline 의 운영 측 누락
부분* 메우는 작업. ADR-010 메타 원칙 적용 대상 아님. 페이퍼 1주 운영
검증 후 ADR-015 (페이퍼 운영 모델) 에서 차감 후 기댓값 update.

## 결과 (Consequences)

### 긍정적

- **백테 ↔ 실전 갭 mitigation**: 사용자 룰 운영 시 -10~17%p 손상 잠재
  → 백테 가정 그대로 실현 가능 흐름.
- **Claude augmentation 한계 명문화**: alert/portfolio 카드에서 trigger
  종목 *명시 의무* + trail/stop *재계산 금지*. ADR-009 narrative 위험
  재현 차단.
- **운영 흐름 단일화**: D 19:00 cron / D+1 06:25 cron / D+1 08:30 동시호가
  3 layer 명확. 마스터 의사결정 = "morning-report 의 🎯 청산 평가 줄
  보고 동시호가 예약 매도/매수" 1줄.

### 부정적

- **stock-automation 별도 레포 의존성**: morning-report 가 Notion DB
  필드를 통해 stock-automation 출력에 의존. EOD tracker 19:00 cron 실패
  시 morning-report 06:25 cron 이 STALE 분기로 fallback (4 필드 None →
  ⚠️ 갱신 누락 명시).
- **휴장일 처리 미정**: 한국 공휴일 / 임시 휴장 시 EOD tracker 가 실행
  되지 않으면 morning-report 가 D-2 데이터 inherit. 24시간 stale 임계로
  방어하나 정밀도 낮음. 1주 운영 후 정밀화 (ADR-015 후보).

### 측정 항목 (1주 운영, ~05-05)

- 마스터 동시호가 매도 예약 누락 0건 (TRAIL/STOP 발동 시)
- EOD tracker 갱신 시각 stale 발생률 ≤ 5%
- 백테 vs 실전 portfolio 수익률 추적 (월말 누적)

## 미래 폐기 조건

다음 중 하나라도 발생 시 본 ADR 재검토:

1. **백테 룰 자체 변경**: ADR-001 의 T10/CD60 가 다른 룰로 변경되면 본
   ADR 의 운영 흐름도 동기화 필요.
2. **장중 청산 알파 검증**: 학술 1차 출처 또는 sensitivity test 로 장중
   trail 이 종가 trail 보다 알파 우위 확인 시 (ADR-010 메타 원칙 사전
   게이트 통과 필요).
3. **EOD tracker 운영 실패**: 1주 측정 stale 발생률 > 20% 시 morning-report
   자체 trail/stop 계산으로 fallback (현재가/매수가/일봉 직접 조회).
