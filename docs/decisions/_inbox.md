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
