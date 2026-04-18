# 모닝 리포트 데이터 파이프라인

매일 아침 KST 06:05, 시장 개장 전에 미장·국장·섹터·매크로 데이터를 자동 수집·통합하여 **Google Drive**와 **GitHub**에 동시 업로드합니다. Claude.ai 채팅창에 `모닝리포트` 한 단어로 리포트를 생성할 수 있도록 설계되었습니다.

---

## 파이프라인 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                   GitHub Actions (KST 06:05)                    │
│                                                                 │
│   morning_report.py   ──▶  us_data.txt                          │
│   kr_report.py        ──▶  kr_data.txt      ┐                   │
│   sector_report.py    ──▶  sector_data.txt  │                   │
│                                             ▼                   │
│                     combine_data.py ── morning_data.txt         │
│                           │                                     │
│         ┌─────────────────┼──────────────────┐                  │
│         ▼                 ▼                  ▼                  │
│   [GitHub private]  [GitHub public]   [Google Drive]            │
│   morning-report    morning-data      ClaudeMorningData/        │
│   (archive)         (archive+raw)     ├─ morning_data.txt       │
│                                       └─ morning_data_YMD.txt   │
└────────────────────────────────────────────┬────────────────────┘
                                             │
                                             ▼
                              ┌──────────────────────────┐
                              │   Claude.ai + Drive 커넥터  │
                              │   "모닝리포트" 입력 →      │
                              │   Drive 검색 → 리포트 출력 │
                              └──────────────────────────┘
```

---

## 주요 구성 요소

### 데이터 수집 스크립트

| 파일 | 역할 | 출력 |
|---|---|---|
| `morning_report.py` | 미국 시장 데이터(yfinance) | `us_data.txt` |
| `kr_report.py` | 국내 시장 + KIS API 수급 | `kr_data.txt` |
| `sector_report.py` | 섹터 ETF 주도 분석 | `sector_data.txt` |
| `combine_data.py` | 3개 파일 + 매크로 캘린더 통합 | `morning_data.txt` |
| `gdrive_upload.py` | Google Drive 업로드 유틸 | (Drive 파일 업로드) |

### 워크플로우

- `.github/workflows/morning.yml` — 매일 KST 06:05 자동 실행 (`cron: '5 21 * * 0-4'` UTC)
- 수동 실행: Actions 탭 → **Run workflow**

### 보관 대상

| 대상 | 경로 | 용도 |
|---|---|---|
| private 레포 | `gengar200005/morning-report/morning_data.txt` | 최신본 백업 |
| public 레포 | `gengar200005/morning-data/morning_data.txt` | raw URL 외부 접근용 |
| public 레포 아카이브 | `gengar200005/morning-data/YYYY/MM/morning_data_YMD.txt` | 과거 전량 보관 |
| Google Drive | `ClaudeMorningData/morning_data.txt` | Claude 커넥터 읽기 |
| Google Drive | `ClaudeMorningData/morning_data_YMD.txt` | Claude 날짜 지정 읽기 |

---

## 처음 설정하는 경우

1. **`SETUP.md`** — Google Cloud 프로젝트 / 서비스 계정 / Drive 폴더 / GitHub Secrets 세팅 (1회성)
2. **`TESTING.md`** — 파이프라인 정상 동작 검증 체크리스트
3. **`claude_project_prompt.md`** — Claude.ai 프로젝트 시스템 프롬프트 (Drive 커넥터 전용)

---

## Secrets 요약

레포 Settings → Secrets에 다음이 등록되어 있어야 함:

| Secret 이름 | 용도 |
|---|---|
| `GITHUB_TOKEN` | (자동) 레포 자체 커밋 |
| `MORNING_PAT` | public 레포(`morning-data`) 커밋용 PAT |
| `KIS_APP_KEY` | 한국투자증권 OpenAPI |
| `KIS_APP_SECRET` | 한국투자증권 OpenAPI |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | Google Drive 업로드용 서비스 계정 키 |
| `GDRIVE_FOLDER_ID` | Drive 업로드 대상 폴더 ID |

---

## 타임존

모든 날짜 계산은 **`Asia/Seoul` (KST)** 기준. `pytz`를 사용하여 스크립트 내부에서 명시적으로 변환. GitHub Actions의 cron은 UTC 기준이므로 KST 06:05 = UTC 21:05 전날로 설정됨.

## 실패 시 동작

- Drive 업로드 실패는 **GitHub 커밋과 독립적**으로 처리됨. Drive가 실패해도 GitHub 백업은 정상.
- Secrets 미설정 시 Drive 업로드 스텝은 경고만 출력하고 스킵 (구버전 호환).
- 1회 자동 재시도 후에도 실패하면 Actions 로그에 `❌ Drive 업로드 실패` 로그 명시.
