# 월 240종목 제한 연구의 자료 복원

소스는 이 연구 브랜치와 기준 커밋 `1ab461e6d4c4d3d89faff1f3472e7840f4b0507a`에 있다. 시장 입력 묶음과 공시 증빙 색인, 원문 분할 ZIP은 비공개 증빙을 사용한다. 가격 분석을 실행하기 전에도 아래 순서로 공시 검증을 재현할 수 있다.

1. 연구 저장소 옆에 `work_inputs/stage9`를 만든다. 공시 증빙 색인을 그 폴더에 풀고, 동봉한 `raw_parts.json`으로 각 원문 분할 파일의 SHA-256을 확인한다. 분할 파일들을 한 디렉터리에 모아 `python restore_raw.py 분할파일디렉터리 raw/receipts.sqlite`를 실행한다. 원문 파일명·URL·법인·문서번호는 `raw_manifest.csv`에 있다.
2. `Morning_Report_V2_Multiperiod_20261126_Market_Inputs.zip`에서 같은 `work_inputs/stage9`로 KRX 월별 원본과 업종 구성 자료를 푼다. 두 증빙에 함께 들어 있는 월별 명부·시장자료는 해시가 같다. 공식 거래일 입력은 기존 Stage 2 PIT SQLite, 기존 경제수익 입력은 Stage 3/5의 SHA가 확인된 SQLite를 사용한다.
3. 저장소 상위에서 아래 명령을 실행한다. 원장을 다시 만드는 과정에서는 공식 거래일과 공시만 읽는다. `--final`은 재계산 중에 원문이나 인덱스가 바뀌면 오류를 낸다. 공식 네트워크를 사용할 수 있는 별도로 허용된 환경에서는 보관된 manifest와 원장 결측 원인으로 필요한 접수를 정하고, 기존 collector의 `--batch-size`, `--kinds`로 한 묶음씩 추가할 수 있다. 동일 접수·서식의 저장본을 먼저 재사용한다. XBRL 컨테이너 충돌 격리 목록도 함께 복원해야 한다.

```sh
study=morning-report/research/v2_pit/stage9_panel
data=work_inputs/stage9
python "$study/pit_refresh.py" "$data" stage5-cache/Morning_Report_V2_PIT.sqlite "$data/replay" --final
python "$study/coverage_tables.py" "$data/replay/issuer_months.csv" "$data/replay/quality.json" "$data/replay/coverage_tables.json"
python "$study/audit_ledger.py" --panel "$data/limited_issuer_months.csv" --ledger "$data/replay/issuer_months.csv" --versions "$data/identity/receipts.csv" --db stage5-cache/Morning_Report_V2_PIT.sqlite --output "$data/replay/audit_ledger.json"
```

복원한 원장, 공시 버전 표, 180일 검색 범위, 표본 및 시장 입력의 해시는 증빙 색인의 `ledger/final/pit_snapshot.json`과 대조한다. 확정 판단에는 실적쌍 확보율과 독립 원문 판독을 함께 사용한다. 결과 조회는 `outcome_protocol.md`의 게이트를 충족한 신호에만 허용한다.

연구 테스트는 서로 겹치지 않는 세 경로에서 실행한다. 일반 회귀 테스트는 `pytest -q tests`를 기준 커밋과 같은 환경에서 실행해 실패 식별자를 대조한다.

```sh
cd morning-report
export PYTHONPATH=research/v2_pit
python -m unittest discover -s research/v2_pit -p 'test_*.py' -q
python -m unittest discover -s research/v2_pit/stage82b -p 'test_*.py' -q
python -m unittest discover -s research/v2_pit/stage9_panel -p 'test_*.py' -q
python -m pytest -q tests
```
