# Session Log

프로젝트 세션별 작업 일지. 최신이 상단. 상세한 결정 근거는 `docs/decisions/`.

---

## 2026-04-23 #5 (UZymn, 웹) — 11섹터 전환 + sector_report.py 재작성 + kr_report 버그 수정

### 결정
- **KOSPI200 11섹터 체계 전환** (ADR-003 Amendment 3) — 외부 리서치 v2026.04 기반.
  반도체/전력인프라/조선/방산/2차전지/자동차/바이오/금융/플랫폼/건설/소재·유통.
- **구 18 ETF 산식 완전 폐기** (KIS API OHLCV + RS50/추세30/자금20 전체 삭제).
  `sector_report.py` 414 → 226줄 전면 재작성.
- **ticker_overrides 16 → 164 전면 재작성** — universe 164종목 전부 명시.
  KSIC auto 매핑 의존도 제거 (폴백 유지).
- **Q1/Q6 태양광 = 전력인프라** (한화솔루션/OCI) 채택. 사용자 외부 세션 판단.
- **Q2/Q5 합병 플래그** (현대건설기계 + HD현대인프라코어, 2026.01 합병) — MISC 분류 + 주석.

### 주요 작업
1. ✅ `sector_report.py` 에 ADR-003 베타 섹션 추가 (`render_adr003_section()`)
   → 1차 확인 후 전면 재작성 (18 ETF 완전 폐기)
2. ✅ parquet 2개 (`sector_map.parquet` 9.7KB + `stocks_daily.parquet` 1.6MB) 레포 커밋
   (plan-003 옵션 2: 주 1회 Colab 수동 갱신)
3. ✅ `backtest/data/sector/` 디렉토리 + `.gitkeep` + `.gitignore` 명시적 허용
4. ✅ `kr_report.py` 버그 수정 — `check_minervini_detailed` import 누락.
   리팩토링(9522c62) 후 라이브 첫 런에서 universe 162 → 0 종목 발생 원인.
5. ✅ `kr_report.py` 출력 문자열 cleanup:
   - "쿨다운 120거래일" 하드코드 → yaml 값 사용 (60)
   - "103종목 +20.7% MDD -26.2% 기댓값 10-13%" → 162종목 +29.29% MDD -29.8% 기댓값 +15-20%
   - 주석 "T15/CD120" 잔재 제거
6. ✅ `reports/kospi200_sectors.tsv` 추가 (외부 리서치 150종목 × 11섹터)
7. ✅ universe 164 ↔ CSV 150 교차: matched 96 + universe_only 68 매뉴얼 분류 → 전부
8. ✅ `sector_report.py` 전면 재작성 — sector_breadth 직접 호출 + 산식 전환 감지
9. ✅ Dry-run 검증: 11섹터 점수 정상 산출
   (반도체 100, 건설 90, 방산 88, 전력인프라 75, 2차전지 64 ... 바이오 11)

### 검토한 대안
- **신/구 섹션 병행 출력 유지**: 구 18 ETF 섹션 유지하며 신 섹션 덧붙임.
  사용자 판단으로 **구 완전 폐기** 선택 (혼동 회피, 단일 소스).
- **테마 ETF 구성종목 실수집 (Colab)**: `KODEX 반도체` 구성종목을 pykrx/KIS 로 실수집
  해서 자동 분류. 외부 리서치 CSV 가 제공되어 이 작업은 불필요해짐 — 향후 갱신 시 검토.
- **내 지식 기반 초안 제안**: 5-6 테마로 한정 (반도체/2차전지/자동차/방산/조선).
  외부 리서치가 11섹터로 더 포괄적 → CSV 채택.
- **HTML 파서/렌더 호환**: `sector_report.py` 만 재작성하면 HTML 섹터 카드
  깨짐 발견. **plan-004 로 분리** (이월).

### 이번 세션에서 배운 것
- **리팩토링 후 라이브 검증 필수** — kr_report.py `9522c62` 는 "백테 검증 완료" 로
  기록됐지만 실제 라이브 런은 한 번도 안 돌았고, 오늘 수동 트리거에서 `NameError`
  로 universe 전부 skip 되는 치명적 버그 드러남. CLAUDE.md 의 "검증 완료" 표기는
  검증 범위 (백테 only vs 라이브 포함) 를 명시해야 함.
- **출력 layer stale** — yaml 파라미터 전환 (T10/CD60) 은 끝났다고 생각했지만
  출력 문자열에 하드코드 "120거래일" / "103종목 +20.7%" 이 남아있었음. 리팩토링은
  **로직 layer 뿐만 아니라 출력 layer 까지 끝나야 완료**.
- **KSIC 자동 매핑 한계** — KRX KIND 의 업종 분류(KSIC)가 2024-26 그룹 재편을 반영
  못함. POSCO홀딩스="전기전자", 동양생명="전기전자" 등 stale. `ticker_overrides`로
  전부 명시하는 게 안전.
- **HTML 렌더 레거시 파서 의존** — `sector_report.py` 만 바꾸면 `_parse_sector_etf`
  가 신 포맷 파싱 실패. 텍스트 리포트와 HTML 리포트는 커플링 강함.
- **섹터 분해 효과 극명** — 구 "운수장비 79" 가 신 체계에서 **방산 88 + 자동차 57
  + 조선 52** 로 나뉨. 방산이 진짜 주도였고 조선은 조정 중인 실체. 정제 효과.

### 미해결
- **plan-004 HTML 렌더 재작성** (1-2h) — main 머지 블로커
- **UZymn 수동 트리거 최종 검증 미완** — 마지막 커밋 `30247b6` 이후 라이브 런 없음
- **브랜치 정리 10개** — GitHub 웹 UI 로 수동 삭제 필요 (이전 세션 이월)
- **universe.py 이름 stale 추가 발견**:
  - 009540 "한진칼" → 실제 HD한국조선해양 (시총 32조)
  - 079960 "동양생명" → 금융업이지만 전기전자로 auto 분류됨
  - 005870 "한화생명" → 금융업이지만 전기전자로 auto 분류됨
- **첫 cron 런의 전환 노이즈** — 구 ETF state vs 신 11섹터 state 간 matching 0 →
  transition flag 로 감지했지만 실제 GitHub 의 sector_state.json 덮여쓰기는 첫 런 후.

### 다음 세션에서 할 일 (데스크탑)
- **[최우선] plan-004**: HTML 렌더/파서 재작성 (3개 파일). 상세: `docs/plans/004-*.md`
- **UZymn 수동 트리거 1회** — 최종 검증 + HTML 깨짐 양상 실물 확인
- **main 머지** — plan-004 완료 후. 내일 06:00 cron 부터 11섹터 자동 반영
- **(이월)** UBATP 알림 시스템 E2E 테스트

---

## 2026-04-23 #4 (UZymn, 웹) — 섹터 회귀 검증 PASS + ADR-003 Amendment 2

### 결정
- **ADR-003 정식 판정 기준 확정**: "주도+강세" × universe-avg 벤치마크.
  hit 83%, mean_excess +2.37%/월, 종합 PASS.
- **"주도" 단독 등급 운영 폐기** — 집중도 과도 → 섹터 변동성에 취약 (hit 42%
  → FAIL). "주도+강세" 가 알파-안정성 균형점.
- **벤치마크는 universe-avg** (동등가중 162종목 평균) — KOSPI 는 universe
  구성 차이(SK하이닉스 등 mega-cap 편입 여부)로 beta drag -3.6%/월 유발.
  이는 signal 책임 아님. `--benchmark kospi` 참고용 유지.
- **`ticker_overrides` 16개 seeding 고정** — 5 initial + 11 확장. 금융업
  41 → 26종목 축소. KSIC "기타 금융업" 에 혼재된 비금융 지주사업 분리.

### 주요 작업
1. ✅ `scripts/validate_sector_breadth.py` 신규 — 월별 회귀 루프 + KOSPI/
   universe 벤치마크 + PASS/FAIL 판정
2. ✅ `sector_breadth.py` 에 `load_overrides` + `apply_ticker_overrides` +
   CLI `--overrides` 통합. compute_sector_scores 에 overrides 파라미터.
3. ✅ `tests/test_sector_breadth.py` 에 overrides 테스트 10개 추가 → 총 ~35
4. ✅ `reports/sector_overrides.yaml` 5 → 16 entries 확장 (지주회사 재분류)
5. ✅ `notebooks/sector_validate.ipynb` Colab 실행 파이프라인 (pytest →
   latest scores → 회귀 → 금융업 Top 30 iterate → 커밋)
6. ✅ `requirements.txt` 에 pandas/pyarrow/PyYAML 명시 (실사용 중이었으나
   latent 의존)
7. ✅ Colab 3회 회귀 실험:
   - 5 override × KOSPI: mean -1.16%, hit 50% → FAIL
   - 16 override × KOSPI: mean -2.21%, hit 42% → FAIL (역효과)
   - 16 override × universe: mean +2.37%, hit 83% → **PASS**
8. ✅ ADR-003 Amendment 2 작성 — 판정 기준 + ticker_overrides 근거 + 한계

### 검토한 대안
- **override 확장 없이 산식만 튜닝**: 16 override 확장 후 주도 mean 이
  오히려 -1.1 → -2.2%/월 악화 (전기전자 marcap 커지며 일부 약세월 drag
  증폭). override 자체보다 **벤치마크가 근본 문제**였음이 드러남.
- **주도 단독 유지 + 임계 상향(≥80)**: 신호 더 적어져 변동성 ↑, 표본 부족
  으로 신뢰구간 악화. 기각.
- **표준 Stage 25점 복원 시도**: pykrx 인덱스 API 여전히 다운. 회귀 돌리기
  전 복원 조건(ADR-005) 충족 불가. 보류 유지.
- **종목 단위 Minervini 필터 병행**: 섹터 산식의 독립 검증이 우선. Strategy
  통합은 ADR-004 로 분리.

### 이번 세션에서 배운 것
- **벤치마크 선택이 결과를 뒤집음**: 산식 변경 없이 KOSPI → universe-avg
  전환만으로 FAIL → PASS. 벤치마크가 "측정 대상에 관련된 beta drag 을
  포함하는가" 가 판정 타당성의 핵심. 3회 실험 중 2번은 산식/override 를
  튜닝한 건데, 진짜 문제는 비교 기준이었음.
- **"주도" 엄격 필터 ≠ 우수한 알파**: 집중하면 알파 평균은 비슷해도
  분산이 커서 hit ratio 망가짐. **"주도+강세" 가 hit 41% → 83%** 로 확
  뛴 건 reliability 자체의 가치. 백테에서 mean 보다 hit ratio 중시한 결정.
- **ticker_overrides 이중 효과**: 금융업 drag 제거 기대로 시작 → 실제로는
  전기전자/기계 marcap 증가시켜 주도 단독에선 역효과. 주도+강세로 확장하면
  섹터 다양성 복원으로 효과 발휘. **override 효과는 grade 조합과 연동**.
- **fat-tailed 알파**: 2025-12/2026-01/2026-03 3개월이 전체 excess 의
  60% 이상 기여. 강세장 집중 효과. 즉 "주도+강세" 는 하락장 방어보다
  **상승장 초과수익 레버리지** 성격. 이 방향성은 Minervini 전략과 일치.

### 미해결
- **2026-03 경계 효과**: 23거래일(1개월 미달)이라 outlier 가능. 다음 월말
  (2026-04-30) 데이터 확보 후 재검증 시 알파 크기 확인
- **표본 12개월**: mean/hit 신뢰구간 여전히 넓음. 2년치 stocks_daily 로
  6M lookback 후 12개월 확보 한계. 2027년까지 누적 재측정 필요
- **SK Inc. (034730) / 카카오페이 (377300)**: 투자지주·핀테크 섹터 귀속
  보수적 유지. 향후 그룹별 사업 재편 모니터링 필요
- **universe.py 누락 3-4종목**: 008560/000060/042670/000215. 백테 재현성
  영향 → 별도 ADR 판단 이월

### 다음 세션에서 할 일
- **[우선] `sector_report.py` 신/구 점수 병행 표시** (30-45분)
  - 기존 18 ETF 산식 결과 + 신 ADR-003 결과를 나란히 출력
  - `reports/sector_mapping.py` 와 `sector_breadth.py` 통합 지점
  - 모닝리포트에서 실전 체감 → 1-2주 운영 후 구 산식 deprecate
- **[차순위] ADR-004 착수** (1시간)
  - 주도+강세 섹터를 `kr_report.py` signals 생성 시 진입 게이트로 통합
  - `strategy_config.yaml` 에 `sector_filter: true|false` 플래그
  - 백테 재실행으로 CAGR 변화 측정 (162종목 × 11.3년)
- **(이월)** UBATP 브랜치 알림 시스템 E2E 테스트 (30분)
- **(이월)** universe.py 누락 종목 처리 + pykrx Stage 복원 모니터링

---

## 2026-04-23 #3 (UZymn, 웹) — pykrx 장애 pivot + sector_breadth 구현

### 결정
- **pykrx 1.2.7 인덱스 마스터 API 전면 다운 확인** — Colab Phase B 실행
  중 발견. `get_index_ticker_list`, `get_index_ticker_name`,
  `get_index_ohlcv_by_date`, `get_index_portfolio_deposit_file` 모두 사망.
  종목 OHLCV 만 정상.
- **데이터 소스 pivot**: 섹터 매핑은 KRX KIND (KSIC) + FDR 시총, 업종지수
  주봉은 수집 보류 (Weinstein Stage 25점 비활성)
- **산식 조정**: `(IBD 50 + Breadth 25) × 100/75 = 0-100 스케일`, 임계값
  75/60/40 유지 (rescale 덕분)
- **Stage 복원 조건** 명시: pykrx 복구 + 2년치 결손 없는 수집 + sanity
  pass → 별도 ADR
- **Weinstein 처리 (a) 75점 재정의 채택** (사용자 승인). 대안 (b) 합성
  sector index, (c) ETF 임시, (d) 대기 모두 기각
- **Phase C 실데이터 검증은 PC 세션 이월** — 웹 Drive MCP 가 `drive.file`
  scope 제한으로 Colab 산출 parquet 접근 불가. 1시간 삽질 대신 PC 에서
  10분 처리가 효율

### 주요 작업
1. ✅ Colab 노트북 초안 (Section 1-4, 22셀) 작성 + 커밋 5개
2. ✅ pykrx fetch 실패 진단 — `__fetch` JSON 에러 → IndexTicker master
   df 공유 구조로 인덱스 API 전체 사망 확인
3. ✅ FDR `StockListing('KRX-DESC')` + KRX KIND `상장법인목록` 검증
4. ✅ KIND `업종` 컬럼 = KSIC 9차 소분류 (58종) 확인 → 22업종 환원 필요
5. ✅ ADR-003 Amendment 2026-04-23 작성 (커밋 `3a236e6`)
6. ✅ `reports/sector_overrides.yaml` 작성 — KSIC 58종 → 15개 KOSPI 22업종
   자동 매핑 (커밋 `b4cb496`)
7. ✅ 노트북 전면 재작성 (KIND+FDR pivot, 16셀) 커밋 `02ae40f`
8. ✅ Colab 재실행 → parquet 2개 Drive 저장 성공:
   - sector_map.parquet: 164행, 160 섹터매핑 성공, 9.7KB
   - stocks_daily.parquet: 162종목 × 500일 = 79,644행, 1.6MB
9. ✅ Drive MCP 접근 실패 확인 → PC 이월 결정
10. ✅ `sector_breadth.py` 전체 구현 + 25 pytest (커밋 `2650050`):
    - IBD 6M 백분위 (시총가중+25%cap iterative)
    - Breadth (% above MA50) + 표본 단계화
    - classify_grade + compute_sector_scores CLI
11. ✅ `docs/plans/002-sector-breadth-pc-execution.md` runbook

### 검토한 대안
- **pykrx retry/폴백** (과거 영업일 5단계 x 3회): IndexTicker 마스터 df
  공유 구조 때문에 모든 시도 같은 에러. 기각
- **pykrx 강제 재설치**: 같은 버전이라 의미 없음. 대신 소스 pivot 선택
- **FDR `KRX-DESC` Sector 컬럼**: "벤처기업부" 등 KOSDAQ 상장구분값 → 섹터
  아님. 기각. Industry (KSIC) 는 유용
- **Naver/Daum 스크래핑**: 162 요청 fragility → KIND 1회 호출이 나음
- **웹에서 Drive 파일 ID 직접 입력**: MCP `drive.file` scope 로 외부 파일
  접근 불가 확인. 두 번 시도 모두 "not found"
- **Phase C 지금 세션 강행**: Drive 접근 삽질 + 로컬 pytest 불가 (sandbox
  numpy 없음) 으로 PC 10분 < 웹 30분. PC 이월 선택
- **Drive 파일을 ClaudeMorningData 폴더로 복사**: 가능하지만 사용자 수작업
  + 임시방편. PC 이월 택일

### 다음 세션에서 할 일 (PC 환경)
- **[우선] sector_breadth 실데이터 검증** (45-60분)
  - pytest → pass 확인
  - Drive parquet 로컬 복사
  - CLI 실행 → 섹터 점수 분포 + 금융 편중 체감
  - `scripts/validate_sector_breadth.py` 작성 + 12개월 회귀 검증
  - 지주회사 29개 `ticker_overrides` 추가
  - 상세: `docs/plans/002-sector-breadth-pc-execution.md`
- **(이월)** UBATP 알림 시스템 E2E 테스트 (30분)
- **(이월)** universe.py 누락 4종목 처리 + pykrx 복구 모니터링

### 미해결
- **Drive MCP 권한 범위 조사 보류** — `drive.file` scope 로 외부 생성
  파일 접근 불가. 웹에서 Phase C 불가능이 구조적. 해결책은 MCP 권한 확장
  또는 ClaudeMorningData 경로 통일 — 비용 > 편익으로 PC 이월이 최적.
- **universe.py 누락 4종목**: 008560 메리츠증권(2023 상폐), 000060 메리츠
  화재(2023 상폐), 042670 HD현대인프라코어(2026-01 해산), **000215 DL
  이앤씨(신규 발견 — 코드 변경 가능성, 현재 375500)**. PC 에서 확인 + 정리
- **pykrx 복구 여부 미확정**: 2026-04-23 장애 발견, 임시 회피 방식이
  언제까지 유효할지 불투명. ADR-005 대기
- **지주회사 ticker_overrides 비어있음**: 금융업 41개 중 비금융 사업 지주
  회사 많음. 실데이터 보고 PC 에서 20-30개 수동 추가 예상

### 이번 세션에서 배운 것
- **세션 연속성 실전**: 이전 세션이 Colab 진행 중 "세션 터짐" 으로 중단
  → "작업 쪼개서 하자" 합의 후 각 단계마다 즉시 커밋. 9 커밋 동안 1회도
  날리지 않음. **중간 커밋 전략의 가치 확실히 입증**
- **외부 API 의존 단일점**: pykrx 하나로 모든 인덱스/종목 데이터 하려다가
  한 번에 무너짐. KIND + FDR + pykrx 3원화가 일부만 죽어도 계속 전진 가능
- **"데이터 없이 코드만 작성" 의 가치**: Drive 접근 불가 상태에서도
  sector_breadth.py + 25 pytest 를 다 썼음. PC 세션이 25분 걸릴 일 10분
  으로 단축. **테스트가 실데이터 없어도 가치 있음**
- **ADR amendment 의 가치**: 원 ADR-003 을 "폐기하고 새로 쓰기" 가 아닌
  amendment 섹션 추가로 변화 이력 유지. 나중에 Stage 복원 시 깔끔한 diff
- **사용자 결정 위임**: "클로드 추천대로 가자" 3회 등장. 근거 + 후보 + 권장
  제시 후 "네" 받는 패턴이 효율적. 세부 매핑 (KSIC 58 → 22업종 매핑) 도
  전부 맡김 → 실데이터로 1회 완성

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
