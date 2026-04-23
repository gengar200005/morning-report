# Plan 003: sector_report.py 신/구 점수 병행 표시

**브랜치**: `claude/session-start-UZymn`
**선행**: ADR-003 Amendment 2 판정 PASS (SESSION_LOG 2026-04-23 #4).
**목적**: 모닝리포트에 신 산식(ADR-003 "주도+강세" × universe-avg) 결과 노출.
1-2주 운영 체감 후 구 18 ETF 산식 deprecate.

---

## 배경

검증된 산식이 아직 모닝리포트에 안 들어가 있음. 실전 사용성 검증 없이
deprecate 결정하면 회귀 리스크. 두 산식 병행 기간을 둔다.

**현 산식** (`sector_report.py`):
- 입력: 18개 섹터 ETF 가격 (KODEX 반도체, TIGER 2차전지 등)
- 산식: RS(50) + 추세(30) + 자금(20) = 100점
- 한계: ETF 바스켓 ≠ 우리 universe 162종목, 가중치 근거 없음

**신 산식** (`sector_breadth.py`):
- 입력: 우리 universe 162종목 OHLCV + KIND/FDR 매핑
- 산식: IBD(50) + Breadth(25) rescale ×100/75 = 0-100, 임계 75/60/40
- ADR-003 Amendment 2 판정 PASS

---

## 설계 옵션

### A. 모닝리포트 HTML 에 섹션 추가 (권장)

신 점수를 기존 섹터 리포트 블록 아래에 별도 섹션으로 추가.

```
[현 블록 유지]
KODEX 반도체  85.3  🔴 주도
TIGER 2차전지 72.1  🟡 강세
...

[신 블록 추가]
── ADR-003 섹터 강도 (우리 universe 기준, 베타 병행) ──
전기전자  88.9  🔴 주도 (17종목)
건설업    73.3  🟡 강세 (6종목)
운수장비  67.5  🟡 강세 (12종목)
...
```

**장점**: 두 결과 동시 관찰. 어느 쪽이 실전 의사결정에 더 쓸만한지 1-2주 체감.
**단점**: 리포트 길이 증가 (~15행).

### B. 기존 섹션 안에 2개 컬럼 (병렬 표시)

```
섹터           ETF점수  ADR점수  차이
반도체          85.3    88.9    +3.6
...
```

**장점**: 직관적 비교.
**단점**: 섹터 단위가 다름 (ETF 섹터 18개 vs KRX 22업종). 1:1 매핑 필요 →
임시 매핑 테이블 작성 부담.

→ **A 권장** (매핑 충돌 회피)

---

## 구현 단계

### 1. 데이터 파이프라인 (가장 큰 리스크)

`sector_breadth.py` 는 Colab 산출 parquet 2개 필요:
- `sector_map.parquet` (KIND+FDR 매핑 + 시총)
- `stocks_daily.parquet` (162종목 2년 OHLCV)

**모닝리포트는 매일 06:00 KST GitHub Actions 에서 실행** → parquet 접근 방법 결정:

**옵션 1: Actions 에서 직접 수집** (FRESH)
- `01_fetch_data.py` 패턴 따라 `fetch_sector_data.py` 추가
- pykrx + FDR + KRX KIND 호출 (~5-10분 런타임)
- CON: pykrx 장애 시 모닝리포트 전체 실패 리스크. 워크플로 복잡도 ↑.

**옵션 2: parquet 을 레포에 커밋** (SNAPSHOT)
- 주 1회 수동 업데이트 (매주 월 장 마감 후 Colab 실행 → commit)
- `backtest/data/sector/*.parquet` 에 위치
- CON: gitignore 에서 제외 필요. stale 리스크 (주 1회 갱신이면 최근 5일 누락).

**옵션 3: Google Drive 에서 Actions 가 pull** (HYBRID)
- Colab 실행 cron (주 1회 또는 매일)
- Actions 에서 `gdrive_download.py` 로 가져오기 (기존 `gdrive_upload.py` 반대)
- CON: Drive API credentials Actions secret 설정 필요.

→ **초기는 옵션 2 (주 1회 수동) 권장**. 운영 체감 후 1 or 3 으로 전환.

### 2. sector_report.py 수정

현재 구조 파악 후:
```python
from sector_breadth import compute_sector_scores, load_sector_map, load_stocks_daily

def render_adr003_section(sector_map_path, stocks_daily_path) -> str:
    scores = compute_sector_scores(
        sector_map_path=sector_map_path,
        stocks_daily_path=stocks_daily_path,
        overrides=load_overrides("reports/sector_overrides.yaml"),
    )
    # 주도+강세 만 필터 + 시총 top 3종목 표시
    leading = scores[scores["grade"].isin(["주도", "강세"])]
    return render_html(leading)
```

`kr_report.py` 또는 `combine_data.py` 에서 기존 섹터 블록 렌더 후 `render_adr003_section` 호출.

### 3. 폴백

parquet 누락 / sector_breadth import 실패 시 기존 리포트만 출력. "ADR-003 데이터
없음" 경고만 표시. 모닝리포트 전체가 죽으면 안 됨.

### 4. 테스트

- pytest: `tests/test_sector_report.py` 에 신 섹션 렌더 단위 테스트 (mock data)
- 실행: `python kr_report.py --dry-run` 로 HTML 결과 확인
- 1-2일 실 리포트 모니터링

### 5. 커밋 + PR 없이 UZymn 에 머지 준비

main 머지 리허설 전 UZymn 에서 1주일 관찰.

---

## 예상 소요 30-45분

단, 데이터 파이프라인(옵션 1/2/3) 결정은 별도 논의. 옵션 2 (수동 parquet
커밋) 가 가장 빠르지만 gitignore 변경 + 스냅샷 갱신 정책 결정 필요.

---

## 성공 기준

- [ ] 모닝리포트 HTML 에 "ADR-003 섹터 강도" 섹션 출력
- [ ] 주도+강세 섹터 리스트 + 섹터별 종목 수 + 대표 시총 상위 3종목
- [ ] parquet 누락 시 폴백 동작 확인
- [ ] 1주일 운영 관찰 후 판단: 구 산식 유지 / 축소 / deprecate

---

## 이월

- ADR-004 (strategy.py 에 섹터 필터 통합) 은 본 작업 완료 후 별도 세션
- pykrx Stage 복원 → ADR-005
