# Decision Inbox

세션 중 **"해보자" 가 굳어지는 순간** 1~3줄 즉시 추가 + 즉시 commit + push.
코드 변경 0 이어도 OK. 세션이 도중에 뻗어도 다음 세션이 git log + 본 파일만 보고
컨텍스트 회복.

다음 세션 시작 시 회수 → CLAUDE.md / SESSION_LOG / ADR 로 정식 흡수 → 해당 entry 삭제.

**이 파일에 한해 운영 규칙 "마스터 승인 후 push" 예외 허용** (자동 push OK).

---

<!-- entries 가 정식 문서로 흡수되면 위 구분선 아래에서 삭제. 빈 상태로 두면 됨. -->

## 2026-04-29 — 매크로 카드 "당일 Claude 작성" 원칙 (옵션 B 채택)

- **사고**: 04-30 리포트 "FOMC D-6 임박" 가짜 narrative — `combine_data.py:MACRO_EVENTS`
  하드코딩 (FOMC 5/6 / 11/4 / 12/16 가짜 3건 + CPI 5/13 1일 오차) 그대로 Claude 가
  신뢰 + 1차 출처 재검증 누락. 실제 FOMC 4/28-29 어제 종료 (8-4 동결 + 4명 dissent,
  1992년 10월 이후 최초) → 매파 surprise였음.
- **결정**: cron = 객관 숫자만, 해석·일정·narrative = 당일 Claude 작성. 하드코딩은
  fallback skeleton 으로 보존하되 `/analyze` 가 매일 1차 출처 (federalreserve.gov /
  bls.gov / Reuters / CNBC / IEA 등) 재검증 후 덮어쓰기 의무.
- **이행**: `combine_data.py` 가짜 일정 정정 (`754a13d`) + `/analyze` 가이드에
  macro 카드 v2 의무 4개 + 금지 사항 3건 추가.
- **정식 흡수 후보**: ADR-015 "당일 Claude 작성 vs cron 객관 숫자 분리 원칙"
  (1주 운영 후 entry/macro v3/v2 패턴 안정화 확인 → 정식화).
