# Decision Inbox

세션 중 **"해보자" 가 굳어지는 순간** 1~3줄 즉시 추가 + 즉시 commit + push.
코드 변경 0 이어도 OK. 세션이 도중에 뻗어도 다음 세션이 git log + 본 파일만 보고
컨텍스트 회복.

다음 세션 시작 시 회수 → CLAUDE.md / SESSION_LOG / ADR 로 정식 흡수 → 해당 entry 삭제.

**이 파일에 한해 운영 규칙 "마스터 승인 후 push" 예외 허용** (자동 push OK).

---

## 2026-04-28 #3 — NDX 필터 진단 결과 (3 case 결론)

본 세션 (worktree `claude/crazy-kirch-06c1d1`) `backtest/99_ndx_filter_diagnosis.py`
+ `99_signal_gap_diagnosis.py` 진단:

1. **인덱스 차원 mean reversion**: KOSPI 시가→시가, NDX 전일 -2% 이하 →
   +0.255% (+0.20%p vs 전체), -3% 이하 → +0.322%. NDX 전일 +2% → -0.229%,
   +3% → -0.441%. 단조 패턴, n=2,773.

2. **개별 시그널 종목 갭 분포** (백테 333 trade, 162종목 11.3년): 평균
   갭 +0.173%, 중앙 0.000%, 갭상 비율 49.2%. **"시그널 = 갭상" 직관은 사실
   아님**. 시그널 (Minervini + 수급 + RS top-5 + 시장 게이트) 이 잡는 건
   베이스 정리 후 막 돌파 종목 — 이미 점프한 종목 아님.

3. **갭상 ≥3% 거래만 음수 수익률** (12+3건 / 333건 = 4.5% / 0.9%, 평균
   -5.47% / -10.46%). 1단계 mean reversion 패턴이 trade 차원에서도
   확인됨 (-3% 이하 갭다운 9건은 +13.26% 평균).

**결론 (ADR-010 4번째 적용 case)**:
- NDX 필터 추가 ❌ (인덱스 mean reversion + 시그널 종목 갭상 편향 부재)
- 백테 "시가 100% 체결" 가정의 알파 부풀림 효과 **작음** (마스터 직전
  세션 의문에 직접 답). 슬리피지 -1~2%p 보정은 여전, -10%p 같은 큰
  보정 불필요.
- **잠재 후속**: 갭상 ≥3% 회피 룰 — 6% trade 차단 시 효과? 사전 검증
  1차 출처 가능. 다음 세션 추가 검토 후보.

**다음 세션 흡수**: 위 3건 결과를 CLAUDE.md "핵심 지식" 또는 ADR-010
사례 추가에 반영. ADR 후보 5건째 — 갭상 ≥3% 회피 룰 (sensitivity plan
필요). 본 entry 삭제.

본 세션 산출물: `backtest/99_ndx_filter_diagnosis.py`,
`backtest/99_signal_gap_diagnosis.py`, KOSPI parquet (yfinance fallback).

