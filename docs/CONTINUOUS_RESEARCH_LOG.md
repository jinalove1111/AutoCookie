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

## Experiment 2: moderate `_STOP_BUFFER` widths (0.3%, 0.5%) -- 2026 window

**Motivation**: experiment 1's 1% buffer (~7x baseline) fixed delay-
robustness in 2026 but failed cross-year (unprofitable in 2025 even
without delay). Testing more modest widths (2-3x baseline) to see if a
smaller step finds a zone that's delay-robust without the trade-count
collapse/profitability reversal seen at 1%.

### Results (2026-07-12 anchor)

| Buffer | Avg stop % | No-delay PnL | No-delay PF | Delay-1 PnL | Delay-1 PF | Trades |
|---|---|---|---|---|---|---|
| 0.15% (baseline) | 0.238% | $1,547.64 | 5.24 | -$1,239.23 | 0.16 | 42 |
| 0.30% | 0.391% | $1,941.93 | 10.45 | -$981.03 | 0.22 | 39 |
| 0.50% | 0.592% | $1,488.39 | 7.91 | -$558.76 | 0.26 | 32 |
| 1.00% (experiment 1) | 1.100% | $838.97 | 31.18 | +$137.85 | 3.22 | 15 |

### Verdict: REJECTED at both widths -- monotonic improvement, but neither clears the bar

Delay-1 losses shrink monotonically as the buffer widens (-$1,239 ->
-$981 -> -$559 -> +$138), and 0.30% is even a genuine no-delay
improvement over baseline (PF 10.45 vs 5.24) -- but at 0.30% and 0.50%,
delay-1 PnL is STILL NET NEGATIVE. Neither clears the basic bar
(profitable under delay) that would justify a cross-year check in the
first place -- no need to spend a second year's compute confirming a
result that already fails in the first window tested. Only 1% crossed
into delay-profitability in 2026, and that one specifically failed
cross-year (experiment 1).

**Conclusion so far, stated plainly**: across the full range tested
(0.30%, 0.50%, 1%, 2% -- baseline included), `_STOP_BUFFER` alone does
NOT produce a variant that is BOTH delay-robust AND cross-year-profitable.
The one width that achieved delay-robustness in-window (1%) is not a
statistically validated improvement (fails a second, independent year).
This lever is not fully exhausted (values between 0.5% and 1% remain
untested) but the trend so far suggests a narrow, possibly nonexistent
window between "wide enough to survive delay" and "narrow enough to stay
profitable across regimes" for this specific candidate. Continuing
research into other dimensions (time filters, position sizing) rather
than fine-grinding this one parameter further without a stronger signal
that a viable point exists.

## Experiment 3: Asian-session-only entry filter

**Motivation**: `docs/ROBUSTNESS_REPORT.md` test 6 found the Asian
session dominates both trade volume and quality for the production
candidate (Profit Factor 4.65 vs London's 2.41). New opt-in
`require_session` parameter on `SignalEngine.generate_signal` (reuses
`session_liquidity.py`'s already-disclosed Asian/London window constants
directly -- no new indicator, 4 new tests). Question: does restricting
entries to the Asian window improve the candidate's profitability and/or
robustness?

**Method**: `scripts/research_session_filter.py` -- candidate vs.
candidate+`require_session="asian"`, both 2026 and 2025 anchors tested up
front (not sequentially gated), same fixed-anchor methodology.

### Results

| Anchor | Config | Net Profit | Profit Factor | Sharpe | Max DD | Trades | Profitable periods |
|---|---|---|---|---|---|---|---|
| 2026 | candidate | $1,547.64 | 5.24 | 0.90 | 0.80% | 42 | 6/6 |
| 2026 | candidate + Asian only | $1,048.60 | 4.74 | 0.83 | 0.45% | 30 | 6/6 |
| 2025 | candidate | $737.48 | 3.48 | 0.65 | 1.46% | 26 | 5/6 |
| 2025 | candidate + Asian only | $281.74 | 2.53 | 0.47 | 1.12% | 13 | 4/6 |

### Verdict: REJECTED -- worse on profit/PF/Sharpe in BOTH years, no compensating benefit

Not a "looked good, failed the second year" case -- the Asian-only filter
is UNIFORMLY worse on Net Profit, Profit Factor, and Sharpe in both
independent years tested, with trade count roughly halving each time
(2025's 13 trades is thin enough to also be a small-sample concern on top
of the direction being wrong). The only upside is a modest drawdown
improvement in both years -- real, but not large enough to justify giving
up this much profit, and critically, this filter does nothing to address
the actual material robustness failure (execution-delay fragility) that
motivated this whole research thread. Per the operator's rule ("reject
any improvement that fails cross-year... validation" -- this fails on
direction, not just consistency), rejected outright.

## Next experiment (queued)

Pivoting to "entry confirmation" (explicitly in-scope): rather than
widening stops (rejected) or filtering by session (rejected), test
whether an entry-confirmation gate -- skip the fill entirely if the
delayed price has moved too far from the originally-planned entry, rather
than filling at a now-invalidated level -- can fix the execution-delay
material failure without the profitability cost seen in experiments 1-3.
This directly targets the root problem (identified in
`docs/ROBUSTNESS_REPORT.md` test 2) rather than a proxy for it.
