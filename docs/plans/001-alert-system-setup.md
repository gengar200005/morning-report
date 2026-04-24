# Plan-001: 장중 실시간 알림 시스템 구축

> ⚠️ **DEPRECATED (2026-04-24)** — ADR-007 에 의해 폐기. 본 플랜은 이력
> 보존용으로만 남김. 장중 알림이 매매 신호로 기능하지 않으며, 종가 후
> 알림은 다음 날 아침 모닝리포트와 정보량 동일 (중복). 청산 알림도 주식앱
> 기계 stop-loss 로 대체. 상세: `docs/decisions/007-scrap-intraday-alerts.md`.

**작성일**: 2026-04-22
**예상 작업일**: 2026-04-23 (다음 세션, 웹 Claude Code)
**총 작업 시간**: 2.5~3.5시간 (코드 작성 + 테스트)
**상태**: **폐기 (ADR-007)**

---

## 목표

장 열린 시간(평일 09:00~15:30 KST) 동안 **strategy.check_signal 기반으로
164종목을 주기적 스캔**하고, **신규 A/B 등급 종목 발생 시 텔레그램/디스코드로
알림 전송**. 기존 `kr_report.py` (GitHub Actions 06:00 KST 모닝리포트)의
보완재 역할.

---

## 확정 사항

- **실시간성**: 15분 간격 스캔 (KIS API rate limit 안전 범위)
- **알림 채널**: 텔레그램 (또는 디스코드 — 사용자 선택 시점 결정)
- **실행 환경**: 로컬 Windows PC + Task Scheduler (장 중 PC on 필요)
- **중복 방지**: 같은 종목 하루 1회만 알림 (`reports/state/alert_history.json` 활용)

---

## 사용자 사전 준비 (내일 아침)

### 텔레그램 선택 시
- [ ] `@BotFather`에게 `/newbot` → 봇 생성, **토큰** 받기
- [ ] `@userinfobot` 또는 `@getidsbot`에게 아무 메시지 → **chat_id** 받기
- [ ] 두 값을 환경변수로 설정 (또는 `.env` 파일)
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

### 디스코드 선택 시
- [ ] 서버 → 채널 설정 → Integrations → Webhooks → **Webhook URL** 복사
- [ ] 환경변수
  - `DISCORD_WEBHOOK_URL`

### 공통
- [ ] 기존 KIS API 키 환경변수 확인 (`KIS_APP_KEY`, `KIS_APP_SECRET`)
- [ ] 장 중 PC on 상태 유지할지 결정 (또는 VPS 이전 계획)

---

## Claude 작업 순서

### Step 1: 알림 전송 모듈 (30분)
**파일**: `notifier.py` (프로젝트 루트)

```python
# 대략적 인터페이스
def send_alert(message: str, channel: str = "telegram") -> bool:
    """알림 전송. channel: telegram | discord."""
    ...
```

- 환경변수에서 토큰/URL 로드
- 성공/실패 리턴 + 로깅
- 단독 실행 가능 (`python notifier.py "test"` → 메시지 전송 확인)

### Step 2: 장중 스캐너 (1시간)
**파일**: `signals_today.py`

```python
# 흐름
1. 마켓 시간 체크 (09:00~15:30 KST, 평일)
2. KIS API로 164종목 현재가 조회 (기존 kr_report.get_ohlcv 재사용)
3. strategy.check_signal() 로 시그널 판정 (기존 백테 로직 그대로)
4. 신규 A/B 등급 종목 감지 (전회 스캔 대비)
5. alert_history.json 로드 → 오늘 이미 알림 보낸 종목 제외
6. 새 종목에 대해 notifier.send_alert() 호출
7. alert_history.json 업데이트
```

**재사용 가능 코드**:
- `kr_report.get_ohlcv(token, code)` — OHLCV 수집
- `kr_report.get_kis_token()` — KIS 인증
- `strategy.check_signal()` — 시그널 판정
- `strategy.STRATEGY_CFG` — 파라미터

### Step 3: 중복 방지 로직 (30분)
**파일**: `reports/state/alert_history.json`

```json
{
  "last_scan_date": "2026-04-23",
  "alerts_sent": {
    "005930": {"time": "09:15:32", "grade": "A", "rs": 85},
    ...
  }
}
```

- 매일 00:00 KST 이후 첫 스캔 시 `alerts_sent` 초기화
- 같은 날 같은 종목 재알림 금지

### Step 4: Windows Task Scheduler 세팅 (15분)

```
- 트리거: 매일 09:00, 15분 간격, 15:30까지
- 실행: python C:\...\signals_today.py
- 조건: 평일만 (트리거 조건에서 요일 지정)
- 로그: C:\...\reports\state\alert_scan.log
```

Claude가 XML 스크립트 생성해서 사용자가 import하는 방식 권장.

### Step 5: 장외 테스트 (30분)
- `signals_today.py --force` 옵션으로 시간 체크 우회
- 단독 실행으로 KIS 호출 정상 여부 확인
- 가짜 시그널 주입해서 알림 전송 경로 검증

### Step 6 (선택): 쿨다운/필터 세밀화
- 이미 보유 중 종목 제외 (holdings_data.txt 참조)
- 스크리닝 쿨다운(60거래일 이내 청산 종목) 제외
- 관심등급(A만 or A+B) 필터 옵션

---

## 아키텍처

```
[평일 09:00~15:30 KST, 15분마다 Task Scheduler]
         ↓
    signals_today.py
         ├── KIS API (OHLCV, 164종목)
         ├── strategy.check_signal() ← 백테와 동일 로직
         ├── alert_history.json (중복 체크)
         └── notifier.send_alert() → 텔레그램/디스코드
```

**핵심 원칙**: 기존 모듈 최대한 재사용. 새로 만드는 건 `notifier.py` +
`signals_today.py` 2개만. 전략 로직은 이미 strategy.py에 있음.

---

## 테스트 계획

### 단위 테스트 (장외 가능)
1. `python notifier.py "테스트 메시지"` → 텔레그램 수신 확인
2. `python signals_today.py --dry-run` → 스캔 결과만 출력, 알림 안 보냄
3. `python signals_today.py --force-alert 005930` → 특정 종목 강제 알림

### 실전 테스트 (장 열린 날)
- 첫날: 스캔 정상 도는지, 알림 오는지
- 2-3일: 과알림/누락 모니터링
- 1주일: 운영 안정화

### 회귀 검증
- 기존 `kr_report.py` 아침 실행과 결과 일치하는지 (같은 시점 호출 시)
- 백테 `strategy.check_signal` 과 결과 일치하는지

---

## 리스크 / 주의점

### KIS API Rate Limit
- 164종목 × 4회/시 × 6.5시간 = 약 4,264 calls/일
- 자유이용 한도 20K/일 기준 여유 있음. 5분 간격으로 좁히면 주의 필요.

### 장 중 PC on 이슈
- Windows Task Scheduler는 PC 켜져 있어야 동작
- 출근 전 PC on 해두거나, VPS 이전 고려
- 대안: GitHub Actions cron (단, 15분 간격 = 월 한도 초과 위험)

### 중복 알림
- alert_history.json 파일 lock 필요? 동시 실행 가능성?
  - Task Scheduler는 순차 실행이라 race 없음
- 봇 실패 시 재시도 로직 미구현 (v1에선 생략, 실패 로그만)

### 알림 과다
- 강한 상승장에서 164종목 중 20~30개가 동시 A등급 가능
- 일괄 전송 시 한 번에 30개 메시지 → 피곤함
- **Claude가 판단**: v1은 종목 1개당 1메시지, v2에서 "매시 요약" 형태 검토

---

## 내일 세션 시작 가이드

**병원 도착 후 웹 Claude Code에서**:

```
/session-start
```

Claude가 CLAUDE.md 읽고 현재 상태 파악하면:

```
"알림 시스템 작업 플랜 확인했어요. 
텔레그램 봇 토큰 + chat_id 준비하셨나요?"
```

준비됐으면 Step 1부터 순차 진행.

미준비 상태면 다른 작업 대신 페이퍼 저널 등 오프라인 가능한 것부터.

---

## 완료 조건

- [ ] `notifier.py` 완성 + 실제 알림 수신 확인
- [ ] `signals_today.py` 완성 + dry-run 정상
- [ ] Task Scheduler 설정 완료
- [ ] 장 열린 날 1회 실전 동작 확인
- [ ] SESSION_LOG 업데이트 + 커밋 + push

완료되면 이 plan 파일 상태를 `완료`로 변경 + 실전 운영 메모 추가.
