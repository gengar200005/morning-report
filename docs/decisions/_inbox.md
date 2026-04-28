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

- **Claude augmentation 운영 재개 (Claude Code 이식)** ✅ 셋업 완료:
  04-26 ADR-009 폐기 결정 후에도 04-27/28 main 에서 `Claude 분석 반영
  (auto)` commit 패턴이 사실상 운영 재개됨. 마스터의 web Project 가
  GitHub commit 권한 인식 안 되는 이슈로 막혀, **Claude Code 슬래시
  명령 `/analyze` 로 이전**. 기반: `CLAUDE_PROJECT_INSTRUCTION_v5.md`
  v5.1, Drive fetch → 로컬 morning_data.txt 직접 읽기, GitHub MCP →
  git push 로 단순화. main 직접 commit 예외는 web Project 시절부터
  동일 (04-25 `bfd73ea` 등).
  운영 모델: 매일 cron (06:25 KST) 끝난 후 ~07:00 KST Claude Code 세션
  열어서 `/analyze` 한 줄 → 7카드 JSON commit + push → claude_render.yml
  자동 트리거 → PDF + Notion 갱신.
