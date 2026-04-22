# 환경별 작업 가이드

로컬(집 PC, Claude Code CLI) ↔ 웹(병원/맥북, Claude Code 웹 또는 Claude.ai)
간에 어떤 작업을 어디서 하는 게 좋은지 정리.

---

## 환경별 능력 비교

| 항목 | 로컬 PC (CLI) | 웹 Claude Code |
|---|---|---|
| 파일 읽기/쓰기 | ✅ 로컬 파일 직접 | ✅ GitHub 통해 |
| 커밋/푸시 | ✅ git 바로 | ✅ PR 또는 직접 커밋 가능 (권한 있을 때) |
| Python 실행 | ✅ 로컬 env | ⚠️ 샌드박스 제한 (패키지/데이터 없음) |
| pykrx 실행 | ✅ (로컬 IP) | ⚠️ KRX IP 차단 가능 (해외 IP 서버) |
| KIS API 호출 | ✅ 환경변수 | ⚠️ 시크릿 전달 필요 |
| 텔레그램/디스코드 | ✅ requests | ✅ requests |
| auto memory 접근 | ✅ 전용 경로 | ❌ **웹에선 못 봄** |
| 백테 데이터 (16MB) | ✅ 로컬 parquet | ❌ gitignore 되어 있음 |
| Notion/Google Drive | ✅ MCP | ✅ MCP (웹도 지원) |

---

## 작업 유형별 환경 추천

### 로컬에서 해야 하는 작업
- **백테 실행**: `backtest/data/` 파일이 로컬에만 있음
  - `python backtest/strategy.py`
  - `python backtest/99_minervini_vcp_compare.py`
  - `python backtest/99_walkforward.py`
- **pykrx 데이터 수집**: `01_fetch_data.py` — KRX IP 제약
- **장중 알림 시스템 운영**: Windows Task Scheduler
- **실전 매매**: KIS API 직접 호출
- **대용량 파일 생성/편집**

### 웹에서 해도 되는 작업
- **코드 작성/리뷰**: 전략 로직 수정, 리팩토링
- **문서 작성**: CLAUDE.md, SESSION_LOG, ADR, 플랜 문서
- **의사결정 기록**: `/adr` 사용
- **간단한 테스트**: 순수 함수 단위 테스트
- **계획 수립**: 다음 작업 플랜 설계
- **코드 분석**: 기존 코드 읽기/이해
- **GitHub 이슈 관리**: 트래킹, 라벨링

### 둘 다 가능 (하지만 환경 고려)
- **외부 API 호출 스크립트**: 로컬이 편함 (시크릿)
- **데이터 분석**: 로컬에서 데이터 있고 웹은 분석 로직만

---

## 환경 전환 워크플로우

### 로컬 → 웹 (퇴근 ↔ 출근 / 집 ↔ 병원)

**로컬에서 세션 끝날 때**:
```
/session-end [오늘 한 일 요약]
```
→ SESSION_LOG 업데이트 + 커밋 제안 → 푸시 승인

**웹에서 세션 시작할 때**:
1. 레포 pull 또는 GitHub 연결 확인
2. Claude Code에서:
```
/session-start
```
→ CLAUDE.md + SESSION_LOG + git log 자동 파악

### 웹 → 로컬 (퇴근)

**웹에서 세션 끝날 때**:
```
/session-end [오늘 한 일]
```
→ 커밋/푸시

**로컬에서 시작할 때**:
```bash
cd morning-report
git pull
claude
/session-start
```

---

## 주의사항

### 1. auto memory는 환경 종속
- `C:\Users\sieun\.claude\projects\...\memory\` 는 **로컬 전용**
- 웹 환경에선 못 봄
- **핵심 지식은 CLAUDE.md 에 이관해 둘 것** (이번에 완료)
- 세션 종료 시 중요 결정은 SESSION_LOG + ADR 에 기록

### 2. 시크릿/환경변수 이중화
- 로컬: `.env` 파일 또는 시스템 환경변수
- 웹: Claude Code 보안 토큰 또는 런타임 입력
- **`.env` 는 절대 git 커밋 금지** (`.gitignore` 확인)

### 3. 브랜치 전략
- **작업 브랜치**: `claude/automate-morning-report-9bUuB` 유지
- **main 직접 수정 금지** (GitHub Actions 크론 전용)
- main 머지는 **테스트 완료 후 일괄**

### 4. 백테 데이터 재생성
- `backtest/data/ohlcv/*.parquet` 는 gitignore
- 새 환경에서 백테 돌리려면:
  ```bash
  python backtest/01_fetch_data.py    # 2-5분
  python backtest/02_validate_data.py # 10초
  python backtest/strategy.py         # 1-2분
  ```
- 웹 환경에선 pykrx 차단으로 불가능할 수 있음 → **로컬에서만 실행**

---

## 권장 패턴

### "플래닝은 웹, 실행은 로컬"
- 출근길/병원에서: 설계, 문서화, 리뷰, ADR
- 퇴근 후 집에서: 실제 코드 작성, 실행, 테스트

### "작은 변경은 웹, 큰 변경은 로컬"
- 웹: 단일 파일 편집, 문서 수정
- 로컬: 여러 파일 동시 수정, 백테 실행, 파라미터 튜닝

### "공식 기록은 항상 git"
- 메모, 아이디어, 결정은 즉시 SESSION_LOG/ADR/PLAN
- 다음 세션에서 "이거 뭐였지?" 안 되도록

---

## 시크릿 관리 체크리스트 (내일 알림 시스템 세팅 전)

- [ ] KIS API 키: **로컬에만**, `.env` 또는 환경변수
- [ ] 텔레그램 봇 토큰 (준비 시): **로컬에만**
- [ ] GitHub PAT: 로컬 git credential manager
- [ ] `.env` 파일 `.gitignore` 등록 확인
- [ ] 웹 Claude Code에서 로컬 시크릿 필요한 작업은 **로컬로 미루기**
