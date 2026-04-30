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
   | `entry` | T10/CD60 진입 후보 (RS 순) + 산업군 펀더 + 컨센서스 + 출처 | `top5` (derive 결과) + WebSearch |
   | `agrade` | A등급 universe 광폭 | `remaining_a`, `grade_c` |
   | `portfolio` | verdict 별 액션 | `holdings`, `holdings[i].verdict` |
   | `macro` | 신뢰 경제지 뉴스 기반 narrative (D-30 분기점 + 시장 반응 + 한국 함의) | **WebSearch 100%** (Reuters / Bloomberg / WSJ / CNBC / FT / 한경 / 매경 등) — 하드코딩 `macro_calendar` 미사용 |

   **카드 길이 (entry 외 6카드)**: 각 1~3 문장. 데이터 인용 + 액션 한 줄.
   서사 / 추측 금지.

   **entry 카드 — v3 의무사항** (다른 카드와 톤 분리, 종목별 비고 + 액션 환기):
   - **산업군 비교 펀더** — 산업별 임계 다르게 적용. 예: 반도체 ROE 30%대 우량
     vs 유틸리티 ROE 10%대 우량, 뷰티테크 PBR 38 고성장 프리미엄 vs 금융 PBR 1
     기준. ROE/PER/PBR 절대값 단순 라벨 (예: "PBR 15.6 = 펀더멘털 취약") ❌.
   - **WebSearch Top 5 종목 컨센서스** — 종목별 증권사 컨센 평균/최고 + 최소
     3-4곳 인용 (KB·하나·대신·SK·신한·Citi·Macquarie 등). 컨센 부재 시 "컨센
     없음" 명시.
   - **컨센 추월 경계 ⚠️** — 현재가 ≥ 컨센 평균 +10% 면 ⚠️, +50% 면 ⚠️⚠️.
     "이미 가격 반영 / 페이퍼 우선 / 사이즈 보수" 액션 환기.
   - **출처 인용** — 카드 마지막에 *italic* 으로 인용한 증권사 열거. 인용
     시점 (~당월) 명시.
   - **정합도 1위** — 산업군 펀더 ✓ + 컨센 광범위 상승 + 컨센 미추월 3개
     조건 모두 충족 종목 1개 명시.

   **entry 외 6카드** 의무 환기 사항 (톤 변경 아님, 언급 의무):
   - `alert` / `macro`: 페이퍼·재현 의심·매크로 D-day 액션 환기
   - `agrade`: A등급 광폭 시 강세장 재현 의심 + 페이퍼 병행 권장
   - `portfolio`: 매크로 임박 시 추매 자제 명시

   **macro 카드 — v3 의무사항** (2026-04-30 옵션 A 정식화. v2 [하드코딩
   검증] 시도가 mechanical D-day 카운트 narrative 양산 → **신뢰 경제지
   뉴스 기반 100% live 작성** 으로 전면 교체):
   - **하드코딩 완전 무시** — `combine_data.py:MACRO_EVENTS` (현재 빈
     dict) / `morning_data.txt` 매크로 캘린더 블록 (현재 stub 안내문) 은
     **참고조차 하지 말 것**. 데이터 소스 아님.
   - **신뢰 경제지 뉴스 우선** — Reuters / Bloomberg / WSJ / CNBC /
     Financial Times / 한경 / 매경 / 연합인포맥스 / Investing.com 등
     당일·당주 보도 WebSearch. **무엇이 일어났고 / 시장이 어떻게 반응했고 /
     다음 무엇을 봐야 하는가** narrative 우선, 단순 D-day 카운트만 ❌.
   - **다음 분기점 1-3건** — FOMC / NFP / CPI / 주요 경제지표 / 지정학
     이벤트 중 향후 D-30 이내 실제 임박한 것을 신뢰 출처 일정 페이지
     (Reuters Calendar / Bloomberg ECO / federalreserve.gov / bls.gov
     release schedule) 에서 직접 확인 후 인용. 일정만 ❌, **시장 반응 예상
     + 한국 주식 시장 함의** 동반.
   - **WTI / 환율 / 미국채 금리 1%+ 급변** — 원인 (지정학 / 공급충격 /
     정책) 신뢰 보도 (IEA / World Bank / Reuters / Bloomberg) 검증 후
     인용. "지정학·공급 충격 신호" 류 추측 라벨 ❌.
   - **출처 인용** — 카드 마지막에 *italic* 으로 인용 보도사 + 인용
     일자 (당일 / 당주) 열거. 일정 페이지 인용 시 직접 URL 도메인 명시.

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
- **entry 카드 WebSearch 누락** ❌ (Top 5 종목별 컨센서스 조회 의무, 부재 시 "컨센 없음" 명시)
- **entry 카드 컨센 인용 없는 진단** ❌ (증권사 명·목표가·인용 시점 셋 다 있어야 함)
- **entry 카드 산업군 무시 절대값 라벨** ❌ ("PBR 15.6 = 펀더멘털 취약" 류, 산업 임계 적용)
- **entry 카드 컨센 추월 ⚠️ 누락** ❌ (현재가 ≥ 컨센 평균 +10% 시 ⚠️ 의무)
- **macro 카드 하드코딩 참조** ❌ (`combine_data.py:MACRO_EVENTS` 빈 dict /
  `morning_data.txt` 매크로 블록 stub 은 데이터 소스 아님. WebSearch 신뢰
  경제지 뉴스 100% 기반 작성 의무)
- **macro 카드 mechanical D-day 나열** ❌ ("FOMC D-X / NFP D-Y / CPI D-Z"
  형식 단순 카운트만 ❌. **무엇이 일어났고 / 시장 반응 / 한국 함의**
  narrative 동반 의무)
- **macro 카드 출처 인용 누락** ❌ (보도사 + 인용 일자 italic 열거 의무.
  부재 시 "출처 검증 실패" 명시)
- **macro 카드 시장 급변 추측 라벨** ❌ (WTI / 환율 / 금리 1%+ 급변 시
  원인 신뢰 출처 검증 후 인용, "지정학·공급 충격 신호" 류 추측 ❌)

---

## 예시 — entry 카드 v3 (2026-04-28 기준)

v3 의무 4개 (산업군 비교 펀더 / WebSearch 컨센 / 컨센 추월 ⚠️ / 출처 인용)
모두 충족된 reference. `docs/claude_analysis/20260428.json::entry` 원본.

```html
<p>T10/CD60 진입 후보 — A등급 미보유 + check_signal RS Top 5 (균등 가중 09:00 시초가, <strong>페이퍼 우선</strong>). 펀더 평가는 <strong>산업군 비교</strong>, 리서치는 ~4월 컨센서스 기반.</p>
<table>
  <tr><th>Rank</th><th>종목</th><th>코드</th><th>RS</th><th>52W</th><th>산업군 펀더</th><th>리서치 (컨센 / 핵심)</th></tr>
  <tr><td>I</td><td>SK스퀘어</td><td>402340</td><td>99</td><td>+5.6%</td><td>투자지주 — PER 12.4·ROE 31.7%, NAV 디스카운트 회복 단계</td><td>컨센 평균 743K · 최고 970K · ★ Strong Buy 9/9 · 현 833K = 평균 +12% 상회 ⚠️</td></tr>
  <tr><td>II</td><td>효성중공업</td><td>298040</td><td>99</td><td>+1.3%</td><td>변압기/중공업 — PBR 15.6 = 수주잔고 12조 + 765kV 독점 반영, ROE 22%</td><td>하나 4.3M · 대신 4.0M · SK 3.6M · <strong>1Q26 영업익 +64% YoY 서프</strong></td></tr>
  <tr><td>III</td><td>SK하이닉스</td><td>000660</td><td>98</td><td>+2.2%</td><td>반도체 — PER 22·ROE 33.8%, HBM 사이클 정점</td><td>KB 1.9~2.0M · Citi 1.7M · Hana 1.6M · <strong>HBM4 sole supplier ⭐</strong></td></tr>
  <tr><td>IV</td><td>에이피알</td><td>278470</td><td>96</td><td>+3.1%</td><td>뷰티테크 — PBR 38.7 고성장 프리미엄, ROE 64.7% 우량</td><td>KB 480K (14.3% 상향) · 26년 영업익 +79% YoY 전망 · K-뷰티 美→유럽 확장</td></tr>
  <tr><td>V</td><td>한미반도체</td><td>042700</td><td>95</td><td>-2.8%</td><td>HBM TC본더 — PER 162 사이클 정점, ROE 30.7% 우량</td><td>유진 230K · 리딩 240K · LS 180K · <strong>현 363K = 컨센 평균 187K +94% 상회</strong> ⚠️⚠️</td></tr>
</table>
<p><strong>정합도 1위 = III SK하이닉스</strong> (HBM4 sole supplier + 컨센 1.6~2.0M 광범위 상승 + ROE 33.8%). <strong>⚠️ 컨센 추월 경계</strong> — V 한미반도체 (+94%) / I SK스퀘어 (+12%) 이미 가격 반영, 페이퍼 우선 + 사이즈 보수. II 효성중공업·IV 에이피알은 컨센 상회 여지.</p>
<p><em>리서치 출처 (~4월): KB·하나·대신·SK·신한·유진·리딩·LS·한국투자·Citi·Macquarie 컨센서스.</em></p>
```

**의무 매핑**:
- 산업군 비교 펀더 ✓ — "투자지주 PER 12.4·ROE 31.7%" / "반도체 PER 22·ROE 33.8%" / "뷰티테크 PBR 38.7" 산업별 임계 다르게 적용
- WebSearch Top 5 컨센서스 ✓ — 종목별 컨센 평균/최고 + 증권사 4-5곳 (KB·하나·대신·SK·신한·유진·리딩·LS·Citi 등)
- 컨센 추월 ⚠️ ✓ — V 한미반도체 ⚠️⚠️ (+94%) / I SK스퀘어 ⚠️ (+12%) 명시 + "이미 가격 반영, 페이퍼 우선" 액션 환기
- 출처 인용 ✓ — 마지막 단락 *italic* 으로 증권사 11곳 + "(~4월)" 시점 명시
