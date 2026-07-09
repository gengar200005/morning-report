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

## 2026-07-09 — 시장 게이트 stale 데이터 사고 근본 수정 (브랜치 `claude/analysis-s2hk4c` `6f5f224`)

- **사고**: 07-09 리포트 게이트 "✓ 통과 −4.8%" 자기모순. 코스피 7,246.79
  < MA60 7,612.15 인데 A등급 11개 발행. 원인 3층: (1) `get_market_context`
  yfinance 단독 → 06:00 KST 상시 1거래일 지연 (6~7월 GH Actions 로그
  전수 재현, **만성**) → 게이트가 늘 D-2 종가 판정. (2) KIS 지수 엔드포인트
  **경로 오타** (`inquire-index-daily-chartprice` → 정답
  `inquire-daily-indexchartprice`) 로 상시 404 → fallback 체인 사실상
  snapshot 단독 → PC 미갱신 날 (6/16, 7/8) 리포트 통째로 하루 밀림.
  (3) 등급 카운트 199 vs 195 표기 비대칭 (보유 제외 규칙).
- **수정** (`6f5f224`, main 머지 대기): KIS 경로 수정 + 게이트/추세 소스를
  get_index fresh 종가 append 로 보정 + LTD 미확보 시 게이트 강제 미통과
  + 기준일 명시 (silent fallback 차단) + 카운트 통일.
- **검증**: 스텁 3시나리오 + 파서 호환 통과. **KIS 경로는 다음 cron 로그로
  확정 필요** (크리덴셜 부재로 로컬 검증 불가).
- **주의**: 07-09 발행 리포트의 A등급 11개는 게이트 오판 산물 (정상 판정
  시 전종목 D). 당일 분석 JSON 에는 게이트 미통과 간주 명시 완료.
