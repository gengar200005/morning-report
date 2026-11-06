# Stage 4.1 execution audit

Keep all four signal rules, PIT rankings, exit rules and economic assumptions.
Use 2017–2021 development and 2022–2023 selection only. E1 is the exact Stage 4
prior-close order, E2 is a prior-close premium cap of 2% with predeclared 1%
and 3% cases, E3 uses the E2 2% pre-sized integer order but waives the entry
limit in the opening simulation, subject to available settled cash and all other
reservations. E3 is an optimistic diagnostic, not a return bound or an executable
order recommendation. Every case is run with both 1% and 0.1% volume ceilings.
No best-premium selection. Orders expire next session. The reported daily volume
is used only for execution rejection, never for sizing.

Use the existing KOSPI dated tick table, round submitted prices down and cap them
at the normal KRX +30% band using prior-close information. At execution in E2/E3
use the observed KRX reference for a conservative ordinary band guard; a limit outside a changed
reference band or an opening outside the modeled band leaves the order unfilled.
For opening price-limit days reject a buy at the upper band and a sell at the
lower band as an auction-liquidity precaution. E1 does not inherit these guards
because it must reproduce the old tape. Log quote gaps, zero volume, invalid
bars, conditional price misses, volume caps and cash/slot blocks separately.
Whole-order fills remain an approximation of opening-auction capacity.
