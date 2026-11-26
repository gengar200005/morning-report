# Stage 5 보존 입력과 조건부 재사용 범위

2026-11-26 현재 파일명, ZIP 중앙 디렉터리의 멤버명·바이트 길이·CRC, 원 입력의 SHA-256을 검사했다. Stage 5 inputs.json은 입력 해시만 담은 메타데이터다. 입력 4개의 원바이트를 SHA-256으로 스트리밍 대조했다. DB 질의, 표·현금흐름·수익률 파일의 행 열람, 신규 연구 성과 계산은 실행하지 않았다. 임시 사본과 별도로 원본 ZIP 4개는 사용자 보관 파일에서 다음 이름으로 확인됐다. 상세 수치와 해시는 stage5_input_inventory.json에 있다.

|원본 ZIP|기존 자산|확인 범위|
|---|---|---|
|Morning_Report_V2_Stage5_Evidence_20261106.zip|formations.csv.gz, outcomes.csv.gz, calendar.json, inputs.json, SHA256SUMS|형성 신호 4,361,303B, 개별 관측 결과 3,563,492B. 단순 집계표 외 개별 패널이 보존됨. 개별 행은 열람하지 않음.|
|Morning_Report_V2_Stage2_Evidence_20261106.zip|Morning_Report_V2_Economic.sqlite 1,158,238,208B|Stage 5 입력 database 해시와 일치. 경제 DB 재구축 불필요.|
|Morning_Report_V2_Stage3_Evidence_20261106.zip|inputs/yahoo_069500.json, inputs/daum.json, benchmark.json, inputs/issuer1~6.json|앞의 세 입력이 Stage 5 etf·secondary·benchmark 해시와 각각 일치. 분배금 증빙 파일 6개의 멤버명도 확인.|
|Morning_Report_V2_PIT_Foundation_20261106.zip|Morning_Report_V2_PIT.sqlite 757,428,224B|원천 PIT DB도 보존됨. Stage 5가 실제 사용한 입력은 위 Stage 2 경제 DB.|

Drive KRX_PIT_GITHUB_ACTIONS_PRIVATE 폴더는 138개 항목이며 월별 KRX 원본 130개와 과거 V1 자료 등이 보인다. 해당 폴더에는 위 Stage 5 출력 파일명이나 Stage 2 경제 DB 파일명이 없다. 조회된 다른 Drive PIT 폴더는 비어 있고 모닝리포트 v2 검증 폴더에는 이전 클라우드 인계 ZIP 및 배당·기업행동 보고서가 있다. 프로젝트 체크아웃에서 발견되는 기존 stocks_daily.parquet·sector_map.parquet는 Stage 5 입력 해시 목록에 없는 다른 파일이다.

## 적용 순서

1. 2021Q1 품질 게이트가 미달이면 아래 성과 연구를 열지 않는다. 원본 정기공시 실적 연구에서는 잠정실적 최초 시장발표일이 확정되지 않아도 문서 공개일 이후의 사용 가능 시점을 지킨다. 정정·선후 관계를 해결할 수 없는 관측은 격리한다.
2. Q1 게이트를 통과한 신호만 2021년 Q2, Q3, Q4 순서로 같은 정책의 품질검사를 한다. 각 분기는 그 분기말 역사적 보통주 모집단을 다시 고정한다. 누적과 3개월, 연결과 별도, 원화와 표시단위, 정정, 당기/전년 비교일을 각각 확인한다. Q4는 연간수치를 4분기로 대입하지 않는다. 접수 당시 검증된 독립 3개월 금액이 없는 경우 기존 사전 규칙대로 보류한다. Q4 가용성이 낮다는 이유로 Q1만 거래하거나 상장 종목/검증 기간을 임의 변경하지 않는다. 2017~2021 연도별 품질 게이트와 사전 통계 코드 검증까지 통과해야 본검증을 시작한다.
3. 전체 지표 런을 반복하지 않는다. Stage 5 formations 출력은 당시 종가와 그 전 252일 연속 유효 수익 링크가 있는 종목에 한정된다. outcomes의 ISIN도 동일 제한이다. 따라서 두 파일은 Stage 10 F2/F3 × M4 및 Stage 9 공통 적격군 민감도에 재활용할 수 있다. 모든 실적 종목에 대한 Stage 9 주 분석은 신규 상장·가격 결측 종목 등을 원래 모집단에 남긴다. 보존 경제 DB의 membership, execution_bars, krx_return_checks, economic_momentum, corporate_actions, exit_audit 및 공식 거래일을 읽기 전용으로 활용해 기존 패널에 없는 날짜·ISIN만 평가한다. 주 분석에 개별 결과가 없는 종목을 일괄 삭제하지 않는다. 해당 구성과 필드명은 기존 momentum_study.py 구현 기준이며 이번에 DB 행 내용은 조회하지 않았다.
4. 2017~2021 개발과 이후 재검증을 분리한다. Stage 5 outcomes.csv.gz에는 기존 2022~2023 결과도 같이 있으므로 본검증 시 개발 범위의 날짜만 쿼리하여 통계에 포함한다. Stage 5 생성기의 원래 기간 경계 검열을 유지하고, 비용·실제계좌 성과는 별도 11단계 전까지 계산하지 않는다. 현재 8.2 감사에서 어떠한 전략 수익률도 계산하지 않았다.
