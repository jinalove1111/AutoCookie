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

## Experiment 4: entry-confirmation gate (`max_entry_drift_pct`)

**Motivation**: experiments 1-3 (stop-buffer widening, session filtering)
were proxies that didn't fix `docs/ROBUSTNESS_REPORT.md` test 2's
material execution-delay failure. New opt-in `max_entry_drift_pct`
parameter on `BacktestEngine.run()` (only has effect when
`entry_delay_candles > 0`): skips the trade entirely if the delayed fill
price has drifted more than the given fraction from the signal's
originally-planned `entry_price`, instead of filling at an unconfirmed
price. Targets the root mechanism directly (2 new unit tests).

**Method**: `scripts/research_entry_confirmation.py` -- no-delay
reference, delay=1 with no gate (the known-bad baseline), and delay=1
with the gate at 0.05%/0.10%/0.15% (fractions of the ~0.23% average stop
distance). Both confirmed years tested up front.

### Results

**2026-07-12:**

| Config | Net Profit | PF | Sharpe | Max DD | Win Rate | Trades | Walk-Forward |
|---|---|---|---|---|---|---|---|
| No-delay (reference) | $1,547.64 | 5.24 | 0.90 | 0.80% | 78.6% | 42 | PASSED |
| Delay=1, no gate | -$1,239.23 | 0.16 | -0.55 | 4.28% | 31.4% | 35 | FAILED |
| Delay=1, gate 0.05% | $108.15 | 1.29 | 0.13 | 1.29% | 50.0% | 18 | FAILED |
| Delay=1, gate 0.10% | -$135.09 | 0.79 | -0.12 | 1.77% | 40.0% | 25 | FAILED |
| Delay=1, gate 0.15% | -$43.89 | 0.94 | -0.03 | 2.92% | 48.4% | 31 | FAILED |

**2025-07-12:**

| Config | Net Profit | PF | Sharpe | Max DD | Win Rate | Trades | Walk-Forward |
|---|---|---|---|---|---|---|---|
| No-delay (reference) | $737.48 | 3.48 | 0.65 | 1.46% | 69.2% | 26 | PASSED |
| Delay=1, no gate | -$1,161.54 | 0.03 | -1.24 | 4.98% | 12.0% | 25 | FAILED |
| Delay=1, gate 0.05% | -$279.76 | 0.13 | -1.17 | 1.71% | 11.1% | 9 | FAILED |
| Delay=1, gate 0.10% | -$351.19 | 0.11 | -1.31 | 2.22% | 10.0% | 10 | FAILED |
| Delay=1, gate 0.15% | -$334.96 | 0.22 | -0.78 | 2.58% | 25.0% | 12 | FAILED |

### Verdict: REJECTED -- helps partially in one year, provides no benefit in the other

In 2026, the tightest gate (0.05%) meaningfully improves the delay
scenario (PnL -$1,239 -> +$108, PF 0.16 -> 1.29) -- a real, non-trivial
effect. But it still falls far short of the no-delay reference, and
**every gated variant in both years still fails walk-forward**. In 2025,
the gate provides essentially no benefit at all -- every threshold stays
deeply unprofitable (PF 0.11-0.22, 0 of 6 profitable periods each time),
not meaningfully different from the ungated delay scenario's own 0.03 PF.
Per "commit only if statistically better" / "reject any improvement that
fails cross-year validation" -- this is rejected outright, not a partial
accept.

## Synthesis after 4 experiments: the execution-delay fragility appears architectural, not parameter-fixable

Four independent approaches have now been tested against
`docs/ROBUSTNESS_REPORT.md` test 2's material failure: widening the stop
buffer (2 rounds), an Asian-session-only entry filter, and an
entry-confirmation drift gate (3 threshold levels). **None produced a
configuration that is both delay-robust AND confirmed across both tested
years.** The pattern common to all four: any change that measurably
improves the 2026 delay scenario either (a) fails cross-year validation
outright (1% stop buffer, experiment 1) or (b) still fails walk-forward
even in the year where it helps (entry-confirmation gate, experiment 4).
2025 in particular is consistently harder to fix than 2026 across every
lever tried.

**Working hypothesis, not yet proven**: this candidate's core mechanism
-- R-multiple-capped structural targets (`structure_tp_max_r=3.0`)
combined with tight, zone-boundary-derived stops -- may be fundamentally
incompatible with any realistic execution latency, rather than having a
fixable parameter setting hiding somewhere in the space tested so far.
This does not mean the underlying `structure_tp`/`premium_discount_filter`
edge is fake (sections 12-14 of `docs/PROFITABILITY_EXPERIMENT_REPORT.md`
stand on their own -- the edge is real under the zero-latency assumption
every backtest before this research round made). It means realizing that
edge in live/paper execution may require infrastructure guarantees
(sub-candle execution) rather than a strategy-side fix, OR a genuinely
different exit/stop architecture not yet tried within this research
round's scope (session filters / market regime filters / execution
timing / entry confirmation / exit logic / risk management).

## Experiment 5: combined defense (moderate stop buffer + entry-confirmation gate)

**Motivation**: neither lever fixed the problem alone (experiments 2 and
4). Testing whether they compound favorably in combination -- 0.3% stop
buffer (experiment 2's best no-delay result, PF 10.45) + 0.05% drift gate
(experiment 4's best 2026 result). No new code -- reuses both
already-built mechanisms together.

### Results

| Anchor | Config | Net Profit | PF | Sharpe | Max DD | Win Rate | Trades | Walk-Forward |
|---|---|---|---|---|---|---|---|---|
| 2026 | no-delay | $1,941.93 | 10.45 | 1.37 | 0.34% | 84.6% | 39 | PASSED |
| 2026 | delay=1, combined | -$58.98 | 0.41 | -0.45 | 0.36% | 25.0% | 4 | FAILED |
| 2025 | no-delay | $718.27 | 4.67 | 0.80 | 0.66% | 71.4% | 21 | PASSED |
| 2025 | delay=1, combined | -$69.33 | 0.00 | -12.83 | 0.37% | 0.0% | 2 | FAILED |

### Verdict: REJECTED -- the combination compounds the DOWNSIDES, not the benefits

Trade count collapses to 4 (2026) and 2 (2025) -- both individually
already reduce trade count (wider buffer lengthens average trade
duration via the concurrency guard; the drift gate skips trades outright),
and stacking them compounds that reduction past the point of any
meaningful sample. Both years net negative, both fail walk-forward, 2025
shows a 0% win rate on only 2 trades. Worse than either lever tested
alone.

## Synthesis after 5 experiments: execution-delay fragility not fixable within the tested parameter space

Five independent approaches now tested against
`docs/ROBUSTNESS_REPORT.md` test 2's material failure: stop-buffer
widening (2 rounds: 1%/2%, then 0.3%/0.5%), Asian-session-only filtering,
entry-confirmation drift gating (3 thresholds), and the combination of
the two most promising individual levers. **None produced a
configuration that is delay-robust AND confirmed across both independent
years.** Every approach that measurably helped in the 2026 window either
failed cross-year outright or still failed walk-forward in the SAME
window where it helped. Combining levers made results worse, not better.

**This round's conclusion, stated plainly**: within the six categories
authorized for this research round (session filters, market regime
filters, execution timing, entry confirmation, exit logic, risk
management), the specific mechanisms tried (session filter, execution
timing/entry confirmation, and risk management via stop-buffer width) do
not fix this candidate's execution-delay fragility. Two categories remain
genuinely untested: market regime filters (e.g. volatility-percentile
entry restriction) and exit logic beyond the buffer (e.g. a
volatility-scaled rather than zone-boundary-scaled stop distance) -- both
would require new code, not just new parameter values on existing code,
raising the engineering-risk bar for further attempts. Given 5
consecutive rejections all pointing the same direction, continuing to
search for a fix to THIS specific candidate's THIS specific fragility has
reached diminishing returns for this research round. The Legacy engine
remains the production baseline, untouched; the BTC/SOL candidates from
sections 12-14 remain validated-but-not-deployable pending either
infrastructure guarantees or a genuinely different exit architecture, per
`docs/ROBUSTNESS_REPORT.md`'s original recommendation.
