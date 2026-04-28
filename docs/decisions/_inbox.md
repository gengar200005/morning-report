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
- **KOSPI 200 전체 추적 (라이브 한정)** ✅ 적용 완료: 라이브 리포트
  universe 162 → 200. `kr_report.py::UNIVERSE` 200 갱신,
  `reports/sector_overrides.yaml::ticker_overrides` 164 → 234 (KOSPI 200
  100% 매핑 + KOSPI 200 외 stale 34 보존). 섹터 분류 7개 모호 케이스
  (팬오션/카카오뱅크/아세아/풍산/한진칼/SK케미칼/두산로보틱스) 는
  코드베이스 선행 분류 + 시장 정체성 기준 결정. 백테 universe (162) 는
  스냅샷 그대로 유지.
- **stale cleanup 후속 (KOSPI 200 외)**: 293490 (옛 카카오뱅크 추정) →
  323410 정식, 000215 (옛 DL이앤씨) → 375500 정식, 298000 (옛 효성티앤씨)
  → 298020 정식, 005870 (옛 한화생명) → 088350 정식. KOSPI 200 universe
  외이므로 라이브 영향 0. 다음 세션 정리.

- **Claude augmentation 운영 재개 (Claude Code 이식)** ✅ 셋업 완료 →
  **B 옵션 채택 (저널 거울)**: 04-26 ADR-009 폐기 결정과 04-27/28 운영
  재개의 어긋남을 **분업 frame** 으로 재정의. 룰 (백테 + 신호 + 게이트)
  = 자동 / 인간 판단 (매크로 / 사이즈 / 페이퍼 vs 실전 / 심리) = 인간 →
  7카드는 **인간 판단 영역의 저널 거울** (의사결정 input 아님). "객관적
  옳음" 평가 폐기, "오늘 읽고 1분 내 의사결정 정리에 도움됐나" 만 점검.
  마스터 1주 자체 점검 후 NO 면 즉시 A (전면 폐기) 전환.
  ADR-009 는 "augmentation = 알파 input" 가정으로 폐기됐는데 분업 frame
  으로 재정의하면 폐기 사유 사라짐. 다만 narrative bias 위험은 여전 →
  매주 자체 점검 의무.

- **운영 모델**: 매일 cron (06:25) 끝 ~07:00 KST Claude Code 세션 →
  `/analyze` → `docs/claude_analysis/{YMD}.json` main commit + push →
  `claude_render.yml` 자동 트리거 → PDF + Notion 갱신.
