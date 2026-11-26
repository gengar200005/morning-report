# Stage 8.1 continuation — PIT evidence audit (2026-11-26)

## Status and scope

- Parent: `961120dc8ddc90e07a7735b795667177ba2b9dfe` (research/v2-fundamentals-pilot-20261106).
- Existing Stage 8.1 Library report: Morning_Report_V2_Stage81_Validation_20261106.md. Prior authenticated calls and receipt archive comparisons: 0.
- This environment: OPENDART_API_KEY and checked aliases DART_API_KEY / OPEN_DART_API_KEY absent; no credential value printed or obtained. Direct git network checkout unavailable; GitHub connector used for inspection. DART receipt viewer unavailable via web retrieval. No authenticated call, receipt ZIP download, original/correction lineage verification, database rebuild or strategy replay performed.
- Verdict: **BLOCKED** for authenticated PIT verification and expansion; public-source cross-check PARTIAL. No alpha claim. No source-code changes; no automated regression suite run here. 2024–2026 outcomes untouched.

## Receipt candidates (not verified API originals)

| Code | Quarter | Candidate receipt | Evidence |
|---|---|---|---|
| 005930 | 2021Q1 | 20210517001185 | https://samara.kr/en/disclosure/20210517001185 |
| 066570 | 2021Q1 | 20210517000890 | https://dart.cinia.kr/today/?c=00401731&cp=3&cs=new&tg=%EC%A0%95%EA%B8%B0%EB%B3%B4%EA%B3%A0%EC%84%9C |
| 000660 | 2021Q1 | 20210517000667 | https://samara.kr/disclosure/20210517000667 |
| 005930 | 2023Q1 | 20230515002335 | https://samara.kr/en/disclosure/20230515002335 |
| 066570 | 2023Q1 | 20230515001288 | https://samara.kr/disclosure/20230515001288 |
| 000660 | 2023Q1 | 20230515001677 | https://samara.kr/disclosure/20230515001677 |
| 117930 | 2016Q3 | 20161130001119 | **Correction**, not original; https://www.k5.co.kr/stock/117930/official_notice?page=2 |
| 002000 | 2018Q3 | 20181114002813 | https://www.k5.co.kr/stock/002000/official_notice?page=2 |

All eight candidates remain unverified against official authenticated receipt bytes. Historical code/ISIN checks for exits were done in the prior report, not rerun. Hanjin initial receipt still missing. Do not treat absence of evidence as a non-filing or as zero earnings. Candidate links: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}.

### Issuer-hosted Samsung report

Official issuer page dated 2023-05-15: https://www.samsung.com/sec/ir/reports-disclosures/public-disclosure/3209/
PDF: https://images.samsung.com/kdp/ir/business-report/2023_1Q_Interim_Business_Report_vF_kr.pdf
Printed pages 54 and 104 visually cross-checked. Consolidated three-month periods (2023-01-01 through 2023-03-31, versus 2022 corresponding period), in KRW millions except EPS in KRW per common share:

| Item | 2023Q1 | 2022Q1 comparison as published in 2023 report |
|---|---:|---:|
| Revenue | 63745371 | 77781498 |
| Operating profit | 640178 | 14121409 |
| Basic common-share EPS | 206 | 1638 |

EPS YoY -87.42%. These are values in the issuer-hosted copy, not a certified original receipt payload. Do not backdate EPS to April's preliminary announcement; use report publication date as conservative bound for this document (next session, subject to trading eligibility) unless earlier field-specific evidence is authenticated. Distinguish annual vs quarter comparisons, consolidated vs standalone, and common vs preferred shares.

### LG 2021Q1 preliminary/correction example

Public mirror candidates (not official raw bytes): 
- 2021-04-07, receipt 20210407800092, https://samara.kr/disclosure/20210407800092
- 2021-04-29, receipt 20210429800242, https://samara.kr/disclosure/20210429800242

Mirrored correction table links back to April 7. Consolidated revenue and operating profit in KRW 100 million: originally 188057 and 15178; corrected 188095 and 15166. Preserve both timestamps and payloads when authenticated. Do not overwrite the earlier value or assume later EPS was known. The mirror alone cannot establish completeness of corrections.

## Next execution gate (minimal)

Reuse dart_receipts.py, existing planned 8-event list and PIT DB. Securely inject the already issued credential as OPENDART_API_KEY in an execution environment with OpenDART network access. Never put it in source, outputs, chat, URLs in logs or GitHub commits. Do not assume GitHub Secrets exist or are readable here. Run bounded listings (A and I, last_reprt_at=N), reconcile corporate identities and exact original and correction receipt numbers, archive receipt-keyed documents and XBRL where applicable with hashes. Allow explicit missing or unavailable fields; compare selected original amounts to the evidence above. Date-only disclosure usable starting the next eligible session, no look-ahead. Report PASS/FAIL/BLOCKED at event/field level, distinguishing a genuinely absent field from missing original or unresolved scope. Require an original plus a real correction pair and a historical exit identity before expansion; unresolved records stay excluded, not fabricated. No strategy candidates until data gate.

## Proposed next signal research (before examining outcomes)

This is a proposal for the next research run, not an implemented pipeline or alpha result. After gate passes, use one fixed quarter census (2021Q1) across the historical eligible KOSPI universe as extraction/coverage QC only; include delisted issuers, document every exclusion. Prefer receipt-keyed original public values; bulk latest financials cannot prove historical first disclosure. Extend to 2017–2021 only once extraction is reliable and freeze the following signal definitions before outcomes:
- Quarterly basic common-share EPS YoY growth (previous positive EPS only; nonpositive base or unresolved share basis handled separately, never substituted with zero; use published comparable share basis and only corporate actions known then).
- YoY consolidated operating margin change in percentage points (positive comparable revenue denominator).
- YoY consolidated quarterly revenue growth (positive comparable prior revenue).
- No acceleration or thresholds sweep until these primary signals evaluated. Distinguish preliminary and periodic information by field availability; no duplicate event weighting. Do not subtract cumulative EPS to infer quarter EPS; use published three-month EPS, or mark missing.
- At monthly formation dates select latest available valid quarter per issuer using disclosure history, entry no earlier than next eligible session. Use existing M4 and cap/turnover controls. Compare ranks and top 20% against remaining eligible observations; A/B/C/D with M4 top quintile and each fundamental signal top quintile, on the same eligible sample. The earlier Stage 8 margin >0 definition remains an unchanged pilot; new rank rule is a proposed broader protocol. No outcome-driven selection. Check 20/60/120 trading-session returns, economic return validity, same-sample baseline, issuer and time-block dependence, missingness by year, size, and exit status. Avoid repeated overlapping outcomes masquerading as independent observations. Primary confirmatory contrasts C-A, C-B; distinguish signal predictive power from executable portfolio CAGR. 
- 2017–2021 discovery, 2022–2023 reused diagnostic only, 2024 onward embargo until explicit rule freeze. Truly prospective forward validation remains necessary. Stop or reduce scope if no stable incremental evidence. Only promising predeclared signals enter the existing integer-share, cost/tax, settlement and corporate-action account engine.

OpenDART official guide: https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001 ; bulk-download caution on revised values: https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do .

No changes to main, production reports, orders or deployment.
