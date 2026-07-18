# H3 — Regime-Conditional Delay Survival Results — Milestone 27

Evaluation Agent deliverable (2026-07-18), CTO directive. This closes out
`docs/HYPOTHESES_ROUND_1.md` section 3 (H3): the pre-registered
per-regime-bucket delay-retention join of `--structure-tp`,
`--tag-regimes`, and `--delay-check` -- three already-built,
already-independently-validated mechanisms that had never been run
together before. Unlike H1 (two standard anchors), H3's own keep-rule
requires **three** tested years (2024/2025/2026), matching the standard
this platform already applies to Legacy's own delay-fragility evidence
(`docs/LEGACY_DELAY_ROBUSTNESS.md`). New analysis-only harness
`scripts/research_regime_delay.py` (+
`backend/tests/test_research_regime_delay.py`, 23 tests) was implemented
and verified this round. `RiskManager.evaluate()`'s live sequential-
approval logic is untouched -- this harness joins two already-existing,
already-independently-validated flags' outputs (`--tag-regimes`,
`--delay-check`) per bucket rather than adding new detection or
execution logic. Full suite: 739/739 passed (716 prior + 23 new), 0
failures. Every number below is transcribed from
`scripts/reports/research_regime_delay_2026.json` /
`_2025.json` / `_2024.json`.

## 1. Purpose and methodology

**The gap this closes**: `docs/PROFITABILITY_EXPERIMENT_REPORT.md`
§12-14 validated `use_structure_tp=True` as this platform's strongest
candidate family (cross-asset, cross-year on raw profitability), while
`docs/ROBUSTNESS_REPORT.md` Test 2 found the SAME family catastrophically
delay-fragile in AGGREGATE (PF 5.24 -> 0.16 at a 5-minute delay on a 5m
anchor) -- the finding that started this platform's entire
delay-robustness thread, later confirmed structural for Legacy itself
(`docs/LEGACY_DELAY_ROBUSTNESS.md`). No prior round had ever
regime-tagged a `structure_tp` delay-check run. `structure_tp` targets a
real structural level (the previous swing high/low, or the
premium/discount equilibrium if farther -- `docs/strategy_spec.md` §6)
rather than a fixed-RR target, so its stop/target distances vary with
market structure, unlike a uniform ATR floor. **H3 asked**: in regimes
with more directional persistence (`strong_trend/*`, or BTC's dominant
`weak_trend/normal_volatility` bucket), does a 15-minute delay matter
proportionally less -- because price has less opportunity to reverse
through a farther-away stop before the delayed fill -- than in
choppy/reversal-prone regimes, where the aggregate 0.16 PF collapse
could be concentrated? This is a genuinely different mechanism from the
already-REJECTED ATR floor (`docs/ATR_FLOOR_EVALUATION.md`): the floor
uniformly widened stops regardless of regime and was shown to merely
thin the population without conferring robustness; H3 touches no
parameter at all -- it asks whether an already-built, already-validated
candidate's EXISTING variable stop/target geometry happens to be
delay-robust in specific, identifiable regimes.

**New instrumentation** (analysis-only, does not touch `RiskManager`'s
live sequential-approval logic or `BacktestEngine`'s trade-generation
mechanics): `scripts/research_regime_delay.py` runs `BacktestEngine`
once at `entry_delay_candles=0` and once at `entry_delay_candles=1`,
both with `use_structure_tp=True` and `tag_regimes=True`, then joins the
two trade sets per regime bucket (`"{trend}/{volatility}"`, plus an
aggregate `"all"` row) and computes baseline PF, delayed PF, PF
retention, and sign flip PER BUCKET rather than only in aggregate --
reusing `tag_regimes` and `delay-check`'s existing, independently-tested
mechanics verbatim.

**Anchor (identical across all three years)**: `--symbol BTCUSDT
--timeframe 15m --candles 3000 --periods 6`, `structure_tp` uncapped
(the CLI-exposed variant, not the refined `structure_tp_max_r=3.0` +
`require_premium_discount_filter=True` combo from
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` §13.4, which remains only
reachable via `run_backtest_period()`'s Python parameter -- per H3's own
pre-registered experiment text), varying only `--end-date`
(`2026-07-10`, `2025-07-10`, `2024-07-10`).

## 2. Results, all three anchors

**2026 anchor** (`--end-date 2026-07-10`, 10 buckets incl. `all`):

| Bucket | Baseline N | Delayed N | Baseline PF | Delayed PF | PF Retention | Sign Flip |
|---|---|---|---|---|---|---|
| range/high_volatility | 1 | 1 | 0.000 | 0.000 | insufficient_data | null |
| range/low_volatility | 13 | 12 | 19.639 | 0.756 | 0.038 | true |
| range/normal_volatility | 13 | 14 | 21.430 | 66.166 | 3.087 | false |
| strong_trend/high_volatility | 13 | 11 | 2.469 | 0.429 | 0.174 | true |
| strong_trend/low_volatility | 7 | 6 | 23.682 | 0.547 | 0.023 | true |
| strong_trend/normal_volatility | 10 | 9 | 11.739 | 0.354 | 0.030 | true |
| weak_trend/high_volatility | 14 | 18 | 6.834 | 0.277 | 0.041 | true |
| weak_trend/low_volatility | 8 | 7 | 20.534 | 0.618 | 0.030 | true |
| weak_trend/normal_volatility | 22 | 20 | 2.851 | 0.483 | 0.170 | true |
| **all** | **101** | **98** | **6.723** | **0.536** | **0.080** | **true** |

**2025 anchor** (`--end-date 2025-07-10`, 9 buckets incl. `all` -- no
`range/high_volatility`, zero trades that regime that year):

| Bucket | Baseline N | Delayed N | Baseline PF | Delayed PF | PF Retention | Sign Flip |
|---|---|---|---|---|---|---|
| range/low_volatility | 10 | 10 | 22.335 | 0.341 | 0.015 | true |
| range/normal_volatility | 11 | 10 | 5.977 | 0.227 | 0.038 | true |
| strong_trend/high_volatility | 5 | 4 | 1.460 | 0.432 | 0.296 | true |
| strong_trend/low_volatility | 4 | 4 | 8.481 | 0.125 | 0.015 | true |
| strong_trend/normal_volatility | 4 | 5 | 5.858 | 1.390 | 0.237 | false |
| weak_trend/high_volatility | 9 | 9 | 11.283 | 0.524 | 0.046 | true |
| weak_trend/low_volatility | 13 | 11 | 2.755 | 0.145 | 0.053 | true |
| weak_trend/normal_volatility | 2 | 3 | inf | 0.355 | 0.000 | true |
| **all** | **58** | **56** | **6.887** | **0.350** | **0.051** | **true** |

**2024 anchor** (`--end-date 2024-07-10`, 8 buckets incl. `all` -- no
`range/high_volatility` or `strong_trend/low_volatility`, zero trades
those regimes that year):

| Bucket | Baseline N | Delayed N | Baseline PF | Delayed PF | PF Retention | Sign Flip |
|---|---|---|---|---|---|---|
| range/low_volatility | 7 | 7 | 2.563 | 0.210 | 0.082 | true |
| range/normal_volatility | 8 | 8 | 18.827 | 2.533 | 0.135 | false |
| strong_trend/high_volatility | 7 | 5 | 7.617 | 0.487 | 0.064 | true |
| strong_trend/normal_volatility | 8 | 6 | 28.153 | 0.044 | 0.002 | true |
| weak_trend/high_volatility | 6 | 6 | 5.456 | 0.172 | 0.031 | true |
| weak_trend/low_volatility | 9 | 9 | 6.147 | 0.449 | 0.073 | true |
| weak_trend/normal_volatility | 19 | 18 | 6.171 | 0.810 | 0.131 | true |
| **all** | **64** | **59** | **7.811** | **0.526** | **0.067** | **true** |

## 3. Keep-rule verdict -- applied literally, all 27 bucket-year cells

Quoting `docs/HYPOTHESES_ROUND_1.md` section 3's keep-rule verbatim:

> **Keep-rule (declared now)**: a regime bucket counts as a genuine
> delay-robust pocket only if it clears the SAME bar the platform
> already applies everywhere else: n>=20 trades on the delayed side of
> that bucket, PF retention >=0.5, no sign flip, in AT LEAST 2 of the 3
> tested years. If no bucket clears this bar in any year, REJECT the
> regime-conditional-survival hypothesis outright ... A bucket clearing
> the bar in only 1 of 3 years is recorded as a directional lead, not a
> keep.

**Applying the rule across all 27 bucket-year cells** (10 in 2026 + 9 in
2025 + 8 in 2024): `meets_keep_bar` is FALSE for every single one. Not
one bucket clears n>=20 on the delayed side AND PF retention >=0.5 AND
no sign flip in even a single year, let alone 2-of-3. Only ONE cell
reaches the n>=20 delayed-side floor at all -- 2026's
`weak_trend/normal_volatility` (delayed N=20) -- and it fails outright
on PF retention (0.170, needs >=0.5) and carries a sign flip. Since not
even one bucket clears the bar in even one year, this does not reach the
"directional lead" tier the rule reserves for a bucket clearing the bar
in exactly 1 of 3 years -- it is a harder, cleaner zero than that.

**VERDICT: REJECT**, per the rule's own explicit "if no bucket clears
this bar in any year, REJECT the regime-conditional-survival hypothesis
outright" clause. Not ambiguous, not MIXED (compare Milestone 25's H4
verdict, which genuinely did not resolve to one branch) -- this is a
clean negative result on the rule exactly as pre-registered.

## 4. Evidence-scarcity caveat (important -- read before citing this REJECT elsewhere)

This REJECT is compounded by data scarcity, not purely a clean failure
on well-sampled buckets. **26 of the 27 bucket-year cells never even
reach the n>=20 delayed-side threshold** needed to evaluate the keep-rule
meaningfully in the first place -- only the single 2026
`weak_trend/normal_volatility` cell does, and it still fails on PF
retention and sign flip. This is consistent with this platform's
already-documented regime-bucket evidence scarcity
(`docs/REGIME_PERFORMANCE_ANALYSIS.md`: 8 of 9 buckets evidence-starved
for Legacy's own signal stream) -- H3's independently-computed
`structure_tp` regime buckets show the same scarcity pattern on a
completely different feature/exit family. **Honest framing**: this
REJECT is "insufficient data to test most buckets meaningfully" as much
as it is "buckets were tested and failed." A future round with a larger
candle history, more assets, or accumulated shadow-mode data could in
principle surface a bucket that clears the n>=20 floor and THEN meets or
fails the PF-retention/sign-flip bar on its own merits -- that
possibility is not ruled out by this round, only the specific 27
bucket-year cells actually tested here.

## 5. Secondary observation, not a keep driver

The aggregate (`all`) row's PF retention for `structure_tp` -- 0.080
(2026), 0.051 (2025), 0.067 (2024) -- is systematically ~2-3x HIGHER
than Legacy's already-documented default-exit aggregate retention at the
same anchors (2026: 0.023, 2025: 0.015, from
`docs/LEGACY_DELAY_ROBUSTNESS.md`; 2024 has no prior default-exit
delay-check on record to compare against). Both remain catastrophically
below the 0.5 bar with a sign flip in all three years for `structure_tp`
too -- **this is a quantitative footnote, not evidence of practical
delay-robustness, and does not change the REJECT verdict above**. It
DOES reinforce, as a third independent data point alongside Legacy's own
Milestone 24 finding, that this platform's execution-delay fragility is
STRUCTURAL across strategy/exit-logic variants tested so far on this
window, not specific to one exit-logic family.

## 6. Minor data caveat: the regime-bucket set differs slightly by anchor

The regime-bucket SET differs slightly across anchors (2026: 10 buckets,
2025: 9, 2024: 8) because `range/high_volatility` had zero trades in
2025 and 2024 (only 1 in 2026, itself marked `insufficient_data`), and
`strong_trend/low_volatility` had zero trades in 2024. This is a
regime-occurrence artifact of each year's actual market conditions, not
a tool bug -- the harness reports whichever buckets a given year's trade
set actually populated, exactly as `regime_analysis.py`'s existing
`aggregate_by_regime` behavior already does elsewhere on this platform.

## 7. Promotion path

**NONE -- this was a REJECT.** Per H3's own pre-registered promotion-path
text (`docs/HYPOTHESES_ROUND_1.md` §3, "Promotion path if KEEP"): even a
KEEP would have required cross-asset confirmation (ETH/SOL/XRP) plus
Phase-1 gate #4's measured live-latency requirement before any operator
conversation -- moot here since the result is REJECT.

**Legacy's live/paper trading behavior is completely unchanged by this
milestone.** This was a 100% backtest-only, read-only research round:
`RiskManager.evaluate()`, `scripts/run_paper.py`, and `BacktestEngine`
internals are all byte-for-byte unchanged, verified during
implementation. No orders were placed; no writes to
`backend/paper_validation.db` occurred.

## 8. Caveats

- **One asset (BTCUSDT), one timeframe (15m), three Jan-Jul windows
  (2024, 2025, 2026)** -- matching H3's own pre-registered 3-year anchor
  set (unlike H1's 2-year set). Not cross-asset checked.
- **Uncapped `structure_tp` only** -- the refined
  `structure_tp_max_r=3.0` + `require_premium_discount_filter=True`
  combo validated in `docs/PROFITABILITY_EXPERIMENT_REPORT.md` §13.4 was
  not tested this round (not exposed as a CLI flag, and H3's own
  pre-registration only committed to the uncapped, already-CLI-exposed
  variant). A different, untested exit-parameter combination remains a
  theoretical possibility not ruled out by this REJECT.
- **Evidence-scarcity dominates this result** (section 4) -- 26 of 27
  bucket-year cells never reach the n>=20 floor needed to test the
  keep-rule meaningfully. This REJECT should be read as "not enough
  regime-tagged delayed-side trades exist yet to find a genuine pocket,
  if one exists" rather than "regime conditioning was tested at scale
  and definitively fails everywhere."
- **No code was touched, no live/paper system was modified.** This is a
  read-only evidence document per the department's scope -- the
  mechanism and secondary-observation notes in sections 4-5 are
  findings, not changes.
