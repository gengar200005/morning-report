# 2021년 3월 분기 정기공시 원장 재현

Python 3.12와 상위 폴더의 public_dart_requirements.txt에 지정된 패키지를 사용한다. 명령의 작업 디렉터리는 이 문서의 폴더다.

## 확정 산출물 오프라인 재현

```bash
python census_ledger.py identity_universe.csv census_context.csv public_xbrl_receipt_index.json census_xbrl_evidence.json.gz census_versions.csv /tmp/verify-census --display census_display_evidence.json.gz
python census_audit.py /tmp/verify-census/census_rows.csv /tmp/verify-census/census_audit.json
python census_asof.py /tmp/verify-census/census_rows.csv census_amendments.json /tmp/verify-census/census_asof_20210601.csv
sha256sum /tmp/verify-census/census_rows.csv /tmp/verify-census/census_asof_20210601.csv
```

정기공시 782행의 SHA-256은 `25df3aacfe0cd03e2c9cfe009fd39c858bf6b4b875f23a0dbb37c6c3df1ea3a2`, 6월 1일 사용 가능 버전의 SHA-256은 `b8facb8369f1fe3ab6e5e72bee9702cbbe61a83ea4aeef64f132fa319a259f7b`다. 숫자 원장은 원화 정수로 제공하며 EPS는 분석에서 제외했다.

## 원본 다운로드와 재개

```bash
python census_collect.py identity_universe.csv public_xbrl_receipt_index.json /tmp/portal.sqlite --workers 5 --nondec identity_nondec.json
python census_amendments.py identity_universe.csv census_versions.csv public_xbrl_receipt_index.json /tmp/amendments.sqlite /tmp/portal.sqlite /tmp/census_amendments.json
```

수집기는 공개 OpenDART XBRL 다운로드 버튼의 접수번호와 문서번호를 쓴다. 공식 웹페이지와 같은 User-Agent와 Referer가 없으면 HTTP 200과 함께 빈 응답이 올 수 있으며 빈 응답은 저장하지 않는다. 728개 당기 원본 중 9개는 기존 표본의 검증 기록을 재사용했다. 나머지 719개 ZIP은 각각 원본 바이트와 SHA-256, 태그·기간·단위 판정 결과를 SQLite에 저장했다. 기존 표본과 원본 전수 수집 여부는 `census_xbrl_evidence.json.gz`의 접수별 자료를 통해 대조할 수 있다. 정정본 30개는 원본과 별도 캐시에 저장했다. HTML 대체는 `kind_display.py` 및 `display_fields.py`를 사용했다. 국내 공식 DART 뷰어의 503 응답과 대체 웹서비스의 정상 동작을 서로 구분했다. 최초 5개 ZIP 요청은 일시적 시간 초과 후 재개 실행에서 모두 회수했다.

원본 ZIP의 데이터 구조나 공시 목록이 달라지는 경우에는 새 응답의 해시를 기존 증거와 비교한다. `census_bundle.py`는 SQLite의 ZIP 해시를 검산한 뒤 Git에 보존할 필드별 증거를 압축해 내보낸다. 원문 HTML의 행과 원본 URL·SHA-256은 `census_display_evidence.json.gz`에 있다. 연결재무제표 적용 대상이 없다고 명시된 92건은 정기공시 연결 실적 신호에서 제외했다. 별도재무제표의 값은 `OFS_` 열에서만 확인한다.

## 버전과 적용 범위

`census_versions.csv`는 4월 1일~6월 30일 DART 전시장 분기보고서 검색 결과 중 연결된 법인에 해당하는 2021.03 원본 및 정정 색인이다. 구체적인 원본 검색식과 30개 페이지의 SHA-256은 이전 연구 기록인 evidence_20261126/dart_all_index.json에 있다. 9월 결산 기업 두 곳은 반기 정기공시의 명시적인 3개월 비교 열을 독립적인 XBRL·표시원문·수기 검산으로 확인했다. 이 두 회사의 별도 색인은 identity_nondec.json에 있다. 첫 정보 사용일은 공시일 다음 KRX 거래일이다. 이 기간 밖의 정정이나 더 이른 잠정공시는 이 데이터셋의 대상에 포함되지 않는다.

동일 날짜에 원본과 정정이 있는 경우 원본은 확정 신호에서 보류한다. 정확히 하나의 정정이 그 원본을 대체한 경우에는 정정 금액을 다음 세션부터 사용할 수 있다. 같은 날 정정이 여러 건이면 접수번호만으로 선후를 정하지 않는다. 해시가 있는 최신 공시에 항목이 빠졌을 때 직전 공시값을 복사하지 않는다. 6월 1일 원장은 직전 3월 31일 782종목 대상으로 만든 것이므로 실험의 실제 6월 1일 투자 가능 종목과 해당 일자 WICS가 다를 수 있다. 당시 종목군과 업종을 별도 확인해야 한다.

금융 52개에는 금융업 영업수익·영업이익이 실제 출력되어 있어도 비금융 신호 적용군에 넣지 않았다. 8개 업종 미확인 기업은 분모 민감도에 남겼다. 원장 신호 품질분자 598개를 비금융 722개와 비교하면 82.83%, 업종 미확인 8개를 추가한 730개와 비교하면 81.92%다. 6월 1일에는 정확한 정정본을 연결해 605개의 3월 기준 비금융 관찰을 사용할 수 있었다. 실적 수집 모듈은 주가·계좌 성과 데이터를 읽지 않는다.
