# Plan 005 — Paper Trading Notion DB Schema

**상태**: 🔵 spec (DB 미생성, parent URL 대기)
**선행**: CLAUDE.md "다음 진입점 1순위" — 페이퍼 트레이딩 인프라 셋업
**후속**: Plan 006 (예정) — `backtest/strategy.py` 실시간 모드 자동 모듈 spec

---

## 목적

페이퍼 트레이딩 = **자동 백테스트 forward + 인간 행동/심리 저널**. 단순
실시간 백테스트는 자동 룰 알파만 측정하지만, 본 프로젝트는 다음 3가지를
같이 측정:

1. **자동 룰 정확도** — 백테 CAGR ±3-5%p 이내 재현되나
2. **인간 실행 충실도** — 신호→진입 지연 median ≤ 5일 (CLAUDE.md "실전 매매 규약")
3. **심리 견딤 자기진단** — 박스권 -5% 연속 견딜 수 있나 (CLAUDE.md "착수 전 체크리스트")

→ Notion DB 1개로 (1)(2)(3) 모두 기록. 자동 모듈이 채울 필드 + 인간이
채울 필드 분리.

## 검토 결정 (2026-04-28)

| # | 결정 | 근거 |
|---|---|---|
| 1 | Industry/Grade/RS/52W 자동필드 유지 | 사후 분석 (어느 산업/grade/RS 구간에서 알파 강했나) 핵심 입력. 자동 채움이라 노이즈 0. |
| 2 | Mode 필드 미리 두고 PAPER 디폴트 | (b) 자본 10-15% 실전 + 페이퍼 5종목 풀 절충안 1-2개월 차 결정 가능. 추후 LIVE row 추가 시 마이그레이션 부담 0. |
| 3 | Days delayed = calendar days | 영업일 정확도는 ±2일 차이뿐 (median ≤ 5일 기준이면 거의 무관). Notion formula 쉬움. 자동 모듈 부하 감소. |
| 4 | docs/plans spec 선행, DB 생성 후속 | parent page URL 마스터 결정 후 Notion MCP 로 자동 생성. spec 은 영구 reference. |

## DB Schema

한 row = 한 진입/청산 사이클. 한 종목 여러 번 진입 가능 (cooldown 60일 후).
Primary key: 종목코드 + 진입일.

| 필드 | 타입 | 입력 | 비고 |
|---|---|---|---|
| **Title** | Title | 자동 | `{Entry date} {종목명}` 예: `2026-04-29 SK하이닉스` |
| Code | Text | 자동 | 종목코드 6자리 |
| Industry | Select | 자동 | 11섹터 (반도체/방산/...). `sector_overrides.yaml` 참조 |
| Grade | Select | 자동 | A / B / C |
| RS | Number | 자동 | 진입 시점 |
| 52W % | Number | 자동 | 신고가 거리 (%) |
| **Signal date** | Date | 자동 | `strategy.py::check_signal=True` 첫날 |
| **Entry date** | Date | 인간 | 실제 시초가 매수일 |
| Entry price | Number | 인간 | 실제 진입가 (slippage 측정용) |
| Stop loss | Number | 자동 | `entry × 0.93` (STOP_LOSS 7%) |
| Trail stop | Number | 자동 | 매일 갱신 `max(close × 0.90, stop_loss)` |
| Cooldown end | Date | 자동 | `entry + 60거래일` (대략 calendar 90일) |
| **Exit date** | Date | 자동 | 룰 트리거 또는 인간 입력 |
| Exit price | Number | 자동 | 청산가 |
| Exit reason | Select | 자동 | STOP_LOSS / TRAIL / GATE_OFF / MANUAL |
| **Return %** | Formula | 자동 | `(Exit price - Entry price) / Entry price` |
| Hold days | Formula | 자동 | `dateBetween(Exit date, Entry date, "days")` |
| **Days delayed** | Formula | 자동 | `dateBetween(Entry date, Signal date, "days")` |
| **Entry note** | Text | 인간 | "왜 들어가나" 한 줄 |
| **Entry psychology** | Number 1-5 | 인간 | 1=불안, 5=확신 |
| **Exit note** | Text | 인간 | 청산 후 회고 한 줄 |
| **Exit psychology** | Number 1-5 | 인간 | 박스권 견딤 자기진단 |
| Status | Select | 자동 | OPEN / CLOSED |
| Mode | Select | 자동 | PAPER (default) / LIVE |

## Views (3개)

1. **Open positions** — `Status = OPEN`, sort by Entry date asc
2. **Closed (recent)** — `Status = CLOSED`, sort by Exit date desc
3. **Stats source** — 모든 row, CSV export → 월간 CAGR/MDD/지연 median 분석

## 인간 부담 = 한 사이클당 6필드

진입 시 (4): Entry date · Entry price · Entry note · Entry psychology
청산 시 (2): Exit note · Exit psychology
→ 5종목 동시 운영해도 부담 적정. 날짜/가격 자동, 사유/심리만 인간.

## 통과 기준 (CLAUDE.md "다음 진입점 1순위")

- 백테 대비 CAGR **±3-5%p**
- 신호→진입 지연 **median ≤ 5일** (Days delayed)
- 진입 심리 점수 평균 **≥ 3.5**

6개월 누적 후 평가. 통과 시 (b) 자본 10-15% 실전 + 페이퍼 5종목 절충안
검토. 미달 시 원인 분석 (자동 룰? 인간 실행? 심리?).

## 다음 단계

1. **마스터: Notion parent page URL 결정** — workspace 의 어느 page 아래
   DB 생성할지. 후보: "morning-report" page / "투자 저널" page / 신규 생성.
2. **Claude Code: Notion MCP 로 DB 자동 생성** — 본 spec 그대로 properties
   생성. parent URL 받으면 즉시.
3. **Plan 006 작성** — `backtest/strategy.py` 실시간 모드 자동 모듈 spec.
   매일 종가 후 (또는 cron 06:25 직후) 모듈 1회 호출 → 다음 처리:
   - 신호 발생 종목: signal_date 기록 + DB row 신규 생성 (status=OPEN 대기)
   - 보유 중 종목: trail_stop 갱신, STOP_LOSS/TRAIL/GATE_OFF 트리거 시 자동 청산
   - 인간 입력 대기 row: 마스터가 entry_date/entry_price 채우면 활성화
4. **Plan 007 (선택)** — PDF 첫 페이지 "현재 페이퍼 포지션 / 누적 수익률"
   카드 추가. v6.2 template 영역, CI 작업.

## 미해결

- **종목 분할/병합/상폐** 발생 시 row 처리 — 일단 인간 수동 청산 (Exit reason: MANUAL) 으로 처리, 6개월 운영 후 자동화 검토.
- **Cooldown end 영업일 60 → calendar days 변환** — 자동 모듈에서 KRX
  거래일 캘린더 참조 필요. pykrx 로 처리 가능.
- **Notion API rate limit** — 5종목 × 매일 trail_stop 갱신 = 5 req/day, 무관.
