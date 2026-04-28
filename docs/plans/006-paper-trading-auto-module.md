# Plan 006 — Paper Trading 자동 모듈 spec

**상태**: 🔵 spec (미구현)
**선행**: Plan 005 (DB 스키마, 2026-04-28 생성 완료)
**구현 위치**: `backtest/strategy.py` 실시간 모드 추가 vs `paper_trading.py` 신규 모듈 (검토)

---

## 책임 범위

매일 1회 실행. DB 의 OPEN 포지션 + 신규 신호 처리.

1. **신규 신호 row 생성** — 오늘 `check_signal=True` A등급 종목 중
   DB OPEN 미보유 + cooldown 해제 → DB row 신규 생성 (Status=OPEN,
   Signal date=오늘, 자동 18필드 채움, 인간 6필드 비움 대기)
2. **Trail stop 갱신** — 모든 OPEN row 의
   `Trail stop = max(close × 0.90, Stop loss)` 매일 갱신
3. **자동 청산** — STOP_LOSS / TRAIL / GATE_OFF 트리거 시
   Exit date / price / reason 자동 채움 + Status=CLOSED 전환
4. **Cooldown 관리** — Cooldown end 지나면 동일 종목 재진입 가능

## 입력

- `morning_data.txt` (오늘 cron 결과) — 종가, RS, 52W, Grade, Industry,
  market gate 상태
- DB OPEN rows (data_source_id = `d02501fe-58a4-4ba1-9bed-0478ebb3e3be`)

## 출력

- DB row CREATE / UPDATE
- 로그 파일 (`logs/paper_trading_YMD.log`) — 신규/갱신/청산 추적

## 트리거 옵션

| | 시점 | 장점 | 단점 |
|---|---|---|---|
| (a) | `morning.yml` cron 끝 06:25 KST | 1 cron 단일, 인프라 단순 | 종가 미확정 (전일 종가 기준) |
| (b) | 별도 cron 19:00 KST | 종가 확정 후 정확 | cron 추가 운영 부담 |
| (c) | Task Scheduler (PC) | 로컬 실행, GH Actions 무관 | PC 가동 의존 |

**추천: (b) 별도 cron 19:00**. 종가 정확 + market gate 정확.

## DB 인터페이스 규칙

- Property name: spec 005 24필드 그대로 사용
- Date 필드: `date:<col>:start` ISO 8601 (예: `"date:Entry date:start": "2026-04-29"`)
- Number/Select/Text: 그대로
- Formula 3개 (Return % / Hold days / Days delayed): API 입력 불가, 자동 계산
- **자동 채움 18필드만 모듈이 update**, 인간 6필드 (Entry date / price /
  note / psychology, Exit note / psychology) 절대 건드리지 않음

## 미해결

- **KRX 거래일 캘린더** — Cooldown end (60거래일) 정확히 계산하려면 pykrx
  KRX_ID/PW 환경변수 셋업 필요. 일단 calendar days 90일 근사, 6개월
  운영 후 정확도 검증.
- **Slippage 모델링** — 가상 청산가 = 종가? 또는 다음날 시초가? 백테
  일관성 위해 종가 사용 (= strategy.py 동일).
- **Re-entry detection** — 동일 종목 cooldown 후 재진입 시 신규 row vs
  기존 row 갱신? → **신규 row** (사이클 분리, 백테 통계 일관).
- **Market gate OFF 처리** — KOSPI < MA60 시 OPEN 전체 청산 vs 신규
  진입만 차단? → **신규 차단만** (백테 baseline 일관, OPEN 은
  STOP_LOSS/TRAIL 룰로만).
- **Notion API token 위치** — `.env` 로컬 vs GitHub Secrets vs Task
  Scheduler env. 트리거 (a/b/c) 결정 후 자연 결정.

## 다음 단계

1. **마스터: 트리거 (a/b/c) 결정**
2. **구현 위치 결정** — `backtest/strategy.py` 실시간 모드 vs
   `paper_trading.py` 신규 모듈
3. **환경변수 셋업** — Notion API token + Data source ID
4. **첫 실행** — 1주 모니터링 (DB row 생성·갱신·청산 정확도 검증)
5. **Plan 007 (선택)** — PDF 첫 페이지 "현재 페이퍼 포지션 / 누적 수익률"
   카드 추가
