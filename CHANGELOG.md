# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
