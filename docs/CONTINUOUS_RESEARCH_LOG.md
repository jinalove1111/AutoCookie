# Continuous Research Log

Operator directive (2026-07-14): continuous research mode. Objective:
increase net profit while preserving robustness, testing existing
parameters/filters/models systematically. Legacy engine stays the
production baseline throughout; nothing here is a production default.
Every experiment logged here, accepted only if statistically meaningful
AND confirmed across multiple years/assets.

## Experiment 1: widen `_STOP_BUFFER` to fix the execution-delay material failure

**Motivation**: `docs/ROBUSTNESS_REPORT.md` found the BTC production
candidate (`use_structure_tp=True, structure_tp_max_r=3.0,
require_premium_discount_filter=True`) has a material robustness failure
-- a single 5-minute execution delay collapses Profit Factor from 5.24 to
0.16, traced to a very tight average stop distance (0.23% of price).
`entry_model._STOP_BUFFER` (currently 0.15%) is an existing, already-
implemented, disclosed-not-tuned constant -- widening it is a direct,
non-invented lever to test.

**Method**: `scripts/research_stop_width.py`, monkey-patching
`_STOP_BUFFER` (same pattern as `scripts/parameter_sweep.py`), same
candidate config, same fixed-anchor methodology as the rest of this
session. Tested 0.15% (baseline), 1%, 2%, each at `entry_delay_candles`
0 and 1, on BOTH confirmed years (2026-07-12, 2025-07-12).

### Results

| Buffer | Year | Avg stop % | No-delay PnL | No-delay PF | Delay-1 PnL | Delay-1 PF | Trades |
|---|---|---|---|---|---|---|---|
| 0.15% (baseline) | 2026 | 0.238% | $1,547.64 | 5.24 | -$1,239.23 | 0.16 | 42 |
| 0.15% (baseline) | 2025 | 0.225% | $737.48 | 3.48 | **-$1,161.54** | **0.03** | 26 |
| 1% | 2026 | 1.100% | $838.97 | 31.18 | $137.85 | 3.22 | 15 |
| 1% | 2025 | 1.100% | **-$83.38** | **0.00** | -$116.11 | 0.00 | 3 |
| 2% | 2026 | 2.149% | $34.53 | 2.29 | $18.61 | 1.41 | 2 |

**2% dropped after year 1** -- collapsed to 2 trades (pure noise), not
worth repeating on a second year.

### Verdict: REJECTED -- does not survive cross-year validation

The 1% buffer looked like a genuine fix in the 2026 window alone (delay
Profit Factor 0.16 -> 3.22, no longer a sign-reversal) -- but in 2025 it
is not just delay-fragile, it is UNPROFITABLE even with NO delay at all
(PF 0.00, -$83.38, and only 3 trades -- both too small a sample and the
wrong sign). This is exactly the failure mode this project's whole
cross-year discipline (`ENGINEERING_DECISIONS.md` #14/#15) exists to
catch: a promising single-window result that turns out to be regime-
specific, not a real, generalizable improvement. **Per the operator's
own rule ("accept only statistically significant improvements" /
"immediately backtest across multiple years"), this change is REJECTED.**

**Secondary finding, itself important**: the baseline candidate's
delay-fragility is confirmed WORSE in 2025 than 2026 (PF 0.03 vs 0.16,
both catastrophic) -- the original material-failure finding was not a
2026-specific artifact; it reproduces, and if anything is more severe, in
a second independent year.

**Why the trade count/position-size dropped so much at 1%**: with
`structure_tp_capped_3r`, take-profit is R-multiple-based (up to 3.0R
from risk). A wider stop increases the risk denominator, which pushes
the R-multiple target proportionally farther away -- harder to reach,
longer average trade duration, and (via the one-position-at-a-time
concurrency guard) fewer total signals executed per period. Position
sizing (`calculate_position_size`, risk-based) also shrinks the absolute
notional per trade for the same risk-percent-of-account. Both effects
compound against a fixed 6-period test window, which is also why the
sample sizes got so thin (15, then 3, then 2 trades) -- not enough
signals survive the concurrency guard's longer hold times to build a
trustworthy sample at this window length.

## Next experiment (queued)

A more modest buffer widening (e.g. 0.3%-0.5%, roughly 2-3x baseline
rather than 1%'s ~7x) might land in a zone that improves delay-robustness
meaningfully without the trade-count collapse and profitability reversal
seen at 1%. Testing next, same 2-year methodology, before considering
this lever exhausted.
