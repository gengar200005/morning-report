# 1~3분기 발표 연구의 증빙 재생

`data_gate.json`에 결과 접근 보류를 고정했다. 아래 명령은 KRX 거래일·기본정보와 재무 원문만 사용한다. KRX ZIP의 시세 데이터에서는 필드 이름만 읽고 가격 값, 이후 수익률, M4 성과는 계산하지 않는다.

비공개 증빙에는 입력 파일 목록과 SHA-256, 증빙 파일 전체 해시를 기록했다. ZIP에서 `replay/formation_roster.csv`와 `replay/filing_recovery_ledger.csv`를 바로 읽을 수 있다. 2017년 법인명 일치, 2021Q1 개별 공시의 확인 근거 및 형성일 게이트는 구별한다. 2017~2020년 모든 회사의 원·정정 이력이 있는 경우에만 전체 색인을 추가로 검증할 수 있다.

```sh
# 저장소 상위에서 실행
s=morning-report/research/v2_pit/quarterly_events
python "$s/feasibility.py" "$MARKET_ZIP" "$RAW01_ZIP" "$STAGE82B_ZIP" \
  evidence/inputs/raw_facts_by_document.csv evidence/inputs/exit_list.csv repro
python "$s/flow_check.py" "$MARKET_ZIP" evidence/inputs/exit_list.csv \
  evidence/flow/flow_probe_results.json evidence/flow repro/flow_results.json
```

`repro/`의 출력을 증빙의 `replay/` 파일 및 전체 해시와 비교한다. 가격 평가를 위한 Stage 5 자료는 필요하지 않다. 기존 원문 및 수급 응답을 다시 받지 않고 실행한다. 버전을 바꾸지 않은 파이썬 의존성은 기존 연구와 같다.

테스트는 아래 네 연구 검색 경로와 일반 테스트 경로를 각각 실행한다.

```sh
cd morning-report
export PYTHONPATH=research/v2_pit:research/v2_pit/stage82b:research/v2_pit/stage9_panel:research/v2_pit/quarterly_events
for suite in '' /stage82b /stage9_panel /quarterly_events; do
  python -m unittest discover -s "research/v2_pit$suite" -q
done
python -m pytest -q tests
```
