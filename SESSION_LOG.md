# Session Log

프로젝트 세션별 작업 일지. 최신이 상단. 상세한 결정 근거는 `docs/decisions/`.

---

## 2026-04-22 — Phase 3 완료 + 전략 재확정 + 아키텍처 + 문서 인프라

### 결정
- **T15/CD120 → T10/CD60 재확정**
  - 103종목 백테가 검증 과엄격으로 61종목 제외된 것 발견
  - Validation 로직 수정 (거래정지일 제외 + 0.1% 톨러런스) → 162종목 복원
  - 162종목 재백테: T15/CD120 +16.16% vs T10/CD60 **+29.29%** → 뒤집힘
  - Walk-forward (IS/OOS) 양쪽에서 T10/CD60이 일관되게 상위권
  - 실전 기댓값 +10-13% → **+15-20%**로 상향
- **strategy.py + strategy_config.yaml 단일 소스 아키텍처 도입**
  - 백테(99_*.py)와 라이브(kr_report.py)가 같은 함수 import
  - 파라미터는 yaml 한 곳, 로직은 strategy.py 한 곳
  - kr_report.py가 구 T15/CD120 파라미터로 돌고 있던 drift 버그 제거
- **의사결정 기록 시스템 도입** (CLAUDE.md + SESSION_LOG.md + ADR + 슬래시 명령어)
  - 환경(로컬 ↔ 웹 Claude Code) 간 작업 이어가기 위함
- **내일 알림 시스템 작업 플랜 사전 문서화** (docs/plans/001-alert-system-setup.md)
  - 웹 환경에서 `/session-start` 한 줄로 작업 재개 가능하도록
- **슬래시 명령어 전역 + 프로젝트 이중 배치**
  - 레포 내 `.claude/commands/`: git 추적 → 웹 환경/clone에서 사용
  - `~/.claude/commands/`: 로컬 편의 미러 (다른 프로젝트에서도 사용)
  - 마스터는 레포 쪽. 수정 시 레포에서 하고 전역으로 수동 sync.

### 검토한 대안
- **T10/CD120** (OOS 최고 +49.94%): IS 랭크 #11로 불안정, 채택 X
- **T20/CD60** (IS #2, OOS #3): MDD -42.2%로 악화, 채택 X
- **VCP auto 3요소**: 거래 124건으로 너무 적음, 수동 차트 판정으로 유지
- **재수집** (pykrx adjusted / FDR / KIS): 진단 결과 데이터는 정상, validation 로직만 수정으로 해결

### 주요 작업
1. ✅ Samsung parquet 진단 → 거래정지일 OHLV=0 + 라운딩 편차 원인 규명
2. ✅ validation 로직 수정 (backtest/02_validate_data.py) — 103 → 162종목
3. ✅ 162종목 TRAIL × CD 그리드 재백테 실행
4. ✅ Walk-forward 분석 (backtest/99_walkforward.py 신규)
5. ✅ strategy_config.yaml 작성 (T10/CD60 파라미터)
6. ✅ strategy.py 작성 (check_signal, run_backtest, calc_metrics)
7. ✅ 99_minervini_vcp_compare.py → strategy.py delegate 리팩토링
8. ✅ kr_report.py → strategy.py 연결 (Minervini 8조건 공유)
9. ✅ 백테 회귀 검증 (+29.29% 재현, diff 0바이트)

### 다음 세션에서 할 일
- **[우선] 실시간 알림 시스템 구축** (2026-04-23, 웹 Claude Code)
  - 상세 플랜: `docs/plans/001-alert-system-setup.md`
  - 사용자 준비: 텔레그램 봇 토큰 + chat_id (또는 디스코드 webhook)
  - 작업: notifier.py + signals_today.py + Task Scheduler (총 2.5-3.5h)
- **페이퍼 트레이딩 저널 템플릿** (실전 착수 전 검증)
- **2025+ 이상치 검증**: +157% CAGR의 종목/섹터 집중도 분석
- **2022년 방어 실패 상세 분석**
- **main 머지**: pyyaml requirements 추가 후 workflow_dispatch 테스트 → 머지

### 미해결
- kr_report의 수급 로직(KIS 외인/기관)과 strategy.check_supply(up/dn vol)의
  의도적 차이 재확인 필요
- 생존편향 정량화 (2015년 상폐 종목 실제 리스트 확보)

### 이번 세션에서 배운 것
- **기댓값 숫자는 유니버스 구성에 극도로 민감**: 103 → 162로 바꿨을 뿐인데
  최적 파라미터 자체가 바뀜. 과적합 탐지는 유니버스 확대로 검증 가능.
- **MDD 프레이밍 수정**: 전략 -29.8% < ETF -43.9%. 자동 손절이 오히려
  버티는 심리 부담 덜어줌. 진짜 리스크는 "박스권 언더퍼폼" 기회비용.
- **파라미터 drift는 조용히 발생**: kr_report가 구 T15/CD120 값 그대로
  운영 중이었고 아무도 몰랐음. 단일 소스 원칙의 실전적 필요성 확인.
