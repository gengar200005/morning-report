# Decision Inbox

세션 중 **"해보자" 가 굳어지는 순간** 1~3줄 즉시 추가 + 즉시 commit + push.
코드 변경 0 이어도 OK. 세션이 도중에 뻗어도 다음 세션이 git log + 본 파일만 보고
컨텍스트 회복.

다음 세션 시작 시 회수 → CLAUDE.md / SESSION_LOG / ADR 로 정식 흡수 → 해당 entry 삭제.

**이 파일에 한해 운영 규칙 "마스터 승인 후 push" 예외 허용** (자동 push OK).

---

<!-- entries 가 정식 문서로 흡수되면 위 구분선 아래에서 삭제. 빈 상태로 두면 됨. -->

## 2026-04-30 — 매크로 카드 "신뢰 경제지 뉴스 100% live" 전면 교체 (옵션 A)

- **사고**: 04-30 리포트 "FOMC D-6 임박" 가짜 narrative (`combine_data.py:
  MACRO_EVENTS` 하드코딩 가짜 3건). 실제 FOMC 4/28-29 종료 (8-4 동결 +
  4명 dissent 1992년 10월 이후 최초 매파 surprise).
- **1차 시도 옵션 B (PR #32 머지 `2a89634`)**: 하드코딩 정정 + `/analyze`
  가 1차 출처 재검증 의무 (v2). → 테스트해보니 mechanical D-day 카운트
  narrative ("FOMC 6/17 D-48 / NFP 5/8 D-8 / CPI 5/12 D-12") 양산. 마스터
  불만족.
- **2차 결정 옵션 A (본 entry)**: 하드코딩 완전 폐기. `combine_data.py:
  MACRO_EVENTS` 빈 dict + `build_macro_section()` stub 안내문만. 매크로
  카드 = **WebSearch 신뢰 경제지 뉴스 100% live 작성** (Reuters / Bloomberg /
  WSJ / CNBC / FT / 한경 / 매경 / 연합인포맥스). "무엇이 일어났고 / 시장
  반응 / 한국 함의" narrative 의무.
- **이행**: `combine_data.py` MACRO_EVENTS 빈 dict + `/analyze` 가이드
  macro v2 → v3 (전면 교체) + 금지 사항 4건 (하드코딩 참조 / mechanical
  D-day 나열 / 출처 누락 / 추측 라벨).
- **정식 흡수 후보**: ADR-015 "당일 Claude 작성 vs cron 객관 숫자 분리"
  — 매크로는 100% Claude 작성 영역으로 확정. 1주 운영 후 정식화.

## 2026-05-12 — Broker 시장가 stop-order 금기 확정 + workflow 분리 결정

- **사고**: 한미반도체 5/12 broker 시장가 stop trigger 체결 371K (매수가
  392.5K -5.5%) → 현재가 390.5K 회복. Stop hunt 패턴.
- **백테 a/b 검증** (`backtest/strategy_config.yaml::risk.stop_trigger`
  flag 신설, commit `4a6be8d`):
  - `close` 모드 (종가 stop, baseline): CAGR **+32.77%** / MDD -30% /
    PF 2.29 / 335 trades / 승률 42.4% (162종목 11.3년)
  - `intraday` 모드 (broker 시장가 stop 시뮬, 당일 저가 hit 즉시 발동):
    CAGR **-7.48%** / MDD -67% / PF 0.89 / 617 trades / 승률 30.5%
  - **Stop hunt drag = -40%p CAGR**. 강세장 +191% → +6% (-185%p) 가장
    심각. 백테 종가 가정과 broker 시장가 stop 의 실전 운영 사이 systemic
    risk.
- **결정**:
  - ❌ Broker 시장가 stop-order 자동 매도 **금기** (실전 운영 ❌)
  - ❌ Broker 지정가 stop 도 비추 (미체결 위험 → 추가 손실 가능)
  - ✓ **종가 기준 수동 매도** — 매일 장 마감 후 (15:30 이후) 보유 종목
    종가 vs 매수가 -7% (또는 trail peak -10%) 비교 → 종가 stop 라인
    미만 시 다음날 09:00 시초가 시장가 매도 (08:30~09:00 동시호가 시장가
    예약 또는 09:00 직후)
- **구조 변경 방향** (1주 안에 단계적 구현):
  - `evening.yml` cron 신설 (16:00 KST, 국장 마감 후) — kr_report +
    holdings + sector + 보유 종가 stop 자동 alert (Notion / Slack push)
  - `morning.yml` 06:25 cron 은 미장 only + 합본 + 렌더 (가벼움)
  - 마스터 저녁 알람 → 다음날 아침 시초가 매도 결정
- **즉시 운영 룰 (5/13 부터)**:
  - broker 자동 stop-order 즉시 해제
  - 매일 저녁 종가 stop 수동 점검 (5분)
  - 종가 -7% 미만 시 다음날 08:30 동시호가 시장가 예약 매도
- **정식 흡수 후보**:
  - ADR-014 페이퍼 트레이딩 운영 모델 — 종가 기준 stop 룰 정식화 +
    1주 운영 검증
  - ADR-016 "백테 가정 ↔ 실전 운영 정합성" — stop-execution method
    명시 의무, intraday stop ablation 기록
  - CLAUDE.md "실전 매매 규약" 업데이트 — stop 발동 방식 명시
  - Plan 008 자동 stop alert 모듈 (evening cron + Notion push)

