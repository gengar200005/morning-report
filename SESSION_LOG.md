# Session Log

프로젝트 세션별 작업 일지. 최신이 상단. 상세한 결정 근거는 `docs/decisions/`.

---

## 2026-04-23 (UZymn 브랜치) — ADR-003 섹터 강도 산정 방법론 채택

> **참고**: 같은 날짜에 `claude/session-start-UBATP` 브랜치에서 별개 작업
> (장중 알림 시스템 + 세션 연속성 구조) 진행됨. 본 세션은 그것과 독립적인
> ADR 작업. 두 작업 모두 PC 환경에서 통합 처리 필요.

### 결정
- **섹터 강도 산정을 ETF top-down → 유니버스 bottom-up 으로 전환**
  (ADR-003). 18개 ETF 가격 기반에서 우리 백테 162종목을 KRX 22 업종으로
  분류 + 3요소 산식으로 변경.
- **3요소 100점 산식**:
  - (A) IBD 6M 백분위 — **50점**
  - (B) Weinstein Stage 2 — **25점**
  - (C) Breadth (% above MA50) — **25점**
- **한국 시장 적용 4대 판단** (Claude가 결정):
  - 비중 50/25/25 (40/30/30 균등 안 채택) — O'Neil/Minervini 본인 우선
    순위 (IBD 1차, Stage 2차) + 한국 변동성 22% 로 Stage whipsaw ↑
  - **시총 가중 + 단일 종목 25% cap** — 삼성전자 KOSPI ~20% 단독 영향
    차단. KRX 200 인덱스 30% cap 보다 보수적 (섹터 단위는 종목 적어 cap
    영향 더 큼)
  - 임계값 75/60/40 유지 (백테 후 조정 명시)
  - 표본 부족 단계화: ≥5 정상 / 3-4 breadth=0 (max 75) / <3 N/A
- **strategy 진입조건 통합은 별도 ADR-004 로 분리** (검증 통과 후 결정).
  본 ADR은 "표시용 점수 산정"까지만 범위.
- **세션 종료 (구현은 PC 세션으로 이월)**: 웹 환경에서 pykrx KRX 호출
  실패 (sandbox 네트워크 isolation) 확인. 추측 기반 구현은 회귀 위험
  높아 PC 세션에서 데이터 보고 구현하는 게 효율적.

### 검토한 대안
- **main 머지** (앵커 확립으로 세션 연속성 해결): 세부 작업 미완으로 의미
  없다고 사용자 판단. 알림 시스템 PC 검증 후 재논의.
- **UZymn 에 UBATP 머지** (알림 시스템 코드 가져오기): 이번 세션에 알림
  시스템 작업 없으므로 중복 브랜치만 origin에 추가 → 보류.
- **UBATP 로 체크아웃 이동**: 시스템 지시("UZymn에서 develop") 어긋남.
- **메타 인프라 구축** (main 인덱스 파일 + SessionStart 훅으로 브랜치
  난립 근본 해결, 1.5-2h): 1-2 세션 더 해보고 패턴 명확해진 후 판단.
- **비중 40/30/30** (균등): O'Neil/Minervini 우선순위 미반영, 기각.
- **비중 60/20/20** (IBD 강조): Stage 너무 약화, Minervini 2단 필터
  구조 무력화, 기각.
- **동등 가중**: 한국 소형주 노이즈 ↑ + 시장 신호 왜곡, 기각.
- **순수 시총 가중** (cap 없이): 삼성전자 단독 영향 과대, 기각. KRX 200
  자체가 30% cap 사용.
- **WICS 세분류** (10섹터→24산업그룹→69산업): FnGuide 유료/스크래핑 부담.
  KRX 22업종 충분하다고 판단.
- **Jegadeesh-Titman 12-1 Momentum**: 12M lookback 한국 변동성 대비 김.
  Chae & Eom (2009) 한국 negative momentum 보고 → 6M 이 더 robust.
- **RRG (Relative Rotation Graph)**: 산식 복잡, 단일 점수 환산 시 정보
  손실. v2 시각화로 보류.
- **즉시 구현 진입**: 웹 환경에서 KRX 데이터 접근 불가로 추측 기반 코드
  되어 다음 세션에서 다시 손봐야 → 비효율, 기각.

### 주요 작업
1. ✅ `/session-start` → 현재 브랜치(UZymn) 상태가 stale 임을 발견
2. ✅ 모든 원격 브랜치 스캔 → UBATP 가 최신 (알림 시스템 + 세션 연속성)
3. ✅ "세션 연속성 문제" 근본 원인 분석 — 웹 Claude 가 매 세션 새 브랜치
   를 만드는데 앵커 부재 → 이전 작업 누락
4. ✅ 머지 전략 검토 → 이번 세션엔 머지 없이 진행 결정
5. ✅ 사용자가 실제 작업으로 pivot: "섹터 구분 명확화 + 방향성 판단 기준"
6. ✅ 현재 `sector_report.py` 분석 → 한계 4가지 정리
7. ✅ 업계 표준 섹터 강도 지표 6가지 조사 (IBD, Weinstein, RRG, Breadth,
   Jegadeesh-Titman, Dorsey Wright)
8. ✅ Minervini 생태계 표준 조합 식별 (IBD 1차 + Weinstein 2차)
9. ✅ pykrx 데이터 가용성 확인 — KRX 22업종 + 종목 매핑 + 업종지수 OHLCV
   모두 무료 가능 (단, sandbox 네트워크 isolation으로 라이브 검증 미가능)
10. ✅ ADR-003 초안 작성 (40/30/30, 임계값 75/60/40)
11. ✅ ADR-003 한국 적용 판단 반영 갱신 (50/25/25 + 25% cap + 표본 단계화)
12. ✅ 커밋 2회 (`f7efc35`, `b38ae2e`) + push (origin/UZymn 신규 등록)

### 다음 세션에서 할 일
- **[우선] PC 환경에서 두 작업 묶음 처리** (총 1.5-2h)
  1. **UBATP 브랜치** → 알림 시스템 E2E 테스트 (이월 작업, 30분)
     - `git pull` + `pip install -r requirements.txt` + `.env` 생성
     - `notifier.py` 단독 테스트 → 디스코드 수신 확인
     - `signals_today.py --force --dry-run` → KIS 스캔
     - Task Scheduler XML import + 경로 수정
  2. **UZymn 브랜치** → `sector_breadth.py` 신규 구현 (1시간)
     - ADR-003 명세 그대로: 50/25/25, 시총가중+25%cap, 표본 단계화
     - `reports/sector_overrides.yaml` 신규 (KRX 자동 분류 보강용)
     - `sector_report.py` 출력에 신/구 점수 병행 표시 (검증)
- **회귀 검증**: 최근 1년 월별 → 새 산식 "주도" 판정 섹터의 다음 1개월
  수익률이 코스피 기준선 이상인지 확인
- **(이월)** 1주일 알림 모니터링 후 v2 개선 / main 병합 리허설 / 페이퍼
  트레이딩 저널 / 2025+ 이상치 검증 / 2022 방어 실패 분석

### 미해결
- **세션 연속성 근본 해결 보류**: 메타 인프라(main 인덱스 + SessionStart
  훅) 구축이 가장 확실한 해법이지만 1.5-2h 부담으로 1-2 세션 더 해보고
  판단. **다음 새 세션이 UZymn/UBATP 외 브랜치에서 파생되면 또 누락 가능**.
- **KRX 22업종 중 우리 162종목 실제 분포 미확인**: PC 세션에서 pykrx 호출
  후 표본 부족 섹터 (3개 미만) 실제 몇 개인지 확인 필요. 그 결과로 섹터
  단위 점수 산출 가능 개수 확정.
- **ADR-003 임계값/표본 처리 세부 조정**: 백테 검증 후 75/60/40 임계값과
  표본 임계 (5/3) 가 적절한지 실측. 첫 결과 후 ADR 갱신 가능성.
- (이월) 포인터 갱신 수동 의존, kr_report 수급 vs strategy.check_supply
  차이 재확인, 생존편향 정량화, 공휴일 달력 미구현.

### 이번 세션에서 배운 것
- **세션 연속성 fix 의 자기 모순**: UBATP 세션이 만든 fix(`/session-start`
  브랜치 스캔 + CLAUDE.md 포인터)가 UBATP 브랜치에만 존재 → 이번 세션이
  다른 브랜치(UZymn)에서 시작하면서 fix 자체에 도달 못 함. 메타 인프라가
  파편화된 채 작동하면 의미 없다는 실증.
- **"클로드가 결정" 위임의 가치**: 사용자가 "한국에 적합한 방식으로 구성"
  요청하면서 4가지 판단(비중/가중/임계값/표본) 한 번에 정리 가능. 일일이
  사용자 의견 묻는 것보다 근거 명시 + 결정 + 사용자 검토가 효율적.
- **웹 환경 한계 인지**: pykrx KRX 호출이 sandbox 에서 안 되는 것 일찍
  확인 → 구현 미루는 결정 합리화. 환경 제약을 일찍 점검하면 작업 범위
  자연스럽게 좁혀짐.
- **ADR 분리 원칙의 가치**: ADR-003 (점수 산정) vs ADR-004 (strategy 통합)
  분리해두면 검증 단계 명확. 한 번에 결정하지 않고 단계별 결정.

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
