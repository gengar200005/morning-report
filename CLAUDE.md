# CLAUDE.md

Claude Code 세션 간 공유되는 프로젝트 컨텍스트. 진행 중인 이니셔티브와 작업 규칙을 기록한다.

## Phase 3 진행 상황 (2026-04-21 기준)

**완료**:
- Git 세팅: phase3-backtest 브랜치 생성, 원격 동기화 완료
- 커밋 3개 push 완료 (최종: 62d4053)
  - 3e85d4c: .gitignore 추가
  - 5945d99: 백테스트 프레임워크 스켈레톤
  - 62d4053: yfinance 전환 (pykrx 지수 API 버그 우회)
- 스모크 테스트 통과: 삼성전자·SK하이닉스 11년치 OHLCV 정상
- 데이터 소스 검증: yfinance ↔ FDR ↔ KRX 공식값 일치 확인

**다음 단계 (Step 5)**:
- 전체 163종목 OHLCV 본 수집
- 실행: `python backtest/01_fetch_data.py`
- 예상 소요: 5~15분
- 스모크 테스트된 005930/000660은 캐시 스킵됨
- 실행 후 meta.json의 failures 리스트 반드시 검토

**알려진 데이터 이슈** (signals 단계에서 처리):
- 종목-지수 영업일 불일치 4~5일
- volume=0 캐리오버 2건
- 거래대금(value) 컬럼 pykrx 미반환

**주의사항**:
- phase3-backtest 브랜치에서만 작업 (main 직접 수정 금지)
- backtest/ 폴더 외 수정 금지
- 푸시는 명시적 승인 후에만
- GitHub UI "Run workflow" 시 반드시 main 브랜치 선택
