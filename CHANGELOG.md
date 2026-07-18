# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] - Milestone 29: H5 pre-registered then evaluated at Step 0 -- REJECT, session-quality gradient does not transfer across candidate/timeframe

2026-07-19. Full report: `docs/H5_SESSION_GROUNDING_RESULTS.md` (cite,
don't duplicate here). **The question**: `docs/HYPOTHESES_ROUND_1.md`
section 6 (H5, ranked #5, the last unresolved hypothesis from Round 1,
previously only a ranking-table row per `CLAUDE.md`'s explicit caution
against fabricating its spec) was pre-registered in full this round --
mechanism, grounding, pre-registered experiment, keep-rule, cost,
promotion path -- built entirely from evidence already on record, not
invented after the fact. Two things surfaced during pre-registration
that the original 2026-07-17 ranking did not have: new supporting
grounding (Milestone 26's H1 finding that trade FREQUENCY matters more
than per-trade selectivity on this platform, published a day after H5's
original ranking, independently backs sizing-over-filtering as a
mechanism class) and a disclosed grounding gap (H5's sole motivating
evidence, `docs/ROBUSTNESS_REPORT.md` Test 6, was measured on BTCUSDT 5m
against the `structure_tp` candidate, not the 15m Legacy candidate H5
would size). The pre-registration added a **Step 0 gate** specifically to
check that gap before any sizing code was written.

**Step 0 was then run this same round**: new analysis-only harness
`scripts/research_h5_step0_session_grounding.py` (+
`backend/tests/test_research_h5_step0_session_grounding.py`, 8 tests)
buckets already-produced Legacy-baseline trades by UTC entry hour into
Test 6's three session windows (Asian/London/NY-other), no new
`BacktestEngine` parameter or CLI flag needed. BTCUSDT 15m
2024/2025/2026, `--candles 3000 --periods 6`, plain Legacy default --
trade counts (111/65/73) confirmed exact matches to the already-published
baseline before trusting the new bucketing logic.

| Anchor | Asian N / PF | London N / PF | Gradient holds (Asian > London)? |
|---|---|---|---|
| 2026 | 71 / 3.565 | 24 / 5.303 | NO |
| 2025 | 42 / 2.690 | 17 / 4.451 | NO |
| 2024 | 47 / 3.916 | 20 / 2.753 | YES |

**VERDICT: REJECT at Step 0.** Applying H5's own pre-registered gate
literally ("Asian PF > London PF in at least 2 of 3 tested years, both
buckets n>=10"): the gradient direction holds in only 1 of 3 years
(2024) -- in 2026 and 2025, including the platform's single
most-evidenced anchor (2026, 111 trades), London's PF exceeds Asian's,
the OPPOSITE of Test 6's finding. Per H5's own text, this ends the
hypothesis outright -- `session_risk_scalar`/`--session-scaled-sizing`
were never implemented, Step 1 never ran.

**The substantive finding**: a session-quality gradient measured on one
candidate/timeframe does not transfer to a different candidate/timeframe,
even on the same asset and session-window convention -- a standalone,
disclosed caveat for any future hypothesis tempted to condition on Test
6's numbers without re-verifying them on the actual candidate being
sized. **Hypothesis Round 1 is now fully resolved**: H1 REJECT, H2
REJECT, H3 REJECT, H4 MIXED, H5 REJECT at Step 0 -- zero KEEPs. Full
suite 756/756 (up from 748). No orders placed, no DB writes, no
production code touched -- notably, this REJECT required zero new engine
flags, unlike H1/H3/H4's harnesses. Details: `ENGINEERING_DECISIONS.md`
#67.

## [Unreleased] - Milestone 28: H2 passive limit-at-level entry evaluated -- REJECT, delay-robustness achieved cleanly but entry model itself unprofitable

2026-07-18. Full report: `docs/H2_LIMIT_ENTRY_RESULTS.md` (cite, don't
duplicate here). **The question**: `docs/HYPOTHESES_ROUND_1.md` section 4
(H2, ranked #4 -- highest implementation cost of the five) asks whether a
passive resting limit order at the structural entry zone (OB/FVG/sweep
level, `docs/strategy_spec.md` §§2-5) -- instead of an immediate market
fill -- is a genuinely delay-robust alternative entry model. Unlike H1/H3
(pure aggregation atop existing flags), H2 needed real new fill-timing
logic: new opt-in `--limit-at-level` / `--limit-timeout-candles N` flags
in `BacktestEngine`/`entry_model.py`, default off, byte-identical when
unset (confirmed by 2 dedicated regression tests,
`backend/tests/test_backtest_engine.py`). `RiskManager.evaluate()` and
`scripts/run_paper.py` untouched.

**Disclosed implementation judgment calls**: fill price is the zone
level itself (`signal.entry_price`), slippage applied identically to the
existing immediate-fill path; `entry_delay_candles` interpreted as
placement/dispatch latency, shifting when the resting order's scan
window starts (timeout still measures window length from there);
unfilled/expired signals are not recorded as trades or losses.

**Anchor**: BTCUSDT 15m, `--candles 3000 --periods 6 --limit-at-level
--limit-timeout-candles 4 --walk-forward --delay-check`, all three years
(2024/2025/2026), vs. the already-recorded Legacy market-order baseline.

| Year | Legacy Net Profit | H2 Net Profit | H2 Profitable periods | H2 delay-gate PF retention | H2 Sign flip |
|---|---|---|---|---|---|
| 2026 | +$3,400.62 | -$744.13 | 1/6 | 1.003 | NO |
| 2025 | +$1,714.56 | -$727.22 | 0/6 | 0.883 | NO |
| 2024 | +$1,807.75 | -$895.05 | 2/6 | 0.935 | NO |

**VERDICT: REJECT**, applying H2's own pre-registered two-part keep-rule
literally: "Both must hold for KEEP. Either failing alone is REJECT."
**Check 2 (delay-robustness) PASSES cleanly, 3/3 years** -- PF retention
1.003/0.883/0.935, no sign flip anywhere, genuinely and robustly solving
the execution-delay fragility that both Legacy's default exit
(retention 0.015-0.026) and `structure_tp` (Milestone 27, 0.051-0.080)
failed catastrophically. **Check 1 (cost-of-passivity) FAILS
catastrophically, 0/3 years** -- inverts sign in every single year
(2026: +$3,400.62 -> -$744.13; 2025: +$1,714.56 -> -$727.22; 2024:
+$1,807.75 -> -$895.05). Check 1 alone disqualifies.

**Precision note (the substantive finding)**: this is NOT simply "the
same shape of failure the ATR floor already showed" (the keep-rule's own
analogy). Trade count only drops modestly (13-21% fewer than Legacy)
while profitable-periods collapses almost entirely (1/6, 0/6, 2/6 vs.
Legacy's 6/6 in all three years) and walk-forward fails everywhere with
elevated losing streaks (5, 6, 3) -- too small a volume reduction to
explain a swing from strongly profitable to net-loss on its own. The
more precise finding: the retest-based passive-fill mechanism itself
systematically selects for structurally worse trade outcomes,
independent of delay entirely -- waiting for a retest of the zone edge
appears to filter FOR setups that subsequently underperform (or filters
OUT the immediate-continuation setups that drove Legacy's edge). A
genuinely novel, third distinct failure mode among this platform's three
tested delay-robustness fixes: ATR floor (thinned population), entry-
drift gate (inconsistent/partial), and now H2 (clean delay-robustness,
but an unprofitable entry model independent of delay).

**Promotion path**: NONE -- REJECT. Even a KEEP would have had a
uniquely different promotion story per H2's own pre-registered text (a
candle-only approximation of a resting limit order is not verified live
limit-order behavior) -- moot here. Legacy's live/paper trading behavior
is completely unchanged: `RiskManager.evaluate()`, `scripts/run_paper.py`,
`BacktestEngine` internals untouched. No orders placed, no DB writes.

**Full suite 748/748 at evaluation time** (up from 739).

## [Unreleased] - Milestone 27: H3 regime-conditional delay survival of structure_tp evaluated -- REJECT across all three anchors, compounded by regime-bucket evidence scarcity

2026-07-18. Full report: `docs/H3_REGIME_DELAY_RESULTS.md` (cite, don't
duplicate here). **The question**: `docs/HYPOTHESES_ROUND_1.md` section 3
(H3, ranked #3 behind Milestone 26's H1) asks whether `use_structure_tp`'s
already-validated (`docs/PROFITABILITY_EXPERIMENT_REPORT.md` §12-14),
already-known-delay-fragile-in-aggregate (`docs/ROBUSTNESS_REPORT.md`
Test 2, PF 5.24 -> 0.16 at a 5-minute delay) exit family survives a
15-minute execution delay better in some market regimes than others --
combining three already-built, already-independently-validated
mechanisms (`--structure-tp`, `--tag-regimes`, `--delay-check`) that had
never been run together before this round.

**H3 experiment**: new analysis-only harness
`scripts/research_regime_delay.py` (+
`backend/tests/test_research_regime_delay.py`, 23 tests) joins
`--tag-regimes` and `--delay-check` output per bucket, computing PF at
`entry_delay_candles=0` and `=1` separately for each regime bucket
instead of only in aggregate. `RiskManager.evaluate()`'s live
sequential-approval logic is untouched -- purely an aggregation layer
atop already-existing, already-tested mechanics. Unlike H1's two-anchor
requirement, H3's own pre-registered keep-rule requires **three** tested
years (2024/2025/2026, matching `docs/LEGACY_DELAY_ROBUSTNESS.md`'s
standard) -- all three were run: BTCUSDT 15m, `--candles 3000 --periods
6`, uncapped `--structure-tp --tag-regimes`.

| Anchor | Buckets (incl. all) | "all" Baseline PF | "all" Delayed PF | "all" PF Retention | "all" Sign Flip |
|---|---|---|---|---|---|
| 2026 | 10 | 6.723 | 0.536 | 0.080 | true |
| 2025 | 9 | 6.887 | 0.350 | 0.051 | true |
| 2024 | 8 | 7.811 | 0.526 | 0.067 | true |

**VERDICT: REJECT**, applying H3's pre-registered keep-rule literally:
"a regime bucket counts as a genuine delay-robust pocket only if it
clears ... n>=20 trades on the delayed side, PF retention >=0.5, no sign
flip, in AT LEAST 2 of the 3 tested years. If no bucket clears this bar
in any year, REJECT ... outright." Across all 27 bucket-year cells
(10+9+8), not one clears the bar in even a single year -- only ONE cell
(2026 `weak_trend/normal_volatility`) reaches the n>=20 delayed-side
floor at all, and it fails outright on PF retention (0.170) with a sign
flip. Since no bucket clears the bar even once, this does not reach the
rule's own "directional lead" tier (1-of-3) -- a harder, cleaner zero.

**Evidence-scarcity caveat (the substantive finding)**: 26 of the 27
bucket-year cells never reach the n>=20 delayed-side threshold needed to
evaluate the keep-rule meaningfully in the first place -- consistent with
this platform's already-documented regime-bucket scarcity
(`docs/REGIME_PERFORMANCE_ANALYSIS.md`: 8 of 9 buckets evidence-starved
for Legacy's own signal stream). This REJECT is "insufficient data to
test most buckets meaningfully" as much as it is "buckets were tested
and failed."

**Secondary observation, not a keep driver**: the aggregate ("all") PF
retention for `structure_tp` (0.080/0.051/0.067) runs ~2-3x HIGHER than
Legacy's already-documented default-exit aggregate retention at the same
anchors (2026: 0.023, 2025: 0.015, `docs/LEGACY_DELAY_ROBUSTNESS.md`).
Both remain catastrophically below the 0.5 bar with a sign flip in all
three years -- a footnote, not evidence of practical robustness, and it
reinforces (a third data point) that this platform's execution-delay
fragility is structural across strategy variants, not one exit family.

**Promotion path**: NONE -- REJECT. Legacy's live/paper trading behavior
is completely unchanged: `RiskManager.evaluate()`, `scripts/run_paper.py`,
`BacktestEngine` internals all byte-for-byte unchanged. No orders placed,
no DB writes.

**Full suite 739/739 at evaluation time** (up from 716 -- 23 new
`research_regime_delay` tests).

## [Unreleased] - Milestone 26: H1 quality-ranked signal selection evaluated -- REJECT, second confirmation that throughput beats selectivity under the fixed daily cap

2026-07-18. Full report: `docs/H1_SIGNAL_SELECTION_RESULTS.md` (cite,
don't duplicate here). **The question**: `docs/HYPOTHESES_ROUND_1.md`
section 2 (H1, ranked #2 behind Milestone 25's H4) asks whether, holding
`MAX_TRADES_PER_DAY` fixed at 2, selecting the two highest-QUALITY
signals of the day (instead of the first two chronologically) improves
expectancy -- a narrower, safer question than raising the cap itself
(explicitly out of scope, operator-gated per `ENGINEERING_DECISIONS.md`
#62), directly targeting the largest disclosed, quantified opportunity in
this platform's evidence base: 89-92% of Legacy's raw signal stream
rejected purely by the FIFO daily cap (`docs/LEGACY_DELAY_ROBUSTNESS.md`
§2).

**H1 experiment**: new research-only harness
`scripts/research_signal_selection.py` (+
`backend/tests/test_research_signal_selection.py`, 15 tests) re-batches
each simulated day's full signal supply and ranks by a disclosed-not-tuned
score (`rr` = `TradeSignal.rr`; `rr_confluence` = `rr + confluence_count`,
both declared before any run), taking only the top-`MAX_TRADES_PER_DAY`
by score. `RiskManager.evaluate()`'s live sequential-approval logic is
untouched -- purely a research re-batching layer atop `BacktestEngine`'s
existing fee/slippage/fill/PnL mechanics. Baseline reproduction confirmed
exactly (Net Profit to the cent, trade count, walk-forward outcome,
matching `docs/LEGACY_DELAY_ROBUSTNESS.md`/`docs/ATR_FLOOR_EVALUATION.md`)
before trusting the comparison.

| Year | Variant | Net Profit | Profit Factor | Trades | Walk-forward |
|---|---|---|---|---|---|
| 2026 | chronological (baseline) | $3,400.62 | 4.378 | 111 | PASSED |
| 2026 | rr | $2,579.99 | 4.662 | 82 | PASSED |
| 2026 | rr_confluence | $1,737.16 | 2.883 | 77 | PASSED (5/6) |
| 2025 | chronological (baseline) | $1,714.56 | 3.498 | 65 | FAILED (known degradation) |
| 2025 | rr | $1,644.20 | 8.336 | 43 | PASSED |
| 2025 | rr_confluence | $968.04 | 2.708 | 46 | FAILED (5/6) |

**VERDICT: REJECT for both variants**, applying H1's pre-registered
keep-rule literally: `rr` wins Profit Factor in BOTH anchors (+6.5%
2026, +138.3% 2025) but LOSES Net Profit in BOTH anchors (-24.1% 2026,
-4.1% 2025) -- disqualified directly by the rule's own explicit
"wins on PF but not Net Profit, is REJECT" clause. `rr_confluence` loses
both metrics in both anchors outright. Unlike Milestone 25's H4, which
genuinely did not resolve to a single keep-rule branch and was reported
MIXED, H1's rule resolves cleanly -- a straightforward negative result.

**Mechanism**: both ranked variants realize markedly fewer trades than
the chronological baseline under the SAME fixed cap (2026: 82/77 vs. 111;
2025: 43/46 vs. 65) -- a day's top-scored candidates can cluster in time
such that the second-ranked candidate's window overlaps the still-open
first trade and is skipped, whereas FIFO naturally spreads fills as
signals arrive live. Quality-ranking traded away raw throughput for
higher per-trade selectivity, but the throughput loss cost more aggregate
Net Profit than the quality gain recovered, in both years without
exception -- Legacy's edge on this platform scales more with trade
FREQUENCY under the fixed cap than with per-trade selectivity. This
reinforces `docs/strategy_spec.md` §6's existing finding that stricter
confluence does not reliably improve trade quality (`rr_confluence`
performed worse than plain `rr` on both metrics, both years -- a second,
independent data point) and confirms the cap-rejection opportunity
(`ENGINEERING_DECISIONS.md` #62) requires trade throughput, not smarter
selection, to capture -- raising the cap remains explicitly operator-gated,
not something this result argues for.

**Disclosed, un-root-caused discrepancy**: the harness's own PF for the
`chronological` variant runs consistently lower than the previously-
published baseline PF for the identical run (2026: 4.378 vs. 5.024; 2025:
3.498 vs. 4.593) despite Net Profit/trades/walk-forward matching
byte-for-byte -- plausibly a PF-aggregation methodology difference
(per-period-averaged vs. pooled), not verified this round. Does not
affect the verdict (Net Profit is the deciding metric and it reproduced
exactly); flagged as a standing follow-up to resolve before this harness
is reused.

**Promotion path**: NONE -- REJECT. Legacy's live/paper trading behavior
is completely unchanged: `RiskManager.evaluate()`, `scripts/run_paper.py`,
`BacktestEngine` internals all byte-for-byte unchanged. No orders placed,
no DB writes.

**Full suite 716/716 at evaluation time** (up from 701 -- 15 new
`research_signal_selection` tests).

## [Unreleased] - Milestone 25: the research-company loop's first full cycle -- Hypothesis Round 1 + H4 position-sizing parity, verdict MIXED

2026-07-17/18. Full reports: `docs/HYPOTHESES_ROUND_1.md`,
`docs/H4_SIZING_PARITY_RESULTS.md` (cite, don't duplicate here). **The
change**: operator directive (2026-07-17) formalized the platform's
operating model as a research company with named agent roles -- Research,
**Hypothesis (NEW)**, Experiment, Evaluation, Ranking, Promotion, Shadow,
Regime, Risk, Monitoring, QA, Performance, Documentation, CTO. This
milestone is the first time the full loop (Research -> Hypothesis ->
Experiment -> Evaluation) ran end to end.

**Hypothesis Round 1**: 5 falsifiable, mechanism-grounded hypotheses
(H1-H5), each with an external citation, a pre-registered experiment
(exact `run_backtest.py` invocation), and a keep-rule declared BEFORE any
run -- ranked by (evidence-grounding x testability) / cost. 7 other
directions were surveyed and explicitly rejected, with citations
(raising `MAX_TRADES_PER_DAY`, Asian-only entry filter, naive ATR floor,
entry-drift gate, deep RL, HMM regime detection, full L2/spread
modeling). **H4 (close the backtest/live position-sizing gap) ranked
#1** and ran first -- not a search for new edge, but a verified code-level
blind spot: Milestone 7 (2026-07-15) shipped volatility-scaled sizing
(0.5x in high-volatility regimes) live into paper trading, but
`BacktestEngine.run()` never passed the volatility argument to
`calculate_position_size`, meaning every backtest number in this
platform's evidence base (`docs/REGIME_PERFORMANCE_ANALYSIS.md`,
`docs/LEGACY_DELAY_ROBUSTNESS.md`, `docs/ATR_FLOOR_EVALUATION.md`,
`docs/PROFITABILITY_EXPERIMENT_REPORT.md`) was computed at a uniform 1.0x
scalar that live trading has not actually run since 2026-07-15.

**H4 experiment**: new opt-in `--vol-scaled-sizing` flag (default off,
byte-identical when unset, mirrors `run_paper.py`'s exact fail-open
pattern) on a 3-year pre-registered BTCUSDT comparison against the
already-recorded unscaled baselines:

| Year | Trades | PnL scaled vs. baseline | Delta | Worst-DD scaled vs. baseline | Walk-forward | Delay retention scaled vs. baseline |
|---|---|---|---|---|---|---|
| 2026 | 111 | $2,910.07 vs $3,400.62 | -14.42% | 1.42% vs 1.64% (improved) | PASSED both | 0.025 vs 0.023 |
| 2025 | 65 | $1,593.60 vs $1,714.56 | -7.06% | 0.88% vs 0.88% (unchanged) | FAILED-degrading both | 0.015 vs 0.015 |
| 2024 | 73 | $1,764.10 vs $1,807.75 | -2.42% | 1.08% vs 1.25% (improved) | PASSED both | 0.025 vs 0.026 |

**VERDICT: MIXED**, applying the pre-registered keep-rule literally, no
softening. The first bullet ("drawdown improves AND PnL/PF materially
unchanged, at least 2 of 3 years, same years") clears only 1 of 3 (2024)
-- 2026's PnL move (-14.4%) exceeds the ~10% materiality band even though
its drawdown improved, so the conjunction fails there. The second bullet
("Net Profit materially degrades," no year-count qualifier) is literally
triggered by 2026 alone, so it fires as the operative branch. **Operator-
relevant finding, stated as a finding only -- no recommendation to change
the live scalar**: the live 0.5x volatility scalar shows a real,
asset/year-dependent cost/benefit tradeoff, most pronounced in 2026
(-14.4% PnL for a -13.4% relative drawdown improvement), much smaller in
2024, absent in 2025. Whether to act on this is squarely an operator
decision, same boundary as `MAX_TRADES_PER_DAY` (decision #62).

**Footnote check**: delay-gate retention moved <=0.002 in all three
years (noise; all three remain catastrophically below the 0.5 criterion)
and walk-forward verdicts were unchanged in direction/reason everywhere
-- `docs/LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL/3-for-3 verdict needs
no correction, confirmed to hold under vol-scaled sizing too. Open
caveat, not resolved this round: any finding elsewhere resting on Net
Profit margins narrower than ~10-15% could plausibly flip and would need
a targeted re-check.

**Full suite 701/701 at commit time** (up from 692 -- vol-scaled-sizing
implementation tests).

## [Unreleased] - Adaptive platform milestone 24: cross-year evidence round on Legacy's own delay fragility -- STRUCTURAL, plus a MAX_TRADES_PER_DAY discovery

2026-07-17. Full report: `docs/LEGACY_DELAY_ROBUSTNESS.md` (cite, don't
duplicate here). **The question**: milestone 20b found the production
Legacy baseline itself fails the 1-candle (15-minute) delay gate on the
2026 window (PF 5.024 -> 0.117, retention 0.023, sign flip) -- a single
window in a single year. The house cross-year discipline (already
applied to break-even, partial TP, the tuned defaults, and the unified
candidate before any of them were treated as settled) requires testing
the time axis before a finding is labeled structural. This round applies
that same discipline to the platform's own headline finding rather than
exempting it: is the delay fragility structural, or a 2026-regime
artifact?

**Method**: one pre-declared run, the same standard BTC 2025 anchor
every prior cross-year round uses (`--symbol BTCUSDT --timeframe 15m
--candles 3000 --periods 6 --end-date 2025-07-10 --walk-forward
--delay-check`), one config, no parameters tuned. Reproduced the known
BTC-2025 baseline profile to the cent ($1,714.56, 6/6 profitable, 35.4%
second-half retention) -- confirming apples-to-apples comparability
before trusting the delay numbers.

**Result**: baseline PF 4.593 -> delayed PF 0.068, retention **0.015**
(vs. 2026's 0.023), sign flip YES, delay gate FAILED; walk-forward FAILED
on the already-documented BTC-2025 degradation (correctly attributed as
known context, not a new finding of this round).

**VERDICT: STRUCTURAL.** Legacy's delay fragility fails the gate in
BOTH tested years, and slightly worse in 2025 (retention 0.015 vs 0.023)
despite a materially different regime (65 vs 111 trades, degrading
walk-forward vs passing). The regime-dependent hypothesis is falsified:
if the 2026 collapse were regime-specific, a regime this different should
have moved retention materially toward the 0.5 criterion, not further
away from it. `docs/ADAPTIVE_ARCHITECTURE.md` gate #4's requirement note
upgrades from "observed in the 2026 window" to "structural property of
the Legacy strategy family, confirmed across two independent years
(2025, 2026) on BTCUSDT" -- the requirement's substance is unchanged, its
justification is now cross-year. Caveats: one asset (BTCUSDT only),
15-minute delay granularity, two Jan-Jul windows, 2024 still untested.

**Second finding (first real yield from milestone 23's rejection
instrumentation)**: 2025's low trade count (65 vs 111 in 2026) is NOT a
signal drought -- the entry pipeline generated 869 raw signals, of which
804 (92.5%) were rejected, and every single rejection cites the same
reason: `trades_today 2 reached MAX_TRADES_PER_DAY 2`, the only rejection
reason that fired anywhere in the run. Legacy's apparent selectivity in
this window is substantially a `MAX_TRADES_PER_DAY=2` effect, not signal
scarcity -- meaning the regime-bucket evidence starvation previously
attributed to "Legacy trades too selectively" (`docs/
REGIME_PERFORMANCE_ANALYSIS.md`) needs that same qualifier. Recorded as
an insight, not a recommendation: `MAX_TRADES_PER_DAY` is a risk-limit
constant, and any change to it is an operator-gated production-behavior
decision, not something this round proposes.

**Operational validation**: wall time ~11 minutes for the full 2025
round (fetch + baseline + delayed + walk-forward passes) vs. ~3h05m for
the equivalent pre-milestone-22 2026 run -- the milestone 19 + milestone
22 performance work validated in real production use, not just isolated
benchmarks.

Full evidence, per-period tables, and the pre-declared decision rule:
`docs/LEGACY_DELAY_ROBUSTNESS.md`. Rationale: `ENGINEERING_DECISIONS.md`
#62.

## [Unreleased] - Adaptive platform milestones 22-23: FVG mitigation-scan quadratic term eliminated (performance round 2, corrected deferral) + risk-rejection observability

2026-07-17. Two milestones, both closing gaps decision #60 left open.

**Milestone 22 (performance round 2, Fix B -- code in the working tree,
692/692).** Milestone 19's round-1 deferral of "Fix B" (incremental
zone-mitigation caching for `is_zone_mitigated`, the ~22% of runtime it
accounted for after round 1's own fix) rested on the assumption that
closing it required cross-walk-forward-step STATE inside a
`SignalEngine` that's stateless by design. That assumption is now
CORRECTED, not just revisited: no stateful caching was needed at all --
the consumer's own semantics admitted an M19-style reverse scan.
**Discovery**: `entry_model.build_entry_model` only ever uses the
highest-index FVG zone whose type matches `bias` (`wanted_type`
provably collapses to `bias` for the only two values that ever proceed
past `build_entry_model`'s early return). The old code eagerly ran
`is_zone_mitigated` on EVERY historical zone of BOTH types, every step
(round 1 profiling: 965,864 calls, 22.2% of runtime), just to build a
list that gets collapsed to one argmax pick immediately downstream.
**Fix**: new `signal_engine._select_unmitigated_fvg_zones`
(neutral bias short-circuits to `[]`) delegates to new
`fvg.find_latest_unmitigated_fvg_zone` -- a fused newest-to-oldest scan
with early exit (`detect_fair_value_gap`'s loop body has no
cross-iteration state, so a reversed scan visits the identical zones,
merely in reverse order). `detect_fair_value_gap` itself is untouched --
its other two consumers (`entry_point_engine`, `htf_ltf_confluence`)
need the full zone list; every call site was grepped to confirm.

**Verification** (the M19 battery): two independent 5,200-case seeded
property tests against verbatim reference copies of the old logic (0
mismatches, now permanent regression tests); a golden run on anchored
real BTC data across the same 4 flag combinations M19 used -- deep-equal
trade lists 4/4. The namespace-binding trap that caught M19's golden run
(three modules binding `detect_order_block` at import) does NOT recur
here -- only one namespace binds the touched functions, grep-verified
rather than assumed.

**Measured**: n=1000 1.693s->0.933s (1.81x), n=2000 7.484s->3.172s
(2.36x); `is_zone_mitigated` calls 965,864->11,141 (~87x fewer); the FVG
chain is now 1.68% of total runtime; `detect_fair_value_gap`'s forward
scan no longer appears in this path's hot loop at all. **New dominant
costs**: `find_swing_highs`/`find_swing_lows` and the `cf()` OHLCV
accessor -- out of scope this round, recorded for a future round.
Combined with M19's 2.3x, full-scale evidence rounds
(`--candles 3000 --periods 6`) are now roughly **5x faster than the
pre-M19 baseline**.

**Totals**: full suite **692/692 passed / 0 failed**. Code complete in
the working tree; not yet committed. Full report:
`docs/PERFORMANCE_M22.md`. Full rationale: `ENGINEERING_DECISIONS.md`
#61(a).

## [Unreleased] - Adaptive platform milestone 23: risk-rejection observability (committed 3e508d8)

2026-07-17. `BacktestResult` gains `risk_rejections`
(`{total_signals, approved, rejected, by_reason}`) -- purely
observational, closing the instrumentation gap decision #60 flagged
explicitly: the ATR-floor evidence round (milestone 20b) could observe
the 111->60 trade-count drop under `--min-stop-atr 1.5` but could not
report how many signals the risk gate itself rejected, or why. Every
non-`None` signal that reaches a `risk_manager.evaluate()` call
increments `total_signals`; the resulting `approved`/`rejected` outcome
increments the matching counter; a rejected decision's `reasons`
(verbatim strings) each increment their own `by_reason` key. Since
`RiskManager.evaluate()` deliberately does not short-circuit on the
first failing check, a single rejected signal can fail multiple gates at
once, so multiple `by_reason` keys can increment for one `rejected`
increment -- `sum(by_reason.values()) >= rejected`, by design, not a
bug. Default-populated on every path (including the below-`MIN_CANDLES`
early return) via a shared `_empty_risk_rejections()` factory, so a
consumer never needs a `getattr`/`None` guard.
`scripts/run_backtest.py` prints a compact per-period rejection line
only when that period actually rejected something (quiet runs stay
quiet) plus one aggregate line across `--periods` that always prints.

**Totals**: **690/690 passed / 0 failed** at commit time. Purely
additive -- no change to which trades happen, in backtest or anywhere
else. Full rationale: `ENGINEERING_DECISIONS.md` #61(b).

## [Unreleased] - Adaptive platform milestone 20: ATR stop-distance floor wired for A/B testing and REJECTED on evidence -- Legacy production baseline itself found delay-fragile

2026-07-16/17. **20a (wiring, code).** `BacktestEngine.run()` gains a
`min_stop_atr_mult` parameter and `scripts/run_backtest.py` gains
`--min-stop-atr`, making the milestone 18b `RiskManager` ATR
stop-distance floor A/B-testable for the first time. ATR is computed
from the signal's own no-lookahead slice. The disabled path (flag
omitted) is proven byte-identical: a fake-`RiskManager`-that-raises-on-
unexpected-kwargs test exercises the unflagged path, so any leakage of
the new kwargs into disabled behavior would fail the suite outright, not
just silently change results. 7 new tests.

**20b (evidence round).** Full report: `docs/ATR_FLOOR_EVALUATION.md`
(final). Identical BTCUSDT 15m anchor (6x3000 candles,
`--end-date 2026-07-10`, walk-forward + delay-check on every config).
**Baseline** (floor off): 111 trades, +$3,400.62, 6/6 profitable
periods, walk-forward PASSED -- delay-check FAILED (PF 5.024 -> 0.117,
retention 0.023, sign flip). **`--min-stop-atr 1.5`**: 60 trades (-46%),
+$1,113.35 (-67%), 3/6 profitable, walk-forward FAILED, delay retention
only 0.079 (still 6x below the 0.5 pass criterion), sign flip remains,
delay-check FAILED. **2.0x deliberately NOT run** -- CTO early stop per
the project's dead-config discipline: 1.5x tripled retention
(0.023->0.079) while destroying consistency and profit, with no
plausible path to 0.5.

**VERDICT: ATR stop-distance floor REJECTED as a delay-robustness fix.**
It "trades less, worse," not "trades the same, safer": -46% signals,
-67% PnL, -53% PF, walk-forward PASS->FAIL, with the delay retention
still 6x below criterion and the sign flip intact. `settings.
MIN_STOP_ATR_MULT` stays `0.0` (disabled) everywhere -- not enabled in
paper trading, not recommended for promotion. This is the honest
negative result `docs/RESEARCH_ROUND_1.md` section 4c pre-committed to
recording rather than quietly tuning around.

**HEADLINE FINDING: production Legacy itself fails the 1-candle delay
gate on this window** -- previously unknown (`docs/ROBUSTNESS_REPORT.md`
test 2 only delay-tested the already-killed `structure_tp` candidate).
Delay fragility is a property of the shared entry pipeline on this
window, not one candidate's defect. Severity caveat: 1 candle = 15
minutes on this 15m anchor, 3x harsher than the original 5-minute test
-- this does NOT prove failure at seconds-scale live latency; the honest
statement is that Legacy's backtested edge here lives inside a
sub-15-minute execution window. Consequence: verified low-latency
execution infrastructure is now an explicit hard prerequisite for
`docs/live_trading_checklist.md` gate #4.

**Ops notes**: an instrumentation gap (the runner doesn't print
rejected-signal counts, so the 111->60 trade drop is the observable
proxy, not a direct count); wall-clock timing evidence for the Fix B
performance backlog (baseline ~3h05m, 1.5x run ~1h17m -- `--delay-check`
triples engine passes, both far over the ~5-15 min/config estimate); one
harness background-task kill worked around with detached OS processes;
the live paper trader was killed once by the same cleanup and relaunched
immediately on latest source (including Milestone 21 alerting).

**Totals**: full suite **669/669 passed / 0 failed**. 20b is read-only
evidence collection -- no orders placed, no writes to
`backend/paper_validation.db`. Full rationale: `ENGINEERING_DECISIONS.md`
#60, full evidence: `docs/ATR_FLOOR_EVALUATION.md`.

## [Unreleased] - Adaptive platform milestone 19: backtester quadratic-scan fix -- reverse-scan early-exit in detect_order_block, bit-identical verified, 2.3x measured speedup

2026-07-16. Closes the "performance profiling analysis" item left pending
by milestone 18 after a session-usage-limit interruption. **Performance
round 1 (profiling, measurement-only, prior session)**: diagnosed the
backtest engine as effectively quadratic -- log-log scaling exponent
~2.26 measured across 500/1000/2000/3000-candle runs on real BTCUSDT
data. `detect_order_block()` accounted for 62.6% of total runtime: its
forward scan recomputed a fresh 15-candle average-range window at every
history position on every walk-forward step, while only the LAST
qualifying match it found ever survived to be returned. `#2` was
`is_zone_mitigated()` at 22.2% (O(n) FVG zones times per-step scans);
the `cf()` OHLCV accessor was a large constant factor in self-time (~40%,
220M calls at n=3000) without driving the quadratic shape itself.
Slicing (`ltf_candles[:i+1]`) was measured and ruled out -- under 0.2% of
runtime. Window-capping history was explicitly REJECTED as
behavior-unsafe: sweeps/FVGs/CHOCH legitimately reference arbitrarily
old structure in this strategy's own logic, so capping would silently
change trades generated, not just speed.

**Fix (Milestone 19, `order_block.py`).** `detect_order_block()` now
scans newest-to-oldest and returns the FIRST qualifying match (impulse
candle + opposite-color prior candle) -- provably the same candle the
old oldest-to-newest scan kept (its "last match found" behavior means it
always returned the newest qualifying match, exactly what a
newest-to-oldest scan finds first), reached with far less work. Both of
the forward loop's existing traps are preserved unchanged: a
non-qualifying impulse candle continues scanning toward older
candidates, and so does a doji candle. A rolling-window-sum
micro-optimization for the average-range computation was implemented,
tested, and DELIBERATELY SKIPPED -- float addition/subtraction is not
associativity-safe, and it failed this round's own bit-identical
verification gate.

**Verification.** (1) A property test against a verbatim reference copy
of the old implementation: 5,200 seeded synthetic candle series
including adversarial modes, 0 mismatches -- now a permanent regression
test. (2) A golden run on anchored real data (BTCUSDT 15m, 2000 candles,
`end_time_ms` 2026-06-27) across all 4 flag combinations
(default/breaker/structure-tp/jade) -- trade lists deep-equal at exact
float precision. Noteworthy subtlety: three modules (`signal_engine`,
`entry_point_engine`, `htf_ltf_confluence`) each bind
`detect_order_block` into their own namespace at import, so the
golden-run's old-vs-new comparison had to patch all three module
namespaces, not just `order_block.py`'s own.

**Measured speedup** (unprofiled wall-clock): 1000 candles 4.32s ->
1.81s (2.39x), 2000 candles 16.15s -> 7.09s (2.28x) -- Milestone-10-style
evidence rounds (`--candles 3000 --periods 6`) drop from roughly 40
minutes to roughly 17.

**Deferred**: Fix B (incremental zone-mitigation caching for
`is_zone_mitigated`, the remaining ~22%) -- medium risk, needs
cross-step state inside a currently-stateless `SignalEngine`; revisit
only if this 2.3x proves insufficient.

**Totals**: full suite **653/653 passed / 0 failed** (652 + 1 permanent
property test). Code complete in the working tree; not yet committed.
Full rationale: `ENGINEERING_DECISIONS.md` #59.

## [Unreleased] - Adaptive platform milestone 18: research round 1's top-3 adopted -- delay-check promotion gate, RiskManager ATR stop-distance floor, realistic shadow-fill resolution (v2)

2026-07-16. Implements the top-3 recommendations of
`docs/RESEARCH_ROUND_1.md` (committed) -- the Research department's
survey of established quant technique against this platform's four
actual open problems. All three adopted items trace to a PROVEN failure
mode already observed on this platform. The same round also REJECTED
HMM regime-switching (this platform's own analysis shows trade scarcity,
not classifier noise, is the bottleneck) and deferred the heavyweight
statistical tests (at n=20-60 they agree with the existing 20-sample
floor) -- evidence-over-hype working as designed.

**Milestone 18a: `run_backtest.py --delay-check`.** New
`delay_robustness_report()` compares a zero-delay run vs. an
`entry_delay_candles=1` run on IDENTICAL fetched candles: passes only if
`pf_retention >= 0.5` (disclosed-not-tuned; the reference failure,
`docs/ROBUSTNESS_REPORT.md` test 2, retained only 0.03) AND no
profitable-to-unprofitable sign flip. Honest edges: zero trades or an
undefined baseline PF yield `passed=None` "insufficient data" -- never a
fake pass. Composable with `--strategy`/`--walk-forward` (combined
promotion-gate summary when both gates run). 12 new tests.

**Milestone 18b: RiskManager ATR stop-distance floor.** `evaluate()`
gains caller-computed `stop_distance_atr_mult` + `min_stop_atr_mult`
(decision #49 pattern -- RiskManager computes nothing itself); rejection
reason `"stop_distance_below_atr_floor"`; boundary convention mirrors
`MIN_RR` (exactly at the floor passes, strictly below rejects); a
missing measurement never rejects (missing data is not evidence of a
tight stop). New `settings.MIN_STOP_ATR_MULT`, default `0.0` = DISABLED
-- enabling changes trade acceptance and requires A/B backtest evidence
first (implemented-is-not-evidenced discipline). Root cause addressed:
the dead candidate's 0.17-0.23%-of-price stops (Wilder-convention
literature: 1.5-3.0x ATR). 6 new tests.

**Milestone 18c: realistic shadow fills (v2).** Migration `6b085b904777`
adds `shadow_signals.resolution_model` (String, nullable; `NULL` =
legacy optimistic rows, permanently distinguishable, never backfilled).
The resolver now: fills entries at the NEXT candle's open after
`captured_at` (1-candle delay), applies adverse slippage plus both-leg
fees from `paper_broker`'s real imported constants, and recomputes
`resolved_r` from the ACTUAL fill -- an sl can now be worse than -1R
(gap-through-stop resolved honestly), and a gap-past-TP is excluded as a
missed entry rather than optimistically credited (counted separately in
the summary). `collect_regime_evidence` counts ONLY
`resolution_model="v2_realistic_fills"` rows toward `n` (old rows go to
`n_excluded`), so the two measurement regimes never mix. The disclosed
optimism caveat softens to "simulated but fee/slippage/delay-adjusted."

**Totals**: full suite **652/652 passed / 0 failed** at commit time.
Committed as `4fe7496` without its docs round -- a session-limit
boundary killed two sub-agents mid-flight, so the orchestrator ran the
QA gate itself (652/652) and committed to secure the work; this docs
round completes the debt after the reset. **Same-day ops**: the live DB
was migrated to head `6b085b904777` and the trader restarted with v2
resolution active plus 4-symbol shadow collection. Full rationale:
`ENGINEERING_DECISIONS.md` #58.

## [Unreleased] - Operating-model shift to continuous CTO-driven improvement, plus adaptive platform milestone 17: multi-symbol shadow collection and daily CTO reporting

2026-07-16. Adaptive-platform milestones 1-16 are complete; the operator
directive shifts the mandate from feature implementation to continuous
CTO-driven improvement -- specialist-agent roles (CTO/Research/Strategy/
Backtest/Risk/Monitoring/QA/Performance) select the next highest-ROI
milestone by bottleneck analysis rather than asking what to build next,
stopping only for architectural decisions, credentials, production
deployment, or destructive actions. Promotion gates are unchanged and
never bypassed (significant edge, positive expectancy, lower drawdown,
sufficient sample, multi-market, regime validation); Legacy remains the
only production engine. A daily morning CTO report is now standing
practice.

**Milestone 17a: multi-symbol shadow collection.** Bottleneck-driven by
`docs/REGIME_PERFORMANCE_ANALYSIS.md`'s finding that 8 of 9 regime
buckets were evidence-starved due to single-symbol collection. New
`settings.SHADOW_SYMBOLS` (comma-separated, default `""` -- byte-
identical off): when set, `run_paper.py`'s shadow block additionally
fetches candles and runs resolve+record for each extra symbol (ETH/SOL/
XRP intended), per-symbol fault-isolated. Summaries surface under
`summary["shadow"]["extra_symbols"]`. On extra symbols no strategy is
active, so `active_strategy_name=None` excludes nobody -- ALL six
registered strategies, including `legacy` and `jade`, get shadow-
evaluated there, multiplying evidence for the scarcest resource: Legacy's
own per-bucket live sample count. Trading logic never touches extra
symbols. 9 new tests plus a real-temp-DB smoke test (live DB untouched).

**Milestone 17b: daily CTO report generator.** New `scripts/cto_report.py`
+ `app/portfolio/cto_report.py`: 8 fixed sections (completed work,
evidence accumulated, strategy rankings + shadow performance, selector
dry-run bucket count, a mechanical disclosed bottleneck rule, live risk
checks, suggested next milestone quoted from `ROADMAP.md`, completion %
parsed from `docs/ADAPTIVE_ARCHITECTURE.md` section 7). Every section has
an explicit "unavailable: <reason>" fallback -- it never fabricates a
number. Read-only DB (`mode=ro`), ASCII-only, file-write-before-print
(decision #54 conventions). 22 new tests. First real run against the live
DB: 28 regime snapshots (3 buckets), 0 shadow signals yet, 0 sufficient
evidence cells -> bottleneck = evidence accumulation; trader running; DB
at head `65aba13281ad`; 100.0% of the 16 currently-scoped section-7
milestones (explicitly not the long-term vision).

**A real bug, found and fixed during the build**: `subprocess.run(...,
text=True)` decodes captured `git log` output as cp1252 on Windows,
mangling UTF-8 commit-message characters BEFORE any sanitizer sees them.
Fixed with an explicit UTF-8 decode (`errors="replace"`). The second
cp1252-decoding lesson on this platform, after decision #54.

**Totals**: full suite **602 -> 633 passed / 0 failed** (+31: 9 multi-
symbol + 22 report). Live trader untouched during the build; a restart
with `SHADOW_SYMBOLS` set is a pending, orchestrator-handled operational
step. Full rationale: `ENGINEERING_DECISIONS.md` #57.

## [Unreleased] - Adaptive platform milestones 13-16: shadow-data tooling, outcome resolution, rolling per-regime evidence, and a built-but-unwired RollingPerformanceSelector -- plus a JSON-serialization bugfix

Four milestones plus one production bugfix, all 2026-07-16, completing the
evidence-to-selection chain `docs/ADAPTIVE_ARCHITECTURE.md` section 4.3
has described since milestone 4. Routing remains evidence-gated and
unwired -- `AVAILABLE_STRATEGIES` and both production selectors
(`DefaultToLegacySelector`, `ConfigurableFallbackSelector`) are untouched.

**Milestone 13: shadow-data status tool.** New `scripts/shadow_status.py`
(read-only CLI, opens SQLite with a `mode=ro` URI so a write attempt is
refused by SQLite itself) + `app/portfolio/shadow_status.py` (pure
helpers: reuses milestone-12's bucket convention, snapshot stats,
per-(strategy, bucket) signal counts, distance-to-the-20-sample-floor
report). ASCII-only console output (applies decision #54's cp1252 lesson
pre-emptively). Output carries an explicit honesty note: raw signal
counts are necessary but not sufficient for routability -- performance-
evaluated samples are what matters, which milestone 14 supplies. 18
tests. Live smoke: 3 regime snapshots already accumulating, 0 shadow
signals yet.

**Milestone 14: shadow outcome resolution.** New migration `65aba13281ad`
(chained on `36cb62e9e2ac`): `ShadowSignal` gains `outcome` (nullable
indexed, `"tp"`/`"sl"`/`"expired"`, `NULL`=open), `resolved_at`,
`resolved_r` (`+rr` for tp, `-1.0` for sl, `NULL` for expired). 8 tests
including old-generation `migrate_existing` upgrade paths. New
`app/portfolio/shadow_resolver.py`:
`resolve_open_shadow_signals(symbol, ltf_candles, now)` walks candles
strictly after `captured_at`, resolving SL before TP within a candle --
mirroring `BacktestEngine._simulate_trade`'s own documented convention
rather than inventing a second one. `EXPIRY_HOURS = 168` (7 days,
disclosed-not-tuned) -> `"expired"`. Wired into `run_paper.py`'s existing
shadow block behind the same `ENABLE_SHADOW_STRATEGY_SIGNALS` flag,
fault-isolated, resolution runs BEFORE recording so a signal is never
resolved in the same pass it was captured. Summary surfaces under
`summary["shadow"]["resolution"]`. 9 tests plus a real-temp-DB smoke test
(end-to-end `run_once` resolved a pre-inserted signal to tp/+2.0R).
Disclosed caveat: shadow outcomes are simulated fills with no fees or
slippage -- an optimistic upper bound, not an unbiased estimate.

**A real bug, found by milestone 14's own smoke test and fixed the same
day.** `shadow_recorder.record_shadow_pass()` wrote `asdict(signal)`
straight into a JSON column; `TradeSignal.timestamp` is a real `datetime`
in production despite its `str` type hint, so `json.dumps` raised
`TypeError` at flush. Worse: the raise sat OUTSIDE the per-strategy
try/except guard, aborting the ENTIRE shadow-recording pass rather than
just one strategy's slice of it. Latent-live: `ENABLE_SHADOW_STRATEGY_
SIGNALS` had been operator-enabled that same day, so the first real
shadow signal generated by the live paper trader would have hit this
exact error and been silently lost. Fixed with a recursive `_json_safe`
sanitizer (datetime -> isoformat, applied structurally) on
`signal_payload` and `market_regime`; regression test observed failing
pre-fix, passing post-fix.

**SQLite naive-datetime lesson** (hit independently by both milestone 14
and milestone 15): `DateTime(timezone=True)` round-trips through SQLite
as NAIVE on read (SQLAlchemy strips `tzinfo` coming back out) while
candle timestamps stay tz-aware -- comparing them raises `TypeError`.
Both modules needed an explicit naive-UTC normalization helper.

**Milestone 15: rolling per-regime evidence layer.** New
`app/portfolio/rolling_regime_performance.py`: `RegimeCellEvidence`
dataclass + `collect_regime_evidence(session, window_days=30,
min_samples=20)` -> dict keyed `(strategy, bucket, source)`, `source`
one of `"shadow"`/`"live"` -- **deliberately never averaged together**
(simulated fee-free fills and real fee-paying trades are different
measurement instruments; the selector, not this layer, decides
precedence explicitly). Shadow-side counts only resolved `tp`/`sl`
toward `n` (expired/open -> `n_excluded`, not dropped or miscounted);
live-side counts only closed trades with a non-null `market_regime` AND
non-null `r_multiple` (pre-regime-tagging trades are skipped entirely,
not folded into "untagged"). 14 tests against hand-computed arithmetic
fixtures.

**Milestone 16: `RollingPerformanceSelector` -- built, NOT wired.**
Appended to `app/strategy/selector.py` (existing classes untouched):
module-level `select_for_bucket(bucket, evidence, available,
min_samples)` seam + `RollingPerformanceSelector` (`StrategySelector`
Protocol, `select_with_reason()`). Rule, each step disclosed: `regime is
None` -> legacy; Legacy's OWN live cell must itself be sufficient
(n>=20) or the result falls back to `legacy` with reason
`"fallback_legacy_baseline_unmeasured"` (a challenger cannot beat an
unmeasured baseline); challengers read their live cell if sufficient,
else their shadow cell (live precedence, no cherry-picking); a challenger
qualifies only if its expectancy_r is strictly > 0 AND strictly > Legacy's
own; argmax wins among qualifiers; ties or none -> legacy; any
shadow-sourced win carries a `"_shadow_evidence_optimistic"` marker in
its reason. The floor-plus-strict-inequality rule is disclosed as NOT a
statistical significance test -- deferred honestly, not built
prematurely and not silently assumed equivalent. New
`scripts/selector_dry_run.py` (read-only, `mode=ro`): evaluates all 9
regime buckets plus `"untagged"`; run against a scratch head-migrated
database it reproduced the expected result -- `legacy` in all 10 buckets
(baseline unmeasured) -- matching `docs/REGIME_PERFORMANCE_ANALYSIS.md`'s
own prediction. 14 tests. Not wired into `run_paper.py` -- production
selection is unchanged; wiring is a future, evidence-gated operator
decision.

Tests: 18 (M13) + 8 (M14 schema) + 9 (M14 resolver) + 14 (M15) + 14 (M16)
= roughly 63 new tests, plus the bugfix regression test. Full suite
**602 passed / 0 failed** (was 539 after milestone 12). Live paper
trader ran untouched throughout; production behavior unchanged;
`AVAILABLE_STRATEGIES` and both production selectors untouched. Known
pending ops step (not part of this round): the live paper-trading DB is
still one migration behind (`65aba13281ad` not yet applied), and the
process needs a clean restart to activate outcome resolution and the
serialization fix. Design rationale: `ENGINEERING_DECISIONS.md` #55
(milestones 13-15 + bugfix), #56 (milestone 16).

## [Unreleased] - Adaptive platform milestone 12: regime-tagged backtesting + per-regime performance analytics + evidence round 2

`BacktestEngine.run()` gained a new final parameter `tag_regimes: bool =
False` (2026-07-16). When `True`, each accepted/simulated trade dict
gets a `"market_regime"` key holding the full `detect_market_regime`
classification computed at the signal's own candle index, post-risk-
approval -- the same tagging point `run_paper.py` already uses for real
trades (wrapped in try/except, degrades to `None` on failure). When
`False`, the key is absent entirely and behavior is byte-identical to
every pre-milestone-12 run. Works identically on both signal paths (the
default `SignalEngine` path and the milestone-9 `strategy=` injection
path). `scripts/run_backtest.py` gained `--tag-regimes`.

New `backend/app/backtesting/regime_analysis.py` (pure functions, no
I/O): `regime_bucket` (`"{trend}/{volatility}"`, `"untagged"` fallback),
`aggregate_by_regime` (per-bucket trades/wins/win_rate/total_pnl/
expectancy/profit_factor/sufficient_sample, `MIN_TRADES_FOR_CONFIDENCE
=20` per this project's own evidence-floor convention), `comparison_
table` (markdown, insufficient-sample rows marked with the ASCII string
`"(! n<20)"`). `win_rate`/`profit_factor` reused from `app.backtesting.
performance`; `expectancy` reimplemented locally since `scripts/` is not
importable from `app` code. New `scripts/analyze_regime_performance.py`
CLI: fetches candles once, runs Legacy plus all four experimental
strategies over identical periods with `tag_regimes=True`, writes and
prints the comparison table.

**A real bug found by evidence round 2 and fixed.** The first live run
of `analyze_regime_performance.py` crashed with `UnicodeEncodeError` on
the `⚠` (U+26A0) insufficient-sample marker inside `print(table)` --
the Windows console's default cp1252 encoding cannot represent it. The
crash landed AFTER a completed multi-minute run (candle fetch + five
full strategy backtests) and BEFORE the results were written to a file,
so a fully completed run's output was lost outright. Fixed two ways:
the ASCII marker above replaces the Unicode glyph, and the CLI now
writes its output file BEFORE printing to console, so a console-
encoding failure can never again take a completed run's results down
with it. Verified via a cp1252 round-trip encode of the new marker.

Tests: +4 in `test_backtest_engine.py` (real-classification tagging on
both signal paths, key-absence as the untagged default, explicit
`tag_regimes=False` identity -- caught one fixture bug along the way, a
regime-detection candle fixture was missing the `volume` key) + 17 new
in `test_regime_analysis.py` (hand-computed arithmetic fixtures, the
19-vs-20 sample-size boundary, markdown markers, empty input). Full
suite **539 passed / 0 failed** (was 518 after milestone 11).

**Evidence round 2**: same anchor as round 1 (BTCUSDT 15m,
`--candles 3000 --periods 6 --end-date 2026-07-10`); pooled totals
reproduced round 1 exactly (integrity check). No regime bucket shows an
experimental strategy credibly beating Legacy -- the only bucket with
n>=20 on both sides (`weak_trend/normal_volatility`, BTC's dominant
regime) has Legacy at +$26.28 expectancy / PF 3.30 (n=28) versus the
best experimental strategy, `volatility_expansion`, at +$4.29 / PF 1.23
(n=56). Each experimental strategy is least-bad in its own designed
regime (`range_trading` positive only in `range/low_volatility`, PF
1.03, n=44; `breakout` only in `weak_trend/high_volatility`, PF 1.06,
n=44) but none crosses meaningfully above breakeven-with-costs. Legacy
is positive in all 9 buckets but 8 of 9 are n<20 -- it trades too
selectively (111 trades/6mo) for per-regime evidence to accumulate fast.
Platform implication: a correctly built `RollingPerformanceSelector` run
against this data would route Legacy in 9/9 buckets today (8 by
insufficient-data fallback, 1 by argmax) -- shadow-mode recording
(milestone 11) remains the right lever for filling sparse buckets, not
another backtesting round on this same asset/window. Caveats: single
asset/window, in-sample, disclosed-not-tuned rules. Full report:
`docs/REGIME_PERFORMANCE_ANALYSIS.md` (final). Design rationale:
`ENGINEERING_DECISIONS.md` #54.

## [Unreleased] - Adaptive platform milestones 10+11: evidence round 1 (no promotions) + shadow-mode observability (default-off)

Two milestones landed in the same round (both 2026-07-16).

**Milestone 11: shadow-mode observability.** Before this, regime data
persisted only on trade rows (`Trade.market_regime`) and Strategy
Selection decisions only existed in stdout -- a "no signal" pass (the
overwhelming majority) persisted nothing, so the regime-tagged dataset
`docs/ADAPTIVE_ARCHITECTURE.md` section 4.3's future
`RollingPerformanceSelector` needs accumulated only at trade speed
(effectively zero rows to date). New migration `36cb62e9e2ac`
(down_revision `e3110e6a6b59`, additive): tables `regime_snapshots` (one
row per paper pass when enabled) and `shadow_signals` (one row per
signal a NON-active registered strategy would have generated), plus new
ORM models `RegimeSnapshot`/`ShadowSignal` (`app/database/models.py`).
New `app/portfolio/shadow_recorder.py`: `record_shadow_pass()` evaluates
`all_strategies()` minus the active strategy, per-strategy try/except so
one broken strategy never blocks the others. New `app/config.py` flag
`ENABLE_SHADOW_STRATEGY_SIGNALS: bool = False` (default off), wired into
`scripts/run_paper.py` at exactly two settled points of `run_once` (the
no-signal early return and the end of the full trade path, reusing the
already-computed regime) -- flag-off path verified byte-identical via a
real-temp-DB smoke script. `backend/tests/test_db_bootstrap.py` pinned
migration head updated `e3110e6a6b59` -> `36cb62e9e2ac`. 16 new tests
(13 schema + 3 recorder). **518/518 full suite passing** (was 505).
Quarantine intact: shadow mode only asks non-active strategies what they
would have done; `AVAILABLE_STRATEGIES`, both production selectors, and
what actually trades are untouched under every flag combination. Design
rationale: `ENGINEERING_DECISIONS.md` #53.

**Milestone 10: evidence round 1 (backtest evaluation of the four
milestone-9 experimental strategies).** First backtest run of
`trend_following`/`range_trading`/`breakout`/`volatility_expansion`
against the Legacy baseline via the `--strategy` pipeline, all five runs
on identical candles (BTCUSDT 15m, `--candles 3000 --periods 6
--end-date 2026-07-10 --walk-forward`, standard fees/slippage):

| config | trades | win rate | total PnL | profitable periods | worst DD | walk-forward |
|---|---|---|---|---|---|---|
| baseline (Legacy) | 111 | 75.68% | +$3,400.62 | 6/6 | 1.64% | PASSED |
| trend_following | 146 | 26.03% | -$1,009.78 | 1/6 | 3.92% | FAILED |
| range_trading | 258 | 17.83% | -$2,321.08 | 2/6 | 9.85% | FAILED |
| breakout | 347 | 26.51% | -$5,329.19 | 0/6 | 12.10% | FAILED |
| volatility_expansion | 246 | 34.55% | -$892.45 | 3/6 | 7.46% | FAILED |

All sample sizes cleared this project's 20-trade evidence floor 5-17x
over. `breakout` is "clearly dead -- do not extend without code-level
review"; the other three are negative but not uniformly dead;
`volatility_expansion` is least-bad (3/6 profitable periods, smallest
loss) and the only one worth prioritizing if a future round happens.
**No promotions** -- promotion needs cross-asset + cross-year +
out-of-sample confirmation, none of which this round attempted. No code
defects found; losing money is a valid evidence outcome. One
operational note: OKX fetch failed 5x (timeouts) before succeeding for
`trend_following`, network-layer only. Validates the platform thesis:
the evidence pipeline + quarantine correctly rejected all four textbook
rulesets while Legacy stayed protected throughout. Full report:
`docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`. Run artifacts in
`scripts/reports/eval_m10_*` (gitignored by convention -- only the docs
report is committed). Pure evidence round, no design decision recorded.

## [Unreleased] - Adaptive platform milestone 9: four new strategy-content modules, quarantined and evidence-pipeline-ready

Four new `Strategy`-Protocol modules (`app/strategy/`) -- the platform's
first strategies that are NOT `SignalEngine` wrappers, closing out the
last item on `docs/ADAPTIVE_ARCHITECTURE.md` section 7's milestone
roadmap:

- `trend_following.py` (`TrendFollowingStrategy`, `"trend_following"`,
  160 LoC): HTF swing-trend + LTF SMA(20) agreement + ADX(14) >= 20
  filter, pullback-to-MA-then-resumption entry, swing-based stop with a
  0.25*ATR buffer (1.5*ATR fallback when no swing point exists), fixed
  2.5R target.
- `range_trading.py` (`RangeTradingStrategy`, `"range_trading"`,
  154 LoC): ADX < 20 + a 40-candle range at least 2*ATR wide, fades the
  bottom/top 15% edge of that range, stop 0.5*ATR beyond the extreme, TP
  at the opposite extreme, emits only when the honest rr clears 2.0 (this
  platform's `RiskManager.MIN_RR`). An algebraic check of the module's own
  formulas shows this rr floor is effectively ~2.125 whenever the width/
  edge gates already pass -- the guard is defensive, not independently
  reachable; see `ENGINEERING_DECISIONS.md` #52(d).
- `breakout.py` (`BreakoutStrategy`, `"breakout"`, 143 LoC): 20-candle
  Donchian-channel close-through with confirmation (candle body >= 1x
  ATR OR volume > 1.5x its 20-candle average), stop at the broken channel
  edge +/- 0.5*ATR, 2.5R target.
- `volatility_expansion.py` (`VolatilityExpansionStrategy`,
  `"volatility_expansion"`, 156 LoC): squeeze precondition via
  `regime_detector.volatility_percentile <= 0.25` on the candles before
  the current one, trigger = current candle true range >= 2*ATR(14),
  direction = the expansion candle's own direction, stop = its opposite
  extreme, 2.5R target.

All four reuse existing indicator helpers (`regime_detector`/
`market_structure`/`utils`) -- zero reimplemented indicators -- are
detection-only, return `None` generously on ambiguous/insufficient input,
and disclose in their own docstrings that every threshold is a standard
textbook value, not backtest-tuned.

`app/strategy/experimental.py` (new): `EXPERIMENTAL_STRATEGIES`, a
quarantine registry holding these four, plus `all_strategies()` merging
it with `AVAILABLE_STRATEGIES`. The PRODUCTION registry
`AVAILABLE_STRATEGIES` is untouched -- still exactly `{legacy, jade}` --
and no real selector (`DefaultToLegacySelector`,
`ConfigurableFallbackSelector`) ever consults the experimental registry.
Promotion into `AVAILABLE_STRATEGIES` requires backtest/walk-forward
evidence first.

`BacktestEngine.run()` gained an additive `strategy: Strategy | None =
None` parameter (`app/backtesting/backtest_engine.py`, import guarded
behind `TYPE_CHECKING`): default `None` is byte-identical to every
existing caller's prior behavior (proven with a `SignalEngine` fake that
raises if called); when given, ONLY the signal source changes -- risk
gating, sizing, fills, fees, slippage, break-even/partial-TP, PnL, and
reporting are all unchanged. `scripts/run_backtest.py --strategy NAME`
resolves the name via `all_strategies()` before any candle fetch (an
unknown name errors immediately, listing the available names) and prints
a `NOTE` when any SignalEngine-only flag is set alongside it (ignored,
since `--strategy` bypasses the SignalEngine pipeline entirely).

**Why a separate quarantine registry, not registering into
`AVAILABLE_STRATEGIES`**: "registered somewhere in the codebase" must
never silently become "selectable by production/paper trading" --
promotion is a deliberate, evidence-gated act. **Why inject at the
signal source only**: it puts experimental strategies through the exact
same fee/slippage/walk-forward pipeline every existing finding in this
project was validated against, so their eventual backtest numbers are
directly comparable to Legacy's own history. Full rationale:
`ENGINEERING_DECISIONS.md` #52.

38 new strategy/registry tests (7 + 9 + 6 + 8 + 8) + 2 new
`BacktestEngine` injection tests = 40 new tests. **505/505 full suite
passing** (was 465 after milestone 8.1). Production behavior unchanged:
`AVAILABLE_STRATEGIES` still exactly `{legacy, jade}`; the paper trader
(Legacy engine) untouched and running throughout. Smoke check:
`all_strategies()` -> `['breakout', 'jade', 'legacy', 'range_trading',
'trend_following', 'volatility_expansion']`.

## [Unreleased] - Adaptive platform milestone 8.1: live paper-DB migrated to schema head

`app.database.migrate_existing.migrate_database()` (new): brings a
never-alembic-stamped SQLite DB up to the current migration head by
fingerprinting which of 4 historical schema generations the file matches
(`a0f5ebc23690` initial -> `4b8a822a475b` circuit-breaker columns ->
`393afdf7fe67` observability columns -> `e3110e6a6b59` adaptive platform),
stamping that revision, then running a normal `upgrade head`. Refuses
(`ValueError`) rather than guesses on an unrecognized schema; detects an
already-stamped DB and runs a plain, idempotent upgrade instead of
re-stamping; takes an optional timestamped file backup before mutating.
`scripts/migrate_paper_db.py` is a thin CLI over it -- detect-only by
default, `--apply` to migrate, `--no-backup` to opt out of the backup.

**Why**: the live paper-trading DB (`backend/paper_validation.db`) was
created by an early bootstrap predating this project's alembic
discipline -- no `alembic_version` table -- and `scripts/run_paper.py`
never runs migrations (only `app.main`'s FastAPI lifespan does, and no
FastAPI process runs alongside the paper trader). Every adaptive-platform
milestone since #2 added columns/tables the live DB never received, so a
paper-trader restart on current code would have crashed on its first
trade INSERT. `app/database/migrations/env.py` gained a guard so
`migrate_existing`'s arbitrary-file targeting doesn't disturb any
pre-existing caller: it only injects `settings.DATABASE_URL` when the
caller hasn't already set `sqlalchemy.url` programmatically (`alembic.ini`
commits an empty url, so every existing path -- `app.main`, `conftest.py`,
bare CLI alembic -- still falls through to `settings` exactly as before).
11 new tests, built against the real migration chain (old-generation
fixtures are produced by running alembic itself, then hiding the stamp
via a table RENAME) rather than hand-built imitations. Full rationale:
`ENGINEERING_DECISIONS.md` #51.

465/465 full suite passing (454 + 11 new). Ran the live migration this
session: detection matched generation `4b8a822a475b`, un-stamped --
exactly the predicted real-world condition. `--apply` backed up to
`backend/paper_validation.db.backup-20260715T174615Z`, stamped, upgraded
to head (`e3110e6a6b59`), verification passed. The existing `bot_state`
row survived intact; `trades`/`signals`/`strategy_performance_snapshots`
were all empty before and after (no trades recorded yet, so nothing was
at risk). The paper trader process was not running at migration time.

## [Unreleased] - Adaptive platform milestone 7b: Strategy Selection Engine wired into paper trading

`scripts/run_paper.py` now branches its signal-generation step on a new
`settings.USE_STRATEGY_SELECTOR` flag (default `False`). `False` runs the
exact prior code path -- `SignalEngine().generate_signal(...,
use_jade_engine=settings.USE_JADE_ENGINE)` -- byte-for-byte unchanged and
proven so by a regression test. `True` routes through a new
`ConfigurableFallbackSelector` (`app.strategy.selector`) instead:
`USE_JADE_ENGINE` remains a meaningful, explicit operator override
(selects `jade` if `True`); otherwise the selector deterministically
falls back to `legacy` -- no automatic regime-based switching exists yet.
Regime is computed and recorded (console log + `Trade.strategy_config`:
`selection_reason`, `fallback_reason`, `strategy_version`) purely for
observability, verified to never influence the actual selection.

`Strategy` (the Protocol from milestone 1) gains a `version` field --
`"1.0"` on both `LegacyStrategy`/`JadeStrategy`, disclosed as having no
version history yet.

Found and fixed a real test-isolation bug while writing the regression
proof: mixing a module-level `app.*` import with a function-level one in
the same test file can silently bind to two different module instances
(and therefore two different, structurally-identical-but-unequal
dataclasses) if an earlier DB-fixture test in the same pytest session
purged and re-imported `app.*` -- see `ENGINEERING_DECISIONS.md` #50 for
the full mechanism and fix.

21 new tests, 454/454 full suite passing. `DefaultToLegacySelector`
(milestone 4) was deliberately NOT reused for this wiring -- it ignores
`USE_JADE_ENGINE` entirely, which would have silently disabled that
documented operator toggle. **To enable**: set `USE_STRATEGY_SELECTOR=True`
(requires a `run_paper.py` restart, not performed here -- PID 24616 kept
running, untouched, throughout). **To disable**: unset it or leave
`False`. `USE_JADE_ENGINE` works identically either way.

## [Unreleased] - Adaptive platform milestone 7: Risk Engine extensions

`RiskManager.evaluate()` gains `strategy_disabled: bool = False` (rejects
with a clear reason when the originating strategy's latest rolling
snapshot has `is_disabled=True`). `calculate_position_size` gains
`volatility: str | None = None`, scaling risk-percent by
`volatility_risk_scalar()` -- 0.5x in `high_volatility` regimes,
unchanged (1.0x) otherwise, disclosed-not-tuned. Both new parameters are
plain caller-computed values, not lookups performed inside `app.risk`
(verified: no file in `app/risk/` imports `app.database`/`app.portfolio`
anywhere -- this preserves that existing layering, matching how
`circuit_breaker`/`daily_pnl_percent`/etc. are already caller-computed).

Wired live in `scripts/run_paper.py`: `strategy_disabled` via
`StrategyPerformanceEvaluator.is_strategy_disabled()`, `volatility` via
`detect_market_regime()` on the same LTF candles already fetched that
pass -- both fail open (pre-milestone-7-identical behavior) on any error.
`Trade.market_regime` (previously unpopulated) is now set as a direct
byproduct of computing the regime for sizing, which surfaced a real bug
in milestone 6's `market_regime` filter (it compared a string against a
dict; fixed to match the dict's `trend` key). Correlated exposure check
(the 3rd, Low-priority extension named in the architecture doc)
explicitly deferred -- no scenario where multiple strategies are
concurrently active yet. Full rationale: `ENGINEERING_DECISIONS.md` #49.

12 new tests, 441/441 full suite passing. This is the first adaptive-
platform milestone to change actual paper-trading behavior (sizing/
rejection math) rather than being purely additive/observational -- takes
effect only on the paper trader's next restart; Legacy's own signal/
entry/exit logic is untouched, and PID 24616 stayed running throughout.

## [Unreleased] - Adaptive platform milestone 6: rolling performance snapshots + auto-disable

`app.portfolio.performance_snapshots`: `compute_rolling_metrics()` (pure
function) + `StrategyPerformanceEvaluator` (real DB round-trip), computing
win_rate/profit_factor/expectancy/max_drawdown/sharpe/sortino/
recovery_factor over a strategy's most recent closed trades (R-multiple
based, matching decision #47's MAE/MFE convention) and persisting a
`StrategyPerformanceSnapshot` row. Auto-disables (`is_disabled` +
`disabled_reason`) once a strategy has reached the established 20-trade
confidence floor (`experiment_runner.MIN_TRADES_FOR_CONFIDENCE`) with a
rolling profit factor at or below 1.0. Wired as a real producer:
`scripts/run_paper.py` now calls it on every trade close, and now also
populates `strategy_name` on new trades (a deliberate, justified reversal
of milestone 5's scope deferral -- per-strategy metrics are impossible
without it).

Fixed 2 latent bugs, both surfaced by writing the first real inserts into
`strategy_performance_snapshots`: the milestone-2 migration's `computed_at`
server default used Postgres-only `now()` syntax (SQLite has no such
function) instead of this codebase's established `CURRENT_TIMESTAMP`
convention; and `latest_snapshot()`'s ordering was non-deterministic for
two snapshots computed within the same SQLite timestamp tick, fixed with
an `id`-based tie-break. Full rationale: `ENGINEERING_DECISIONS.md` #48.

14 new tests, 430/430 full suite passing. `is_disabled` is computed and
persisted but not yet consulted by `DefaultToLegacySelector` (milestone
4) -- no strategy is actually blocked by this yet.

## [Unreleased] - Adaptive platform milestone 5: MAE/MFE/latency tracking in paper trading

`scripts/run_paper.py` now populates 4 of the 6 Trade columns milestone 2
added: `max_adverse_excursion`/`max_favorable_excursion` (running maximums
in R-multiples of the trade's original risk distance, updated every pass
via the new `TradeTracker.update_excursion()`), `holding_time_seconds`
(computed at close from `closed_at - opened_at`), and `latency_ms`
(wall-clock time around the `ExecutionEngine().execute()` call --
disclosed as measuring the paper engine's own processing time, not real
exchange order latency, since `PaperBroker` never makes a real API
round-trip). `market_regime`/`strategy_name` remain deliberately
unpopulated -- out of this milestone's stated scope (section 7 of
docs/ADAPTIVE_ARCHITECTURE.md names only "MAE/MFE/latency tracking").
6 new tests (`tests/test_portfolio.py`). Full rationale:
`ENGINEERING_DECISIONS.md` #47.

416/416 backend tests passing. Editing `run_paper.py` has no effect on
the already-running paper trader process (PID 24616, Python has no
hot-reload) -- confirmed still running throughout, untouched; this
change only takes effect on a future restart, not performed here.

## [Unreleased] - Adaptive platform milestone 4: Strategy Selection Engine

`app.strategy.selector.StrategySelector` (a `@runtime_checkable
Protocol`, `select(regime, available) -> Strategy`) + its only
implementation, `DefaultToLegacySelector`, which selects `legacy`
unconditionally regardless of regime. Deliberately the least interesting
possible selector: no regime-tagged trade history exists yet, so a real
rule table has nothing to be evidenced against. Gives every downstream
stage a real Strategy Selection stage to integrate with ahead of the
evolution path (`RollingPerformanceSelector`, section 4.3) that depends
on data milestones 5-6 will start producing. 4 new tests. Not yet wired
into any live/paper trading path. Full rationale:
`ENGINEERING_DECISIONS.md` #46.

411/411 backend tests passing. Paper trading (Legacy engine only)
continuously running, untouched.

## [Unreleased] - Adaptive platform milestone 3: Market Regime Detector

`app.regime.regime_detector.detect_market_regime()`: composite
classification (trend: strong_trend/weak_trend/range; volatility:
high/normal/low, percentile-relative not absolute; plus independent
breakout/mean_reversion/liquidity_sweep_environment flags). Built from
objective metrics -- ADX (Wilder's smoothing, new), realized volatility
percentile (new ranking logic over the existing formula), swing
structure via `find_swing_highs`/`find_swing_lows` (reused unmodified),
VWAP and distance-from-MA (new), liquidity sweep frequency via
`detect_liquidity_sweep`/`detect_equal_highs`/`detect_equal_lows`
(reused unmodified). Every classification carries its own raw `metrics`
dict for audit. Disclosed limitations: no true volume-delta (OKX candles
only carry total volume), ADX's DX->ADX step uses a plain trailing
average not exact Wilder smoothing. 20 new tests. Not yet wired into any
live/paper trading path. Full rationale: `ENGINEERING_DECISIONS.md` #45.

407/407 backend tests passing. Paper trading (Legacy engine only)
continuously running, untouched.

## [Unreleased] - Adaptive platform pivot: objective change, design document, Strategy Interface (milestone 1)

### Objective change (operator directive)
From "find one profitable strategy" (Phase 1 scope lock, 2026-07-11) to
"build an adaptive trading system that survives changing market
conditions." `ROADMAP.md` records the reversal explicitly (original text
preserved, struck through, not deleted). `docs/CONTINUOUS_RESEARCH_LOG.md`
archived -- all 6 parameter-search experiments reached documented
conclusions, nothing left unfinished.

### Complete design document
`docs/ADAPTIVE_ARCHITECTURE.md`: architecture diagram + data-flow
contracts, Market Regime Detector design (composite trend/volatility/
event-flag classification, objective metrics), Strategy Interface spec,
Strategy Selection Engine (deterministic `DefaultToLegacySelector`),
Risk Engine extensions, Performance Database schema (new `Trade` columns
+ `strategy_performance_snapshots` table), 8-milestone roadmap.

### Milestone 1: Strategy Interface -- BUILT
`app.strategy.strategy_interface.Strategy` (`Protocol`), `LegacyStrategy`/
`JadeStrategy` adapters (wrap the existing `SignalEngine` integration
point, zero new trading logic -- proven by delegation-equivalence tests),
`AVAILABLE_STRATEGIES` registry. Legacy is now "Strategy A," Jade is
"Strategy B." 7 new tests. See `ENGINEERING_DECISIONS.md` #43.

387/387 backend tests passing. Paper trading (Legacy engine only)
continuously running, untouched -- production behavior unchanged by this
entire pivot so far.

## [Unreleased] - Robustness validation: production candidate NOT PROMOTED, material execution-delay failure found

### Full 7-part robustness suite run against the BTC production candidate
Monte Carlo (2000-iteration bootstrap), randomized execution delay,
slippage stress, fee stress, volatility regimes, market sessions,
leverage analysis. New `scripts/robustness_report.py`,
`scripts/reports/robustness_report.json`, `docs/ROBUSTNESS_REPORT.md`.

### New: `entry_delay_candles` on `BacktestEngine.run()`
Closes a real backtest-fidelity gap -- every backtest this project has
ever run assumed zero-latency instant fills. Opt-in, zero effect unless
set; shifts the fill price to a later candle's close while leaving
stop/target/sizing at their original planned levels. 2 new tests.
`run_backtest()`'s fee_percent/slippage_percent/account_balance are now
also caller-overridable (previously hardcoded) for the stress tests.

### Result: 5 of 7 tests pass, 1 is a non-issue by construction, 1 is a material failure
Monte Carlo (0% chance of a negative outcome across 2000 resamples),
slippage stress, fee stress (both graceful, fail only at unrealistic
extremes), volatility regimes, and sessions (profitable in every session
tested) all PASS. Leverage is a non-issue given this codebase's
risk-based position sizing. **Execution delay is a material failure**:
Profit Factor collapses from 5.24 (no delay) to 0.16 at a single
5-minute delay -- a full sign reversal, not a graceful degradation --
traced to the candidate's very tight average stop distance (0.23% of
price).

### Candidate NOT PROMOTED, per the operator's own stated rule
"Only reject if robustness materially fails" -- this is a material
failure. Does not invalidate the cross-asset/cross-year validation work
(sections 12-14 of `docs/PROFITABILITY_EXPERIMENT_REPORT.md`) -- it's a
latency-fragility finding backtest-only validation could never surface.
Left as an explicit operator decision point (verified low-latency infra,
a wider-stop variant of the same feature family, or hold) rather than
auto-triggering a new strategy search, per this round's own "do not
search for more strategy ideas" instruction.

See `docs/ROBUSTNESS_REPORT.md` and `ENGINEERING_DECISIONS.md` #42.

## [Unreleased] - Third-year validation (2024): BTC candidate confidence revised from "highest" to "high"

Extended BTC's cross-year check to a 3rd independent year (2024).
Baseline itself fails walk-forward in this window (3/5 profitable
periods, degrading) -- a regime-level difficulty, not candidate-specific.
The candidate has HIGHER raw profit and out-of-sample PF than baseline in
2024, but FEWER profitable in-sample periods (2/5 vs 3/5) and also fails
walk-forward. Reported precisely rather than rounded favorably: BTC's
candidate is confirmed in 2 of 3 independent years (2025, 2026), not a
clean 3-for-3 record. This corrects the previous entry's "highest
confidence" framing, which was based on only 2 years. See
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 14.2.

## [Unreleased] - Cross-year validation: BTC candidate confirmed across 2 years, SOL downgraded to moderate confidence

### BTC: confirmed across 2025 AND 2026, out-of-sample both times
Drawdown improves in both windows (1.14%->0.80% in 2026, 1.68%->1.46% in
2025); the candidate additionally FIXES a walk-forward degradation the
Legacy baseline itself has in the 2025 window. Highest-confidence
candidate in this project's history.

### SOL: mixed across years, confidence downgraded (not a new-candidate trigger)
Net Profit/PF still improve in 2025, but drawdown regresses (0.42%->0.65%,
both still small and well under loss limits) and the out-of-sample check
is inconclusive (zero trades in the 2025 holdout period for either
variant). Not treated as a validation failure -- BTC's identical config
remains fully confirmed, and SOL's own 2026 evidence stands -- so no new
SOL-specific candidate search was launched (would risk curve-fitting to
one regressed-but-still-profitable metric in one window).

### Fees/slippage verified already realistic
`run_backtest()`'s hardcoded fee_percent=0.05/slippage_percent=0.02
matches `paper_broker.py`'s real constants exactly -- confirmed applied
to every result in this report, not a separate lenient assumption.

See `docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 14.

## [Unreleased] - Continuous optimization: SOL candidate upgraded, XRP drawdown floor confirmed, ranking now leads with out-of-sample robustness

### Ranking now leads with out-of-sample Profit Factor/Net Profit
Per a second same-day operator directive ("rank every candidate by
out-of-sample robustness"). Gates (walk-forward pass, out-of-sample
profitable) unchanged, still ahead of the score.

### SOL candidate upgraded
`structure_tp_capped_3r_and_premium_discount_filter` replaces plain
`structure_tp` as the recommended SOL candidate -- lower raw profit
($2,238.66 vs $4,292.03 in-sample) but materially better risk-adjusted
profile: drawdown genuinely improves over baseline (1.11%->0.75%, not
just ties), Sharpe 1.08 (highest of any SOL config), out-of-sample
$598.04 with zero losing trades (PF infinite).

### XRP drawdown floor confirmed across 6 independent configs
baseline, 3 exit-cap values, an entry-side filter, and a combo all
produce the IDENTICAL worst-period drawdown (0.7826%) -- strong evidence
this is an irreducible property of one specific trade/period in this
window, not a solvable configuration gap. Further XRP search stopped
after this was established twice independently (once via exit-side caps,
once via an entry-side filter).

### BTC candidate re-evaluated under the same ranking (no new backtest)
Re-analyzed already-collected BTC data under the robustness-first ranking
just applied to SOL: `structure_tp_capped_3r_and_premium_discount_filter`
outranks plain `structure_tp` on BTC too (drawdown 1.14%->0.80%, Sharpe
0.54->0.77, out-of-sample PF 5.77->12.05, despite lower raw profit).
**Both BTC and SOL now share the SAME best candidate config** --
independently derived, not assumed.

See `docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 13.

## [Unreleased] - Cross-asset validation: structure_tp promoted to candidate status for BTC/SOL, no candidate for ETH/XRP

### Ranking reworked to Net Profit / Profit Factor / Max Drawdown / Sharpe
Per operator directive (2026-07-13). Walk-forward-pass and out-of-sample-
profitability kept as gates ahead of the score (not folded in) -- prevents
an unattended candidate-generation loop from ranking a curve-fit in-sample
winner #1. Added Sharpe to `SegmentMetrics` (reuses existing
`performance.calculate_sharpe_ratio`). Fixed a real race condition in the
shared JSON results ledger (parallel invocations, no lock -- added a
portable file-lock mutex).

### 6 new candidate configs (bounded cap-R sweep, no new trading concepts)
`structure_tp_capped_2r/2_5r/4r` + a cap+premium_discount_filter combo, all
reusing the already-implemented `structure_tp_max_r` lever.

### Cross-asset results
- **BTC, SOL**: `use_structure_tp` promoted to documented CANDIDATE status
  (still opt-in, still not a production default) -- both out-of-sample
  confirmed, best result of the whole report on SOL (PF 6.81 in-sample,
  PF 56.45 out-of-sample).
- **XRP**: no candidate -- `structure_tp_capped_3r` ties baseline's
  drawdown exactly rather than beating it (a near-miss, not a regression).
- **ETH**: no candidate -- 5 configs tested at 2026-07-12 all fail
  walk-forward with the SAME signature the Legacy baseline itself
  produces in that window (a regime characteristic, not a strategy
  defect); a second 2025-07-12 window also rejects independently. Not
  pursued further -- would require curve-fitting to these specific
  windows.

See `docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 12 and
`ENGINEERING_DECISIONS.md` #41 for full methodology and diagnosis.

## [Unreleased] - Profitability sprint: rigorous experiment harness, structure_tp clears the keep bar, paper trading started, observability gaps closed

### Started paper trading (Legacy engine, all experimental flags off)
`scripts/run_paper.py --iterations 100000 --interval-seconds 300` against
live OKX BTCUSDT/5m data, 19:29:11. This is Phase 1 gate #3's real
validation run -- the production-approved configuration only.

### Built `scripts/experiment_runner.py` (controlled A/B harness)
One candle fetch anchored to a FIXED `--end-date` (not "now"), reused
across every config compared in an invocation; in-sample vs. held-out
out-of-sample period split enforced structurally; results appended to
`scripts/reports/experiment_results.json`. See ENGINEERING_DECISIONS.md
#37.

### `use_structure_tp` clears the three-metric keep rule (Net Profit,
Profit Factor, Drawdown all improve), confirmed out-of-sample
Net Profit $753.32 -> $2,731.46 (in-sample), Profit Factor 2.81 -> 6.29,
worst-period drawdown 1.16% -> 1.14% (slightly BETTER), walk-forward
PASSED 5/5 with 0 losing streak, out-of-sample confirmed ($611.01, PF
5.77). Supersedes an earlier, less-rigorous same-session ad-hoc verdict
that had rejected it on drawdown -- reconciled in ENGINEERING_DECISIONS.md
#38 (period-boundary sensitivity, same mechanism as #18's BTCUSDT-2025
finding). `ob_fvg_confluence`, `premium_discount_filter`, and the
`structure_tp`+`premium_discount_filter` combination were tested and
REJECTED. Production default unchanged -- see docs/PROFITABILITY_EXPERIMENT_REPORT.md.

### Added `structure_tp_max_r` (opt-in conservative-exit variant)
Caps `use_structure_tp`'s target at a given R ceiling; entry/zone/stop
selection untouched. Diagnostic finding: capping cuts profit roughly in
half but does NOT change worst-period drawdown -- target distance drives
profit here, not drawdown. 3 new tests. See ENGINEERING_DECISIONS.md #39.

### Closed 4 paper-trading observability gaps (additive, nullable columns)
`Signal.rejection_reason`, `Trade.exit_reason`, `Trade.r_multiple`,
`Trade.strategy_config` were computed in-process but never persisted.
Fixed via new nullable columns + new optional method parameters
(backward compatible). Does not affect the already-running paper-trading
process (old code stays in memory; DB schema untouched). See
ENGINEERING_DECISIONS.md #40.

## [Unreleased] - Cross-year validation (2025) on all 4 assets under new tuned defaults: 8 of 9 PASS, 1 real degradation found

### Ran the standard methodology (`--candles 3000 --periods 6 --walk-forward --end-date 2025-07-10`) on all 4 assets
Completing the cross-year picture: BTCUSDT already had a 2025 spot-check
during the parameter sweep itself (using smaller 1500-candle periods,
see the sweep entry) — this round re-ran BTC at the STANDARD scale for
consistency, plus ran ETHUSDT/SOLUSDT/XRPUSDT in 2025 for the first
time ever.

| Asset | 2026 (standard) | 2025 (standard) |
|---|---|---|
| BTCUSDT | PASSED, $3227.08 | **FAILED (degradation)**, $1714.56 — still 6/6 profitable periods |
| ETHUSDT | PASSED, $2851.51 | PASSED, $3090.03 |
| SOLUSDT | PASSED, $5567.94 | PASSED, $4289.78 |
| XRPUSDT | PASSED, $3961.40 | PASSED, $4300.39 |

### Real finding, reported honestly: BTCUSDT 2025 at standard scale FAILS walk-forward
Every one of the 6 periods was individually profitable ($96.18 to
$718.73), so the aggregate/profitable-period criteria all passed. But
the degradation check did NOT: first-half average PnL $422.13, second-
half average PnL $149.40 — the second half retained only 35.4% of the
first half's average, below the 50% retention threshold. This is a
real, measured decline in strategy performance during Apr-Jun 2025
relative to Jan-Mar 2025, not an artifact.

This differs from the sweep's own BTC-2025 spot-check (which used
1500-candle periods and did NOT flag degradation, `docs/parameter_
sweep_report.md` §6) — the discrepancy is itself informative: walk-
forward conclusions can depend on the exact period-granularity chosen,
not just the underlying price data. Neither result is "wrong"; they are
answering slightly different questions (finer-grained vs. coarser-
grained consistency), and both are now recorded rather than only the
more favorable one.

### Decision
This is NOT treated as a reason to revert the new tuned defaults --
BTCUSDT remained net profitable in every single 2025 period at the new
defaults, and 8 of the 9 total asset/year data points at this standard
scale (2026 x4 + 2025 x3, plus this one partial exception) show clean,
undegraded walk-forward passes. It IS treated as a real, disclosed
caveat: the new defaults' robustness on BTCUSDT specifically is weaker
across time than across assets, echoing (at smaller scale) the same
pattern already seen with break-even. Recorded honestly rather than
omitted, consistent with this project's evidence-over-assumption
culture.

### No code changes
Pure validation round. `pytest` re-run for a regression check only
(215/215, unchanged).

## [Unreleased] - Phase 1 gate #2 fully closed under the new tuned defaults (all 4 assets)

### Re-confirmed walk-forward validation on ETHUSDT/SOLUSDT/XRPUSDT
Following the parameter sweep (previous entry), only BTCUSDT had been
re-confirmed at this project's standard reporting scale (`--candles
3000 --periods 6 --walk-forward`) under the new tuned defaults. Ran the
same check on the remaining 3 assets:

| Asset | Old defaults PnL | New (tuned) defaults PnL | Change | Walk-forward |
|---|---|---|---|---|
| BTCUSDT | $1935.35 | $3227.08 | **+66.7%** | PASSED (previous entry) |
| ETHUSDT | $2725.22 | $2851.51 | **+4.6%** | **PASSED** (6/6, 0 losing streak) |
| SOLUSDT | $4198.32 | $5567.94 | **+32.6%** | **PASSED** (6/6, 0 losing streak) |
| XRPUSDT | $2849.89 | $3961.40 | **+39.0%** | **PASSED** (6/6, 0 losing streak) |
| **Total** | **$11708.78** | **$15607.93** | **+33.3%** | **24/24 periods profitable, unanimous** |

All 4 assets: 6/6 periods profitable, 0 losing streaks, no degradation
in any asset (every asset's second-half average PnL was flat-or-better
than its first half). Phase 1 gate #2 (walk-forward validation) is now
**fully closed under the new tuned defaults**, matching how it was
originally closed for the old defaults -- not just spot-checked on one
asset.

### No code changes
Pure validation round -- reused the walk-forward tooling from earlier
entries. `pytest` re-run for a regression check only (215/215,
unchanged).

### Decision
The tuned parameter set (`_RR=2.5`, `_STOP_BUFFER=0.0015`,
`_LOOKBACK=15`, `_IMPULSE_MULT=1.8`) is now validated at the standard
reporting scale across all 4 tested assets, not just BTCUSDT. Combined
with the parameter sweep's own in-sample/out-of-sample/cross-asset/
cross-year evidence, this is the most thoroughly validated state
JadeCap's core strategy has been in this project's history.

## [Unreleased] - Controlled parameter sweep: adopt 4 tuned defaults (Phase 1)

### Added
- `scripts/parameter_sweep.py` (checked in, reproducible): one-at-a-time
  controlled sweep tool for JadeCap's four core-rule constants
  (`entry_model._RR`, `entry_model._STOP_BUFFER`, `order_block._LOOKBACK`,
  `order_block._IMPULSE_MULT`). Monkey-patches the target module constant
  for the duration of each configuration (always restored, even on
  error), fetches candle data once per asset and reuses it across every
  configuration, and reuses `run_backtest.py`'s existing
  `split_into_periods`/`walk_forward_report` rather than reimplementing
  period logic. See `docs/parameter_sweep_report.md` for the full
  methodology and results.
- `BacktestResult` trade dicts gained `stop_loss`, `take_profit`, and
  `risk_per_unit` fields (previously only `entry_price`/`exit_price`/
  `pnl` etc.) -- enables real R-multiple analysis (`pnl / (size *
  risk_per_unit)`) for any caller, not just this sweep. Purely additive,
  no existing caller affected (confirmed: no exact-dict-equality
  assertions existed on trade records).
- `profit_factor()`/`expectancy()`/`average_r()` pure metric functions
  in `parameter_sweep.py`, with 9 new unit tests
  (`test_parameter_sweep.py`).

### Performance finding (discovered mid-sweep, not the main result)
`BacktestEngine`'s walk-forward scan is empirically far worse than
linear in period length: a 3000-candle period took ~88s, a 1500-candle
period ~7s -- a 12x speedup for 2x fewer candles. An initial sweep
attempt using this project's usual 3000-candle periods ran for 80+
minutes with zero visible output (Python's stdout block-buffering when
piped, compounded by the sheer per-configuration cost) before being
killed and redesigned: 1500-candle periods (still ~6 months of data
across 12 periods) plus real-time per-period progress logging
(`flush=True`) brought the full sweep (17 BTC in-sample configs + 4 OOS
validations + cross-asset validation on 3 more assets) down to a
tractable 4049s (~67 minutes).

### Swept and ADOPTED (all 4 candidates cleared every validation gate)
Methodology: in-sample selection (BTCUSDT, 8 of 12 periods) by
robustness (walk-forward pass, meaningful trade count, profitable-period
ratio and average-R both >= baseline) -- NOT highest profit -- then
held-out out-of-sample validation (4 untouched periods), then
cross-asset validation (ETHUSDT/SOLUSDT/XRPUSDT), then (added beyond the
original scope, see rationale below) a cross-YEAR check.

| Parameter | Old | New | In-sample | OOS | Cross-asset (3/3) |
|---|---|---|---|---|---|
| `_RR` | 2.0 | **2.5** | 7/8 profitable, avg-R 0.927 vs 0.643 baseline | 4/4 profitable (was 3/4) | held up on all 3 |
| `_STOP_BUFFER` | 0.001 | **0.0015** | 6/8 profitable, avg-R 0.767 vs 0.643 | 4/4 profitable (was 3/4) | held up on all 3 |
| `_LOOKBACK` | 10 | **15** | 6/8 profitable, avg-R 0.741 vs 0.643 | held up | held up on all 3 |
| `_IMPULSE_MULT` | 1.5 | **1.8** | 6/8 profitable, avg-R 0.791 vs 0.643 | held up | held up on all 3 |

Looser-than-default values (`_LOOKBACK=5`, `_IMPULSE_MULT=1.2`) FAILED
their own in-sample walk-forward check outright -- more signals, but
measurably worse and less consistent. `_RR=1.5` produced 0 trades
(rejected downstream by `RiskManager.MIN_RR=2`, a real, disclosed, not
special-cased result).

### Cross-year check (beyond the operator's original sweep scope)
This project separately found that cross-asset robustness does NOT
guarantee cross-time robustness (break-even's effect flipped sign across
years on BTCUSDT alone -- see `ENGINEERING_DECISIONS.md` #15/#16). Before
finalizing, the combined 4-parameter profile was tested against BTCUSDT
anchored to 2025 instead of 2026: **+33.5% PnL ($1147.45 -> $1531.27),
same profitable-period count (9/12)**. Also confirmed on this project's
standard reporting scale (`--candles 3000 --periods 6 --walk-forward`,
BTCUSDT 2026): **+66.7% PnL ($1935.35 -> $3227.08)**, walk-forward still
PASSED cleanly (0 losing streak, no degradation, second half actually
outperformed the first).

### Changed
- `entry_model._RR`: 2.0 -> 2.5.
- `entry_model._STOP_BUFFER`: 0.001 -> 0.0015.
- `order_block._LOOKBACK`: 10 -> 15.
- `order_block._IMPULSE_MULT`: 1.5 -> 1.8.
- All four constants' inline comments rewritten from "reasonable
  starting default, not yet tuned" to document the tuning evidence
  directly at the constant.
- Two test fixtures (`test_strategy_order_block.py`,
  `test_strategy_signal_engine.py`) extended from 9 quiet candles to 15
  (matching the new `_LOOKBACK`) so their order-block/breaker-block
  detection scenarios still trigger under the stricter constants;
  affected exact-index assertions updated accordingly. Two `rr == 2.0`
  assertions updated to `2.5`.
- `docs/strategy_spec.md`/`docs/strategy_coverage_audit.md`: constants
  no longer described as "untuned defaults".

### Verified
- `pytest backend/tests/` 215/215 passing (206 + 9 new for
  `parameter_sweep.py`'s metric functions).
- Real backtests: in-sample (BTC x4 params x4 values), out-of-sample
  (BTC held-out), cross-asset (ETH/SOL/XRP), cross-year (BTC 2025),
  and a final confirmatory run on the standard 3000-candle/6-period
  scale -- see `docs/parameter_sweep_report.md` for every number.

### Decision
All four candidates ADOPTED as new defaults -- not just reported and
left at the old values -- because all four cleared every validation
gate in the methodology, including a cross-year check that goes beyond
what the operator's original instructions required, added specifically
because this project already has a concrete example (break-even) of a
finding that looked robust across assets but wasn't robust across time.
See `docs/parameter_sweep_report.md` §8 for the full caveats (the
in-sample/cross-asset window is still only ~6 months plus one 2025
spot-check; interaction effects between the four parameters were only
spot-checked, not fully swept).

## [Unreleased] - Resolve confluence-strength spec ambiguity (core JadeCap rule, Phase 1)

### Scope note
Per the operator's continued Phase 1 scope lock: implemented ONLY the
core-rule ambiguity (confluence strength -- already a real, specified
JadeCap rule with a genuine spec-vs-code disagreement). Did NOT
implement equal-highs/equal-lows liquidity detection, since the spec
does not currently define that rule at all (confirmed:
`docs/strategy_spec.md` section 2 has no equal-highs/lows language) --
per the operator's explicit instruction to implement "only if they are
core JadeCap trading rules," adding an entirely new, unspecified rule
is out of scope here and remains documented in `ROADMAP.md` as a
future item requiring a spec decision first.

### Added
- `app.strategy.entry_model.build_entry_model(..., require_full_confluence:
  bool = False)`: when `True`, requires BOTH a matching liquidity sweep
  AND a matching CHOCH (not just one) before producing an entry
  candidate -- the stricter, spec-literal reading of
  `docs/strategy_spec.md` section 6's prose. Default `False` preserves
  the existing (looser, `sweep OR choch`) behavior for every caller.
- `SignalEngine.generate_signal(..., require_full_confluence: bool =
  False)` and `BacktestEngine.run(..., require_full_confluence: bool =
  False)`: threaded straight through, same opt-in pattern as
  `use_breaker_block`/`use_breakeven`/`use_partial_tp`.
- `run_backtest.py --strict-confluence` CLI flag.
- 5 new tests: 4 in `test_strategy_entry_model.py` (rejects sweep-alone,
  rejects choch-alone, accepts both-present, still respects direction
  matching under the strict rule) + 1 integration test in
  `test_strategy_signal_engine.py` proving the parameter threads through
  the REAL detector pipeline (not just synthetic unit-test dicts) using
  an existing real fixture that has sweep but no choch.

### A/B tested across all 4 assets (BTC/ETH/SOL/XRP), 6-month/6-period each
Default (loose, `sweep OR choch`) vs. `--strict-confluence` (`sweep AND
choch`):

| | Baseline trades | Baseline PnL | Strict trades | Strict PnL |
|---|---|---|---|---|
| BTCUSDT | 111 | $1935.35 | 31 | $684.29 |
| ETHUSDT | 106 | $2725.22 | 18 | $548.26 |
| SOLUSDT | 124 | $4198.32 | 37 | $957.74 |
| XRPUSDT | 116 | $2849.89 | 24 | $734.29 |
| **Sum** | **457** | **$11708.78** | **110** | **$2924.58** |

- Trade count: **-75.9%** (457 -> 110).
- Total PnL: **-75.0%** ($11708.78 -> $2924.58) -- almost exactly
  proportional to the trade-count drop.
- Average PnL per trade: $25.62 (baseline) vs. $26.59 (strict) -- a
  **+3.8%** difference, well within noise given the strict mode's
  resulting small per-period sample sizes (as low as 0-2 trades in
  several periods).
- Profitable periods: 24/24 (baseline) vs. 21/24 (strict) -- 3 periods
  flipped non-positive under strict confluence, two of which were
  ZERO-trade periods (not genuine losses) and one a trivial -$7.58 on
  only 2 trades.

### Conclusion: resolved in favor of the existing (looser) implementation
Requiring both sweep AND CHOCH does NOT produce meaningfully
higher-quality trades -- per-trade PnL is statistically indistinguishable
from the looser rule. It only produces far FEWER trades of essentially
the same quality, cutting total realized profit by ~75%. The spec's
ambiguous wording is the thing that needed fixing, not the code:
`docs/strategy_spec.md` section 6 now explicitly states the confluence
rule requires EITHER sweep or CHOCH (matching the implementation), with
this A/B evidence cited directly in the spec text. `require_full_
confluence=True` / `--strict-confluence` remain available as an opt-in
for further research (e.g. as an input to a future parameter sweep) but
are not recommended.

### Verified
- `pytest backend/tests/` 206/206 passing (201 + 5 new).
- Real backtests across 4 assets (table above), not just unit tests.

## [Unreleased] - Circuit breaker auto-reset (production-ready risk controls, Phase 1)

### Scope decision (operator)
Per the operator's Phase 1 scope lock, real-balance integration
(`settings.PLACEHOLDER_ACCOUNT_BALANCE` -> a real, live-queried exchange
balance) is explicitly deferred to Phase 1 gate #4 (Small Live
Validation), not built now -- paper trading has no real capital
regardless, so the fixed placeholder is honest and sufficient until real
capital is actually at risk. Documented in `app/config.py` and
`ROADMAP.md`'s Phase 1 gate table. Instead, this round hardens the
EXISTING risk controls (in scope: "build production-ready risk
controls" from the Phase 1 checklist, without expanding architecture).

### Fixed
- **Circuit breaker had no auto-reset mechanism at all.** Once tripped
  (e.g. a daily loss limit breach), `CircuitBreaker.reset()`'s own
  docstring already flagged this as a known gap ("day-boundary
  scheduling... is a future milestone's responsibility"), and no
  operator-facing reset path existed anywhere (no dashboard endpoint, no
  CLI) -- a trip halted ALL future trading PERMANENTLY until someone
  manually edited the database. For a "production-ready" risk control,
  a limit that can never un-trip itself is a real gap: `MAX_DAILY_LOSS_
  PERCENT`/`MAX_WEEKLY_LOSS_PERCENT` are inherently periodic limits, so
  a trip should clear once the offending period has genuinely rolled
  over.
- `scripts/run_paper.py::_check_drawdown_and_maybe_trip` now auto-resets
  a currently-tripped breaker when a fresh check finds BOTH daily and
  weekly loss limits no longer breached. Works correctly with no new
  date-math of its own: `TradeJournal.generate_daily_report()`/
  `generate_weekly_report()` are already UTC-calendar-day/ISO-calendar-
  week SCOPED, so once a new day/week genuinely begins, "today"/"this
  week"'s realized PnL naturally reflects only the new period -- a trip
  caused by a prior period's loss clears on its own the next time this
  runs. An alert fires on auto-reset too (not just on trip), so an
  operator watching Telegram/Discord sees trading resume, not just that
  it stopped.
- Documented caveat (not hidden): this assumes every trip currently
  routes through this one drawdown-check call site (true today -- it's
  the only `trip()` call site in the codebase). If a future trip reason
  unrelated to drawdown is ever added (e.g. "exchange API failure",
  mentioned as a possibility in `circuit_breaker.py`'s module docstring),
  auto-clearing based on drawdown alone would be wrong and this logic
  would need to become reason-aware first.
- `CircuitBreaker.reset()`'s docstring updated to point at the new
  caller-level auto-reset instead of describing it as an open gap.

### Verified
- `pytest backend/tests/` 201/201 passing (no new unit tests --
  `_check_drawdown_and_maybe_trip` isn't independently pytest-covered,
  matching this repo's existing convention that `run_paper.py` has no
  direct pytest coverage).
- Real-temp-SQLite-DB script exercising all 3 scenarios: (1) a tripped
  breaker with no current breach auto-resets, (2) a real daily-loss
  breach (-1.5% against a 1% limit) trips a fresh breaker, (3) a
  still-breached day does NOT incorrectly auto-reset. All passed.

## [Unreleased] - Phase 1 gate #2 closed: walk-forward validation PASSES on all 4 tested assets

### Ran `--walk-forward` on the remaining 3 assets (BTCUSDT already done, previous entry)
Same 2026/6-month/6-period baseline, no experimental features:

| Asset | Profitable periods | Max losing streak | First-half avg PnL | Second-half avg PnL | Result |
|---|---|---|---|---|---|
| BTCUSDT | 6/6 | 0 | $237.47 | $407.64 | **PASSED** |
| ETHUSDT | 6/6 | 0 | $367.22 | $541.19 | **PASSED** |
| SOLUSDT | 6/6 | 0 | $585.79 | $813.65 | **PASSED** |
| XRPUSDT | 6/6 | 0 | $474.38 | $475.59 | **PASSED** |

24 of 24 periods profitable across all 4 assets, zero losing streaks
anywhere, and every single asset's second half performed flat-or-better
than its first half — not one asset showed any hint of degradation.
This is a unanimous, clean result: JadeCap's baseline strategy (no
experimental features) walk-forward validates across every asset tested
so far.

### No code changes
Pure validation round — reused the walk-forward tooling built in the
previous entry, no new logic. `pytest` re-run for a regression check
only (201/201, unchanged).

### Decision
Phase 1 gate #2 (walk-forward validation) is now considered CLOSED for
the current asset set (BTC/ETH/SOL/XRP, 2026 window). Note this
specifically validates the STRATEGY's baseline behavior, not the mixed/
inconsistent experimental features (break-even, Breaker Block, partial
TP), which remain separately tracked and off by default. See
`ROADMAP.md`'s Phase 1 gate table for the updated status.

## [Unreleased] - Build walk-forward validation (Phase 1 gate #2) — BTCUSDT baseline PASSES

### Scope note
Operator issued a scope-lock directive this round: Phase 1 objective is
narrowly "build, validate, and prove ONE profitable JadeCap automated
trading system," tracked against 4 explicit gates (Backtest ->
Walk-Forward -> Paper Trading -> Small Live Validation). This entry
implements gate #2, the one explicitly-named gate that didn't yet exist
as a distinct, reusable artifact (see `ROADMAP.md`'s new "Phase 1 gate
status" table).

### Added
- `scripts/run_backtest.py::walk_forward_report(results, ...)`:
  evaluates a chronological sequence of period results against explicit,
  deterministic criteria instead of just an aggregate sum:
  - `min_profitable_ratio` (default 0.66): fraction of periods that must
    be profitable.
  - `max_losing_streak` (default 2): max CONSECUTIVE unprofitable
    periods allowed (catches a strategy going cold for several periods
    in a row, which a simple profitable-period count can hide).
  - Degradation check: second-half average PnL must retain at least 50%
    of the first-half average (or, if the first half averaged <= 0, must
    not decline further) — a simple, explicitly-documented heuristic,
    not a formal statistical trend test.
  Returns a dict including a `passed: bool` verdict.
- `run_backtest.py --walk-forward` CLI flag (requires `--periods > 1`):
  prints the report and an explicit PASSED/FAILED verdict.
- 10 new tests in `backend/tests/test_run_backtest.py` — previously ZERO
  pytest coverage existed for any of `scripts/run_backtest.py`'s pure
  functions (including the pre-existing `split_into_periods`, now also
  covered). `scripts/` is a sibling directory to `backend/`, so the test
  file adds it to `sys.path` explicitly.

### Why this is NOT a parameter-refitting walk-forward
`ENGINEERING_DECISIONS.md` decision #8 already documents why: the
strategy has no tunable/fitted parameters yet (`_LOOKBACK`,
`_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`, `BREAKEVEN_TRIGGER_R` are all
fixed, disclosed-as-untuned constants) — a refit-then-test-forward loop
would have nothing to refit. This IS a genuine walk-forward-style check
that performance holds up moving STRICTLY FORWARD through chronological
time (not just independently-shuffled periods), which is what "walk-
forward validation" means as a Phase 1 gate: does the strategy keep
working as you move through it in order, without hidden degradation an
aggregate sum would mask.

### Real result: BTCUSDT 2026 baseline
`--symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6
--walk-forward`:
```
profitable periods     : 6/6 (100.0%, criterion >= 66%)
max losing streak      : 0 (criterion <= 2)
first-half avg PnL     : 237.47
second-half avg PnL    : 407.64
degrading trend        : no
WALK-FORWARD VALIDATION: PASSED
```
Second half of the chronological sequence actually OUTPERFORMED the
first half — the strongest possible walk-forward result (no hint of
decay over the 6-month window). This is the formal Phase 1 gate #2
artifact for JadeCap's baseline strategy.

### Verified
- `pytest backend/tests/` 201/201 passing (191 + 10 new).
- Real CLI run against live OKX data (above) confirms the feature works
  end-to-end, not just in unit tests with synthetic PnL sequences.

### Decision
Phase 1 gate #2 (walk-forward validation) is now built and has produced
its first PASS. Per `ROADMAP.md`, the same check should be run for
ETHUSDT/SOLUSDT/XRPUSDT baselines before considering this gate fully
closed project-wide (currently proven for BTCUSDT only).

## [Unreleased] - Add time-anchored backtesting (`--end-date`); first cross-YEAR validation shows break-even flips sign on BTCUSDT itself

### Added
- `CandleFetcher.fetch_ohlcv_history()` gained an optional `end_time_ms`
  parameter: anchors the fetch to end at a specific past millisecond
  timestamp instead of always "now". Previously there was no way to
  request a specific past window (e.g. "6 months ending July 2025")
  without fetching everything from now back to that window and
  discarding the rest -- for anything more than a few months back this
  would blow past the `max_pages` safety cap long before reaching the
  target. With `end_time_ms`, the first page's `after` cursor is set
  directly to it (OKX's `after=<ts>` already means "strictly older than
  ts"), so pagination starts exactly at the requested end point.
- `scripts/run_backtest.py --end-date YYYY-MM-DD`: uses the above to
  validate the strategy against a specific past year/regime instead of
  only whichever window `--candles` happens to reach back to from today.
  Threaded through both the LTF and HTF fetches so both series are
  anchored to the same end point.
- 1 new test in `test_candle_fetcher.py`
  (`test_fetch_ohlcv_history_end_time_ms_anchors_first_page_instead_of_now`).

### Why this matters
Every out-of-sample test so far (BTC/ETH/SOL/XRP, all previous entries)
covered the SAME calendar window (January-July 2026) -- testing whether
results generalize across ASSETS, never across TIME. Given asset choice
alone already produced a coin-flip spread for break-even (previous
entry), time period was the obvious next axis to test, and there was no
existing way to do it without an expensive full-depth fetch.

### First cross-year validation: BTCUSDT, 6-month/6-period, anchored to end at 2025-07-10 (vs. the existing 2026 window)
`--symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date
2025-07-10`. Baseline: **6 of 6 periods profitable** ($1346.13) -- but
in a visibly different regime: only 67 total trades across 6 periods
(vs. BTC 2026's much higher count), period 1 had only 2 trades. The
strategy finding SOME setups is regime-dependent, not just their
profitability.

| | P1 | P2 | P3 | P4 | P5 | P6 | Sum |
|---|---|---|---|---|---|---|---|
| Baseline (2025) | $61.82 | $387.70 | $338.23 | $182.27 | $247.76 | $128.36 | $1346.14 |
| Break-even (2025) | $61.82 | $431.58 | $338.23 | $124.82 | $226.00 | $138.44 | **$1320.89 (-1.9%)** |
| Breaker Block (2025) | $61.82 | $387.70 | $338.23 | $182.27 | $247.76 | $128.36 | **$1346.14 (0.0%)** |
| Partial TP (2025) | $43.15 | $275.57 | $216.55 | $92.77 | $189.28 | $96.86 | **$914.18 (-32.1%)** |

- **Break-even: flips sign on BTCUSDT itself, same asset, different
  year.** 2026 window: +9.2%. 2025 window: **-1.9%**. This is the
  clearest evidence yet that break-even's effect is regime/time-
  dependent, not just asset-dependent -- even holding the asset constant,
  changing the TIME WINDOW flips the sign. Combined with the 4-asset
  coin-flip result (previous entry), there is now no dimension (asset OR
  time) along which break-even has shown a reliable direction.
  `ENABLE_BREAKEVEN` stays off by default, permanently.
- **Breaker Block: exactly zero effect in the 2025 window** -- the
  detector never altered signal generation in any of the 6 periods
  (identical PnL to baseline in every period). Consistent with the
  original small-sample finding (also zero effect) -- this feature
  appears to only matter in some windows and not others, adding further
  support to "not recommended, inconsistent effect" rather than a
  confident "harmful."
- **Partial TP: reproduces almost exactly, across a different YEAR this
  time, not just a different asset.** -32.6% (BTC 2026) vs. **-32.1%**
  (BTC 2025) -- nearly identical magnitude, all 6 periods worse. This is
  now confirmed robust across 4 assets in one time window AND 2 time
  windows on one asset -- the strongest possible form of evidence
  gathered in this project so far for a single finding.

### Verified
- `pytest backend/tests/` 191/191 passing (190 + 1 new).
- Feasibility-checked before committing to the full run: a 5-candle
  direct fetch anchored to 2025-01-15 returned genuine
  2025-01-14T22:45:00+00:00 -> ...23:45:00+00:00 timestamps, confirming
  `end_time_ms` anchors correctly rather than silently falling back to
  "now".

### Decision
No change to any default. This result promotes "test different years"
over "test more assets" as the higher-ROI next step (see `ROADMAP.md`) --
a single time-anchored asset test just produced a bigger revision to the
break-even story (sign flip on the SAME asset) than three additional
assets combined.

## [Unreleased] - Re-validated all 3 audit findings on XRPUSDT (4th asset): break-even and Breaker Block both flip back to genuinely mixed

### Re-validated on a fourth, independent asset (ROADMAP item #1)
Same methodology again: XRPUSDT/15m, `--candles 3000 --periods 6`, same
January-July 2026 window. Baseline: **6 of 6 periods profitable**
(aggregate $2817.37).

| | P1 | P2 | P3 | P4 | P5 | P6 | Sum |
|---|---|---|---|---|---|---|---|
| Baseline | $382.46 | $530.67 | $477.48 | $303.82 | $504.99 | $617.95 | $2817.37 |
| Break-even | $382.46 | $569.74 | $427.04 | $303.82 | $453.61 | $832.63 | **$2969.31 (+5.4%)** |
| Breaker Block | $382.46 | $573.34 | $477.48 | $303.82 | $504.99 | $617.95 | **$2860.04 (+1.5%)** |
| Partial TP | $250.07 | $400.88 | $296.58 | $166.81 | $358.77 | $536.36 | **$2009.47 (-28.7%)** |

### Four-asset picture (BTCUSDT / ETHUSDT / SOLUSDT / XRPUSDT, all 6-month/6-period)

| Feature | BTC | ETH | SOL | XRP | Verdict |
|---|---|---|---|---|---|
| Break-even | +9.2% | -1.9% | -4.8% | +5.4% | **2 of 4 positive, 2 of 4 negative — genuinely mixed, no reliable direction** |
| Breaker Block | -3.8% | -12.0% | -1.9% | +1.5% | **3 of 4 negative, 1 of 4 positive — mostly negative, no longer unanimous** |
| Partial TP | -32.6% | -35.4% | -29.1% | -28.7% | **Negative on 4 of 4 assets, 24 of 24 periods, zero exceptions** |

- **Break-even: back to genuinely mixed, NOT "more often negative."** The
  prior entry (SOLUSDT) read this as trending negative (2 of 3 assets
  negative). XRPUSDT's +5.4% breaks that trend -- the honest picture with
  4 data points is a coin flip (BTC/XRP positive, ETH/SOL negative), not
  a lean in either direction. This is itself an important, load-bearing
  finding: a 2-of-3 trend that looked meaningful reverted to noise with
  one more data point, which is exactly the risk `ENGINEERING_DECISIONS.md`
  entry #14/#15 warn about -- small sample counts (of assets, not just
  periods) produce apparent trends that don't survive more data.
  `ENABLE_BREAKEVEN` remains off by default; a coin-flip-across-assets
  result is, if anything, a STRONGER case for never defaulting it on
  globally than a consistent-negative result would have been (a
  consistent-negative result would at least be predictable and avoidable
  per-asset; a coin flip means no one has a reliable way to predict which
  assets it'll help without testing each one directly).
- **Breaker Block: mostly negative, no longer unanimous.** XRPUSDT's
  +1.5% is the first positive result for this feature across 4 assets
  (BTC -3.8%, ETH -12.0%, SOL -1.9%, XRP +1.5%). Still 3 of 4 negative,
  so the "not recommended" posture holds, but "negative on every tested
  asset" is no longer an accurate description.
- **Partial TP: negative on all 4 assets, 24 of 24 tested periods worse,
  zero exceptions anywhere.** This remains the single most robust,
  unambiguous finding in the project -- four independent assets, zero
  counterexamples at the period level.

### Verified
- `pytest backend/tests/` 190/190 passing (no code changes -- pure
  research/validation round).

### Decision
No code changes from this finding. `ENABLE_BREAKEVEN` and the backtest
CLI's `--breaker-block`/`--partial-tp` flags all remain opt-in,
off-by-default. Partial TP is now strong enough evidence to consider
actively recommending AGAINST it (beyond just "not proven") in any future
paper/live rollout guidance; break-even and Breaker Block both need
either more assets or a different kind of test (e.g. different years,
different market regimes) before any directional claim beyond "mixed,
asset-specific, no default recommendation" is honest. See `ROADMAP.md`.

## [Unreleased] - Re-validated all 3 audit findings on SOLUSDT (3rd asset): break-even now negative on 2 of 3 assets

### Re-validated on a third, independent asset (ROADMAP item #1)
Same methodology again: SOLUSDT/15m, `--candles 3000 --periods 6`,
same four configurations, same January-July 2026 window. Baseline: **6
of 6 periods profitable** (aggregate $4147.36 -- SOLUSDT's baseline win
rates/PnL ran noticeably higher than BTC/ETH's this period, e.g. period
2 was 100.00% win rate, 18/18 trades).

| | P1 | P2 | P3 | P4 | P5 | P6 | Sum |
|---|---|---|---|---|---|---|---|
| Baseline | $631.31 | $743.90 | $337.93 | $184.68 | $1326.04 | $923.50 | $4147.36 |
| Break-even | $579.84 | $743.90 | $221.15 | $184.68 | $1318.43 | $898.42 | **$3946.42 (-4.8%)** |
| Breaker Block | $553.00 | $743.90 | $337.93 | $184.68 | $1326.04 | $923.50 | **$4069.05 (-1.9%)** |
| Partial TP | $444.40 | $537.32 | $243.88 | $117.23 | $933.46 | $662.50 | **$2938.79 (-29.1%)** |

### Three-asset picture (BTCUSDT / ETHUSDT / SOLUSDT, all 6-month/6-period)

| Feature | BTC | ETH | SOL | Verdict |
|---|---|---|---|---|
| Break-even | +9.2% | -1.9% | -4.8% | **Positive on 1 of 3 assets, negative on 2 of 3** |
| Breaker Block | -3.8% | -12.0% | -1.9% | **Negative on 3 of 3 assets** |
| Partial TP | -32.6% | -35.4% | -29.1% | **Negative on 3 of 3 assets, 18 of 18 periods** |

- **Break-even: now net-negative across assets tested.** This is a
  further, more decisive escalation of the ETHUSDT finding (previous
  entry, same file): what looked like "the most robust of the three
  findings" after two BTCUSDT time windows is now negative on 2 of the 3
  assets it has actually been tested on. SOLUSDT's break-even result
  (0 of 6 periods improved, 4 of 6 worse, 2 unaffected) is not even
  mixed the way ETHUSDT's was -- it is uniformly flat-to-negative.
  Combined picture: break-even helped on BTCUSDT and hurt on both
  ETHUSDT and SOLUSDT. The honest conclusion is no longer "asset-
  dependent, could go either way" -- it is "more often negative than
  positive on the assets tested so far," though 3 assets is still a
  small sample of assets. `ENABLE_BREAKEVEN` remains off by default in
  paper trading; this result is a reason to consider whether it should
  ever become the recommended default, not just a reason for caution
  about ETHUSDT specifically.
- **Breaker Block: negative on all 3 assets now**, magnitude ranging
  -1.9% (SOL) to -12.0% (ETH). Consistent direction, inconsistent size --
  still enough to keep this un-recommended.
- **Partial TP: negative on all 3 assets, 18 of 18 periods tested worse,
  zero exceptions across three independent assets.** This is now the
  single most robust finding in the project -- the mechanistic
  explanation (fixed 2:1 RR + high win rate means partial exits trade
  away more winner upside than they protect from losers) has held on
  every asset tested without a single counterexample period.

### Verified
- `pytest backend/tests/` 190/190 passing (no code changes -- pure
  research/validation round, matching this project's audit discipline).

### Decision
No code changes from this finding. Given break-even is now negative on
a majority of tested assets, the next natural step (see `ROADMAP.md`) is
to test a 4th asset before drawing a final conclusion either way --
2-of-3 could still flip with more data, exactly as the 1-of-2 BTC-only
picture did. `ENABLE_BREAKEVEN` stays off by default either way.

## [Unreleased] - Re-validated all 3 audit findings on ETHUSDT: break-even does NOT generalize, the other two do

### Re-validated on a second, independent asset (ROADMAP item #1)
Same methodology as the BTCUSDT 6-month/6-period re-validation (see the
entry below): ETHUSDT/15m, `--candles 3000 --periods 6`, same four
configurations (baseline, `--breakeven`, `--breaker-block`,
`--partial-tp`), January-July 2026. Baseline: **6 of 6 periods
profitable** (aggregate $2906.18).

| | P1 | P2 | P3 | P4 | P5 | P6 | Sum |
|---|---|---|---|---|---|---|---|
| Baseline | $317.23 | $684.60 | $30.02 | $568.11 | $692.01 | $614.22 | $2906.18 |
| Break-even | $401.77 | $684.60 | -$18.17 | $568.11 | $601.63 | $614.22 | **$2852.16 (-1.9%)** |
| Breaker Block | $308.06 | $667.97 | $30.02 | $568.11 | $611.84 | $372.57 | **$2558.56 (-12.0%)** |
| Partial TP | $269.30 | $507.60 | $0.94 | $392.71 | $463.05 | $245.31 | **$1878.91 (-35.4%)** |

- **Break-even: NOT REPRODUCED — this is the headline finding.**
  BTCUSDT showed +13.5% (small sample) then +9.2% (6-month sample), both
  positive, which is why it was just wired into paper trading (previous
  entry, same file). ETHUSDT's 6-month result is **slightly negative**
  (-1.9%), and the period-by-period picture is genuinely mixed, not
  uniformly bad: P1 improved (+$84.54), P3 flipped from a small win to a
  small loss (-$48.19, win rate 60%->40% — a trade that would have hit
  take-profit instead reversed after 1R and exited near breakeven, which
  is exactly the known risk/mechanism of this feature), P5 got worse
  (-$90.38), and P2/P4/P6 were unaffected (the trigger was never reached
  in those periods). Net: break-even's benefit looks **asset-dependent,
  not universal** — positive on BTCUSDT across two independent samples,
  roughly neutral-to-slightly-negative on ETHUSDT. This does not
  invalidate wiring it into paper trading (it ships off by default,
  opt-in via `ENABLE_BREAKEVEN`, and an operator running ETHUSDT now has
  the evidence to leave it disabled) — but it does mean the earlier
  "reproduced positive on two independent samples" framing overstated
  generality: both of those samples were BTCUSDT. Two independent TIME
  WINDOWS on the same asset is weaker evidence than one time window each
  on two different assets, and this result is exactly why that
  distinction matters.
- **Breaker Block: REPRODUCED negative, more strongly.** BTCUSDT was
  -3.8% (1 of 6 periods affected). ETHUSDT is -12.0% (4 of 6 periods
  affected, all negative, 0 positive). Same direction on both assets now
  — this meaningfully strengthens the "kept optional, not recommended"
  verdict from the prior entry.
- **Partial TP: REPRODUCED negative, again very strongly.** BTCUSDT
  -32.6% (6 of 6 periods worse), ETHUSDT -35.4% (6 of 6 periods worse) —
  12 of 12 periods worse across both assets now, no exceptions. The
  mechanistic explanation (fixed 2:1 RR + high win rate means banking
  half the position at 1R trades away more upside from winners than it
  protects from losers) holds on a second, independent asset.

### Verified
- `pytest backend/tests/` 190/190 passing (no code changes this entry —
  research/validation only, matching this project's "don't add features
  unless the strategy becomes more complete or statistically stronger"
  discipline from the coverage-audit round).

### Decision
No code changes from this finding alone. `ENABLE_BREAKEVEN` stays
off-by-default (already was) — this result is a reason FOR that default,
not a reason to revert the paper-trading wiring itself: an operator
choosing to enable it for BTCUSDT now has stronger evidence for doing so
than for ETHUSDT. See `ROADMAP.md` for the natural follow-up (more
assets, more years) before any of these three findings should be treated
as settled either way.

## [Unreleased] - Wire break-even stop management into paper trading

### Added
- `app.portfolio.trades.TradeTracker.update_stop_loss(trade_id, new_stop_loss)`
  — updates an OPEN trade's `stop_loss`. Raises `ValueError` if the trade
  id doesn't exist, and a separate `ValueError` if it exists but isn't
  currently open (moving the stop on a closed trade would silently do
  nothing useful and almost certainly indicates a caller bug — same
  fail-loudly contract as `close_trade`).
- `app.config.settings.ENABLE_BREAKEVEN` (default `False`) and
  `BREAKEVEN_TRIGGER_R` (default `1.0`) — the latter is now the single
  source of truth for the break-even trigger distance, imported by
  `BacktestEngine`'s own `BREAKEVEN_TRIGGER_R` module constant (was a
  hardcoded `1.0` before this change) so paper trading and backtesting
  always agree on how far price must move before the stop is moved.
- `scripts/run_paper.py::_maybe_move_to_breakeven(current_price)` — for
  every open position whose stop hasn't already reached breakeven,
  computes the 1R trigger from that position's original entry/stop
  distance and moves `stop_loss` to `entry_price` once price reaches it.
  No-ops entirely unless `ENABLE_BREAKEVEN` is `True`. Wired into
  `run_once()` immediately after the existing exit-check step (and
  before the one-trade-open-at-a-time concurrency guard) — deliberately
  AFTER, not before, mirroring `BacktestEngine._simulate_trade`'s
  same-pass conservative rule: a position that reaches the breakeven
  trigger price this same pass is still exit-checked against its OLD
  stop this pass; only a later pass sees the moved stop. `run_once()`'s
  returned summary dict gained a `breakeven_moved: list[int]` field
  (trade ids moved this pass, always `[]` when the feature is disabled).
- Idempotency without a new DB column: "already moved to breakeven" is
  inferred from the stop itself (`stop_loss >= entry_price` for a long,
  `<=` for a short) rather than a new tracked flag — safe because a
  genuine signal's stop can never legitimately start on the profit side
  of its own entry (that would mean zero or negative risk), so that
  state is only ever reached via a prior breakeven move.
- 3 new tests in `backend/tests/test_portfolio.py`
  (`test_trade_tracker_update_stop_loss_moves_stop_on_open_trade`,
  `..._raises_for_unknown_id`, `..._raises_for_closed_trade`).

### Why this matters
Break-even was the only one of the three A/B-tested experimental
execution features (break-even/Breaker Block/partial-TP — see the entry
below) with evidence strong enough to act on: it reproduced a positive
result on two independent backtest samples (+13.5% on a ~31-day sample,
+9.2% on a 6-month sample). Breaker Block (slightly negative) and
partial-TP (negative, reproduced) have no such evidence and are
deliberately NOT wired into paper trading.

### Verified
- `pytest backend/tests/` 190/190 passing (187 + 3 new).
- A real-temp-SQLite-DB script (not pytest — matches this repo's existing
  convention that `run_paper.py` has no direct pytest coverage, since it
  needs a live network candle feed) exercised: a long position below its
  trigger (no move), at its trigger (stop moves to entry), and a later
  pass at a higher price (correctly skipped — already at breakeven, no
  duplicate write); a short position at its trigger (stop moves to
  entry); and `ENABLE_BREAKEVEN=False` (no move regardless of price). All
  passed.

### Decision
Ship as opt-in (`ENABLE_BREAKEVEN`, mirroring `ENABLE_TELEGRAM_ALERTS`'s
existing pattern), off by default, so a live paper-trading run's behavior
never changes silently. See `ROADMAP.md` and `ENGINEERING_DECISIONS.md`
for the ongoing validation plan (ETHUSDT, more assets, more years) before
this or any other experimental feature would ever be considered for live
trading.

## [Unreleased] - Fixed HTF over-fetch bug; re-validated all 3 audit findings across 6 months of real regimes

### Fixed
- **`scripts/run_backtest.py` requested the SAME candle COUNT for both
  the LTF and HTF fetch**, discovered while attempting a deep
  multi-period run: requesting 18000 candles at `15m` (to cover ~187
  days across 6 periods) also requested 18000 candles at `4h` for
  HTF -- ~8.2 years of history, causing the HTF fetch to page through
  vastly more data than needed and hang for many minutes (had to be
  killed). Added `app.data.candle_fetcher.timeframe_to_timedelta()` and
  `scripts/run_backtest.py::htf_candle_count_for_span()`, which sizes
  the HTF request off the REAL TIME SPAN the LTF request covers (with a
  300-candle floor so `detect_htf_bias()` never starves of history) --
  confirmed directly: the exact same buggy scenario now requests 1125
  HTF candles (~187 days, matching the LTF span) instead of 18000
  (~8.2 years).

### Verified
- `pytest backend/tests/` 187/187 passing (2 new: `timeframe_to_timedelta`
  unit conversion + bad-format error tests).

### Re-validated all 3 audit findings on a much larger, more diverse sample
- Using the fix above, re-ran all four configurations (baseline,
  `--breakeven`, `--breaker-block`, `--partial-tp`) on BTCUSDT/15m
  across 6 periods of 3000 candles each (~187 days total, January
  through July 2026 -- genuinely different market conditions per period:
  win rates ranged 62.5%-90.48%, trade counts 8-28, unlike the single
  ~31-day window every prior result in this project rested on).
  Baseline itself: **6 of 6 periods profitable** (aggregate $1905.29).

  | | P1 | P2 | P3 | P4 | P5 | P6 | Sum |
  |---|---|---|---|---|---|---|---|
  | Baseline | $433.51 | $208.77 | $70.14 | $567.92 | $162.77 | $462.18 | $1905.29 |
  | Break-even | $383.30 | $235.08 | $96.52 | $596.91 | $274.69 | $493.95 | **$2080.45 (+9.2%)** |
  | Breaker Block | (same) | (same) | (same) | $496.11 | (same) | (same) | **$1833.48 (-3.8%)** |
  | Partial TP | $282.50 | $98.83 | $42.89 | $404.57 | $157.88 | $297.21 | **$1283.87 (-32.6%)** |

  - **Break-even: CONFIRMED positive** (+9.2% here vs. +13.5% on the
    smaller sample -- same direction, reproducible across two
    independent, non-overlapping datasets). 5 of 6 periods individually
    improved.
  - **Partial TP: CONFIRMED negative** (-32.6% here vs. -31.4% on the
    smaller sample -- also reproducible). Every period got worse; the
    earlier mechanistic explanation (fixed 2:1 RR + high win rate means
    partial exits trade away winner upside without protecting losers)
    holds up on the larger sample too.
  - **Breaker Block: REVISED from neutral to slightly negative.** The
    smaller sample showed literally zero effect (the 2 confirmed
    signal-level differences both happened to fall inside an
    already-open trade's window). On this larger sample, it DID get a
    real chance to matter once (period 4: win rate 90.48% -> 85.71%,
    PnL $567.92 -> $496.11) -- and the effect was negative. Still only 1
    of 6 periods affected, so "proven harmful" would overstate this, but
    "neutral" no longer accurately describes it either -- the evidence
    now leans negative, not neutral. This is exactly why the out-of-
    sample tooling and the "re-test at larger scale" roadmap item exist:
    the smaller sample's conclusion was real but incomplete.

### Why this matters
- All three audit findings from the previous session rested on a SINGLE
  ~31-day window. Re-testing on a 6x larger, genuinely more varied
  sample reproduced two of the three conclusions almost exactly
  (break-even positive, partial-TP negative) and meaningfully refined
  the third (Breaker Block neutral -> slightly negative). This is
  itself validation of the out-of-sample methodology: results that
  reproduce across independent samples are real; one that changes with
  more data is exactly the kind of thing more data is supposed to
  reveal.

## [Unreleased] - Partial take-profit wired and A/B tested (measured NEGATIVE, kept optional)

### Added
- `BacktestEngine`'s `_simulate_trade()` now supports a two-leg exit: when
  `use_partial_tp=True` (opt-in, default `False`), `PARTIAL_TP_PORTION`
  (50%) of the position closes once price moves `PARTIAL_TP_TRIGGER_R`
  (1R) in favor, at its own price/fee; the remaining size continues to
  the ORIGINAL stop_loss/take_profit. Ordering within a candle:
  stop-loss first (worst case, unchanged), THEN the partial-TP trigger
  (if not yet triggered), THEN take_profit -- deliberately in that order
  because the partial trigger price is always closer to entry than
  take_profit for any RR > 1, so a candle that reaches take_profit
  necessarily passed through the partial trigger too; checking it first
  lets a single candle that jumps straight to take_profit still
  correctly bank the partial leg at its own nearer price.
  `use_partial_tp` is completely independent of `use_breakeven` (not
  combined in this round's test -- one variable at a time). Trade
  records gain `partial_tp_triggered`/`partial_tp_exit_price`/
  `partial_tp_pnl`. Threaded through `BacktestEngine.run(...,
  use_partial_tp=False)` and `scripts/run_backtest.py --partial-tp`, same
  pattern as `--breakeven`/`--breaker-block`.
- This is the last of the three HIGH-priority `docs/strategy_coverage_audit.md`
  findings (`OrderManager.handle_partial_tp()` existed and was
  unit-tested since Milestone 3 but was never called from any trade
  path) -- all three are now wired and A/B tested.

### Verified
- `pytest backend/tests/` 185/185 passing (5 new: disabled-by-default
  contrast, enabled locks in profit then still reaches the real
  take_profit, enabled protects against a later full loss, the
  same-candle-jump-still-banks-the-partial-leg-first proof, short-
  direction mirror).
- Real end-to-end A/B, live OKX data, the IDENTICAL 6 out-of-sample
  periods used for break-even and Breaker Block (BTCUSDT/ETHUSDT 15m, 3
  periods each): **partial-TP reduced total PnL in EVERY SINGLE
  period tested, 6 of 6, no exceptions.**

  | | BTCUSDT P1 | P2 | P3 | ETHUSDT P1 | P2 | P3 |
  |---|---|---|---|---|---|---|
  | Without | -$48.64 | +$165.81 | +$184.62 | +$148.51 | +$60.04 | +$308.75 |
  | With | -$56.43 | +$111.63 | +$135.58 | +$106.83 | +$24.85 | +$239.81 |

  Aggregate: **$819.09 -> $562.27 (-31.4%)**. Win rate and
  profitable/unprofitable classification were UNCHANGED in every period
  (partial-TP doesn't change whether a trade ultimately wins or loses,
  only how much) -- it purely reduced magnitude.

### Why this makes mechanistic sense (not a fluke, a real strategy-shape interaction)
- This strategy has a fixed `_RR = 2.0` (`entry_model.py`) and, in this
  sample, a high win rate (many trades already run the full distance to
  the real take_profit). Locking in half the position at 1R trades away
  half of a 2R winner's upside on every one of those winners, while
  rarely helping the losers (a trade heading to a full stop-loss loss
  usually never reaches +1R in the first place, so there's nothing to
  partially lock in). In a strategy that mostly wins and mostly wins big
  relative to its stop, "let it run" structurally beats "cash in early."
  A strategy with a lower win rate or a smaller RR target might show the
  opposite result -- this is sample- and strategy-shape-dependent, not a
  universal verdict on partial take-profit as a technique.

### Decision: kept opt-in, evidence points against enabling it for THIS strategy
- Per operator instruction ("if it does not improve performance, document
  the evidence and keep it optional"): this is the clearest negative
  result of the three audit items tested this session -- not neutral
  (Breaker Block) or positive (break-even), but consistently worse across
  every single tested period. `--partial-tp` remains available (in case
  the strategy's RR/win-rate profile changes later, or for a genuinely
  different strategy plugged in behind the same interface), but is
  actively NOT recommended for the current strategy shape, is NOT the
  default, and is NOT wired into `scripts/run_paper.py`.

## [Unreleased] - Breaker Block wired into signal generation (A/B tested, no measurable backtest effect -- kept optional)

### Added
- `detect_breaker_block()` (`app/strategy/order_block.py`) now returns
  `retest_index` (the candle that confirmed the flip) alongside the
  existing `index` (the original order block's base candle) -- needed
  for correct zone-mitigation-window checking, same reasoning as
  `detect_order_block()`'s existing `impulse_index`.
- `build_entry_model()` gains an optional 6th parameter `breaker_block`
  (default `None`, every existing call site unaffected): a second zone
  candidate alongside `order_block`, competing via the same "most recent
  index wins" rule already governing FVG vs. OB.
- `SignalEngine.generate_signal(..., use_breaker_block=False)` (opt-in):
  when `True`, detects an unmitigated breaker block and offers it to
  `build_entry_model`. `detect_breaker_block` has existed and been
  unit-tested since Milestone 2 but was never called from signal
  generation until now (see `docs/strategy_coverage_audit.md`).
  Threaded through `BacktestEngine.run(..., use_breaker_block=False)`
  and `scripts/run_backtest.py --breaker-block`, same opt-in pattern as
  `--breakeven`.

### Verified
- `pytest backend/tests/` 180/180 passing (6 new: breaker-block-wins-
  zone-selection unit tests in `test_strategy_entry_model.py`, and a
  real end-to-end contrast pair in `test_strategy_signal_engine.py` --
  a setup whose ONLY viable zone is a breaker block produces no signal
  with the default `False`, and a real short signal with `True`).
- Real end-to-end A/B, live OKX data, IDENTICAL 6 periods used for the
  break-even comparison (BTCUSDT/ETHUSDT 15m, 3 periods each): **zero
  difference** in trade count, PnL, or win rate in every single period,
  with or without `--breaker-block`.
- Diagnosed WHY (not just accepted the null result): a raw walk-forward
  scan of the real BTCUSDT/15m/1000-candle sample found breaker blocks
  ARE detected regularly (124 of 970 steps had a raw breaker-block
  candidate, 29 unmitigated) and CAN change signal-level output (2 real
  signal-level differences found when re-evaluating every step with the
  flag on vs. off, independent of the backtest engine's concurrency
  guard). But in the actual walk-forward backtest, both differing steps
  fell within an already-open trade's window (`BacktestEngine`'s
  one-trade-at-a-time guard skips signal generation while a trade is
  open), so neither ever reached the point of opening a real trade.

### Decision: kept opt-in, not proven to improve performance in this sample
- Per operator instruction ("if it does not improve performance, document
  the evidence and keep it optional"): the feature works correctly
  (proven at the signal level) but produced **zero measurable backtest
  effect** across all 6 tested periods. This is NOT evidence the feature
  is broken or harmful -- it's evidence that, in this specific sample, it
  never got the chance to matter. A different/larger sample, or a period
  with more idle time between trades, could show a real difference in
  either direction. `--breaker-block` remains available and validated
  for the same A/B methodology going forward, but is NOT wired into
  `scripts/run_paper.py` and is NOT made the default.

## [Unreleased] - Strategy coverage audit + break-even stop management (A/B tested)

### Added
- `docs/strategy_coverage_audit.md`: full rule-by-rule matrix of every
  JadeCap rule from `docs/architecture.md`'s six-layer design against its
  actual implementation status, test coverage, missing logic, assumptions,
  ambiguity, and priority. Found three HIGH-priority items sharing the
  same shape -- real logic that already exists, is unit-tested in
  isolation, and is completely disconnected from the live decision loop:
  breaker-block detection (never called from `SignalEngine`), break-even
  stop management, and partial take-profit (`OrderManager.move_to_breakeven`/
  `handle_partial_tp`, never called anywhere outside their own module).
- `BacktestEngine.run(..., use_breakeven=False)` (opt-in, default
  preserves exact prior behavior): once a trade has moved
  `BREAKEVEN_TRIGGER_R` (1R, a disclosed-as-untuned default) in favor, its
  stop moves to entry. Conservative same-candle ordering: a candle that
  touches both the original stop and the breakeven trigger level in the
  same bar always resolves as a normal stop-out, never an optimistic
  "triggered then saved" outcome (matches this method's existing
  SL-before-TP conservative assumption). Trade records gain a
  `breakeven_triggered` field. `scripts/run_backtest.py --breakeven` wires
  it up for real A/B comparisons.

### Verified
- `pytest backend/tests/` 174/174 passing (5 new: enabled vs. disabled
  contrast on an identical pullback-to-entry candle, breakeven not
  blocking a later real take-profit, the conservative same-candle-
  ordering proof, and a short-direction mirror). Full suite unaffected
  by the opt-in default.
- Real end-to-end A/B comparison, live OKX data, same 3-period splits
  used in the prior commit's out-of-sample validation (identical seed
  data, only `--breakeven` toggled):

  | | BTCUSDT/15m P1 | P2 | P3 | ETHUSDT/15m P1 | P2 | P3 |
  |---|---|---|---|---|---|---|
  | Without | -$48.64 (50%) | +$165.81 (83%) | +$184.62 (80%) | +$148.51 (100%) | +$60.04 (60%) | +$308.75 (90%) |
  | With | **+$67.48 (58%)** | +$165.81 (83%) | +$150.88 (60%) | +$148.51 (100%) | +$60.04 (60%) | **+$336.78 (90%)** |

  Aggregate across all 6 independent periods: **$819.09 -> $929.49
  (+13.5%)**, profitable periods **5/6 -> 6/6** (the one losing period,
  BTCUSDT P1, flipped to profitable). Effect is genuinely mixed, not
  uniformly positive -- BTCUSDT P3 got worse (some winners that reached
  full take-profit anyway got cut short at breakeven on the way there);
  3 of 6 periods were completely unaffected (no trade ever pulled back
  through the breakeven level after triggering). Net effect: reduces the
  RANGE of outcomes more than it reduces the total -- protects the worst
  period more than it costs the best one, which is the expected,
  textbook effect of break-even stop management.

### Decision: kept opt-in, not made the default (yet)
- 6 total periods is still a small sample to declare a permanent behavior
  change, even though the direction is consistently positive-to-neutral
  (never made a previously-profitable period unprofitable, only ever
  traded some upside in the best period for eliminating the only loss).
  `--breakeven` is validated and available for the same
  out-of-sample-periods methodology going forward; NOT wired into
  `scripts/run_paper.py`/live paper trading in this round -- per operator
  instruction, no further features were added past this single validated
  component. Flagged in HANDOFF.md as a strong candidate for the next
  decision point (either promote to default after more periods confirm
  the pattern, or wire into paper trading as opt-in first).

## [Unreleased] - Backtest quality: multi-period out-of-sample validation

### Added
- `scripts/run_backtest.py --periods N`: splits the fetched history into
  `N` equal, non-overlapping chronological chunks and runs the backtest
  independently on each (fresh account balance, no shared trades/equity
  state between periods) instead of one continuous run. `split_into_periods()`
  is a pure function (every candle used exactly once, no overlap, no
  gaps -- verified directly). Deliberately NOT a walk-forward with a
  rolling parameter-fit window -- this strategy has no tunable/fitted
  parameters to fit against a training window (see entry_model.py's
  documented "reasonable default, not tuned" constants). Total candles
  fetched is `--candles * --periods`. `--periods 1` (default) is
  byte-for-byte the prior single-run behavior. Prints a per-period
  summary plus an aggregate, and writes a separate report/CSV per period
  (`<stem>_period<N>.md/.csv`) when `--periods > 1`.

### Why this matters (addresses last commit's own honest caveat)
- The previous commit's before/after comparison was three separate
  single-continuous-window samples -- encouraging, but explicitly flagged
  as not sufficient to call the strategy validated (no genuinely disjoint-
  period check). This closes that gap directly: real, disjoint-period
  results now show a MORE NUANCED picture than the single continuous
  samples suggested -- BTCUSDT/15m: 2 of 3 independent periods profitable
  (period 1: 12 trades/50% win rate/-$48.64; period 2: 6 trades/83.33%/
  +$165.81; period 3: 10 trades/80.00%/+$184.62). ETHUSDT/15m: 3 of 3
  periods profitable (4 trades/100%/+$148.51; 5 trades/60%/+$60.04; 10
  trades/90%/+$308.75). 5 of 6 independent periods profitable across two
  assets, with the one losing period a small loss, not a blowup -- more
  genuinely informative than either "it's definitely broken" or "it's
  definitely proven," and a real, reusable tool for future strategy
  changes to be checked against the same way.

### Still not sufficient for a "validated" claim (updated caveat)
- Per-period trade counts (4-12) are even smaller than the single-window
  samples, so per-period win-rate confidence intervals are wide. All
  three periods for both assets fall within the same ~31-day calendar
  span (this run's `--candles 3000` history depth) -- genuinely disjoint
  in trade sequence/walk-forward state, but not a different market
  regime/year. A meaningfully stronger claim would need periods spanning
  materially different market conditions (trending vs. ranging, high vs.
  low volatility), which requires either a longer total history fetch or
  running this tool again once more calendar time has passed.

## [Unreleased] - Strategy accuracy: fixed duplicate signal generation on already-tested zones

### Fixed
- **`SignalEngine` could generate near-identical duplicate signals on the
  same FVG/order-block zone, back-to-back.** `detect_fair_value_gap`/
  `detect_order_block` report a zone for as long as it remains anywhere
  in the given candle window, with no awareness of whether price has
  already traded back into it. Discovered by analyzing a real deep
  backtest (made possible by the prior pagination fix): in a 28-trade,
  31-day BTCUSDT/15m sample, 5 pairs (10 of 28 trades, ~36%) were EXACT
  duplicate re-entries of a setup that had just been stopped out of --
  the same still-visible zone kept re-qualifying as "the most recent
  zone" on the next walk-forward step, immediately after a failed
  attempt at the identical price level.

### Added
- `app.strategy.utils.is_zone_mitigated(candles, start_index, top, bottom)`:
  true if any candle strictly between a zone's formation and the current
  (most recent, excluded) candle has overlapped it -- standard SMC
  "mitigation" concept. The current/last candle is deliberately excluded
  since it touching a zone as part of triggering a signal (e.g. a sweep
  wick tapping straight into a nearby FVG in the same candle) is the
  setup itself, not a disqualifying prior retest.
- `SignalEngine.generate_signal()` now excludes any FVG/order-block zone
  already mitigated before selecting an entry zone. Deliberately
  implemented at the orchestration layer, NOT inside `detect_fair_value_gap`/
  `detect_order_block` themselves, which stay unchanged/mitigation-unaware
  -- `detect_breaker_block` depends on `detect_order_block` returning the
  raw, un-filtered zone to do its own closed-through/retest analysis on
  top of it.
- `detect_order_block()` now also returns `impulse_index` (the confirming
  impulse candle's index, separate from `index`, the base/zone candle) --
  needed so mitigation checking starts AFTER the impulse, not after the
  base candle (whose own confirming impulse routinely overlaps it, which
  would make every fresh order block look immediately mitigated by its
  own confirming move).

### Verified
- `pytest backend/tests/` 169/169 passing (12 new: direct unit-level
  proofs of `is_zone_mitigated`'s boundary rules, including the
  last-candle exclusion; an end-to-end regression test reproducing the
  exact real-world duplicate-signal pattern -- a fresh zone signals once,
  then price retesting that same zone correctly produces no second
  signal). 3 existing test fixtures (shared between
  `test_strategy_signal_engine.py`/`test_backtest_engine.py`) needed a
  small fix: their "confluence" zigzag pattern's own oscillation was
  legitimately retracing through every FVG it created internally (a real,
  correct mitigation detection exposing that those fixtures weren't
  actually testing a genuinely fresh setup) -- a trailing unmitigated leg
  was appended to each. Full suite re-run 2x with no flakiness.
- Real end-to-end, three independent live-data samples (before vs. after
  this fix, same 3000-candle deep-history fetch as the pagination fix's
  verification): BTCUSDT/15m flipped from 28 trades/25% win rate/-$577.82
  to 28 trades/75% win rate/+$462.18 (max drawdown 5.78% -> 2.04%);
  ETHUSDT/15m (new sample): 19 trades/89.47% win rate/+$614.22/0.45% max
  drawdown; BTCUSDT/5m (new sample): 10 trades/90.00% win rate/+$257.83/
  0.40% max drawdown. Consistent, large, positive shift across symbol AND
  timeframe -- not a single lucky sample.

### Honest caveat (not proof of a profitable strategy yet)
- Three same-period, overlapping-regime samples are encouraging but NOT
  sufficient to claim the strategy is validated: no out-of-sample/
  walk-forward split has been done, trade counts (10-28) are small enough
  that win-rate confidence intervals are wide, and BTC/ETH move highly
  correlated with each other so the two 15m samples are not fully
  independent evidence. This is a real, large, and mechanistically
  well-understood improvement (a duplicate-trade bug is gone), not yet a
  claim that this strategy is production-ready. Next validation step
  flagged in HANDOFF.md.

## [Unreleased] - Backtest data depth: fixed OKX pagination bug, real deep history now fetchable

### Fixed
- **`CandleFetcher.fetch_ohlcv`'s `since` parameter was wired to OKX's
  `before` query param**, which (confirmed empirically, not assumed from
  docs) returns candles NEWER than the given timestamp -- the exact
  opposite of what backward pagination into history needs. `since` could
  therefore never deepen a historical sample; every caller requesting
  more than one page silently got a shallower sample instead (documented
  for a long time as a known limitation across `run_backtest.py`'s module
  docstring and multiple HANDOFF.md entries, but never actually root-
  caused/fixed until now). `since` now correctly maps to `after`.

### Added
- `CandleFetcher.fetch_ohlcv_history(symbol, timeframe, total_candles, ...)`:
  real deep-history pagination against OKX's separate
  `/market/history-candles` endpoint (same request/response shape as
  `/market/candles`, but confirmed empirically to page back reliably for
  months of data -- `/market/candles` itself is hard-capped at ~1440
  total candles regardless of pagination, confirmed empirically by
  fetching until an empty page). Paces requests between pages, caps
  total HTTP calls independently via `max_pages` (safety net against a
  pagination bug becoming a runaway loop), and returns fewer than
  requested (not an error) if OKX's actual history genuinely runs out.
- `scripts/run_backtest.py` now uses `fetch_ohlcv_history()` instead of a
  single 300-candle-capped call. `DEFAULT_CANDLE_COUNT` raised from 900
  (a single-page-call artifact) to 5000, now that fetching that much is
  real. A shortfall (OKX genuinely has less history than requested) is
  now a clear, honest note rather than a silent single-page cap.

### Why this matters (profitability, not just plumbing)
- Every prior backtest run in this project's history was capped at ~300
  candles (~1 day at 5m) -- far too shallow to say anything statistically
  meaningful about whether the strategy has real edge. This was the
  single largest blocker to ever answering that question. First deep run
  after this fix (BTCUSDT/15m, 3000 candles / ~31 days, real OKX data):
  28 real trades, 25% win rate, -$577.82 total PnL on a $10,000 start --
  a real, previously-unobtainable signal that the strategy's current
  parameters are not yet profitable over this sample. This is not itself
  a strategy fix; it's the instrument that now makes strategy iteration
  possible at all.

### Verified
- `pytest backend/tests/` 162/162 passing (12 new in `test_candle_fetcher.py`,
  the first-ever test coverage for this module: pure symbol/timeframe
  conversion, `fetch_ohlcv_history`'s multi-page assembly/ordering/dedup,
  early-stop when OKX's history genuinely runs out, the `max_pages` safety
  cap, and a regression pin for the exact `since`/`after` bug fixed here).
  Full suite re-run 2x with no flakiness.
- Real end-to-end against live OKX data (no mocks): `run_backtest.py
  --symbol BTCUSDT --timeframe 15m --candles 3000` fetched genuinely 3000
  LTF + 3000 HTF candles (previously would have silently capped at 300)
  and produced the 28-trade result above.

## [Unreleased] - Dashboard: /dashboard/signals now real -- generated signals actually persisted

### Fixed
- **No process ever persisted a generated signal to the `signals` table**,
  even though `app.database.models.Signal`'s `status` column has always
  documented a pending/approved/rejected/executed convention, and
  `TradeSignal`'s own docstring says it "matches the signals DB table" --
  the write path was simply never built. `/dashboard/signals` returned a
  hardcoded `{signals: [], note: "not yet wired..."}`.

### Added
- `app.portfolio.signals.SignalTracker` (new module, mirrors
  `TradeTracker`'s exact pattern): `record_signal()`, `update_signal_status()`
  (raises `ValueError` for an unknown id, same contract as
  `TradeTracker.close_trade()`), `get_recent_signals(limit=20)`.
- `scripts/run_paper.py`'s `run_once()` now persists every genuinely
  generated `TradeSignal` as soon as it's produced (status "pending"),
  then updates that status to "rejected" (risk-declined), "approved" (risk
  passed), or "executed" (order placed) as it moves through the pipeline
  -- best-effort throughout (a broken persistence call is a loud WARNING,
  never a pipeline-blocking error, same pattern as the existing
  trades_today/daily_pnl_percent best-effort queries). No existing
  `run_once()` summary field/semantic changes.
- `/dashboard/signals` now returns the real ~20 most recent signals
  (newest first) via `SignalTracker`.
- Frontend: `Signal`/updated `SignalsResponse` types, `SignalsPanel` now
  renders the real list (mirrors `LogsPanel`'s pattern) instead of a
  hardcoded "Not live yet" badge + count.

### Verified
- `pytest backend/tests/` 150/150 passing (9 new: `SignalTracker`
  record/query round-trip, status transitions, unknown-id rejection,
  newest-first + limit ordering; `/dashboard/signals` fresh-DB empty state
  and a real seeded signal reflecting its real status through the live
  endpoint). Full suite re-run 2x with no flakiness.
- Real end-to-end, twice: drove the ACTUAL `run_paper.run_once()` (not
  just `SignalTracker` in isolation) against a real temp SQLite DB with a
  controlled fake signal -- (1) an approved signal persists through
  pending -> approved -> executed, matching the resulting trade, and (2)
  a signal with `rr` below `MIN_RR` persists through pending -> rejected,
  matching `RiskManager`'s real rejection reason.

## [Unreleased] - Dashboard: /dashboard/bias now real, live-computed
## [Unreleased] - Dashboard: /dashboard/bias now real, live-computed

### Fixed
- **`/dashboard/bias` hardcoded `"neutral"`/`"neutral"` with a "not yet
  wired" note.** Now fetches real OKX HTF/LTF candles (read-only, no API
  key, the same live-fetch pattern `scripts/run_paper.py`/
  `run_backtest.py` already use) and computes `htf_bias` via the real
  `detect_htf_bias()` -- the exact same function the live strategy's bias
  gate uses. A live fetch failure degrades gracefully (returns
  `"neutral"`/`"neutral"` with a note describing the failure) instead of
  500ing the dashboard.
- Removed a hardcoded "Not live yet" badge from the frontend `BiasCard`
  (same stale badge already removed from `RiskStatusPanel` in the
  previous commit), now misleading since the data is live.

### Design note (not a bug, documented for the next engineer)
- **`ltf_bias` has no defined meaning in the real strategy design** --
  `docs/strategy_spec.md`/`signal_engine.py` only ever call
  `detect_htf_bias()` on HTF candles; LTF candles feed the
  sweep/CHoCH/FVG/order-block detectors instead, not a bias concept. This
  API field predates that design. Rather than fabricate a number, this
  reuses the same real, generic structural-bias algorithm on the LTF
  series -- a genuine "recent LTF swing-structure bias" reading, but a
  distinct concept from the strategy's real HTF bias gate. Flagged in
  HANDOFF.md as worth an explicit design confirmation if this field's
  meaning matters downstream (e.g. is ever consumed by an actual trading
  decision rather than just displayed).

### Verified
- `pytest backend/tests/` 145/145 passing (2 new: HTF/LTF bias computed
  independently from two genuinely different fetched series -- proving
  `ltf_bias` isn't just `htf_bias` duplicated -- and graceful degradation
  on a simulated fetch failure). Full suite re-run 2x with no flakiness.
- Real end-to-end: booted the actual FastAPI app, hit the live
  `/dashboard/bias` endpoint through `TestClient` against REAL OKX data
  (no mocks) -- returned `{"symbol": "BTCUSDT", "htf_bias": "neutral",
  "ltf_bias": "neutral", "note": ""}` (neutral is a valid real result in
  today's flat market, not an error -- consistent with the same day's
  0-trade backtest run in an earlier commit).
- `npx tsc --noEmit` clean.

## [Unreleased] - Dashboard: /dashboard/risk-status now real, DB-backed

### Fixed
- **`/dashboard/risk-status` hardcoded `0`/`0`/`0` with a "not yet wired"
  note**, even though every building block it needs (`TradeJournal`'s
  daily/weekly reports, a trades-today count) already existed and is
  already used for real by `RiskManager.evaluate()`/the loop-mode circuit
  breaker. Now computes real `daily_loss_used_percent`/
  `weekly_loss_used_percent` (magnitude of a net loss for the UTC day/ISO
  week, `0` on a net-positive day rather than a negative number) and real
  `trades_today`. The frontend `RiskStatusPanel` also had a hardcoded
  "Not live yet" badge, now removed since the data is live.

### Changed
- `PLACEHOLDER_ACCOUNT_BALANCE` moved from a local constant in
  `scripts/run_paper.py` into `settings.PLACEHOLDER_ACCOUNT_BALANCE`
  (`app/config.py`), so `/dashboard/risk-status` and `run_paper.py` share
  the exact same fixed denominator for PnL-to-percent conversion instead
  of each needing their own copy (or silently drifting onto different
  bases).
- `scripts/run_paper.py`'s private `_count_trades_opened_today()` moved to
  `TradeTracker.count_trades_opened_today()` (same logic, same tests
  extended) so `/dashboard/risk-status` can reuse it too.

### Verified
- `pytest backend/tests/` 143/143 passing (7 new: fresh-DB zero-state,
  real-seeded-loss reflecting in the endpoint, a net-positive day
  reporting 0% (not negative), and a direct `count_trades_opened_today()`
  unit test). Full suite re-run 3x with no flakiness.
- Real end-to-end: booted the actual FastAPI app against a fresh temp
  SQLite DB, seeded a real -$150 closed trade via `TradeTracker`, hit the
  live `/dashboard/risk-status` endpoint through `TestClient` -- returned
  `daily_loss_used_percent: 1.5` (not the old hardcoded `0`).
- `npx tsc --noEmit` clean (frontend type/contract changes).

## [Unreleased] - BacktestEngine now enforces real daily/weekly loss limits

### Fixed
- **`BacktestEngine.run()` never passed `daily_pnl_percent`/`weekly_pnl_percent`
  to `RiskManager.evaluate()`** (only `trades_today`), so both silently
  defaulted to `0.0` inside the risk gate -- a backtest could keep opening
  trades through a day/week that would have tripped paper/live's real
  loss-limit reject (wired in the previous `RiskManager`/circuit-breaker
  commit). This made backtest results a systematically easier, less
  representative test of a strategy than what paper/live will actually
  run -- the same class of gap the previous position-sizing fix closed for
  notional/PnL, now closed for the loss-limit gate itself.

### Added
- `_day_bounds()` / `_week_bounds()` / `_realized_pnl_in_window()` in
  `app.backtesting.backtest_engine` -- an in-memory equivalent of
  `TradeJournal.generate_daily_report()`/`generate_weekly_report()`'s
  UTC-calendar-day / ISO-calendar-week windowing, recomputed from the
  backtest's own `trades` list on every step (not a running accumulator,
  to avoid drift when a trade's close lands on a later day/week than the
  step that opened it). `run()` now passes real `daily_pnl_percent`/
  `weekly_pnl_percent` to `risk_manager.evaluate()`, computed against the
  run's starting `account_balance` (a fixed denominator, deliberately
  mirroring `scripts/run_paper.py`'s `PLACEHOLDER_ACCOUNT_BALANCE`-based
  `_pnl_to_percent()`, not the compounding balance used for position
  sizing) so backtest and paper loss-limit percentages stay comparable.

### Verified
- `pytest backend/tests/` 140/140 passing (6 new: 2 direct unit-level
  proofs of the day/week boundary math against independently
  hand-computed dates, and 2 full `BacktestEngine.run()` end-to-end
  proofs using the REAL `RiskManager` -- a stop-loss hit that alone
  breaches `MAX_DAILY_LOSS_PERCENT` blocks a second, otherwise-valid
  signal offered later the same day, contrasted with a small loss within
  the limit NOT blocking it). Full suite run 3x in a row with no
  order-dependent flakiness.
- Real end-to-end run against live OKX data (`scripts/run_backtest.py`,
  BTCUSDT/5m): completes cleanly, exit code 0, report/CSV generated (0
  trades today -- no confluence in current market conditions, a normal
  outcome, not an error).

## [Unreleased] - Paper trades now actually close on SL/TP, with real fill prices recorded

### Fixed
- **Paper trades opened but never closed**: `TradeTracker().record_trade(status="open")`
  recorded a trade, but nothing afterward ever checked it against a
  current price or closed it — `TradeJournal`'s daily/weekly reports (and
  therefore the loss-limit circuit breaker) could never see a realized
  loss. `scripts/run_paper.py`'s `run_once()` now runs an exit-check step
  against every open position on EVERY pass (single-pass and loop mode
  alike) before signal generation, closing any position whose SL/TP is
  reached via `PaperBroker().check_exit()` / `TradeTracker().close_trade()`.
- **Trade persistence recorded the unfilled planned price, not the real
  fill**: found while verifying an in-flight, uncommitted diff for
  completeness — its own docstring already claimed `entry_price` was
  being recorded from `ExecutionResult.fill_price`, but the actual
  assignment still used `signal.entry_price` (the diff was left
  incomplete). Fixed to actually use `result.fill_price` (falling back to
  `signal.entry_price` only if absent). This matters because the new
  `_compute_exit_pnl()` assumes `position["entry_price"]` is the real
  fill — uncorrected, every paper trade's PnL would have been silently
  computed against a price that was never actually filled.
- `PaperBroker.check_exit()` previously assumed SL/TP fills happen at
  exactly the trigger price. Now applies the same unfavorable-slippage
  convention as `fill_entry()`, mirrored in the opposite direction (exits
  are the opposite-side trade from entries).

### Added
- `ExecutionResult` gains `fill_price`/`fee_percent` (both `None` on any
  failure path), surfacing what `PaperBroker.fill_entry()` already
  computed instead of forcing callers to fall back to the unfilled
  planned price and a hardcoded fee.
- `scripts/run_paper.py`: `_check_and_close_open_positions()` /
  `_compute_exit_pnl()` (PnL formula deliberately mirrors
  `BacktestEngine._simulate_trade()` exactly — real position size × real
  price move, minus a flat taker fee applied per leg to that leg's actual
  notional). A one-trade-open-at-a-time concurrency guard skips signal
  generation for the rest of a pass if any position remains open after
  the exit-check step (mirrors `BacktestEngine`'s no-overlap model).
  `run_once()`'s summary dict gains `positions_closed` /
  `skipped_signal_generation` / `skipped_reason` (existing fields
  unchanged in meaning).

### Verified
- `pytest backend/tests/` 136/136 passing.
- Real temp-SQLite, real `alembic upgrade head`, no mocks: executed a
  signal through the real `ExecutionEngine`/`PaperBroker` (fill_price
  0.02% above the planned entry, as expected from `SLIPPAGE_PERCENT`),
  persisted it via the fixed logic (`entry_price` = the real fill, not
  the planned price), reloaded the open position from the DB, drove it
  through a take-profit exit via `PaperBroker.check_exit()`, computed the
  round-trip PnL, and closed it — confirming the DB no longer shows it as
  open.

## [Unreleased] - Capital-protection: real date-scoped daily/weekly PnL wired into RiskManager and the circuit breaker

### Fixed
- **`TradeJournal.generate_journal_report()` had zero date/time filtering**:
  it aggregated `total_pnl`/`win_rate`/`total_trades` across EVERY paper
  trade ever recorded (all-time cumulative), with no way to ask for "just
  today" or "just this week". `scripts/run_paper.py`'s loop-mode drawdown
  check consumed this all-time total as if it were a daily figure
  (`daily_pnl_percent = report["total_pnl"] / PLACEHOLDER_ACCOUNT_BALANCE
  * 100`), so the circuit breaker's "daily loss limit" check was actually
  comparing all-time cumulative PnL against `MAX_DAILY_LOSS_PERCENT` —
  mislabeled as daily, and immune to a real same-day loss spike that was
  still small relative to history.
- **`RiskManager().evaluate()` — the real per-signal trade-approval gate,
  called in BOTH single-pass and loop mode — never received
  `daily_pnl_percent`/`weekly_pnl_percent`**, so both silently defaulted to
  `0.0` and `DrawdownGuard.check_daily_loss`/`check_weekly_loss` could
  never reject a trade regardless of real losses — dead code in the live
  pipeline.
- **`MAX_WEEKLY_LOSS_PERCENT` had zero enforcement anywhere.**

### Added
- `TradeJournal.generate_journal_report()` gains optional `start`/`end`
  timezone-aware datetime bounds (both required together; raises
  `ValueError` if only one is given or either is naive). Default
  (no args) is UNCHANGED — the original all-time/cumulative contract,
  byte-for-byte, for existing callers/tests. When bounds are given, the
  query switches to counting only `status == "closed"` paper trades with
  `closed_at` inside `[start, end]` (a trade's PnL only counts once
  realized/closed; open trades have no `closed_at` and are excluded from
  `total_trades` in this mode, unlike the all-time default which includes
  open trades too).
- `TradeJournal.generate_daily_report(as_of=None)` /
  `generate_weekly_report(as_of=None)`: thin convenience wrappers around
  the above. "Daily" = the UTC calendar day
  `[00:00:00.000000, 23:59:59.999999]`. "Weekly" = the ISO calendar week,
  Monday `00:00:00.000000` UTC through Sunday `23:59:59.999999` UTC. ISO
  calendar week (not a rolling 7-day window) was chosen specifically for
  consistency with the UTC-calendar-day convention `run_paper.py`'s
  `_count_trades_opened_today` already uses — documented in
  `docs/risk_rules.md`'s new "Daily/weekly boundary convention" section.
- `scripts/run_paper.py`'s `_pnl_to_percent()` helper centralizes the
  PnL-to-percent-of-`PLACEHOLDER_ACCOUNT_BALANCE` conversion so the
  circuit-breaker check and the `RiskManager.evaluate()` call can't drift
  onto different formulas.

### Changed
- `scripts/run_paper.py`'s `_check_drawdown_and_maybe_trip()` (loop mode
  only) now uses `TradeJournal().generate_daily_report()` /
  `generate_weekly_report()` for real, correctly-scoped daily/weekly PnL%,
  and trips the circuit breaker on EITHER a daily OR a weekly breach — a
  deliberate, documented design call (this function is the only
  Telegram/Discord-alerting integration point in loop mode; relying on
  RiskManager's per-signal weekly rejection alone would silently reject
  every future signal without ever alerting the operator).
- `run_once()` (shared by both single-pass and loop mode) now computes
  real `daily_pnl_percent`/`weekly_pnl_percent` from the journal
  (best-effort, same fallback-to-0.0-with-a-loud-WARNING pattern as the
  existing `trades_today` computation) and passes them into
  `RiskManager().evaluate(...)`. Documented conclusion (module docstring):
  this alone is judged sufficient protection for single-pass mode, since
  the PnL figures are queried fresh from the real DB on every invocation
  (not from in-process memory) — a real breach is independently
  re-detected and re-rejected on every future single-pass run. Flagged
  (not fixed, out of scope): a single-pass rejection due to a real
  daily/weekly loss breach is currently silent from an alerting
  standpoint — no Telegram/Discord alert fires, unlike loop mode.
- `docs/risk_rules.md`'s "Behavior" section rewritten to state precisely
  what happens today: the circuit breaker trips and requires a manual
  `.reset()` (DB-persisted via `PersistentCircuitBreaker`) — there is
  currently NO automatic day/week-boundary auto-reset. Stated as a
  deliberate design choice for a single-trader system, not an
  unacknowledged gap; automatic reset is explicitly out of scope for this
  change. Also documents that `MAX_WEEKLY_LOSS_PERCENT` is now actually
  enforced (previously documented only, never wired).

### Tests
- 5 new tests in `backend/tests/test_portfolio.py`: `start`/`end` must be
  given together (`ValueError` otherwise) and must be timezone-aware;
  `generate_daily_report()` proven to include only a trade closed inside
  today's UTC window while excluding trades closed 1 microsecond before
  today, 1 second into tomorrow, and 8 days ago (all seeded with large
  losses so a boundary bug would be impossible to miss), plus an
  open/never-closed trade; `generate_weekly_report()` proven against the
  ISO-week boundary the same way (1 microsecond before/after the week,
  independently verified dates, not derived from the formula under test);
  all-time default (`generate_journal_report()` with no args) proven
  unaffected.
- 3 new tests in `backend/tests/test_risk_daily_weekly_real_integration.py`
  (real migrated temp SQLite DB, no mocks): a real seeded daily-loss-
  breaching trade correctly rejects a signal via the real
  `RiskManager.evaluate()` end-to-end (journal query -> percent conversion
  -> risk decision); a real seeded weekly-only loss (closed earlier in the
  same ISO week, not "today") rejects via the weekly reason specifically,
  proving the two checks are genuinely independent, not just both firing
  together; a contrast case with a small in-limits loss still approves
  (proves the wiring doesn't just reject everything unconditionally).
- Full `pytest backend/tests/` **135/135 passing** (127 pre-existing + 8
  new).
- Real end-to-end verification (temp SQLite, real `alembic upgrade head`,
  real OKX candle fetch): plain `run_paper.py` single-pass run, exit code
  0, `"No signal generated this pass."` (real market data, no error).
  Seeded a real closed trade (`pnl=-150.0`, i.e. -1.5% of the $10,000
  placeholder balance) and re-ran in loop mode
  (`--iterations 2 --interval-seconds 0`): both iterations printed `ALERT:
  Circuit breaker tripped: daily loss limit breached (daily PnL -1.50%,
  limit 1.0%)` — the real seeded loss, correctly scoped and labeled,
  actually tripping the real persistent circuit breaker end-to-end; exit
  code 0 (expected — a trip alone is a safe/handled outcome, not a
  process-level failure).
- `py_compile` clean on all changed/new files. Grep-confirmed: no
  TODO/placeholder-stub/mock/bare `pass`/`NotImplementedError` introduced
  (the pre-existing `PLACEHOLDER_ACCOUNT_BALANCE` name/comments are
  unrelated prior art, not new stub code).

### Scope
- `backend/app/strategy/*`, `backend/app/backtesting/*`,
  `backend/app/execution/*`, `backend/app/exchange/*`,
  `backend/app/risk/risk_manager.py`, `backend/app/risk/drawdown_guard.py`,
  `frontend/*`, and all live-trading gating are unchanged (diff does not
  touch them) — `risk_manager.py`/`drawdown_guard.py` were read closely to
  confirm their existing `daily_pnl_percent`/`weekly_pnl_percent`
  parameters and `DrawdownGuard` boolean convention already supported this
  wiring correctly with zero changes needed there.
- **git commit not done** — operator/CTO independent re-verification
  pending, same pattern as prior milestones this session.

## [Unreleased] - Backtest engine: real RISK_PER_TRADE_PERCENT position sizing (replaces 100%-notional placeholder)

### Fixed
- **`BacktestEngine._simulate_trade()`'s own docstring admitted this was a
  placeholder**: PnL was computed as `account_balance * net_return`, which
  implicitly risks 100% of `account_balance` as notional on every trade —
  meaning backtest PnL/win-rate/max-drawdown described a far riskier,
  unrealistic strategy than what `RISK_PER_TRADE_PERCENT`-governed
  paper/live trading actually runs (`scripts/run_paper.py` already used the
  real `calculate_position_size()` sizing correctly; `BacktestEngine` was the
  one remaining place using the old model). Backtest results were therefore
  non-representative evidence, undermining the point of backtesting before
  paper/live.

### Changed
- `BacktestEngine.run()` now calls
  `calculate_position_size(account_balance, settings.RISK_PER_TRADE_PERCENT,
  signal.entry_price, signal.stop_loss)` (`app.risk.position_sizing` —
  unmodified, consumed only) right after risk approval, sized off the
  signal's original pre-slippage entry/stop, exactly mirroring
  `run_paper.py`'s pattern.
- `_simulate_trade()`'s PnL/fee math rewritten for real position-based
  accounting instead of the old notional-fraction approximation:
  `raw_pnl = size * (exit_price - entry_fill)` (sign flipped for short); fees
  are charged per-leg on the ACTUAL notional (`size * entry_fill` on entry,
  `size * exit_price` on exit) rather than a flat percent-of-account-equity
  approximation. Reasoning documented inline rather than mechanically porting
  the old formula onto the new `size` variable.
- Trade records gain an additive `size` (units) field — a real sizing
  decision shouldn't be invisible in the trade record.
  `report_generator.py`'s `TRADE_FIELDS`/`.get()`-based CSV export needed no
  changes (new field flows through automatically).

### Added
- Degenerate-case guard: when `entry == stop_loss`, `calculate_position_size`
  returns `0.0` (its own division-by-zero guard) — `BacktestEngine.run()`
  now treats this exactly like a rejected/no-signal step (`i += 1;
  continue`), never recording a fake zero-notional "trade". Defended
  directly rather than trusting `entry_model.py`'s upstream
  `if risk <= 0: return None` guarantee to make this unreachable.
- 4 new tests in `backend/tests/test_backtest_engine.py` (existing 6,
  including both mandatory no-lookahead regression tests, pass unchanged):
  size correctness verified against an independent `calculate_position_size`
  call; PnL proven to scale exactly with `size` (not a flat fraction of
  `account_balance`, via two scenarios differing only in stop distance);
  `run()`'s wiring to the real `settings.RISK_PER_TRADE_PERCENT` proven
  end-to-end; degenerate zero-size signals proven to be skipped, never
  recorded, across every remaining walk-forward step. Full suite: 127/127
  passing (123 pre-existing + 4 new).
- Real end-to-end verification: `scripts/run_backtest.py` against real OKX
  data produced actual trades (`BTCUSDT/15m`: 2 trades, `total_pnl=-89.85`,
  `max_drawdown=0.90%`; `SOLUSDT/15m`: 2 trades, `total_pnl=-80.25`,
  `max_drawdown=0.80%`) — with `account_balance=10000`/
  `RISK_PER_TRADE_PERCENT=0.25%` ($25 risk budget/trade), max drawdown stays
  well under 1% even across 2 consecutive losses, bounded and sane, versus
  the old model where a single trade's notional exposure was the entire
  account regardless of `RISK_PER_TRADE_PERCENT`.

## [Unreleased] - Backtest engine: real HTF/LTF walk-forward with no-lookahead HTF cursor

### Fixed
- **Resolves the "Known gap" blocker flagged below**: `BacktestEngine.run()`
  still called `signal_engine.generate_signal()` with the old single-series
  signature after the Strategy Engine's HTF/LTF separation landed, so any
  full `scripts/run_backtest.py` run failed immediately with a `TypeError`.
  `BacktestEngine.run()`'s signature is now
  `run(self, ltf_candles, htf_candles, signal_engine, risk_manager, ...)`.

### Added
- `app.backtesting.backtest_engine._advance_htf_cursor()`: a forward-only,
  O(n)-total two-pointer cursor that, at each LTF walk-forward step, exposes
  to `generate_signal()` ONLY the HTF candles that are provably fully closed
  as of that LTF step's timestamp (an HTF candle at index `k` is provably
  closed once HTF candle `k + 1` exists with `timestamp <= ` the current LTF
  timestamp — sidesteps needing to parse/hardcode the HTF timeframe's
  duration). This prevents lookahead bias: a still-forming HTF candle can
  never influence a signal generated at an earlier LTF step. Degrades safely
  to an empty HTF slice (-> `detect_htf_bias([])` -> `"neutral"` -> no
  signal) when no HTF candle has closed yet relative to the current LTF step.
- `scripts/run_backtest.py` now fetches LTF and HTF candles as two
  independent `CandleFetcher` calls (mirrors `run_paper.py`'s pattern): an
  HTF fetch failure or empty result is a hard failure (exit code 1), never a
  silent fallback to LTF-as-HTF.
- `MIN_CANDLES` (still `31`) sizing decision documented explicitly in code:
  it is sized only for LTF history and is deliberately NOT raised to
  guarantee real HTF history exists (for realistic ratios like 5m LTF / 4h
  HTF, meaningful HTF bias needs hundreds of LTF candles of runway) — this
  is safe as-is because the empty-slice/`"neutral"`-bias degrade path never
  produces a wrong signal, only some early no-op walk-forward iterations.
- 6 new tests in `backend/tests/test_backtest_engine.py`, including a
  mandatory no-lookahead regression proof at both the unit level
  (`_advance_htf_cursor` directly, with a contrasting "naive/buggy cursor
  would have leaked the still-forming bar" assertion proving the test is
  non-vacuous) and the full end-to-end level (two `BacktestEngine.run()`
  calls with LTF held identical and HTF differing only in a still-forming
  final bar, asserting byte-identical `BacktestResult`s including a real,
  non-empty trade). Full suite: 123/123 passing (117 pre-existing + 6 new).
- Real end-to-end verification: `scripts/run_backtest.py` run against real
  OKX data (BTCUSDT/5m and ETHUSDT/15m, 300 candles each, real HTF 4h fetch)
  completes with exit code 0 (0-trade outcome today — a valid, non-error
  result, not a crash).

## [Unreleased] - Strategy Engine correctness: real HTF/LTF separation + confluence direction-matching

### Fixed
- **HTF/LTF separation was fake**: `SignalEngine.generate_signal()` fed the
  same single candle list to `detect_htf_bias()` as well as every other
  detector, so "HTF bias" was actually computed from the LTF series (and
  `HTF_TIMEFRAME` was referenced nowhere in `backend/app`). Signature is
  now `generate_signal(symbol, ltf_candles, htf_candles)`: bias comes from
  `htf_candles` only, everything else (sweep/CHOCH/FVG/order block) stays
  on `ltf_candles`. `scripts/run_paper.py` now fetches both series
  independently via `CandleFetcher`; an HTF fetch failure/empty result is
  a hard failure (exit code 1), never a silent fallback to LTF-as-HTF.
- **Confluence gate ignored directional agreement (correctness bug)**:
  `entry_model.build_entry_model()` only checked *presence* of a
  sweep/CHOCH (`sweep is None and choch is None`), never whether its
  `type` matched the bias-derived trade direction — meaning the engine
  could produce a signal to enter directly against a sweep/CHOCH it just
  detected. Now a `sell_side` sweep / `bullish_choch` only count as
  confluence for `long`; a `buy_side` sweep / `bearish_choch` only count
  for `short`. A direction-mismatched sweep/CHOCH is treated as absent
  (not an error).

### Added
- `market_structure.detect_choch_mss()` gains an optional `swept_index`
  parameter: when provided, only swing highs/lows at index `>= swept_index`
  are eligible as the broken level, so the returned CHOCH causally follows
  the specific liquidity sweep that preceded it rather than referencing an
  arbitrary earlier structural shift. `swept_index=None` (default) leaves
  existing behavior unchanged. `SignalEngine` wires
  `detect_liquidity_sweep(ltf_candles)`'s `swept_index` into this call.
- Inline "why" comments for previously-unjustified magic numbers:
  `order_block._LOOKBACK`/`_IMPULSE_MULT`, `entry_model._STOP_BUFFER`/`_RR`
  — documented honestly as reasonable starting defaults not yet
  backtested/tuned, rather than implying a derivation that doesn't exist.
- 8 new regression tests across `test_strategy_signal_engine.py` (real
  HTF-vs-LTF bias divergence proof), `test_strategy_entry_model.py`
  (direction-mismatch sweep/CHOCH now correctly rejected), and
  `test_strategy_market_structure.py` (`swept_index` excludes an earlier,
  unrelated swing break). Full suite: 117/117 passing.
- `docs/strategy_spec.md` sections 1-3 updated to state these deterministic
  resolutions explicitly instead of leaving them implicit/ambiguous.

### Known gap (blocker) — RESOLVED
- `backend/app/backtesting/backtest_engine.py` (out of scope for this
  change) still called `generate_signal()` with the old single-series
  signature inside its walk-forward loop, so a full `scripts/run_backtest.py`
  run failed fast with a clear `TypeError` (exit code 1) rather than
  silently misbehaving. Fixed in the "Backtest engine: real HTF/LTF
  walk-forward with no-lookahead HTF cursor" entry above.

## [Unreleased] - Capital-protection follow-up: CircuitBreaker DB persistence

### Fixed
- `CircuitBreaker` tripped state was process-memory-only in `scripts/run_paper.py`
  loop mode; a crash, redeploy, or cron respawn while tripped silently reset
  the daily-loss protection. Added `PersistentCircuitBreaker` (DB-backed via
  new `bot_state.circuit_breaker_*` columns) so a respawned process observes
  and honors a prior real trip. Plain `CircuitBreaker` is unchanged and stays
  fully decoupled from the database for unit testing.

### Added
- Alembic migration `4b8a822a475b` adding `circuit_breaker_tripped`,
  `circuit_breaker_reason`, `circuit_breaker_tripped_at` to `bot_state`.
- `load_circuit_breaker_state()` / `save_circuit_breaker_state()` in
  `portfolio/positions.py`.
- 8 new tests in `backend/tests/test_circuit_breaker_persistence.py`,
  including a real two-process integration test simulating crash-and-respawn.

## [0.1.0] - Milestone 1: System Architecture

### Added
- Architecture documentation (`docs/architecture.md`) covering the 6 core
  layers, system data flow, trading modes, folder structure, and module
  responsibility table.
- Strategy Engine spec/contract (`docs/strategy_spec.md`).
- Risk rules documentation (`docs/risk_rules.md`).
- API key security practices (`docs/api_keys_security.md`).
- Live trading safety checklist (`docs/live_trading_checklist.md`).
- Database schema draft (`docs/database_schema.md`) for the 6 core tables.
- Milestone 2 plan (`docs/next_milestone_plan.md`).
- Repo folder structure scaffolding (`backend/app/*`, `frontend/*`) with
  stub files only.
- `.env.example` documenting all required environment variables.
- `docker-compose.yml` for backend, frontend, postgres, and redis services.
- `README.md` project overview and quickstart.

### Notes
- No trading logic is implemented yet. Strategy detection, risk validation,
  execution, and portfolio tracking are all documentation/spec only as of
  this milestone.
