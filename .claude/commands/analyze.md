# /analyze — 모닝리포트 7카드 분석 + main publish

오늘자 `morning_data.txt` → `docs/claude_analysis/{YMD}.json` (main) → `claude_render.yml`
자동 트리거 → PDF 재렌더 + Drive 업로드 + Notion publish.

기반: `CLAUDE_PROJECT_INSTRUCTION_v5.md` (web Project v5.1, 2026-04-26).
Claude Code 이식 차이: Drive fetch → 로컬 `morning_data.txt` 직접 읽기,
GitHub MCP `create_or_update_file` → `git commit/push`.

---

## 절차

1. **KST 오늘 날짜** 확인 → `YMD = YYYYMMDD`, `YMD_DASH = YYYY-MM-DD`.
   `TZ=Asia/Seoul date +%Y%m%d`.

2. **morning_data.txt 읽기** (repo root). 헤더의 날짜 ≠ KST 오늘 또는 D-1
   이면 `alert` 카드에 명시 (silent fallback 금지).

3. **schema 진실 위치**: `reports/parsers/morning_data_parser.py`
   `parse_morning_data()`. 본 명령에 schema 중복 작성 금지. 자주 실수하는
   지점:
   - `minervini.grade_a[i]` 종목코드 키는 **`code`** (NOT `ticker`)
   - `minervini.grade_c` 는 **`list[str]`** (NOT `list[dict]`)
   - `grade_d` 존재하지 않음 (A/B/C 만)
   - `holdings[i]` 에 `verdict` / `stop_price` / `add_threshold` 등 derive 후 필드

4. **이미 오늘자 JSON 존재 확인**: `docs/claude_analysis/{YMD}.json` 있으면
   마스터에게 덮어쓰기 / 스킵 / 신규 분석 여부 확인. 동일 날짜 중복 commit
   해도 claude_render 다시 돌아 PDF 갱신.

5. **7카드 작성** → `docs/claude_analysis/{YMD}.json`. 각 값은 짧은
   HTML snippet (`<p>...` 또는 `<p>...</p><ul><li>...</li></ul>`). Jinja
   `| safe` 그대로 주입되므로 escape 책임은 작성자.

   **키 7개 모두 채울 것** (누락 = template fallback, 무결성 가드 위반):

   | 키 | 1줄 질문 | 데이터 소스 (parser dict 키) |
   |---|---|---|
   | `alert` | 오늘 단 하나의 경계 | `vix`, `kr_indices`, `market_context`, `kospi_flow`, anomaly |
   | `gate_flow` | 시장 게이트 + 수급 흐름 | `market_context.kospi_above_ma60`, `kospi_flow` |
   | `sector` | leaders 변동 + ETF 동조 | `sector_adr003`, `sector_etf` |
   | `entry` | T10/CD60 진입 후보 (RS 순) | `top5` (derive 결과) |
   | `agrade` | A등급 universe 광폭 | `remaining_a`, `grade_c` |
   | `portfolio` | verdict 별 액션 | `holdings`, `holdings[i].verdict` |
   | `macro` | D-30 high impact 우선 | `macro_calendar` (dday≤30, impact="high") |

   **카드 길이**: 각 1~3 문장. 데이터 인용 + 액션 한 줄. 서사 / 추측 금지.

6. **main 에 commit + push** (claude_render.yml 가 main 만 트리거):
   ```bash
   # 현재 브랜치가 main 아니면 main 으로 체크아웃
   git checkout main && git pull origin main
   git add docs/claude_analysis/{YMD}.json
   git commit -m "Claude 분석 {YMD_DASH} (auto)"
   git push origin main
   # 작업 후 원래 브랜치 복귀
   ```
   `morning-report/CLAUDE.md` 운영 규칙상 main 직접 commit 은 GH Actions
   전용이지만 **claude_analysis JSON 은 예외 허용** (web Project 시절부터
   동일 패턴, 04-25 `bfd73ea` 등).

7. **완료 보고**: 7카드 요약 1줄씩 + commit 해시 + workflow 트리거 안내
   (claude_render run id 는 마스터가 GH Actions 에서 확인).

---

## 분석 원칙 (T10/CD60)

- **Trail 10% / Cooldown 60거래일**, A등급 RS 정렬 Top 5 균등 가중
- 차트 판독으로 종목 거르기 ❌ (백테 안 된 추가 필터)
- 단독 종목 추천 ❌ (5종목 포트폴리오 통계 알파)
- **시장 게이트 (KOSPI MA60) 미통과** 시 진입 자제 메시지 명시
- 박스권/약세장: 손절 -2~5% 가능성 환기

실전 기댓값 (차감 후): 박스권 -5~+3% / 중립 +25~30% / 강세 +130%+ / 전체 +20~23%

---

## 금지 사항

- **schema 중복 작성** ❌ (`morning_data_parser.py` 가 진실)
- **template 직접 수정** ❌ (`v6.2_template.html.j2` 는 CI 영역)
- **추측 prefix** ❌ ("아마", "추정", "보입니다" 사용 시 카드 재작성)
- **claude_analysis JSON 외 docs/ 수정** ❌ (`docs/latest.html`, `docs/archive/*` 는 CI 만 작성)
- **silent fallback** ❌ (1차 경로 실패·키 누락·날짜 불일치 → `alert` 카드 명시)
