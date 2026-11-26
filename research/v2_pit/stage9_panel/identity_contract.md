# 2017~2021 동결표본의 증권·공시 연결

월별 명부는 stage82b/limited_panel.py가 시점별 KRX membership과 sessions만 읽어 만든다. 60회×240행, 고유 ISIN 270개이며 CSV SHA-256은 84e5723e32f798a3fa7266c4dba6fa3fb076a014b4b01700077d4540ca369390이다. 기존 명부와 동일한 파일을 work_inputs/stage9/limited_issuer_months.csv로 복원했다.

| 산출물 | 키·내용 |
|---|---|
| identity/receipts.csv | 법인·증권·개별 버전 교차확인. KIND와 DART의 서로 다른 접수번호, DART 문서번호, 공개일, 회계기간과 SHA-256을 보관한다. |
| identity/monthly_coverage.csv | 명부의 14,400개 (formation, isin) 행을 유지한다. complete는 해당 형성일의 180일 창을 거래소의 3개 정기공시 유형이 덮고, 금융감독원 기업별 3유형 전체 목록 수집과 법인 교차근거가 있다는 뜻이다. 개별 공시 미확정 사유와 해당 행의 수치·업종·시점 게이트를 추가로 적용한다. |
| identity/coverage.csv | ISIN별 월 명부 대비 180일 검색창 완결월 수를 보존한다. |
| identity/technical_download_candidates.csv | 사전고정 기술표본의 원본 다운로드를 위한 DART 전체공시·공개 XBRL 목록 교집합이다. 실제 투자 신호는 원장 합격, 범위·단위 검수, 시점 게이트에서 확정한다. |
| identity/raw, identity/parsed | 페이지별 공식 검색 응답 및 재사용용 메타데이터다. KRX 조회는 화면·엑셀 내보내기, DART 조회는 3개 정기 유형을 선택한 단일 요청, OpenDART XBRL 검색은 서식별 요청을 사용한다. |

원장은 `isin, stock_code, corp_code, kind_receipt, receipt, document, filing_date, available_session, period_end, report_type, version, identity_status, kind_timestamp, source_kind_sha256, source_dart_sha256, original_receipt, reason`과 추가 감사 열을 가진다. 날짜는 YYYYMMDD이며 KIND 원문 시각은 KST다. 서식 코드 11011·11012·11013은 사업·반기·분기보고서다. 접수번호가 같은 문서는 원문 재요청 없이 재사용한다. 합격 접수에도 XBRL 주소가 없을 수 있다.

- DART·KIND 색인 표시일과 원문 접수번호 숫자는 독립 정보다. 가능한 FSS 목록 공개일, XBRL 색인 공개일, KIND 시각의 날짜 중 늦은 날짜를 filing_date로 삼고 다음 KRX 세션을 확인한다. 접수번호 앞 날짜는 날짜 차이 조회의 보조 단서다. 공개일이 다르면 KIND의 시·분만으로 동일 날짜의 DART 버전 순서를 확정하지 않는다.
- 날짜가 다른 버전 매칭은 두 공시의 종목·법인, 양식·대상기간·정정 여부, 인접 공식 거래일과 접수번호 날짜 관계가 모두 맞고 양방향에서 유일한 경우에만 허용한다. 실제 2016년 거래일 이전 자료는 2015년 비교 증거로만 보존하고 첫 사용 가능일은 비운다.
- 거래소 전체 목록의 각 페이지 순번·페이지수·신고 총수와 화면/엑셀상의 6자리 종목코드, 회사명, 제목, 제출인, 시각을 확인한다. 현재 회사 이름을 과거 법인으로 단독 지정하지 않는다. 당시 원문과 KRX 정보가 연결되지 않은 건은 kind_receipt 또는 receipt를 비워 사유별로 남긴다.
- DART의 제출기한연장신고서 등 접수 행은 자료 수집 건수에 포함되더라도 정기보고서 원문으로 쓰지 않는다. ‘[정]’ 아이콘과 정정 접수 자체를 구별한다. 같은 날짜·서식·기간에 복수 정정 후보가 있으면 번호 크기만으로 매칭하지 않는다.
- 기술 원장은 원본, 정정, 9개월·연간, 비교연도 구분 없이 각 접수를 보존한다. 실제 시점에서는 해당 형성일 전에 사용 가능해진 **가장 최근 회계기간**을 먼저 정하고 그 기간의 버전을 고른다. 늦게 올라온 오래된 분기의 정정이 최신 기간을 밀어내지 않는다. 신원과 기간에 대한 판정은 재무제표 수치 추출과 별개다.
