# Stage 4 predeclared candidate protocol

One representative per family, no alternates. All use five equal slot budgets,
3% assumed cash yield, existing gross equity cashflows and transaction costs,
and the same next-open limit, T+2 and integer-share account. No cash allocation
target. Price averages exclude the signal close, as in the V1 template.

| Candidate | Entry and priority | Exit |
| --- | --- | --- |
| A Relative | At first session close each calendar month, top five positive equal-weight 126/252-session return scores. | At the same monthly close if outside the new top five. |
| B Breakout | Close at or above the prior 252-session high and current volume at least 1.5 times prior 20-session mean. Sort by breakout distance. | Close below prior MA50 or 10% loss versus entry. |
| C Moving average | Close > MA50 > MA150 > MA200 and MA200 above its level 22 sessions earlier. Sort by 252-session return. | Close below prior MA150 or 10% loss versus entry. |
| D Momentum and trend | Positive 126/252-session blend in the PIT universe top quintile, above a rising MA200, KOSPI close above prior MA60. Sort by blend. | Close below prior MA200 or 12% loss versus entry. |

No V1 cooldown, trailing stop or maximum-hold rule is inherited for these four
new policies. Unfilled entry orders expire as usual. A fixes its targets monthly and retries orders against those targets, using
newly settled cash and freed slots on subsequent closes. A buy still needs
a current valid 252-session history. B/C/D review exits each close. If the required average
is unavailable on a held name, their entry-based stop still applies.

Use continuous accounts. Annual and phase returns chain from the prior
session's ending value when available. Development ends 2021-12-31 and
selection ends 2023-12-31. Run three conditions (1% daily volume with base
economic assumptions; 0.1% with the same assumptions; 1% with Stage 3.1
corporate-action stress). Undefined research NAV invalidates a phase
containing it. To select a single finalist require positive selection-phase
CAGR spread over KODEX 200 in both volume cases and the corporate stress,
and positive development spread in the base case. Among eligible candidates
maximize the minimum selection CAGR spread across the three cases, breaking
ties by candidate ID. Otherwise record no finalist and preserve the final
segment. Evaluate only the frozen finalist on 2024 through October 2026.
The final segment is held back for these new candidates; historical market
and prior V1/ETF results are already known. Four correlated tests can still
produce a chance winner. No claim of statistical significance or live alpha.
