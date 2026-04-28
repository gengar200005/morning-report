# Decision Inbox

세션 중 **"해보자" 가 굳어지는 순간** 1~3줄 즉시 추가 + 즉시 commit + push.
코드 변경 0 이어도 OK. 세션이 도중에 뻗어도 다음 세션이 git log + 본 파일만 보고
컨텍스트 회복.

다음 세션 시작 시 회수 → CLAUDE.md / SESSION_LOG / ADR 로 정식 흡수 → 해당 entry 삭제.

**이 파일에 한해 운영 규칙 "마스터 승인 후 push" 예외 허용** (자동 push OK).

---

## 2026-04-28

- **결정 인박스 도입**: 본 파일 자체. 세션 뻗음 → 컨텍스트 손실 4번 연속
  발생한 패턴 mitigation. ADR 까지 안 가는 가벼운 방향성도 OK.
- **KOSPI 200 전체 추적 (라이브 한정)**: 라이브 리포트 universe 를 기존
  162종목 → KOSPI 200 으로 확장. 백테 universe 확대는 **생략** (페이퍼
  트레이딩 우선). 종목 목록은 마스터 수동 수집 (KRX [11006] 또는 동등
  소스), **섹터 매핑은 Claude 담당** (기존 ticker_overrides.yaml 164 →
  200 확장).
