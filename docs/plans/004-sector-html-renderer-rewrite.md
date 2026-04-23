# Plan 004: 섹터 HTML 렌더/파서 재작성 (구 18 ETF → 신 11섹터)

**브랜치**: `claude/session-start-UZymn`
**선행**: Plan 003 완료 (`sector_report.py` 18 ETF 폐기 + 신 ADR-003 전용).
**블로커**: main 머지. 이 작업 완료 전 머지하면 HTML 섹터 카드 깨짐.

---

## 배경

2026-04-23 세션 #5 에서 `sector_report.py` 전면 재작성 완료 (구 18 ETF 폐기).
그러나 **HTML 렌더 경로는 여전히 구 포맷 의존**. 머지 전 재작성 필수.

---

## 영향 받는 파일 3개

### 1. `reports/parsers/morning_data_parser.py`

**현재**: `_parse_sector_etf()` 함수가 구 ETF 패턴 파싱.
```python
# 현재 기대 포맷:
# "1. KODEX IT 99.0점 ▲0.00% (RS 49 / 추세 30 / 자금 20)"
# "  └ 1M +33.3% / 3M +69.7% / 6M +134.1% MA20✓ MA60✓ MA120✓"
```

**신 포맷** (`sector_report.py` 산출):
```
🔥 주도 (≥75점)
  • 반도체        100.0점  ( 5종목, breadth 100%)
  • 건설          89.8점  ( 8종목, breadth  88%)
...
```

**작업**:
- 새 함수 `_parse_sector_adr003()` 추가 (신 포맷 파싱)
- 기존 `_parse_sector_etf()` 는 유지하되 호출부에서 제거
- 반환 dict 구조 결정:
  ```python
  {
      "leaders": [{"sector": "반도체", "score": 100.0, "n_stocks": 5, "breadth": 1.0}, ...],
      "strong":  [...],   # 강세
      "neutral": [...],
      "weak":    [...],
      "na":      [...],   # 표본부족
      "ref_date": "2026-04-23",
      "changes": {"new_leaders": [...], "demoted": [...], "score_jumps": [...]},
  }
  ```
- line 657: `"sector_etf": _parse_sector_etf(text)` → `"sector_adr003": _parse_sector_adr003(text)`

### 2. `reports/render_report.py`

**영향 라인**:
- line 26: `from reports.sector_mapping import resolve_sector` — sector_mapping 재작성 필요 (아래)
- line 161: `short = leading["etf_name"].replace("KODEX ", "")` — KODEX 의존 제거
- line 189: `leading = resolve_sector(stock["name"], data["sector_etf"])` — 신 매핑 함수 호출
- line 240: `leaders = data["sector_etf"].get("leaders") or []` — 키 이름 변경

**작업**:
- 섹터 카드 섹션 렌더 함수를 신 포맷 기반으로 재작성
- "KODEX" 접두어 제거 로직 삭제 (이름 그대로 "반도체", "방산" 등)
- `data["sector_adr003"]` 키 사용
- `resolve_sector()` 시그니처 변경 반영 (아래)

### 3. `reports/sector_mapping.py`

**현재**: `STOCK_TO_SECTOR_ETF` dict 하드코드.
```python
"SK하이닉스": "KODEX 반도체",
"DB하이텍": "KODEX 반도체",
...
```

**작업**:
- `reports/sector_overrides.yaml` 의 `ticker_overrides` (164종목) 에서 로드
- `resolve_sector(stock_name, sector_adr003)` 새 구현:
  - 종목명 → ticker → 섹터 이름 매핑
  - 섹터 이름으로 `sector_adr003["leaders"] / strong / ...` 에서 조회
  - tier/score 반환
- 종목명 → ticker 매핑은 `universe.py` 의 UNIVERSE 리스트 활용 (또는 역매핑 dict)

---

## 작업 순서 (예상 1-2시간)

1. **UZymn 수동 트리거로 현 상태 HTML 확인** (5분)
   - 실제 깨진 양상을 보고 재작성 방향 확정
   - GitHub → Actions → Run workflow → `claude/session-start-UZymn`

2. **sector_mapping.py 재작성** (20분)
   - `STOCK_TO_SECTOR_ETF` 삭제
   - `_load_ticker_to_sector()` 추가: overrides.yaml 로딩
   - `_load_name_to_ticker()` 추가: universe.py 역매핑
   - `resolve_sector(stock_name, sector_adr003)` 새 구현

3. **morning_data_parser.py 추가** (30분)
   - `_parse_sector_adr003()` 신 구현
   - 섹션 헤딩 ("🔥 주도 (≥75점)", "📈 강세 (60~74점)", ...) 으로 파싱
   - 개별 라인 정규식: `  • {섹터명:<10} {점수}점  ({n}종목, breadth {%}%)`
   - 주간 변동 섹션 ("⚡ 주간 변동" 이하) 파싱
   - 659행 반환 dict 에 `"sector_adr003"` 추가

4. **render_report.py 수정** (30분)
   - line 26: import 유지 (resolve_sector 시그니처만 변경됨)
   - line 161 일대: `data["sector_adr003"]["leaders"]` 읽어서 카드 렌더
     - "KODEX" 접두어 제거 로직 삭제
     - 섹터명 그대로 표시 + breadth %, n_stocks 추가
   - line 189: `resolve_sector(name, data["sector_adr003"])` 호출
   - line 240: `data["sector_adr003"].get("leaders")` 로 변경

5. **pytest 추가** (15분)
   - `tests/test_parser.py` 에 신 포맷 파싱 케이스
   - `tests/test_sector_mapping.py` 신규 (resolve_sector 동작)

6. **dry-run 검증** (10분)
   ```bash
   MORNINGREPOT=dummy python sector_report.py   # 신 sector_data.txt 생성
   # morning_data.txt 를 이미 오늘자로 보유 + parser dry-run
   python -c "from reports.parsers.morning_data_parser import parse_morning_data; \
              d = parse_morning_data('morning_data.txt'); print(d['sector_adr003'])"
   ```

7. **커밋 + push + UZymn 수동 트리거 재검증** (10분)
   - HTML 깨짐 해결 확인
   - Claude 해석 AI 가 카드 정상 읽는지 확인

8. **main 머지 + 브랜치 정리** (15분)
   - PR 혹은 fast-forward
   - 머지 후 내일 06:00 cron 에서 자동 반영 시작

---

## 리스크 / 주의사항

- **기존 `morning_data.txt` 의 `_parse_sector_etf` 호출이 여전히 있을 경우** — 기존 함수 삭제
  말고 일단 남겨두고 호출부만 교체. 후속 cleanup 커밋에서 제거.
- **Claude Project Instruction (CLAUDE_PROJECT_INSTRUCTION.md)** — 해석 AI 가 보는
  지침. sector 섹션 해석 범위 점검 필요. stale 확인: `T15/CD120` → `T10/CD60`
- **test_parser.py 에 fixture** — 기존 fixture 에 ETF 포맷 섞여 있으면 수정 필요
- **브랜치 정리 (10개 stale)** — GitHub 웹 UI 로 사용자가 직접 (이전 세션에서 정리 보류)

---

## 완료 정의

- [ ] sector_mapping.py 재작성 + universe 역매핑
- [ ] morning_data_parser.py 에 _parse_sector_adr003 추가
- [ ] render_report.py 섹터 카드 섹션 재작성
- [ ] pytest 통과 (기존 + 신규)
- [ ] UZymn 수동 트리거 → HTML 섹터 카드 정상 렌더
- [ ] main 머지
- [ ] 다음 06:00 cron 런에서 자동 반영 확인

---

## 이월 작업 (이 plan 과 별개)

- universe.py 누락 4종목 (008560/000060/042670/000215) 및 이름 stale (009540 한진칼→
  HD한국조선해양, 079960/005870 전기전자→금융) 정리 — 별도 ADR
- pykrx 인덱스 API 복구 모니터링 → Weinstein Stage 25점 복원 (ADR-005)
- 알림 시스템 (UBATP) E2E 테스트 — 별도 브랜치
- CLAUDE_PROJECT_INSTRUCTION.md `T15/CD120` stale 수정 (머지 타이밍)
