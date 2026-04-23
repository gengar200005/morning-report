# Plan 002: sector_breadth PC 세션 실행 계획

**브랜치**: `claude/session-start-UZymn`
**선행**: Colab 에서 `notebooks/sector_data_fetch.ipynb` 실행 완료 (Phase B).
산출물 2개 Drive 저장됨.
- `MyDrive/morning-report/sector_data/sector_map.parquet` (164행, 9.7 KB)
- `MyDrive/morning-report/sector_data/stocks_daily.parquet` (79,644행, 1.6 MB)

---

## PC 세션 착수 (예상 45-60분)

### 1. 브랜치 + 의존성 (5분)
```bash
git checkout claude/session-start-UZymn
git pull
pip install -r requirements.txt        # pyyaml/pandas/numpy/pyarrow/pytest
```

`requirements.txt` 에 `pyarrow` 없으면 추가:
```bash
pip install pyarrow pytest
```

### 2. 단위 테스트 실행 (5분)
```bash
pytest tests/test_sector_breadth.py -v
```

25개 테스트 모두 통과해야 진행. 실패 시:
- import 에러 → `pip install -e .` 또는 PYTHONPATH 조정
- numpy/pandas 버전 불일치 → `pip install -U numpy pandas`
- 로직 에러 → 해당 함수 수정 + 회귀

### 3. Drive parquet 로컬 복사 (2분)

옵션 A (Windows) — Google Drive for Desktop:
```
G:\내 드라이브\morning-report\sector_data\sector_map.parquet
G:\내 드라이브\morning-report\sector_data\stocks_daily.parquet
```
→ `backtest/data/sector/` 로 복사.

옵션 B — Drive 웹에서 다운로드 후 `backtest/data/sector/` 에 넣기.

### 4. CLI 실데이터 실행 (2분)
```bash
python sector_breadth.py \
    --sector-map backtest/data/sector/sector_map.parquet \
    --stocks-daily backtest/data/sector/stocks_daily.parquet
```

**확인 포인트**:
- 15개 섹터 (universe에 등장한) 점수 출력
- `주도` 등급 섹터 수 (0-3개 예상)
- `N/A` 섹터 (표본 <3) — 비금속광물(1) 이 확실히 해당
- 금융 41개 편중 체감: "금융업" 섹터가 위에 있으면 지주회사 재분류 시급

### 5. 회귀 검증 스크립트 작성 + 실행 (25분)

`scripts/validate_sector_breadth.py` 신규 작성:
- 최근 12개월 각 월말 기준으로 섹터 점수 산출
- 각 월의 "주도" 섹터 리스트 → 다음 1개월 해당 섹터 종목 평균 수익률
- 같은 기간 코스피(KS11) 수익률 과 비교
- 결과 표: 월, 주도 섹터, 섹터 평균, 코스피, 초과수익(%p)

**성공 기준** (ADR-003):
- 12개월 평균 초과수익 > 0
- 60% 이상 월에서 초과수익 양수

실패 시 임계값/표본 수 튜닝 고려. 또는 ADR-003 재검토.

### 6. 지주회사 오버라이드 추가 (10분)

금융 41개 중 사업실체가 비금융인 종목을 `reports/sector_overrides.yaml`
`ticker_overrides:` 에 추가:
```yaml
ticker_overrides:
  003550: 전기전자    # LG
  001040: 음식료품    # CJ
  034730: 통신업      # SK (SKT 주요 자회사)
  078930: 유통업      # GS
  # ... 실데이터 보며 판단
```

재실행해서 섹터 분포 재확인.

### 7. 커밋 + 최종 결정 (5분)

커밋 포인트:
- 회귀 검증 결과 (통과/실패)
- ticker_overrides 추가
- (선택) ADR-003 amendment 추가 — "회귀 검증 결과" 섹션

이월 결정:
- **통과** → sector_report.py 에 신/구 점수 병행 표시 (별도 플랜)
- **실패** → ADR-003 임계값/가중치 재검토
- **pykrx 복구** 여부 → Stage 25점 복원 결정

---

## 참고: 이 세션(웹)에서 완료한 것

커밋 9개 (UZymn 브랜치):
1. `7baef92` notebooks A1 스캐폴드
2. `551bf57` notebooks A2 섹터 분류 셀 (구버전, pykrx 기반)
3. `aeb9f6c` notebooks A3 업종지수 주봉 셀 (삭제됨)
4. `372a8f4` notebooks A4 종목 일봉 셀
5. `61ee16f` gitignore parquet 차단
6. `fc9d7f1` notebooks pykrx retry 폴백 (미완)
7. `3a236e6` ADR-003 amendment - pykrx 장애 대응
8. `b4cb496` sector_overrides.yaml (KSIC→22업종 매핑)
9. `02ae40f` notebooks 재작성 (KIND+FDR pivot)
10. `2650050` sector_breadth.py + 25 pytest

핵심 결정:
- pykrx 인덱스 API 다운 → KRX KIND + FDR 로 pivot
- Weinstein Stage 25점 보류 → score rescale ×100/75
- 임계값 75/60/40 유지

### 이월 이슈 (PC 세션에서 처리)
- universe.py 누락 4종목 (상폐/코드변경): 008560, 000060, 042670, 000215
- 지주회사 29개 재분류 (ticker_overrides)
- pykrx 복구 모니터링 → Stage 복원 조건 충족 시 ADR-005
