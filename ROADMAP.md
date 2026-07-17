# ROADMAP — JadeCap Automated Trading Bot

Forward-looking, prioritized backlog. This file answers "what's next and
why," not "what happened" (see `CHANGELOG.md`/`HANDOFF.md` for that) or
"why did we build it this way" (see `ENGINEERING_DECISIONS.md`).

Guiding principle (see `PROJECT_STATUS.md`'s "Project Philosophy" and
`docs/strategy_coverage_audit.md`): this is a research platform first.
Every item below is ranked by how much it moves the project closer to a
**statistically validated** profitable strategy — not by how much new
code it produces. Evidence over assumption; a rule stays in the system
because data proves it, not because it's popular in ICT/SMC communities.

**SUPERSEDED 2026-07-15 (operator directive) -- see "Objective change" below
for the current mandate.** Original text preserved for history, not
currently in force:

~~**Scope lock (operator directive, 2026-07-11)**: the objective for Phase
1 is narrowly "build, validate, and prove ONE profitable JadeCap
automated trading system" — nothing else. No multi-strategy platform, no
quant research platform, no strategy marketplace, no architecture not
required for JadeCap specifically. Every new item must answer "does this
directly increase the probability that JadeCap becomes a profitable
automated trading system?" — if no, it goes in the "Phase 2 (deferred,
out of scope for now)" section below, not implemented. The objective
does not change until JadeCap has completed, in order: Backtest ->
Walk-Forward -> Paper Trading -> Small Live Validation.~~

## Objective change (operator directive, 2026-07-15): from "one strategy" to "adaptive multi-strategy platform"

The single-strategy scope lock above is explicitly REVERSED, not
extended or clarified -- this is a real, acknowledged pivot, not a
continuation of the prior objective. Six consecutive research
experiments (`docs/CONTINUOUS_RESEARCH_LOG.md`) exhausted the reasonable
parameter space for fixing the JadeCap candidate's execution-delay
fragility without finding a fix, and the operator has concluded (not
this session, unprompted) that "find one perfect strategy" is the wrong
objective. The new objective, verbatim: **"Build an adaptive trading
system that survives changing market conditions."**

Concretely, this means:
- Legacy is no longer positioned as "the strategy to prove" -- it becomes
  **Strategy A**, one module among several, still the only one live in
  production/paper trading until others are validated.
- Multi-strategy architecture (previously explicitly forbidden --
  "Phase 2 (deferred, out of scope for now)" below) is now the ACTIVE
  work: a Market Regime Detector, a Strategy Selection Engine, a common
  Strategy interface, an extended Performance Database, and continuous
  self-evaluation with automatic strategy disabling.
- Jade (`app.strategy.jade_trade_plan` and its component modules --
  entry/exit point engines, HTF/LTF confluence, trendline, CRT, session
  bias -- all already built, all already tested, never wired into
  production) becomes **Strategy B**, reusing that existing work rather
  than discarding it.
- "Do not endlessly tune parameters" / "prefer structural improvements
  over parameter optimization" (operator's own research-rules directive)
  -- the six-experiment parameter search that just concluded is exactly
  the kind of work this new directive says to stop doing; further
  hypothesis-driven experiments remain fine, undirected parameter
  grinding does not.
- **Unchanged**: Legacy stays untouched, stays the production baseline,
  paper trading keeps running exactly as before. Nothing about this
  pivot touches what's currently live.

**Milestone 8.1 (2026-07-16)**: the live-DB schema gap that would have
blocked a safe paper-trader restart on current code is now closed --
`backend/paper_validation.db` predated this project's alembic discipline
(no `alembic_version` table) and was missing every column/table added by
milestones 2-7. `app.database.migrate_existing.migrate_database()`
fingerprinted, stamped, and upgraded it to head (`e3110e6a6b59`), with a
backup taken first. See `ENGINEERING_DECISIONS.md` #51.

**Milestone 9 (2026-07-16)**: the last item on `docs/ADAPTIVE_ARCHITECTURE.md`
section 7's roadmap -- four new strategy-content modules (Trend Following,
Range Trading, Breakout, Volatility Expansion) -- is now implemented AND
quarantined in `app.strategy.experimental.EXPERIMENTAL_STRATEGIES`, with
zero backtest evidence yet. `AVAILABLE_STRATEGIES` (the only registry
either configured selector consults) is untouched, still exactly
`{legacy, jade}`. `BacktestEngine.run(strategy=...)` and
`scripts/run_backtest.py --strategy NAME` now exist specifically so these
(and any future) experimental modules can be evidenced through the same
fee/slippage/walk-forward pipeline as production, before any promotion
decision. See `ENGINEERING_DECISIONS.md` #52.

**Milestone 10 (2026-07-16): evidence round 1 -- DONE, no promotions.**
Ran all four milestone-9 experimental strategies through
`run_backtest.py --strategy NAME` against the Legacy baseline, all five
runs on identical BTCUSDT 15m candles (`--candles 3000 --periods 6
--end-date 2026-07-10 --walk-forward`). Baseline PASSED walk-forward
(+$3,400.62, 6/6 profitable periods); all four experimental strategies
FAILED (`trend_following` -$1,009.78; `range_trading` -$2,321.08;
`breakout` -$5,329.19, "clearly dead"; `volatility_expansion` -$892.45,
least-bad of the four). **No promotions into `AVAILABLE_STRATEGIES`.**
**Cross-asset/cross-year extension of this round is NOT warranted right
now** -- three of the four strategies lost decisively on the one asset
already tested, and the remaining `volatility_expansion` result, while
least-bad, is still net-negative; spending a cross-asset round chasing a
losing config would be the same undirected parameter-grinding this
project's operator directive already told it to stop doing. If a future
round happens, `volatility_expansion` is the one worth prioritizing.
Full report: `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`.

**Milestone 11 (2026-07-16): shadow-mode observability -- DONE,
default-off.** New `regime_snapshots`/`shadow_signals` tables and
`app.portfolio.shadow_recorder.record_shadow_pass()`, gated behind
`ENABLE_SHADOW_STRATEGY_SIGNALS` (default `False`). This directly
targets the regime-tagged-data blocker below. See
`ENGINEERING_DECISIONS.md` #53.

**Natural next steps this unlocks** (not yet started, not commitments):
- **Enabling `ENABLE_SHADOW_STRATEGY_SIGNALS` is now the cheapest
  available path to regime-tagged data.** Flipping the flag is an
  OPERATOR decision (not made this round), and only takes effect on the
  paper trader's NEXT restart -- the currently running process keeps
  executing its already-loaded code regardless of a config-file edit.
  Once enabled and running, it accumulates a `RegimeSnapshot` every pass
  plus a `ShadowSignal` for every non-active strategy that would have
  signaled, at pass speed rather than trade speed.
- **`RollingPerformanceSelector` stays explicitly blocked.** Milestone
  10 supplied one piece of evidence (all four experimental strategies
  evaluated, none profitable) but not the other: enough regime-tagged
  live/paper trade history (this project's own established floor for
  trusting a result is 20+ trades, `experiment_runner.
  MIN_TRADES_FOR_CONFIDENCE`) to make a per-regime comparison meaningful
  rather than invented. `market_regime`/`strategy_name` are populated on
  new TRADE rows (milestones 6-7), but no strategy other than Legacy has
  ever been live, so there is still no regime-tagged trade history for
  any other strategy to compare against -- milestone 11's shadow
  recording is additive signal-level data, not a substitute for that
  trade-level history. This accumulates naturally as paper trading
  continues to run (and faster still once shadow mode is enabled); no
  further new code is required, only an operator decision plus time.

**Milestone 12 (2026-07-16): evidence round 2 -- DONE, thesis unsupported
on this evidence.** `BacktestEngine.run(tag_regimes=True)` plus new
`app.backtesting.regime_analysis` and `scripts/analyze_regime_
performance.py` re-ran Legacy and all four milestone-9 experimental
strategies over the same anchor as evidence round 1 (BTCUSDT 15m,
`--candles 3000 --periods 6 --end-date 2026-07-10`), this time bucketed
by market regime instead of pooled. Pooled totals reproduced round 1
exactly. **No regime bucket justifies routing any experimental strategy
over Legacy** -- the only bucket with n>=20 on both sides has Legacy at
+$26.28 expectancy/PF 3.30 (n=28) versus the best experimental strategy
at +$4.29/PF 1.23 (n=56), and Legacy is positive (though mostly n<20) in
all 9 buckets. A correctly built `RollingPerformanceSelector` evaluated
against this data would route Legacy in 9/9 buckets today. **No
regime-based routing is justified by this evidence.** Full report:
`docs/REGIME_PERFORMANCE_ANALYSIS.md` (final). A real bug was found and
fixed along the way (Windows console encoding crash that would have
silently discarded a completed run's results) -- see
`ENGINEERING_DECISIONS.md` #54.

**Milestones 13-16 (2026-07-16): the build-out of
`docs/ADAPTIVE_ARCHITECTURE.md`'s core evidence-to-selection chain is now
COMPLETE.** Four milestones plus one production bugfix, closing every
item section 7's roadmap table listed as not-yet-built:
`scripts/shadow_status.py` (read-only shadow-data status tool,
milestone 13); shadow outcome resolution -- migration `65aba13281ad` +
`app.portfolio.shadow_resolver` (milestone 14), which also caught and
fixed a real bug (a `datetime` written straight into a JSON column,
crashing OUTSIDE the per-strategy error guard, latent-live since shadow
mode had just been operator-enabled -- see `ENGINEERING_DECISIONS.md`
#55); a rolling per-regime evidence layer keeping shadow and live
evidence permanently separate (milestone 15,
`app.portfolio.rolling_regime_performance`); and
`RollingPerformanceSelector` itself, built and tested with conservative,
disclosed gates (unmeasured-baseline fallback, live precedence over
shadow, strict-inequality qualification, no significance testing) --
milestone 16, `ENGINEERING_DECISIONS.md` #56. A read-only dry-run tool
(`scripts/selector_dry_run.py`) confirmed the selector reproduces
milestone 12's own prediction on a scratch database: `legacy` in all 10
buckets today, baseline unmeasured. **63 new tests, full suite 602
passed / 0 failed** (was 539). Live paper trader ran untouched
throughout; `AVAILABLE_STRATEGIES` and both production selectors
(`DefaultToLegacySelector`, `ConfigurableFallbackSelector`) remain
completely untouched.

**What remains is data and a decision, not more building.** With the
chain now built, what's left is explicitly NOT further architecture
work:
- **(a) Data accumulation.** Shadow-signal collection continues to run
  (`ENABLE_SHADOW_STRATEGY_SIGNALS`, operator-enabled) and now resolves
  to real tp/sl/expired outcomes (milestone 14) instead of only
  capturing signals -- this is the mechanism that fills the sparse
  regime buckets, and it needs time, not new code.
- **(b) Evidence review.** Once enough buckets clear the 20-sample
  floor on both live and shadow sides, an operator (or a future
  documentation/evidence round) reviews what
  `scripts/selector_dry_run.py` actually reports against the live DB --
  today it reports `legacy` everywhere, unmeasured.
- **(c) The wiring decision itself.** Turning `RollingPerformanceSelector`
  on in `scripts/run_paper.py` is a future, EXPLICIT operator decision --
  requiring sufficient evidence per (b) plus explicit approval, exactly
  the same discipline every other production-behavior change in this
  project has followed (see the "Commit discipline" note at the end of
  `docs/ADAPTIVE_ARCHITECTURE.md`). Nothing in milestones 13-16
  authorizes making that call unilaterally.
- **(d) Optional refinements, deliberately deferred.** Fees/slippage
  modeling in shadow fills (closing decision #55(c)'s disclosed
  "optimistic upper bound" caveat) and a real statistical significance
  test in place of the current floor-plus-strict-inequality rule
  (decision #56's disclosed non-significance-test caveat) are both named,
  neither is scheduled -- building either before there's evidence volume
  to justify the extra complexity would be exactly the kind of premature
  work this project's operator directive already told it to avoid.

**Pending ops step, tracked separately (not part of this documentation
round, see `HANDOFF.md`)**: the live paper-trading DB is still one
migration behind (`65aba13281ad` not yet applied), and the paper trader
process needs a clean restart to actually activate outcome resolution
and the JSON-serialization fix -- both are code-complete but only take
effect once applied/restarted, same "code change vs. live effect" gap
every prior milestone in this section has carried.

**Operating model, updated 2026-07-16 (operator directive): continuous
CTO-driven improvement is now the standing mode for this section.** With
milestones 1-16 complete, prioritization here is no longer a fixed
milestone queue -- specialist-agent roles select the next highest-ROI
item by bottleneck analysis against the evidence tables, stopping only
for architectural decisions, credentials, production deployment, or
destructive actions. Promotion gates remain unchanged and are never
bypassed. **Milestone 17 (2026-07-16)** is the first output of this
model: `settings.SHADOW_SYMBOLS` extends shadow collection to extra
symbols (ETH/SOL/XRP intended), and `scripts/cto_report.py` adds a daily
CTO report (now standing practice) covering completed work, evidence
accumulated, strategy rankings, live risk checks, and a mechanical
bottleneck rule. See `ENGINEERING_DECISIONS.md` #57. **Evidence
accumulation runs at 4 symbols (BTC live-trading plus ETH/SOL/XRP
shadow-only) once the paper trader restarts with `SHADOW_SYMBOLS=
ETHUSDT,SOLUSDT,XRPUSDT` set** -- that restart is a pending ops step, not
yet performed. **The next review point is when `scripts/shadow_status.py`
/ the CTO report shows sufficient evidence cells** (n>=20 on both live
and shadow sides for a meaningful number of regime buckets) -- until
then, the evidence-accumulation bottleneck the first CTO report
disclosed (0 sufficient cells) stands unchanged, and no further
architecture work is scheduled ahead of it.

**Research round 1 -- DONE (2026-07-16), all top-3 recommendations
implemented as Milestone 18.** `docs/RESEARCH_ROUND_1.md` (committed,
final) surveyed established quant technique against this platform's four
actual open problems; its top-3 recommendations were all adopted and
shipped the same day (see `ENGINEERING_DECISIONS.md` #58,
`CHANGELOG.md`), while HMM regime-switching was rejected (trade
scarcity, not classifier noise, is the evidenced bottleneck) and the
heavyweight statistical tests were deferred (at n=20-60 they agree with
the existing 20-sample floor). Consequences for this backlog:
- **The execution-delay gate (`run_backtest.py --delay-check`) is now a
  STANDARD promotion-gate check for all future candidates** -- any
  strategy/config seeking promotion runs it alongside `--walk-forward`,
  early, before cross-asset/cross-year effort is spent on a candidate
  that would die on one candle of delay (the exact failure that killed
  the `structure_tp` candidate, `docs/ROBUSTNESS_REPORT.md` test 2).
- **The ATR stop-distance floor (`settings.MIN_STOP_ATR_MULT`, default
  0.0 = disabled) is built and awaiting A/B evaluation** -- enabling it
  changes trade acceptance, so a future backtest round comparing
  candidate floor values against the baseline is the natural next
  evidence step before it is ever turned on in paper trading; do not
  flip it above 0.0 without that evidence.
- **Shadow evidence quality is upgraded**: resolution model v2
  (1-candle-delayed fills, fees, slippage -- migration `6b085b904777`)
  is live as of the same-day trader restart, and
  `collect_regime_evidence` counts only v2 rows toward `n` -- the
  evidence now accumulating toward any future
  `RollingPerformanceSelector` wiring decision no longer rests on the
  zero-fee/zero-delay assumptions already proven decision-relevant.
- **Performance round 1 -- CLOSED (2026-07-16, Milestone 19).** The
  profiling analysis left pending after the session-usage-limit
  interruption noted above resumed and completed. `detect_order_block()`
  was diagnosed as 62.6% of backtest runtime (log-log scaling exponent
  ~2.26 measured across 500/1000/2000/3000-candle runs on real BTCUSDT
  data) and fixed with a reverse-scan (newest-to-oldest) early-exit that
  returns the same result the old forward scan kept, provably, with far
  less work. Verified bit-identical two ways: a 5,200-case property test
  against a verbatim reference copy of the old implementation (now a
  permanent regression test) and a real-data golden run across all 4
  flag combinations, which required patching `detect_order_block` in the
  three separate module namespaces that each bind it at import
  (`signal_engine`, `entry_point_engine`, `htf_ltf_confluence`).
  Window-capping history was rejected as behavior-unsafe (sweeps/FVGs/
  CHOCH legitimately reference arbitrarily old structure); a
  rolling-window-sum micro-optimization was tried and dropped for failing
  the bit-identical bar (float add/subtract is not associativity-safe).
  Measured 2.28-2.39x speedup (1000 candles 4.32s->1.81s, 2000 candles
  16.15s->7.09s) -- **Milestone-10-style evidence rounds
  (`--candles 3000 --periods 6`) now take ~17 minutes instead of ~40**.
  Full suite 653/653. See `ENGINEERING_DECISIONS.md` #59,
  `CHANGELOG.md`.
  - **Fix B -- CLOSED 2026-07-17 (Milestone 22), the deferral assumption
    CORRECTED, not just fulfilled as originally scoped.** The assumption
    above ("needs cross-walk-forward-step state inside a stateless
    `SignalEngine`") turned out to be wrong: consumer-semantics analysis
    of `entry_model.build_entry_model` found it only ever uses the
    highest-index FVG zone matching `bias` (`wanted_type` provably
    collapses to `bias`), so an M19-style fused reverse scan with early
    exit sufficed -- no stateful caching was ever required. New
    `signal_engine._select_unmitigated_fvg_zones` +
    `fvg.find_latest_unmitigated_fvg_zone` eliminate the quadratic term
    the same way Milestone 19 eliminated `detect_order_block`'s.
    `is_zone_mitigated` calls dropped 965,864->11,141 (~87x fewer); the
    FVG-mitigation chain fell from 22.2% to 1.68% of runtime; n=1000
    1.81x / n=2000 2.36x measured wall-clock. Verified via the same M19
    battery (two independent 5,200-case property tests against verbatim
    reference copies, plus a real-data golden run across all 4 flag
    combinations); the three-namespace-binding trap that complicated
    Milestone 19's verification does NOT recur here (grep-confirmed only
    one namespace binds the touched code). **Combined with Milestone 19,
    full-scale evidence rounds (`--candles 3000 --periods 6`) are now
    roughly 5x faster than the pre-Milestone-19 baseline.** Full suite
    692/692; code complete in the working tree, not yet committed. Full
    report: `docs/PERFORMANCE_M22.md`; rationale:
    `ENGINEERING_DECISIONS.md` #61(a).
  - **Remaining hotspots, recorded as future-round candidates, NOT
    scheduled**: `find_swing_highs`/`find_swing_lows` (consumed by
    multiple detectors -- bias, premium/discount, liquidity sweep, regime
    detection -- with no single dominant caller yet identified) and the
    `cf()` OHLCV accessor (already flagged in Milestone 19 as a large
    constant factor in self-time, proportionally larger now that both
    prior dominant costs have shrunk around it). Per this project's own
    established discipline (the same condition Milestone 19 attached to
    the since-closed Fix B): revisit **only if a future evidence round's
    actual wall-clock cost justifies the work** -- not on a fixed
    schedule, and not because either is a large-looking percentage on its
    own.
  - **The profiling methodology, not a specific committed script, is the
    reusable artifact for future performance rounds.** This round's
    profiling script lived in the session scratchpad, not the repo --
    the reusable pattern is: profile against real, anchored data at
    multiple candle counts to measure the actual scaling exponent (not
    assume O(n) or O(n^2) from reading code), isolate the single largest
    cost center, fix exactly one thing, and verify bit-identical output
    (property test against a reference copy plus a real-data golden run)
    before trusting any measured speedup. Any future performance round
    should follow this same sequence rather than starting from
    intuition about what "looks slow."
  - **New performance-backlog evidence (milestone 20b, 2026-07-16/17):
    `--delay-check` triples engine passes** (three full runs per
    config -- zero-delay, `entry_delay_candles=1`, plus the walk-forward
    scan) and wall-clock timing came in far over estimate on both
    milestone-20 configs (baseline ~3h05m, `--min-stop-atr 1.5` ~1h17m,
    against a ~5-15 min/config estimate). This strengthens the case for
    Fix B below whenever a future round needs `--delay-check` combined
    with `--walk-forward` at this project's standard 3000-candle/6-period
    scale -- not itself a reason to schedule Fix B on its own, per the
    condition already stated.

**Milestone 20 -- CLOSED (2026-07-16/17).** Full evidence:
`docs/ATR_FLOOR_EVALUATION.md` (final); rationale: `ENGINEERING_DECISIONS.md`
#60; cite, don't duplicate here. **20a** made the milestone 18b ATR
stop-distance floor A/B-testable (`BacktestEngine.run(min_stop_atr_mult=
...)` + `run_backtest.py --min-stop-atr`, disabled path proven
byte-identical), 7 new tests, 669/669. **20b** ran the pre-declared
evidence round (BTCUSDT 15m, 6x3000, `--end-date 2026-07-10`,
walk-forward + delay-check every config): baseline (floor off) 111
trades/+$3,400.62/6/6 profitable/walk-forward PASSED but delay-check
FAILED (PF 5.024->0.117, retention 0.023, sign flip); `--min-stop-atr
1.5` 60 trades (-46%)/+$1,113.35 (-67%)/3/6 profitable/walk-forward
FAILED/retention 0.079 (still 6x below the 0.5 pass bar)/sign flip
remains; 2.0x deliberately NOT run (CTO early stop, dead-config
discipline -- no plausible path from 0.079 to 0.5). **VERDICT: the
floor is REJECTED as a delay-robustness fix -- `settings.
MIN_STOP_ATR_MULT` stays `0.0` everywhere, not enabled in paper trading,
not recommended for promotion.** This closes the "ATR stop-distance
floor... awaiting A/B evaluation" item flagged under milestone 18 above
-- the evaluation ran, and the answer is no. **Headline finding:
production Legacy itself fails the 1-candle (15-minute) delay gate on
this window** -- previously unknown, read as "the edge lives inside a
sub-15-minute execution window," not a seconds-scale live-latency
failure (see "Phase 1 gate status" and "Explicitly NOT started" below
for the gate #4 consequence). No further ATR-floor work is scheduled;
future work on delay fragility should target the entry pipeline's
shared delay sensitivity, not this specific floor.

**Milestone 23 -- CLOSED (2026-07-17, committed `3e508d8`).** Closes the
instrumentation gap milestone 20b's ops notes flagged (the runner could
not report how many signals the risk gate rejected, or why -- the
111->60 trade-count drop under `--min-stop-atr 1.5` was an inferred
proxy, not a direct count). `BacktestResult.risk_rejections`
(`{total_signals, approved, rejected, by_reason}`) is purely
observational -- counts the same `risk_decision` the engine already
computes, never changes control flow. `scripts/run_backtest.py` now
prints a per-period rejection line whenever a period rejects anything,
plus an always-printed aggregate line across `--periods`. 690/690 at
commit. See `ENGINEERING_DECISIONS.md` #61(b).

**Milestone 24 -- CLOSED (2026-07-17).** Full evidence: `docs/
LEGACY_DELAY_ROBUSTNESS.md` (cite, don't duplicate here); rationale:
`ENGINEERING_DECISIONS.md` #62. Applied the house cross-year discipline
(already used for break-even, partial TP, and the tuned defaults) to
milestone 20b's own 2026 delay-gate finding, rather than exempting it.
One pre-declared run, the standard BTC 2025 anchor (6x3000 candles,
`--end-date 2025-07-10`, `--walk-forward --delay-check`), reproducing
the known BTC-2025 baseline to the cent before trusting the delay
numbers. **Result**: baseline PF 4.593 -> delayed PF 0.068, retention
0.015 (worse than 2026's 0.023), sign flip, delay gate FAILED;
walk-forward FAILED on the already-documented BTC-2025 degradation
(correctly attributed, not new). **VERDICT: STRUCTURAL** -- fails both
tested years, slightly worse in 2025 despite a materially different
regime (65 vs 111 trades); the regime-dependent hypothesis is falsified.
`docs/ADAPTIVE_ARCHITECTURE.md` gate #4's requirement note upgrades to
"structural property, confirmed across two independent years (2025,
2026) on BTCUSDT" -- the requirement's substance is unchanged. **Second
finding**: milestone 23's rejection instrumentation, used for the first
time in an evidence round, found 2025's low trade count (65 vs 111) is
not signal scarcity -- 869 raw signals, 804 (92.5%) rejected, 100% of
fired reasons `trades_today 2 reached MAX_TRADES_PER_DAY 2`. The
regime-bucket evidence starvation previously attributed to "Legacy
trades too selectively" is substantially a `MAX_TRADES_PER_DAY=2`
effect -- recorded as an insight, not acted on (see "Near-term" below
for the conditions under which this becomes an operator decision).
**Operational validation**: ~11 minutes wall time vs. ~3h05m for the
equivalent pre-milestone-22 run, confirming the milestone 19/22
performance work in production-scale use. Read-only -- no orders, no DB
writes, no code touched.

**Natural next steps after milestone 12** (superseded by the above --
retained for continuity): the data path to a justified
`RollingPerformanceSelector` was unchanged from what milestone 11
already established -- enabling `ENABLE_SHADOW_STRATEGY_SIGNALS` (an
OPERATOR decision) plus time, so the 8 currently-insufficient buckets
accumulate real regime-tagged signal/trade history at pass speed rather
than backtest speed. **Cross-asset regime analysis remains a possible
future round but is NOT recommended right now** -- all four experimental
strategies remain rejected (evidence round 1), and spending compute on a
second dimension of analysis for configs already shown to lose would be
the same undirected grinding this project's operator directive already
told it to stop doing. If shadow-mode data eventually fills the sparse
buckets, THAT is the next evidence-generating step -- not a second
backtest sweep of already-rejected strategies on a new asset.

Full architecture review, gap analysis, and prioritized build order:
`docs/ADAPTIVE_ARCHITECTURE.md`.

## CURRENT PRIORITY: Core Rule MVP completion (operator directive, 2026-07-11)

**Supersedes everything under "Immediate"/"Near-term" below until closed.**
Operator instruction: stop all parameter optimization, parameter sweeps,
and multi-year backtests until the remaining core Jade trading rules are
implemented. This also reverses the prior scope decision on equal-highs/
equal-lows (see "Done" below, the "correctly out of scope" entry) — the
operator has now explicitly named it as an in-scope core rule to
implement, not deferred pending a future spec decision. Priority order,
each item done in full (spec verification + implementation + tests +
this-file/PROJECT_STATUS/ENGINEERING_DECISIONS updates + a commit) before
moving to the next:

1. ✅ **Premium/Discount calculation from the current swing range** — DONE.
   `app.strategy.premium_discount.calculate_premium_discount`. New
   `docs/strategy_spec.md` section 8. 5 new unit tests. Detection-only:
   not yet wired into `SignalEngine`/entry filtering or TP (that wiring
   is item #4 below, which depends on this).
2. ✅ **Previous swing high / previous swing low detection** — DONE.
   `app.strategy.market_structure.find_previous_swing_high`/
   `find_previous_swing_low`. New `docs/strategy_spec.md` section 3
   bullet. 4 new unit tests.
3. ✅ **OB + FVG confluence entry model** — DONE. Opt-in
   `require_ob_fvg_confluence` on `build_entry_model` (default `False`,
   same discipline as `use_breaker_block`/`require_full_confluence`)
   changes zone selection from "either zone" to "both agree": a matching
   order block/breaker AND a matching FVG must both be present. Threaded
   through `SignalEngine`/`BacktestEngine`/`run_backtest.py
   --ob-fvg-confluence`. New `docs/strategy_spec.md` section 6 bullet.
   7 new unit/integration tests. Opt-in, default off, NOT YET A/B
   backtested — same "implemented != evidenced" discipline as every
   other experimental flag in this file.
4. ✅ **TP logic: previous high/low first, HTF-permitting extension to
   0.5 equilibrium** — DONE. Opt-in `use_structure_tp` on
   `build_entry_model` (default `False`): `take_profit` targets the
   previous swing high/low first, extends further to the premium/
   discount equilibrium when that reaches farther, falls back to the
   fixed-RR target when neither is a valid forward target; `rr` is
   recomputed to the trade's real reward:risk whenever a structure
   target is used (the Risk Engine's `MIN_RR` gate reads that field
   directly). Threaded through `SignalEngine`/`BacktestEngine`/
   `run_backtest.py --structure-tp`. New `docs/strategy_spec.md` section
   6 bullet; section 8's status line updated to reflect the wiring.
   8 new unit/integration tests. Opt-in, default off, NOT YET A/B
   backtested.
5. ✅ **Equal High / Equal Low liquidity detection** — DONE.
   `app.strategy.liquidity.detect_equal_highs`/`detect_equal_lows`:
   adjacent confirmed swing highs/lows within a 0.1% tolerance, reported
   as resting liquidity pools. New `docs/strategy_spec.md` section 2
   bullet. 8 new unit tests. Detection-only (not yet wired into
   `SignalEngine`), same status Premium/Discount originally shipped
   with.

All 5 Core Rule MVP items are now implemented, unit/integration tested
(27 new tests across items #2-#5: 4+7+8+8 — full suite now 247 tests,
0 known failures), and documented against
`docs/strategy_spec.md`. Items #3 and #4 ship opt-in and default OFF
pending A/B backtest evaluation — being implemented is not the same as
being evidenced, same standard already applied to `use_breaker_block`/
`require_full_confluence`/`use_breakeven`/`use_partial_tp`. The paused
optimization work below (BTCUSDT-2025 investigation, 2024 cross-year
extension, `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R` sweep) may now
resume per the original operator directive; separately, Phase 1 gate #3
(paper trading) validation is proceeding next per operator instruction
(2026-07-12).

## Phase 1 gate status

| Gate | Status | Evidence |
|---|---|---|
| 1. Backtest | ✅ Complete, extensively validated | 4 assets (BTC/ETH/SOL/XRP) x 2026, BTCUSDT also x 2025 — see "Done" below and `CHANGELOG.md`. Every core rule in `docs/strategy_coverage_audit.md` is now implemented, tested, and (where ever ambiguous) resolved with A/B evidence — zero remaining HIGH-priority items, see that doc's summary. **Controlled parameter sweep complete** (`docs/parameter_sweep_report.md`): 4 tuned defaults adopted (`_RR` 2.0->2.5, `_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT` 1.5->1.8), all cleared in-sample + out-of-sample + cross-asset + cross-year validation, +66.7% PnL on the standard BTC 2026 methodology with walk-forward still passing cleanly |
| 2. Walk-forward validation | ✅ CLOSED — PASSED on all 4 assets under BOTH the old AND the new (tuned) defaults | `run_backtest.py --walk-forward` — explicit PASS/FAIL criteria (profitable-period ratio, max losing streak, degradation trend). Old defaults: 24/24 periods profitable across BTC/ETH/SOL/XRP. New (tuned) defaults, re-confirmed 2026-07-11: **also 24/24 periods profitable across all 4 assets**, 0 losing streaks anywhere, no degradation in any asset, PnL improved on every asset vs. the old defaults (BTC +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%, total +33.3%) |
| 3. Paper trading | ✅ Pipeline complete and running | `scripts/run_paper.py` — real open/close/PnL against live OKX data, no real capital. Break-even wired in (off by default, permanently — see research findings). Risk controls (RR floor, daily/weekly loss limits, circuit breaker, position sizing) all real and enforced. Circuit breaker now auto-resets once a fresh daily/weekly check clears (previously a documented gap — a trip halted trading permanently with no operator-facing reset path) |
| 4. Small live validation | ❌ Not started, intentionally gated | Requires operator-issued API keys + staged approval — explicit stop condition, not a CTO-mode decision. **Scope decision (operator, 2026-07-11)**: replacing `settings.PLACEHOLDER_ACCOUNT_BALANCE` (fixed $10,000 constant used for position sizing and loss-limit math) with a real, live-queried exchange balance is explicitly deferred to THIS gate, not built during Phase 1 paper trading — paper trading has no real capital regardless, so the placeholder is honest and sufficient until real capital is actually at risk. **Hardened 2026-07-17 (milestone 20, `docs/ATR_FLOOR_EVALUATION.md`)**: verified low-latency (sub-candle, ideally seconds-scale) execution infrastructure — measured signal-to-fill latency, not assumed — is now an explicit prerequisite of this gate. Legacy's backtested edge on the tested BTCUSDT window did not survive a 15-minute (1-candle) entry delay (PF 5.024→0.117, sign flip); walk-forward validity is unchanged, this adds an execution-latency requirement, it does not invalidate the strategy |

## Done (this session, night CTO mode)

All three HIGH-priority `docs/strategy_coverage_audit.md` findings are
now wired, A/B tested on an initial ~31-day/3-period sample, AND
re-tested on a much larger 6-month/6-period sample (BTCUSDT, genuinely
varied conditions):

- ~~Wire break-even stop management into `BacktestEngine`~~ — DONE
  (opt-in `--breakeven`). Result: **positive, REPRODUCED**: +13.5% on
  the small sample, +9.2% on the 6-month sample. The most robust of the
  three findings -- same direction on two independent datasets.
- ~~Wire partial take-profit into `BacktestEngine`~~ — DONE (opt-in
  `--partial-tp`). Result: **negative, REPRODUCED**: -31.4% on the small
  sample, -32.6% on the 6-month sample -- reduced PnL in every single
  period tested across BOTH samples (12 of 12, no exceptions).
- ~~Wire Breaker Block detection into `SignalEngine`~~ — DONE (opt-in
  `--breaker-block`). Result: **REVISED, neutral -> slightly negative**.
  Zero effect on the small sample (the detector fires and can change
  output, but the 2 confirmed differences happened to fall inside an
  already-open trade's window). On the 6-month sample it fired for real
  once (1 of 6 periods) and the effect was negative (win rate 90.48% ->
  85.71%). Still thin evidence (1 affected period), but "neutral" no
  longer accurately describes it.
- ~~Fixed a real HTF over-fetch bug~~ found while running the 6-month
  test: `run_backtest.py` requested the same candle COUNT for LTF and
  HTF, so a large `--periods` request asked for years more HTF history
  than needed. Added `timeframe_to_timedelta()`/`htf_candle_count_for_span()`
  to size the HTF request off the real time span instead.

- ~~Wire break-even into paper trading~~ — DONE. Added
  `TradeTracker.update_stop_loss()` (raises `ValueError` on an unknown or
  already-closed trade id, same contract style as `close_trade`), a new
  `_maybe_move_to_breakeven()` step in `scripts/run_paper.py`'s
  `run_once()` (runs right after the exit-check step, before the
  concurrency guard -- mirrors `BacktestEngine`'s same-pass conservative
  ordering: a position reaching the 1R trigger this pass is still
  exit-checked against its OLD stop this same pass), and
  `settings.ENABLE_BREAKEVEN`/`BREAKEVEN_TRIGGER_R` (the trigger value is
  imported from `app.config.settings`, shared with `BacktestEngine`'s own
  `use_breakeven` A/B-test path, so paper trading and backtesting always
  agree on the same trigger distance). Off by default. Verified via 3 new
  `test_portfolio.py` tests (round-trip move, unknown-id error,
  closed-trade error) plus a real-temp-SQLite-DB script exercising long,
  short, idempotency (a stop already at breakeven is never re-processed
  or re-written), and the disabled-gate path — see CHANGELOG.md.

- ~~Re-run the 6-month deep test on ETHUSDT~~ — DONE. **Break-even does
  NOT reproduce**: +9.2% on BTCUSDT, -1.9% on ETHUSDT (mixed per-period,
  not uniformly negative) — the earlier "reproduced positive on two
  independent samples" claim rested on two BTCUSDT time windows, not two
  different assets; this is weaker evidence than that framing implied.
  **Breaker Block and Partial TP both REPRODUCE their negative
  verdicts, more strongly**: Breaker Block -3.8% (BTC) -> -12.0% (ETH,
  4/6 periods affected vs. 1/6 on BTC); Partial TP -32.6% (BTC) ->
  -35.4% (ETH, 6/6 periods worse on both assets, 12/12 total). No code
  changed from this finding — `ENABLE_BREAKEVEN` stays off by default,
  which this result is a reason FOR, not against. See CHANGELOG.md for
  the full comparison table.
- ~~Add a third, less-correlated symbol (SOLUSDT)~~ — DONE. **Break-even
  is now negative on 2 of 3 tested assets**: +9.2% (BTC), -1.9% (ETH),
  -4.8% (SOL) — SOLUSDT's result was uniformly flat-to-negative (0
  periods improved, 4 of 6 worse), not mixed the way ETHUSDT's was. The
  honest read is no longer "asset-dependent, could go either way" but
  "more often negative than positive on the assets tested so far," with
  the caveat that 3 assets is still a small sample of assets.
  **Breaker Block (-1.9% SOL) and Partial TP (-29.1% SOL, 6/6 periods
  worse) both reproduce their negative verdicts on all 3 assets now** —
  Partial TP is 18 of 18 tested periods worse across three independent
  assets with zero exceptions, the most robust finding in the project.
  See CHANGELOG.md for the full 3-asset comparison table.
- ~~Test a 4th asset (XRPUSDT)~~ — DONE. **Break-even's apparent
  2-of-3-negative trend did NOT hold** — XRPUSDT came back +5.4%,
  making the 4-asset picture BTC +9.2% / ETH -1.9% / SOL -4.8% /
  XRP +5.4%: a genuine 2-of-4/2-of-4 split, not a lean in either
  direction. This is itself the important result: a trend that looked
  real after 3 assets reverted to noise with a 4th, exactly the
  small-sample-of-assets risk flagged in the SOLUSDT entry above.
  **Breaker Block also softened** — XRPUSDT's +1.5% is its first
  positive result (3 of 4 assets still negative, so still not
  recommended, but "negative on every asset" is no longer accurate).
  **Partial TP remains unanimous**: -28.7% on XRP, negative on 4 of 4
  assets, 24 of 24 tested periods, zero exceptions — the only one of
  the three findings solid enough to actively recommend against, not
  just decline to recommend. See CHANGELOG.md for the full 4-asset
  comparison table.
- ~~Add time-anchored fetching (`--end-date`) and run a first cross-year
  test~~ — DONE. `CandleFetcher.fetch_ohlcv_history()` gained
  `end_time_ms`; `run_backtest.py --end-date YYYY-MM-DD` anchors a fetch
  to end at a specific past date instead of "now". First real use:
  BTCUSDT 6-month/6-period, anchored to 2025-07-10 instead of the
  existing 2026-07-10 window. **Break-even flips sign on the SAME
  asset**: +9.2% (2026) vs. **-1.9%** (2025) — the clearest evidence yet
  that this feature's effect is regime/time-dependent, not just
  asset-dependent; there is now no dimension (asset OR time) along which
  it has shown a reliable direction. Breaker Block had exactly 0.0%
  effect in the 2025 window (never fired differently from baseline).
  Partial TP reproduced almost exactly across YEARS too: -32.6% (2026)
  vs. -32.1% (2025) — now confirmed across 4 assets in one time window
  AND 2 time windows on one asset, the strongest evidence for any single
  finding in this project. See CHANGELOG.md for the full table.
- ~~Build walk-forward validation (Phase 1 gate #2)~~ — DONE.
  `scripts/run_backtest.py::walk_forward_report()` + `--walk-forward`
  CLI flag: evaluates a chronological period sequence against explicit,
  deterministic criteria (>= 66% profitable periods, <= 2 consecutive
  losing periods, no first-half-vs-second-half degradation >50%) rather
  than just an aggregate sum. Deliberately NOT a rolling
  parameter-refitting walk-forward (see `ENGINEERING_DECISIONS.md` #8 —
  no tunable parameters exist yet to refit). 10 new unit tests
  (`test_run_backtest.py`, previously zero coverage for
  `scripts/run_backtest.py`'s pure functions). **Real result: BTCUSDT
  2026 baseline PASSED** — 6/6 profitable, 0 losing streak, no
  degradation (second half actually outperformed the first). This is
  the formal Phase 1 gate #2 artifact.
- ~~Run `--walk-forward` on the other 3 assets' baselines
  (ETH/SOL/XRP)~~ — DONE. **All 4 assets PASSED**: 24/24 periods
  profitable, 0 losing streaks anywhere, every asset's second half
  flat-or-better than its first (BTC $237->$408, ETH $367->$541, SOL
  $586->$814, XRP $474->$476). Phase 1 gate #2 is now CLOSED for the
  current asset set. This specifically validates the baseline
  strategy's forward-time consistency, not the mixed experimental
  features (break-even/Breaker Block/partial-TP), which stay separately
  tracked.
- ~~Harden risk controls: circuit breaker auto-reset~~ — DONE (Phase 1
  checklist item "build production-ready risk controls"). Found and
  fixed a real gap: the circuit breaker had NO auto-reset mechanism at
  all and no operator-facing reset path (no dashboard endpoint, no
  CLI) — once tripped, trading halted permanently until someone
  manually edited the database. `run_paper.py::_check_drawdown_and_
  maybe_trip` now auto-resets once a fresh daily/weekly check both pass
  again, relying on `TradeJournal`'s reports already being UTC-day/
  ISO-week scoped (no new date-math needed). Alerts fire on auto-reset
  too, not just on trip. Real-balance integration
  (`PLACEHOLDER_ACCOUNT_BALANCE`) explicitly deferred to Phase 1 gate #4
  per operator decision — see the Phase 1 gate table above and
  `app/config.py`. Verified via a real-temp-SQLite-DB script (3
  scenarios: auto-reset when clear, trips on a real breach, stays
  tripped while still breached).
- ~~Resolve the spec/implementation ambiguity in confluence strength~~ —
  DONE (audit item #9, a genuine core JadeCap rule with a real
  spec-vs-code disagreement -- confirmed in scope per the operator's
  "only core rules" instruction, unlike equal-highs/lows below). Added
  opt-in `require_full_confluence` (`--strict-confluence` CLI flag),
  A/B tested across all 4 assets, 6-month/6-period each: requiring BOTH
  sweep AND CHOCH (the strict, spec-literal reading) cuts trade count
  75.9% (457 -> 110) for a per-trade PnL only 3.8% different from the
  looser default -- not meaningfully higher quality, just far fewer
  trades of the same quality, costing ~75% of total profit.
  **Resolved in favor of the existing (looser) implementation** —
  `docs/strategy_spec.md` section 6 rewritten to explicitly state the
  rule (sweep OR CHOCH, not both) with this evidence cited directly in
  the spec text, closing the ambiguity for good. 5 new tests. See
  CHANGELOG.md for the full comparison table.
- ~~Equal-highs/equal-lows liquidity detection~~ — NOT implemented as of
  that round, correctly out of scope AT THE TIME: `docs/strategy_spec.md`
  section 2 did not define this rule, so it would have been a NEW rule
  requiring a spec decision first, not an ambiguity resolution (unlike
  confluence strength above). **SUPERSEDED 2026-07-11**: the operator has
  now explicitly named this as an in-scope core rule (see "CURRENT
  PRIORITY" section at the top of this file, item #5) — implementation
  proceeding with the same spec-first-then-code discipline this entry
  originally called for.
- ~~Controlled parameter sweep (`_RR`/`_STOP_BUFFER`/`_LOOKBACK`/
  `_IMPULSE_MULT`)~~ — DONE. One-at-a-time sweep, in-sample selection by
  robustness (not highest profit) on BTCUSDT, validated on held-out
  out-of-sample periods, then ETHUSDT/SOLUSDT/XRPUSDT, then a cross-year
  check (BTCUSDT 2025) added specifically because cross-asset robustness
  alone was already shown insufficient (break-even). **All 4 candidates
  ADOPTED as new defaults**: `_RR` 2.0->2.5, `_STOP_BUFFER`
  0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT` 1.5->1.8. Standard-
  scale confirmatory run (BTC 2026, `--periods 6 --walk-forward`):
  **+66.7% PnL, walk-forward still PASSED**. Full methodology, every
  number, and stated caveats in `docs/parameter_sweep_report.md`.
  Discovered along the way: `BacktestEngine`'s walk-forward scan is far
  worse than linear in period length (3000 candles ~88s vs. 1500
  candles ~7s) — an initial sweep attempt at the usual 3000-candle scale
  ran 80+ minutes with no visible progress before being killed and
  redesigned.
- ~~Re-run walk-forward validation on ETHUSDT/SOLUSDT/XRPUSDT at the
  standard 3000-candle/6-period scale under the NEW tuned defaults~~ —
  DONE. **All 4 assets PASSED unanimously**: 24/24 periods profitable,
  0 losing streaks anywhere, no degradation in any asset, PnL improved
  on every single asset vs. the old defaults (BTC +66.7%, ETH +4.6%,
  SOL +32.6%, XRP +39.0%, combined total +33.3%). Phase 1 gate #2 is now
  fully closed under the new tuned defaults, matching how it was
  originally closed for the old ones — not just spot-checked on BTC.
- ~~Run 2025 cross-year tests on ETHUSDT/SOLUSDT/XRPUSDT under the new
  tuned defaults (plus re-run BTC 2025 at standard scale)~~ — DONE.
  **8 of 9 standard-scale asset/year combinations PASSED cleanly**
  (2026: BTC/ETH/SOL/XRP all PASSED; 2025: ETH $3090.03/SOL $4289.78/XRP
  $4300.39 all PASSED). **1 real, disclosed exception**: BTCUSDT 2025 at
  the standard 3000-candle scale FAILED its walk-forward check on the
  degradation criterion — every period was still individually
  profitable ($1714.56 total, 6/6), but the second half's average PnL
  retained only 35.4% of the first half's (below the 50% threshold).
  This did NOT reproduce in the sweep's own BTC-2025 spot-check (which
  used smaller 1500-candle periods and didn't flag it) — a real,
  informative example of walk-forward conclusions depending on period
  granularity, not just underlying data. Not treated as a reason to
  revert the new defaults (BTC 2025 stayed net profitable throughout),
  but IS a disclosed caveat: the new defaults' robustness on BTCUSDT is
  weaker across time than across assets. See CHANGELOG.md for the full
  table.

See `CHANGELOG.md`/`HANDOFF.md` for full evidence tables on all of this.

## Profitability sprint results (2026-07-12, operator-directed autonomous session)

Built `scripts/experiment_runner.py` (fixed-anchor fetch, in-sample/
out-of-sample split, JSON results ledger -- see
`ENGINEERING_DECISIONS.md` #37) and ran it against the 3 previously-
unvalidated Legacy-pipeline flags plus one justified combination plus one
new conservative-exit variant. Full results, diagnosis, and rejected-
candidate reasons in `docs/PROFITABILITY_EXPERIMENT_REPORT.md`.

**`use_structure_tp` clears the three-metric keep rule** (Net Profit,
Profit Factor, and worst-period Drawdown all improve) under rigorous,
fixed-anchor, out-of-sample-confirmed methodology -- superseding an
earlier, less-rigorous same-session ad-hoc verdict that had rejected it on
drawdown (see `ENGINEERING_DECISIONS.md` #38 for the full reconciliation).
`ob_fvg_confluence`, `premium_discount_filter`, and the
`structure_tp`+`premium_discount_filter` combination were all tested and
REJECTED. A new opt-in `structure_tp_max_r` conservative-exit variant
(`ENGINEERING_DECISIONS.md` #39) also clears the bar with a more
conservative profile. **Production default is UNCHANGED** -- one
experiment (1 asset, 1 time window) is evidence toward a future decision,
not sufficient grounds to flip a default, per this project's own standing
discipline (decisions #14/#15).

**Cross-asset validation COMPLETE (2026-07-13)**: `structure_tp` promoted
to documented CANDIDATE status (not production) for **BTC and SOL**
(clean keep, out-of-sample confirmed on both). **XRP**: no candidate --
`structure_tp_capped_3r` ties baseline's drawdown exactly rather than
strictly improving it, a near-miss worth revisiting if the tie rule is
ever loosened to `<=` (operator decision, not made this round). **ETH**:
no viable candidate found across 2 independent time windows and 6 config
variants -- diagnosed as a Legacy-baseline-level regime characteristic in
both tested windows, not a `structure_tp`-family defect; NOT something
further parameter search should chase (would be curve-fitting to the
specific windows tested). Full detail:
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 12.

**Continuous optimization round (2026-07-13/14)**: applying the same
out-of-sample-robustness-first ranking to BOTH BTC and SOL independently
converged on the SAME best candidate config for both:
`use_structure_tp=True, structure_tp_max_r=3.0,
require_premium_discount_filter=True` (better Sharpe/drawdown/
out-of-sample Profit Factor than plain `structure_tp` on both assets,
despite lower raw profit). XRP's drawdown floor (0.7826%) confirmed
identical across 6 independent configs -- not a solvable configuration
gap within this feature family, further XRP search stopped. Full detail:
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 13.

**Cross-year validation (2026-07-14)**: BTC's unified candidate CONFIRMED
across 2 independent years (2025 AND 2026), out-of-sample confirmed both
times -- the most robustly validated candidate in this project's history.
SOL's candidate is MIXED across years: confirmed in 2026, but drawdown
regresses (still small, still profitable) and out-of-sample is
inconclusive (zero holdout trades) in 2025 -- confidence downgraded to
"moderate," not pursued for a new candidate since profit/PF still improve
and this isn't a clean failure. Fees (0.05%/leg) and slippage (0.02%)
confirmed already realistic and already applied to every result in this
report (matches `paper_broker.py`'s real constants). Full detail:
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 14.

**Third-year validation (2026-07-14, BTC 2024 anchor)**: revises BTC's
confidence from "highest" to "high" -- 2024 is a genuinely difficult
regime where BOTH baseline and candidate fail walk-forward (not a
candidate-specific defect), but the candidate has FEWER profitable
periods than baseline in this window (2/5 vs 3/5) despite higher absolute
profit. BTC remains confirmed in 2 of 3 independent years (2025, 2026)
with out-of-sample support in both. `ROADMAP.md`'s own long-standing
"extend cross-year testing to 2024" item is now addressed for this
candidate specifically. Full detail:
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 14.2.

**Robustness validation (2026-07-14): NOT PROMOTED — material failure
found.** Ran the operator's full 7-part robustness suite (Monte Carlo,
execution delay, slippage stress, fee stress, volatility regimes,
sessions, leverage) against the BTC candidate as the designated
production candidate. 5 of 7 tests pass cleanly; 1 (leverage) is a
non-issue by construction. **Test 2 (randomized execution delay) is a
material failure**: a single 5-minute delay flips the candidate from
Profit Factor 5.24 to 0.16 (full sign reversal), traced to its very tight
average stop distance (0.23% of price). Per the operator's own rule
("only reject if robustness materially fails"), this candidate is NOT
promoted as deployable-as-is. Full detail: `docs/ROBUSTNESS_REPORT.md`.
This does not invalidate sections 12-14's cross-asset/cross-year work --
it's a latency-fragility finding backtesting alone could never surface
(`run_backtest()` has always assumed zero-latency fills). **Next step is
an operator decision** (not assumed): accept only with verified
sub-candle execution infra, re-derive a wider-stop variant of the SAME
already-validated feature family, or hold at "validated but not
deployable" -- explicitly not treated as "go search for a new strategy"
per this round's own instruction.

Paper trading (Legacy engine, all experimental flags off) started
2026-07-12 19:29:11 and is running continuously -- see
`docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 2 for status and the
sandbox-persistence caveat.

## Immediate (highest ROI, unblocked, no operator input needed)

**Un-paused 2026-07-12**: the 5-item Core Rule MVP (see "CURRENT
PRIORITY" above) is now complete, meeting the condition the operator set
on 2026-07-11 for resuming this section. Left otherwise unchanged below
from when it was paused. Phase 1 gate #3 (paper trading) validation is
being prioritized first per operator instruction (2026-07-12); this list
resumes whenever that's picked back up.

1. **Investigate the BTCUSDT 2025 standard-scale degradation directly**
   — periods 4-6 (Apr-Jun 2025) were meaningfully weaker than periods
   1-3 (Jan-Mar 2025) under the new tuned defaults specifically (worth
   checking whether the OLD defaults showed the same pattern in that
   exact window, to isolate whether this is a new-defaults-specific
   sensitivity or a genuine BTC-specific regime shift in that period
   that would show up regardless of parameters).
2. **Extend cross-year testing to 2024** — only 2025/2026 tested so far
   on any asset; a 2024 window (further back, `--end-date` already
   supports it) would be a genuinely third, independent macro period.
   **Optional, cheap follow-up flagged by milestone 24**: a
   `--walk-forward --delay-check` run on the same 2024 BTCUSDT anchor
   would extend the now-STRUCTURAL delay-fragility finding
   (`docs/LEGACY_DELAY_ROBUSTNESS.md`) from a two-year to a three-year
   evidence base at near-zero incremental cost (~11 minutes per the
   milestone 24 timing) — not required (two independent years already
   meets this project's cross-year evidence bar), but a natural
   completeness item if this section is picked back up.
3. **Break-even and Breaker Block: stop looking for a "final verdict" at
   all — treat "no reliable direction across assets OR time" as the
   actual, settled conclusion.** Both now show sign flips or
   inconsistent effects across every axis tested (4 assets, 2 time
   windows on the asset with the strongest original signal). Further
   testing of either dimension alone has clearly diminishing ROI.
4. **`ENABLE_BREAKEVEN` stays off by default, permanently** — reaffirmed,
   now by a same-asset sign flip across time in addition to the earlier
   cross-asset coin flip. This is not being revisited without a
   fundamentally different kind of evidence (e.g. a parameter change
   that's shown to correlate with the sign, not just "one more sample").

## Near-term (needs the above first, or is inherently larger scope)

5. **Parameter sweep of `BREAKEVEN_TRIGGER_R`/`PARTIAL_TP_TRIGGER_R`/
   `PARTIAL_TP_PORTION`** — deliberately EXCLUDED from the 2026-07-11
   controlled sweep (see `docs/parameter_sweep_report.md` §1): those
   three only affect the break-even/partial-TP EXPERIMENTAL features,
   which are off by default with negative-or-inconsistent evidence, so
   tuning their triggers wasn't part of MVP-baseline hardening. Given
   Partial TP's negative result was explained by this strategy's
   SPECIFIC win-rate/RR profile (which the `_RR` sweep just changed from
   2.0 to 2.5), a smaller `PARTIAL_TP_TRIGGER_R` or re-testing against
   the NEW `_RR` might change that conclusion -- worth investigating
   with the same in-sample/out-of-sample/cross-asset/cross-year
   discipline used for the core-rule sweep, not by assumption. **Hard
   rule, non-negotiable, unchanged**: any sweep MUST reserve genuinely
   held-out data never inspected until the final decision.
6. ~~**Equal-highs/equal-lows liquidity detection**~~ — MOVED to
   "CURRENT PRIORITY" section at the top of this file (item #5); no
   longer near-term/deferred as of the 2026-07-11 operator directive.
7. **`MAX_TRADES_PER_DAY` evidence-throughput question — flagged, NOT a
   task, operator decision only if ever raised.** Milestone 24
   (`docs/LEGACY_DELAY_ROBUSTNESS.md`, `ENGINEERING_DECISIONS.md` #62)
   found the 2025 BTCUSDT window's thin trade count is substantially a
   `trades_today 2 reached MAX_TRADES_PER_DAY 2` effect (804 of 869 raw
   signals rejected, 92.5%, for that reason alone), not a signal
   drought — meaning this same cap is also plausibly a major
   contributor to the evidence-starved regime buckets
   `docs/REGIME_PERFORMANCE_ANALYSIS.md` and the shadow-mode work
   (milestones 11/13/15/17) have been trying to fill by other means
   (multi-symbol shadow collection, longer accumulation time). This is
   explicitly NOT a recommendation to raise the cap -- it is a
   risk-limit constant, and any change to it is an operator-gated
   production-behavior decision requiring the same A/B-evidence-first
   discipline as `MIN_STOP_ATR_MULT`/`ENABLE_BREAKEVEN`, not a CTO-mode
   decision. Recorded here only so the connection between "evidence
   throughput problem" and "deliberately chosen risk ceiling" isn't
   lost if the operator ever wants to revisit it.

## Phase 2 (deferred, out of scope for Phase 1 — do not implement yet)

Per the operator's scope-lock directive: Phase 1 is JadeCap only. These
items do not directly increase the probability that JadeCap specifically
becomes a profitable automated trading system — they are architecture/
scalability ideas that only become relevant AFTER JadeCap has cleared
Backtest -> Walk-Forward -> Paper Trading -> Small Live Validation.
Documented here so they aren't lost, not started.

- **Multi-strategy plug-in architecture** — today `SignalEngine` is a
  single hardcoded pipeline. If/when a second, genuinely different
  strategy is worth trying (not just parameter variants of the current
  one), the Strategy Engine's interface (`generate_signal(symbol,
  ltf_candles, htf_candles) -> TradeSignal | None`) is already a clean
  enough contract to support multiple implementations behind it — no
  redesign needed yet. Explicitly a Phase 2 idea (this would be the
  first step toward a "multi-strategy platform," which the scope lock
  names directly as out of scope for Phase 1).
- **Monte Carlo readiness** — the backtest engine's trade list
  (`BacktestResult.trades`) already has everything needed (`pnl`,
  `direction`, `size`, timestamps) to bootstrap/reshuffle trade
  sequences for Monte Carlo drawdown analysis. Not yet built; a natural
  next step once there are enough real trades across enough periods to
  make resampling meaningful (still on the small side for resampling).
  Not required for JadeCap to clear the 4 Phase 1 gates, so deferred.

## Explicitly NOT started, and why

- **Live Trading** (`LiveBroker`, `exchange/okx_client.py`,
  `exchange/orangex_client.py`) — all `NotImplementedError` stubs,
  deliberately. This is Phase 1 gate #4 (Small Live Validation),
  requires, IN ORDER: (a) out-of-sample validation across genuinely
  different market regimes (substantial progress -- 6-month results now
  exist for FOUR assets AND 2 years on BTCUSDT, walk-forward validation
  built and PASSED for ALL FOUR assets, but two of the three
  experimental features show no reliable direction across assets OR
  time — see items #1-2 above for remaining cross-year work), (b)
  replacing `settings.PLACEHOLDER_ACCOUNT_BALANCE` with a real,
  live-queried exchange balance (explicitly deferred here, not built
  during Phase 1 paper trading — see the Phase 1 gate table above), (c)
  operator-issued OKX API keys with withdrawal
  disabled, (d) a small live-capital limit agreed with the operator, (e)
  step-by-step operator approval at each stage per
  `docs/live_trading_checklist.md`, **(f) verified low-latency
  (sub-candle, ideally seconds-scale) execution infrastructure — measured
  signal-to-fill latency, not assumed (added 2026-07-17, milestone 20:
  `docs/ATR_FLOOR_EVALUATION.md` found Legacy's backtested edge on the
  tested BTCUSDT window did not survive a 15-minute entry delay, PF
  5.024→0.117 with a profit-to-loss sign flip)**. None of this proceeds
  without the operator present — API credential provisioning and
  live-trading approval are both explicit stop conditions, not something
  a CTO-mode session decides alone.
- **Paper trading Breaker Block or Partial TP** — NOT planned currently.
  Breaker Block's backtest result is now slightly negative (was
  neutral); Partial TP's is negative on two independent samples. Neither
  has positive evidence to justify wiring into paper trading.
