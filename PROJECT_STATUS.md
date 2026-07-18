# PROJECT_STATUS — JadeCap Automated Trading Bot

This file is the always-current, English snapshot: what the system does
*right now*, as of the latest commit on `master`. It intentionally has
no history — for the round-by-round session log (in Korean, matching
this project's established working language for that file), see
`HANDOFF.md`. For chronological release notes, see `CHANGELOG.md`. For
the "why" behind specific non-obvious engineering choices, see
`ENGINEERING_DECISIONS.md`. For forward-looking prioritization, see
`ROADMAP.md`.

Last updated: 2026-07-12 (all 5 JadeCap MVP core trading rules from the
2026-07-11 operator directive are now COMPLETE: Premium/Discount,
previous swing high/low, OB+FVG confluence, structure-based TP, Equal
High/Equal Low. Progress tracked in the "Core rule completion (MVP)"
section below. Previous swing high/low
(`app.strategy.market_structure.find_previous_swing_high`/
`find_previous_swing_low`) shipped in an earlier round; this round
closed out the remaining three: **OB + FVG confluence entry model**
(opt-in `require_ob_fvg_confluence` on `build_entry_model`, default off,
not yet A/B backtested), **structure-based take-profit** (opt-in
`use_structure_tp` on `build_entry_model`, wires Premium/Discount in as
a TP extension target, default off, not yet A/B backtested), and
**Equal High/Equal Low liquidity detection**
(`app.strategy.liquidity.detect_equal_highs`/`detect_equal_lows`,
detection-only). 27 new tests across the 4 non-Premium/Discount items
(4 previous-swing + 7 OB+FVG confluence + 8 structure-TP + 8 equal
highs/lows) — 247 total, up from 220, 0 known failures — see
`docs/strategy_spec.md` sections 2/3/6/8 and `ENGINEERING_DECISIONS.md`.
Next: Phase 1 gate #3 paper-trading validation, per operator instruction
(2026-07-12). Prior round, unchanged below: completed a
full 2025 cross-year check on all 4 assets under the new tuned defaults
at the standard reporting scale -- **8 of 9 combinations PASSED
cleanly** (2026: BTC/ETH/SOL/XRP all PASSED; 2025: ETH/SOL/XRP all
PASSED). **1 real, disclosed exception**: BTCUSDT 2025 FAILED its
walk-forward degradation check (still net profitable in all 6 periods,
$1714.56 total, but the second half's average PnL retained only 35.4%
of the first half's) -- notably, this did NOT show up in the parameter
sweep's own smaller-scale BTC-2025 spot-check, a real example of
walk-forward conclusions depending on period granularity. Not reverting
the new defaults over this (BTC 2025 stayed profitable throughout), but
recorded honestly as a caveat rather than omitted. Earlier this session:
re-confirmed walk-forward on all 4 assets at 2026 under the new tuned
defaults (BTC +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%, combined
+33.3%); completed the parameter sweep itself (`_RR` 2.0->2.5,
`_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15, `_IMPULSE_MULT`
1.5->1.8, full methodology in `docs/parameter_sweep_report.md`);
resolved the confluence-strength spec ambiguity; hardened risk controls
(circuit breaker auto-reset). Scope locked by operator directive: Phase
1 = JadeCap only, tracked against 4 explicit gates below. See
`CHANGELOG.md` for the full chronological history of this session's
findings).

## Adaptive platform pivot (2026-07-15, operator directive)

Objective changed from "find one profitable strategy" to "build an
adaptive trading system that survives changing market conditions" --
see `ROADMAP.md`'s "Objective change" section and the full design in
`docs/ADAPTIVE_ARCHITECTURE.md` (architecture diagram, Market Regime
Detector design, Strategy Interface spec, Strategy Selection Engine,
Risk Engine extensions, Performance Database schema, 8-milestone
roadmap). **Milestones 1-7 built**:

1. **Strategy Interface**: `app.strategy.strategy_interface.Strategy` (a
   `Protocol`), with `LegacyStrategy`/`JadeStrategy` adapters wrapping the
   existing, unchanged `SignalEngine` integration points -- Legacy is now
   "Strategy A," Jade is "Strategy B," both conforming to one interface,
   neither's underlying behavior touched. 7 tests.
2. **Performance Database schema**: `Trade` gains 6 nullable columns
   (`market_regime`, `strategy_name`, `holding_time_seconds`,
   `max_adverse_excursion`, `max_favorable_excursion`, `latency_ms`); new
   `strategy_performance_snapshots` table for rolling per-strategy/
   per-regime metrics. Schema-only -- nothing populates these yet.
3. **Market Regime Detector**: `app.regime.regime_detector.
   detect_market_regime()` -- composite trend/volatility classification
   plus breakout/mean-reversion/liquidity-sweep-environment event flags,
   built from objective metrics (ADX, percentile-relative realized
   volatility, swing structure, VWAP, distance-from-MA, liquidity sweep
   frequency). 20 tests. Not yet wired into any live path.
4. **Strategy Selection Engine**: `app.strategy.selector.
   StrategySelector` (Protocol) + `DefaultToLegacySelector`, which
   selects `legacy` unconditionally regardless of regime -- deliberately,
   since no regime-tagged trade history exists yet to justify anything
   else. 4 tests. Wired live as of milestone 7b below (via a second
   selector, `ConfigurableFallbackSelector`, not `DefaultToLegacySelector`
   itself -- see that entry for why).
5. **MAE/MFE/latency tracking**: `scripts/run_paper.py` now populates
   `max_adverse_excursion`/`max_favorable_excursion` (running maximums in
   R-multiples, updated every pass) and `holding_time_seconds`/
   `latency_ms` at close/open respectively, via two new `TradeTracker`
   methods. `market_regime`/`strategy_name` remain unpopulated
   (deliberately out of this milestone's scope). 6 tests. Code change
   only -- does not affect the already-running paper trader process
   (PID 24616) until its next restart.
6. **Rolling performance snapshots + auto-disable**: `app.portfolio.
   performance_snapshots.StrategyPerformanceEvaluator` computes rolling
   win_rate/profit_factor/expectancy/max_drawdown/sharpe/sortino/
   recovery_factor per strategy (R-multiple based) over its most recent
   trades and persists a `StrategyPerformanceSnapshot`, auto-flagging
   `is_disabled` once a strategy has >=20 trades and a rolling profit
   factor <= 1.0. Now wired as a real producer (called from
   `scripts/run_paper.py` on every trade close); `strategy_name` is now
   populated on new trades too (a justified reversal of milestone 5's
   deferral -- this milestone cannot group by strategy without it).
   Fixed 2 latent bugs surfaced by writing the first real inserts into
   this table: a Postgres-only `now()` migration default SQLite can't
   run, and a same-second snapshot-ordering tie in `latest_snapshot()`.
   14 tests. `is_disabled` is computed but not yet consulted by the
   Strategy Selection Engine.
7. **Risk Engine extensions**: `RiskManager.evaluate()` gains
   `strategy_disabled: bool` (rejects if the originating strategy's
   latest snapshot is auto-disabled); `calculate_position_size` gains
   `volatility: str | None` (scales risk-percent to 0.5x in
   `high_volatility` regimes, disclosed-not-tuned). Both are
   caller-computed plain values, not lookups inside `app.risk` --
   preserves that package's existing DB/regime-import-free layering.
   Wired live in `scripts/run_paper.py` (fails open to pre-milestone-7
   behavior on any error); `Trade.market_regime` now populated too as a
   byproduct, which surfaced and fixed a real scoping bug in milestone
   6's regime filter. Correlated exposure check (the 3rd, Low-priority
   extension) explicitly deferred -- still no scenario where multiple
   strategies are concurrently active. 12 tests.
7b. **Strategy Selection Engine wired into paper trading** (operator
    directive, 2026-07-16): `scripts/run_paper.py`'s signal-generation
    step now branches on new flag `settings.USE_STRATEGY_SELECTOR`
    (default `False`, reproduces the prior direct-`SignalEngine` call
    path byte-for-byte -- proven by a regression test). `True` routes
    through a new `ConfigurableFallbackSelector`, which honors
    `USE_JADE_ENGINE` as an explicit operator override and otherwise
    deterministically selects `legacy` -- regime is recorded (logs +
    `Trade.strategy_config`: `selection_reason`, `fallback_reason`,
    `strategy_version`) but never influences the choice; no automatic
    regime-based switching yet. `Strategy` gains a `version` field
    (`"1.0"` on both adapters). 21 new tests (16 selector, 2 interface,
    plus the settings-default check and the SignalEngine-equivalence
    proof); found and fixed a real test-isolation bug along the way
    (module-level vs. function-level `app.*` imports binding to
    different module instances after a DB-fixture test purge -- see
    ENGINEERING_DECISIONS.md #50). 454/454 full suite passing.
8.1. **Live paper-DB migrated to schema head** (operator directive,
    2026-07-16): the live `backend/paper_validation.db` predated this
    project's alembic discipline (no `alembic_version` table at all), and
    `scripts/run_paper.py` never runs migrations -- every milestone since
    #2 had added columns/tables this DB never received, so a restart on
    current code would have crashed on its first trade INSERT. New
    `app.database.migrate_existing.migrate_database()` fingerprints which
    of 4 historical schema generations an un-stamped DB matches, stamps
    that revision, and upgrades to head (refuses unrecognized schemas
    rather than guessing); `scripts/migrate_paper_db.py` is a thin CLI
    over it. 11 new tests. Applied to the live DB this session: backed up
    to `backend/paper_validation.db.backup-20260715T174615Z`, stamped
    `4b8a822a475b` (its detected generation), upgraded to head
    (`e3110e6a6b59`), verified -- the existing `bot_state` row survived
    intact, and `trades`/`signals`/`strategy_performance_snapshots` were
    empty both before and after (nothing was at risk). 465/465 full suite
    passing. Full rationale: `ENGINEERING_DECISIONS.md` #51.
9. **New strategy-content modules, quarantined** (2026-07-16): four new
    `Strategy`-Protocol modules -- `trend_following.TrendFollowingStrategy`,
    `range_trading.RangeTradingStrategy`, `breakout.BreakoutStrategy`,
    `volatility_expansion.VolatilityExpansionStrategy` -- the platform's
    first strategies that are NOT `SignalEngine` wrappers, closing out the
    last item on `docs/ADAPTIVE_ARCHITECTURE.md` section 7's roadmap. Each
    is detection-only, reuses existing indicator helpers (zero
    reimplemented indicators), and discloses every threshold as a
    standard textbook value, not backtest-tuned. New
    `app.strategy.experimental.EXPERIMENTAL_STRATEGIES` quarantines all
    four -- `AVAILABLE_STRATEGIES` (the ONLY registry either configured
    selector consults) stays exactly `{legacy, jade}`, untouched;
    promotion requires real backtest/walk-forward evidence first.
    `BacktestEngine.run()` gained an additive `strategy: Strategy | None`
    injection point (signal source only -- risk gating, sizing, fills,
    fees, slippage, PnL all unchanged) so experimental strategies can be
    evidenced through the exact same fee/slippage/walk-forward pipeline as
    production; `scripts/run_backtest.py --strategy NAME` exposes it. 38
    new strategy/registry tests + 2 new injection tests = 40 new tests.
    505/505 full suite passing. Full rationale:
    `ENGINEERING_DECISIONS.md` #52.
10. **Evidence round 1** (2026-07-16): first backtest evaluation of the
    four milestone-9 experimental strategies vs. the Legacy baseline,
    via the `--strategy` pipeline, on identical BTCUSDT 15m candles
    (`--candles 3000 --periods 6 --end-date 2026-07-10 --walk-forward`).
    Baseline (Legacy): 111 trades, 75.68% win rate, +$3,400.62, 6/6
    profitable periods, 1.64% worst drawdown, walk-forward PASSED. All
    four experimental strategies FAILED walk-forward: `trend_following`
    (146 trades, -$1,009.78, 1/6), `range_trading` (258 trades,
    -$2,321.08, 2/6), `breakout` (347 trades, -$5,329.19, 0/6, "clearly
    dead"), `volatility_expansion` (246 trades, -$892.45, 3/6,
    least-bad). **No promotions** -- promotion requires cross-asset +
    cross-year + out-of-sample confirmation, not attempted this round.
    No code defects; losing money is a valid evidence outcome. Full
    report: `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`.
11. **Shadow-mode observability** (2026-07-16): new `regime_snapshots`
    (one row per paper pass) and `shadow_signals` (one row per signal a
    non-active registered strategy would have generated) tables
    (migration `36cb62e9e2ac`), new ORM models `RegimeSnapshot`/
    `ShadowSignal`, new `app.portfolio.shadow_recorder.
    record_shadow_pass()`, wired into `scripts/run_paper.py` at the
    no-signal early return and the end of the full trade path. New
    settings flag `ENABLE_SHADOW_STRATEGY_SIGNALS: bool = False`
    (**default off** -- not enabled in the live process; takes effect
    only on the paper trader's next restart). Exists to start
    accumulating the regime-tagged dataset `docs/ADAPTIVE_ARCHITECTURE.md`
    section 4.3's future `RollingPerformanceSelector` needs, which to
    date has accumulated at trade speed only (effectively zero rows). 16
    new tests. **518/518 full suite passing** (was 505). Full rationale:
    `ENGINEERING_DECISIONS.md` #53.
12. **Regime-tagged backtesting + per-regime performance analytics +
    evidence round 2** (2026-07-16): `BacktestEngine.run()` gained
    `tag_regimes: bool = False` -- when `True`, each accepted/simulated
    trade gets a `"market_regime"` key (full classification, computed
    post-risk-approval at the signal's own candle index, same tagging
    point as `run_paper.py`); when `False`, the key is absent and
    behavior is byte-identical. New `app.backtesting.regime_analysis`
    (pure functions: `regime_bucket`/`aggregate_by_regime`/
    `comparison_table`, `MIN_TRADES_FOR_CONFIDENCE=20`) and new
    `scripts/analyze_regime_performance.py` CLI. **Real bug found and
    fixed**: the CLI crashed with `UnicodeEncodeError` on a Unicode
    marker inside `print(table)` under Windows' default cp1252 console
    encoding -- AFTER a completed multi-minute run and BEFORE the
    results were written to a file, losing the run's output outright.
    Fixed with an ASCII marker plus reordering the CLI to write its
    output file before printing to console. 4 new `BacktestEngine`
    tests + 17 new `regime_analysis` tests. **539/539 full suite
    passing** (was 518). **Evidence round 2**: same anchor as round 1
    (BTCUSDT 15m, `--candles 3000 --periods 6 --end-date 2026-07-10`),
    pooled totals reproduced round 1 exactly. No regime bucket shows an
    experimental strategy credibly beating Legacy -- the only bucket
    with n>=20 on both sides (`weak_trend/normal_volatility`) has Legacy
    at +$26.28 expectancy/PF 3.30 (n=28) vs. best experimental
    `volatility_expansion` at +$4.29/PF 1.23 (n=56). Legacy is positive
    in all 9 buckets but 8 of 9 are n<20 (trades too selectively for
    per-regime evidence to accumulate fast). A correctly built
    `RollingPerformanceSelector` run against this data would route
    Legacy in 9/9 buckets today. Full report:
    `docs/REGIME_PERFORMANCE_ANALYSIS.md` (final). Full rationale:
    `ENGINEERING_DECISIONS.md` #54.
13. **Shadow-data status tool** (2026-07-16): new `scripts/shadow_status.py`
    (read-only CLI -- opens SQLite with a `mode=ro` URI, so a write
    attempt is refused by SQLite itself) + `app.portfolio.shadow_status`
    (pure helpers reusing milestone-12's bucket convention): snapshot
    stats, per-(strategy, bucket) shadow-signal counts, and a report of
    distance to the 20-sample routability floor. ASCII-only output
    (pre-emptively applies decision #54's cp1252 lesson). Discloses that
    raw signal counts are necessary but not sufficient for routability --
    performance-evaluated samples are what milestone 14 supplies. 18 new
    tests. Live smoke: 3 regime snapshots accumulating, 0 shadow signals
    yet at that point. Full rationale: `ENGINEERING_DECISIONS.md` #55(a).
14. **Shadow outcome resolution** (2026-07-16): new migration
    `65aba13281ad` (chained on `36cb62e9e2ac`) gives `ShadowSignal` an
    `outcome` column (`"tp"`/`"sl"`/`"expired"`, `NULL`=open),
    `resolved_at`, `resolved_r`. New `app.portfolio.shadow_resolver.
    resolve_open_shadow_signals()` walks candles strictly after a
    signal's capture time, resolving SL before TP within a candle
    (mirrors `BacktestEngine._simulate_trade`'s own convention), with a
    7-day expiry. Wired into `run_paper.py`'s existing shadow block
    behind the same `ENABLE_SHADOW_STRATEGY_SIGNALS` flag, resolution
    running before recording so a signal is never resolved same-pass.
    17 new tests (8 schema + 9 resolver) plus a real-temp-DB
    end-to-end smoke test. Disclosed caveat: shadow outcomes are
    simulated fills with no fees/slippage -- an optimistic upper bound.
    **Found and fixed a real production bug along the way**:
    `record_shadow_pass()` wrote a raw `datetime` into a JSON column
    (crashes `json.dumps`), and the crash sat OUTSIDE the per-strategy
    error guard, so it would have aborted the entire shadow-recording
    pass -- latent-live, since shadow mode had been operator-enabled
    that same day, meaning the very first real shadow signal would have
    been silently lost. Fixed with a recursive JSON sanitizer. Full
    rationale: `ENGINEERING_DECISIONS.md` #55(b)-(d).
15. **Rolling per-regime evidence layer** (2026-07-16): new
    `app.portfolio.rolling_regime_performance.collect_regime_evidence()`
    returns per-(strategy, bucket, source) evidence cells, where
    `source` is `"shadow"` or `"live"` -- **the two are never averaged
    together** (simulated fee-free fills vs. real fee-paying trades are
    different measurement instruments; the selector decides precedence
    explicitly, this layer does not). Shadow-side `n` counts only
    resolved tp/sl outcomes; live-side `n` counts only closed trades
    with both `market_regime` and `r_multiple` populated (pre-tagging
    trades are skipped entirely, not dumped into an "untagged" bucket).
    14 new tests against hand-computed arithmetic. Full rationale:
    `ENGINEERING_DECISIONS.md` #55(e).
16. **`RollingPerformanceSelector`, built but NOT wired** (2026-07-16):
    appended to `app.strategy.selector` (existing classes untouched) --
    conforms to the existing `StrategySelector` Protocol. Conservative,
    fully disclosed rule: no regime -> legacy; Legacy's own live cell
    must itself be sufficient (n>=20) or fallback to legacy
    (`"fallback_legacy_baseline_unmeasured"` -- a challenger cannot beat
    an unmeasured baseline); challengers read live evidence if
    sufficient, else shadow (live precedence, no cherry-picking); a
    challenger qualifies only with expectancy_r strictly > 0 AND
    strictly > Legacy's; argmax among qualifiers wins, ties/none fall
    back to legacy; shadow-sourced wins carry an explicit
    `"_shadow_evidence_optimistic"` marker. Disclosed as NOT a
    statistical significance test. New read-only `scripts/
    selector_dry_run.py` (`mode=ro`) evaluates all 9 regime buckets plus
    "untagged" against a real DB without selecting anything live -- on a
    scratch, head-migrated database it reproduced milestone 12's own
    prediction exactly (`legacy` in all 10 buckets, baseline
    unmeasured). 14 new tests. **This selector is NOT the production
    selector** -- `scripts/run_paper.py` still runs
    `ConfigurableFallbackSelector`; wiring `RollingPerformanceSelector`
    in is deferred to a future, evidence-gated operator decision. Full
    rationale: `ENGINEERING_DECISIONS.md` #56.

Milestones 13-16 combined: roughly 63 new tests. **Full suite 602
passed / 0 failed** (was 539 after milestone 12). Live paper trader ran
untouched throughout; `AVAILABLE_STRATEGIES` and both production
selectors remain exactly as milestone 7b left them. One pending ops
step, not part of this round: the live paper-trading DB is still one
migration behind (`65aba13281ad` not yet applied), and the process needs
a clean restart to activate outcome resolution and the serialization
fix (tracked in `HANDOFF.md`).

## Operating-model shift + Milestone 17 (2026-07-16, operator directive)

With milestones 1-16 complete, the mandate shifts from feature
implementation to **continuous CTO-driven improvement**: specialist-agent
roles (CTO/Research/Strategy/Backtest/Risk/Monitoring/QA/Performance --
**Hypothesis added 2026-07-17**, see milestone 25 below, as part of the
research-company operating-model expansion: Research/Hypothesis/
Experiment/Evaluation/Ranking/Promotion/Shadow/Regime/Risk/Monitoring/QA/
Performance/Documentation/CTO)
select the next highest-ROI milestone by bottleneck analysis rather than
asking what to build next, stopping only for architectural decisions,
credentials, production deployment, or destructive actions. Promotion
gates are unchanged and never bypassed; Legacy remains the only
production engine. **A daily morning CTO report is now standing
practice** (`scripts/cto_report.py`, milestone 17b below).

17. **Multi-symbol shadow collection (17a) + daily CTO report generator
    (17b)** (2026-07-16): new `settings.SHADOW_SYMBOLS` (comma-separated,
    default `""` -- byte-identical off) extends `run_paper.py`'s shadow
    block to additionally fetch, resolve, and record shadow signals for
    extra symbols (ETH/SOL/XRP intended) per pass, per-symbol
    fault-isolated, surfaced under `summary["shadow"]["extra_symbols"]`.
    On extra symbols no strategy is active, so all six registered
    strategies (including `legacy` and `jade`) get shadow-evaluated
    there -- multiplying evidence for Legacy's own scarce per-bucket
    sample count. Trading logic never touches extra symbols. 9 new tests.
    New `scripts/cto_report.py` + `app.portfolio.cto_report`: 8 fixed
    report sections (completed work, evidence accumulated, strategy
    rankings + shadow performance, selector dry-run bucket count, a
    mechanical disclosed bottleneck rule, live risk checks, suggested
    next milestone quoted from `ROADMAP.md`, completion % parsed from
    `docs/ADAPTIVE_ARCHITECTURE.md` section 7), every section with an
    "unavailable: <reason>" fallback -- never fabricates. Read-only DB
    (`mode=ro`), ASCII-only, file-write-before-print. 22 new tests. Found
    and fixed a real bug: `subprocess.run(..., text=True)` decodes `git
    log` output as cp1252 on Windows, corrupting UTF-8 commit-message
    characters before any sanitizer runs -- fixed with an explicit UTF-8
    decode (`errors="replace"`); the second cp1252-decoding lesson on
    this platform, after decision #54. First live run: 28 regime
    snapshots (3 buckets), 0 shadow signals, 0 sufficient evidence cells
    -> bottleneck = evidence accumulation; trader running; DB at head
    `65aba13281ad`; 100.0% of the 16 currently-scoped section-7
    milestones. **Full suite 602 -> 633 passed / 0 failed** (+31). Live
    trader untouched during the build; restarting it with
    `SHADOW_SYMBOLS=ETHUSDT,SOLUSDT,XRPUSDT` is a pending ops step
    (tracked in `HANDOFF.md`). Full rationale:
    `ENGINEERING_DECISIONS.md` #57.

18. **Research round 1's top-3 adopted: delay-check promotion gate (18a),
    RiskManager ATR stop-distance floor (18b), realistic shadow-fill
    resolution v2 (18c)** (2026-07-16): implements the three adopted
    recommendations of `docs/RESEARCH_ROUND_1.md` (the Research
    department's survey of established quant technique vs. this
    platform's four open problems -- which also REJECTED HMM
    regime-switching, since this platform's own analysis shows trade
    scarcity, not classifier noise, is the bottleneck, and deferred the
    heavyweight statistical tests as premature at n=20-60).
    **18a**: `scripts/run_backtest.py --delay-check` --
    `delay_robustness_report()` compares a zero-delay run vs.
    `entry_delay_candles=1` on identical fetched candles; passes only if
    `pf_retention >= 0.5` (disclosed-not-tuned; the reference failure,
    `docs/ROBUSTNESS_REPORT.md` test 2, retained 0.03) AND no
    profitable-to-unprofitable sign flip; zero trades or an undefined
    baseline PF yield `passed=None` "insufficient data," never a fake
    pass; composable with `--strategy`/`--walk-forward`. 12 tests.
    **18b**: `RiskManager.evaluate()` gains caller-computed
    `stop_distance_atr_mult`/`min_stop_atr_mult` (decision #49 pattern),
    rejection reason `"stop_distance_below_atr_floor"`, boundary
    mirroring `MIN_RR` (at the floor passes, strictly below rejects),
    and a missing measurement never rejects. **`settings.
    MIN_STOP_ATR_MULT` exists, default `0.0` = DISABLED** -- enabling it
    changes trade acceptance and requires A/B backtest evidence first.
    Root cause addressed: the dead candidate's 0.17-0.23%-of-price stops
    (Wilder-convention literature: 1.5-3.0x ATR). 6 tests.
    **18c**: migration `6b085b904777` adds
    `shadow_signals.resolution_model` (nullable; `NULL` = legacy
    optimistic rows, permanently distinguishable); the resolver now
    fills at the NEXT candle's open after capture (1-candle delay),
    applies adverse slippage and both-leg fees from `paper_broker`'s
    real constants, and recomputes `resolved_r` from the actual fill
    (sl can be worse than -1R; gap-through-stop resolved honestly;
    gap-past-TP excluded as a missed entry rather than credited).
    `collect_regime_evidence` counts only
    `resolution_model="v2_realistic_fills"` rows toward `n` --
    **shadow evidence is now v2 realistic** (fee/slippage/delay-
    adjusted), no longer the fee-free optimistic upper bound.
    **Full suite 652/652 passed / 0 failed** at commit time. Committed
    as `4fe7496` without its docs round (session-limit boundary; docs
    completed after the reset). Same-day ops: live DB migrated to head
    `6b085b904777`, trader restarted with v2 active + 4-symbol shadow
    collection. Full rationale: `ENGINEERING_DECISIONS.md` #58.

19. **Performance round 1: backtester quadratic-scan fix in
    `detect_order_block`** (2026-07-16): a profiling round (measurement-
    only, prior session, interrupted by the session usage limit and
    flagged as pending in milestone 18's writeup) diagnosed the backtest
    engine's scaling as effectively quadratic -- log-log exponent ~2.26
    across 500/1000/2000/3000-candle runs on real BTCUSDT data.
    `detect_order_block()` was 62.6% of total runtime: its forward scan
    recomputed a fresh 15-candle average-range window at every history
    position on every walk-forward step, while only the LAST qualifying
    match it found ever survived to be returned. (`is_zone_mitigated()`
    was #2 at 22.2%; the `cf()` accessor was a large constant factor in
    self-time, ~40%/220M calls at n=3000, without driving the quadratic
    shape itself; slicing was measured and ruled out at <0.2%.) Fixed by
    rewriting the scan newest-to-oldest with early-exit on the first
    qualifying match -- provably the identical result the old forward
    scan kept (its "last match survives" behavior always returned the
    newest qualifying match, exactly what a reverse scan finds first),
    reached with far less work, while preserving both of the forward
    loop's existing traps (non-qualifying impulse and doji candles both
    continue to older candidates). Window-capping history was rejected as
    behavior-unsafe (sweeps/FVGs/CHOCH legitimately reference arbitrarily
    old structure); a rolling-window-sum micro-optimization was
    implemented, tested, and DROPPED -- float addition/subtraction is not
    associativity-safe and it failed this round's own bit-identical
    verification bar. **Verified two ways**: a property test against a
    verbatim reference copy of the old implementation (5,200 seeded
    synthetic series including adversarial modes, 0 mismatches, now a
    permanent regression test) and a golden run on anchored real data
    (BTCUSDT 15m, 2000 candles, `end_time_ms` 2026-06-27) across all 4
    flag combinations (default/breaker/structure-tp/jade) -- trade lists
    deep-equal at exact float precision. Had to patch `detect_order_block`
    in three separate module namespaces (`signal_engine`,
    `entry_point_engine`, `htf_ltf_confluence`, each binds it at import)
    for the golden-run comparison to be valid. **Measured speedup**
    (unprofiled wall-clock): 1000 candles 4.32s->1.81s (2.39x), 2000
    candles 16.15s->7.09s (2.28x) -- Milestone-10-style evidence rounds
    (`--candles 3000 --periods 6`) now take roughly 17 minutes instead of
    roughly 40, a ~2.3x reduction in wall time for this project's
    standard validation scale. Full suite **653/653 passed / 0 failed**
    (652 + 1 permanent property test). **Deferred**: Fix B (incremental
    zone-mitigation caching for `is_zone_mitigated`, the remaining ~22%
    of runtime) -- medium risk, needs cross-step state inside a
    currently-stateless `SignalEngine`; revisit only if this 2.3x proves
    insufficient. **Status: code complete in the working tree, not yet
    committed.** Full rationale: `ENGINEERING_DECISIONS.md` #59.

20. **ATR stop-distance floor made A/B-testable, then REJECTED on
    evidence; Legacy production baseline found delay-fragile**
    (2026-07-16/17): **20a** wired the milestone 18b `RiskManager` ATR
    stop-distance floor for A/B testing --
    `BacktestEngine.run(min_stop_atr_mult=...)` +
    `run_backtest.py --min-stop-atr`, ATR computed from the signal's
    own no-lookahead slice, disabled path proven byte-identical (a
    fake `RiskManager` that raises on unexpected kwargs exercises the
    unflagged path). 7 new tests. **20b** ran the pre-declared evidence
    round on the standard BTCUSDT 15m anchor (6x3000 candles,
    `--end-date 2026-07-10`, walk-forward + delay-check every config;
    full numbers in `docs/ATR_FLOOR_EVALUATION.md`, final): baseline
    (floor off) 111 trades, +$3,400.62, 6/6 profitable, walk-forward
    PASSED -- but delay-check FAILED (PF 5.024->0.117, retention 0.023,
    profit-to-loss sign flip). `--min-stop-atr 1.5` (literature-range,
    pre-declared): 60 trades (-46%), +$1,113.35 (-67%), 3/6 profitable,
    walk-forward FAILED, delay retention only 0.079 (still 6x below the
    0.5 pass bar), sign flip remained. 2.0x deliberately NOT run -- CTO
    early stop per this project's dead-config discipline (1.5x tripled
    retention while destroying consistency and profit, no plausible path
    to 0.5). **VERDICT: the floor is REJECTED as a delay-robustness fix
    -- `settings.MIN_STOP_ATR_MULT` stays `0.0` (disabled) everywhere,
    not enabled in paper trading, not recommended for promotion.** It
    "traded less, worse," not "traded the same, safer" -- the exact
    negative result `docs/RESEARCH_ROUND_1.md` section 4c pre-committed
    to recording honestly. **Headline finding**: production Legacy
    itself fails the 1-candle delay gate on this window -- previously
    unknown (`docs/ROBUSTNESS_REPORT.md` test 2 only delay-tested the
    already-killed `structure_tp` candidate). Severity caveat: 1 candle
    = 15 minutes on this anchor, 3x harsher than the original 5-minute
    test -- read as "the edge lives inside a sub-15-minute execution
    window," not a seconds-scale live-latency failure; walk-forward
    validity is unchanged, this is an execution-latency requirement, not
    a strategy invalidation. Consequence: `docs/live_trading_checklist.md`
    gate #4 now requires verified low-latency execution infrastructure
    as an explicit hard prerequisite. **Full suite 669/669 passed / 0
    failed**. 20b is read-only evidence collection -- no orders placed,
    no writes to `backend/paper_validation.db`. Full rationale:
    `ENGINEERING_DECISIONS.md` #60, full evidence:
    `docs/ATR_FLOOR_EVALUATION.md`.

22. **Performance round 2: FVG mitigation-scan quadratic term eliminated,
    Milestone 19's Fix B deferral CORRECTED** (2026-07-17): Milestone 19
    deferred "Fix B" (incremental zone-mitigation caching for
    `is_zone_mitigated`, 22.2% of runtime after round 1's own fix) on the
    assumption that closing it required cross-walk-forward-step state
    inside a stateless-by-design `SignalEngine`. That assumption is now
    corrected -- consumer-semantics analysis found `entry_model.
    build_entry_model` only ever uses the highest-index FVG zone matching
    `bias` (`wanted_type` provably collapses to `bias` for the only two
    values that proceed past its early return), so an M19-style fused
    reverse scan with early exit sufficed; no stateful caching was
    needed. New `signal_engine._select_unmitigated_fvg_zones` (neutral
    bias short-circuits to `[]`) delegates to new `fvg.
    find_latest_unmitigated_fvg_zone` -- newest-to-oldest, fusing gap
    detection, type filtering, and mitigation checking with an early
    exit. `detect_fair_value_gap()` itself is untouched; its other two
    consumers (`entry_point_engine`, `htf_ltf_confluence`) still need the
    full zone list, confirmed by grepping every call site. **Verified**
    via the same M19 battery: two independent 5,200-case property tests
    against verbatim reference copies of the old logic (0 mismatches,
    now permanent regression tests) and a real-data golden run across
    the same 4 flag combinations M19 used (deep-equal 4/4). M19's
    three-namespace-binding trap does NOT recur here -- only one
    namespace binds the touched functions, grep-verified. **Measured**:
    `is_zone_mitigated` calls 965,864->11,141 (~87x fewer), FVG chain
    22.2%->1.68% of runtime, n=1000 1.81x / n=2000 2.36x wall-clock.
    Combined with M19, full-scale evidence rounds are now roughly **5x
    faster than the pre-M19 baseline**. New dominant costs
    (`find_swing_highs`/`find_swing_lows`, the `cf()` accessor) are
    recorded as future-round candidates, not chased this round. Full
    suite **692/692 passed / 0 failed**. **Status: code complete in the
    working tree, not yet committed.** Full report:
    `docs/PERFORMANCE_M22.md`. Full rationale:
    `ENGINEERING_DECISIONS.md` #61(a).

23. **Risk-rejection observability** (2026-07-17, committed `3e508d8`):
    `BacktestResult` gains `risk_rejections`
    (`{total_signals, approved, rejected, by_reason}`) -- purely
    observational, closing the instrumentation gap decision #60 flagged:
    the milestone 20b ATR-floor evidence round could observe the 111->60
    trade-count drop but could not report how many signals the risk gate
    itself rejected or why. Counts the same `risk_decision`
    `BacktestEngine.run()` already computes and branches on; never
    changes control flow or which trades happen. Since
    `RiskManager.evaluate()` does not short-circuit on the first failing
    check, a single rejected signal can increment multiple `by_reason`
    keys -- `sum(by_reason.values()) >= rejected` by design, not a bug.
    Default-populated on every path (including the below-`MIN_CANDLES`
    early return) via a shared factory, so no consumer needs a
    `getattr`/`None` guard. `scripts/run_backtest.py` prints a per-period
    rejection line only when that period's `rejected > 0`, plus one
    aggregate line across `--periods` that always prints. **Full suite
    690/690 passed / 0 failed** at commit time. Full rationale:
    `ENGINEERING_DECISIONS.md` #61(b).

24. **Cross-year evidence round on Legacy's own delay fragility --
    STRUCTURAL, plus a MAX_TRADES_PER_DAY discovery** (2026-07-17): the
    house cross-year discipline (already applied to break-even, partial
    TP, and the tuned defaults) applied to milestone 20b's own 2026
    finding rather than exempting it. One pre-declared run, the standard
    BTC 2025 anchor (6x3000 candles, `--end-date 2025-07-10`,
    `--walk-forward --delay-check`), reproducing the known BTC-2025
    baseline to the cent ($1,714.56, 6/6 profitable, 35.4% second-half
    retention) before trusting the delay numbers. **Result**: baseline PF
    4.593 -> delayed PF 0.068, retention **0.015** (worse than 2026's
    0.023), sign flip, delay gate FAILED; walk-forward FAILED on the
    already-documented BTC-2025 degradation (correctly attributed, not a
    new finding). **VERDICT: STRUCTURAL** -- fails both tested years,
    slightly worse in 2025 despite a materially different regime (65 vs
    111 trades), falsifying the regime-dependent hypothesis. `docs/
    ADAPTIVE_ARCHITECTURE.md` gate #4's requirement note upgrades to
    "structural property, confirmed across two independent years (2025,
    2026) on BTCUSDT" -- requirement substance unchanged. **Second
    finding**: milestone 23's rejection instrumentation, used for the
    first time in an evidence round, found 2025's low trade count is not
    a signal drought -- 869 raw signals, 804 (92.5%) rejected, 100% of
    fired reasons `trades_today 2 reached MAX_TRADES_PER_DAY 2`. The
    regime-bucket evidence starvation previously attributed to "Legacy
    trades too selectively" is substantially a `MAX_TRADES_PER_DAY=2`
    effect -- recorded as an insight, not a recommendation (any change to
    that cap is an operator-gated risk-limit decision). **Operational
    validation**: ~11 minutes wall time vs. ~3h05m for the equivalent
    pre-milestone-22 run, validating the milestone 19/22 performance work
    in production-scale use. Read-only evidence collection -- no orders,
    no DB writes, no code touched. Full report: `docs/
    LEGACY_DELAY_ROBUSTNESS.md`. Full rationale: `ENGINEERING_DECISIONS.md`
    #62.

25. **Research-company loop's first full cycle: Hypothesis Agent + Hypothesis
    Round 1 + H4 position-sizing parity, verdict MIXED** (2026-07-17/18):
    operator directive formally expanded the operating model to named agent
    roles including a new **Hypothesis** role (generates falsifiable,
    mechanism-grounded, pre-registered strategy hypotheses -- mechanism +
    citation + exact experiment invocation + keep-rule, all declared before
    any run). `docs/HYPOTHESES_ROUND_1.md`: 5 hypotheses ranked by
    (evidence-grounding x testability)/cost, 7 rejected directions logged
    with citations. **H4** (close the backtest/live position-sizing gap)
    ranked #1 and ran first -- a verified code fact, not a new-edge search:
    Milestone 7's volatility-scaled sizing (0.5x in high-volatility regimes)
    has been live in paper trading since 2026-07-15, but `BacktestEngine.run()`
    never passed the `volatility` argument to `calculate_position_size`, so
    every backtest number in this platform's evidence base
    (`REGIME_PERFORMANCE_ANALYSIS`, `LEGACY_DELAY_ROBUSTNESS`,
    `ATR_FLOOR_EVALUATION`, `PROFITABILITY_EXPERIMENT_REPORT`) was computed
    at a uniform 1.0x scalar live trading has not actually run since that
    date. New opt-in `--vol-scaled-sizing` flag (default off, byte-identical
    when unset), 3-year BTCUSDT comparison against already-recorded unscaled
    baselines -- full numbers: `docs/H4_SIZING_PARITY_RESULTS.md`. **VERDICT:
    MIXED** -- the pre-registered 3-branch keep-rule, applied literally per
    year, did not resolve to one answer: 2024 matched "confirmed improvement"
    (drawdown -13.6%, PnL/PF within the ~10% band), 2025 matched "nothing
    moves materially," and 2026 alone (Net PnL -14.42%, outside the band)
    triggered "materially degrades" -- the first bullet's own 2-of-3-years
    bar cleared only 1 of 3, so it does not fire; the honest read is MIXED,
    not rounded toward either clean branch. **Operator-relevant finding,
    stated as a finding only, no recommendation made** (same operator-gated
    boundary as `MAX_TRADES_PER_DAY`, decision #62): the live 0.5x scalar
    shows a real, asset/year-dependent cost -- most pronounced in 2026
    (-14.4% PnL for a -13.4% relative drawdown improvement), smaller in 2024,
    absent in 2025. **Footnote check**: delay-gate retention moved <=0.002
    in all three years (noise) and walk-forward verdicts were unchanged
    everywhere -- `LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL/3-for-3 verdict
    needs no correction, confirmed to hold under vol-scaled sizing too. Open
    caveat, not resolved this round: findings elsewhere resting on Net
    Profit margins narrower than ~10-15% could plausibly flip and would need
    a targeted re-check. **Coordination note**: two agents briefly worked
    from the same in-progress 2025 backtest output; the orchestrator caught
    the overlap before either wrote a conclusion from partial data and
    serialized the two runs -- no data corruption, no incorrect number
    recorded. Read-only evidence round, no code touched beyond the
    already-implemented, already-tested `--vol-scaled-sizing` flag. **Full
    suite 701/701 passed / 0 failed** (up from 692). Full reports:
    `docs/HYPOTHESES_ROUND_1.md`, `docs/H4_SIZING_PARITY_RESULTS.md`. Full
    rationale: `ENGINEERING_DECISIONS.md` #63.

26. **H1: quality-ranked signal selection within the fixed daily cap --
    REJECTED, second confirmation that throughput beats selectivity**
    (2026-07-18): `docs/HYPOTHESES_ROUND_1.md` section 2's H1 (ranked #2
    behind milestone 25's H4) asks whether, holding `MAX_TRADES_PER_DAY`
    fixed at 2, selecting the two highest-quality signals of the day
    (instead of the first two chronologically) improves expectancy --
    directly targeting the largest disclosed, quantified opportunity in
    this platform's evidence base (89-92% of Legacy's raw signal stream
    rejected purely by the FIFO daily cap, `docs/LEGACY_DELAY_ROBUSTNESS.md`
    §2) without touching the cap itself (operator-gated per
    `ENGINEERING_DECISIONS.md` #62). New research-only harness
    `scripts/research_signal_selection.py` (+ 15 tests) re-batches each
    simulated day's full signal supply, ranks by a disclosed-not-tuned
    score (`rr` = `TradeSignal.rr`; `rr_confluence` = `rr +
    confluence_count`, both declared before any run), and takes only the
    top-`MAX_TRADES_PER_DAY` by score -- `RiskManager.evaluate()`'s live
    sequential-approval logic is untouched. Baseline reproduction
    confirmed exactly on both anchors (Net Profit to the cent, trade
    count, walk-forward outcome, matching `docs/LEGACY_DELAY_ROBUSTNESS.md`/
    `docs/ATR_FLOOR_EVALUATION.md`) before trusting the comparison.
    **VERDICT: REJECT for both variants**, applying H1's own
    pre-registered keep-rule literally: `rr` wins Profit Factor in BOTH
    anchors (+6.5% 2026, +138.3% 2025) but LOSES Net Profit in BOTH
    anchors (-24.1% 2026, -4.1% 2025) -- disqualified directly by the
    rule's own "wins on PF but not Net Profit, is REJECT" clause;
    `rr_confluence` loses both metrics in both anchors outright. Unlike
    milestone 25's H4, which genuinely did not resolve to a single
    keep-rule branch and was reported MIXED, H1's rule resolves cleanly
    -- a straightforward negative result. **Mechanism**: both ranked
    variants realize markedly fewer trades than the chronological
    baseline under the SAME fixed cap (2026: `rr` 82/`rr_confluence` 77
    vs. baseline 111; 2025: `rr` 43/`rr_confluence` 46 vs. baseline 65)
    -- a day's top-scored candidates can cluster in time such that the
    second-ranked candidate's window overlaps the still-open first
    trade and is skipped, whereas FIFO naturally spreads fills as
    signals arrive live. Quality-ranking traded away raw throughput for
    higher per-trade selectivity, but the throughput loss cost more
    aggregate Net Profit than the quality gain recovered, in both years
    without exception -- Legacy's edge on this platform scales more with
    trade FREQUENCY under the fixed cap than with per-trade selectivity.
    Reinforces `docs/strategy_spec.md` §6's existing finding that
    stricter confluence does not reliably improve trade quality
    (`rr_confluence` performed worse than plain `rr` on both metrics,
    both years -- a second, independent data point) and confirms the
    cap-rejection opportunity (`ENGINEERING_DECISIONS.md` #62) requires
    trade throughput, not smarter selection, to capture -- raising the
    cap remains explicitly operator-gated, not something this result
    argues for changing. **Disclosed, un-root-caused discrepancy**: the
    harness's own Profit Factor for the chronological baseline variant
    runs consistently lower than the previously-published baseline PF
    for the identical run (2026: 4.378 vs. 5.024; 2025: 3.498 vs. 4.593)
    despite Net Profit/trades/walk-forward matching byte-for-byte --
    plausibly a PF-aggregation methodology difference, not verified this
    round, flagged as a standing follow-up (does not affect the verdict,
    since Net Profit is the deciding metric and it reproduced exactly).
    **Promotion path: NONE -- REJECT.** Legacy's live/paper trading
    behavior is completely unchanged: `RiskManager.evaluate()`,
    `scripts/run_paper.py`, `BacktestEngine` internals all byte-for-byte
    unchanged. No orders placed, no DB writes. **Full suite 716/716**
    (up from 701 -- 15 new `research_signal_selection` tests). Full
    report: `docs/H1_SIGNAL_SELECTION_RESULTS.md`. Full rationale:
    `ENGINEERING_DECISIONS.md` #64.

27. **H3: regime-conditional delay survival of the `structure_tp` family --
    REJECTED across all three anchors, compounded by regime-bucket
    evidence scarcity** (2026-07-18): `docs/HYPOTHESES_ROUND_1.md`
    section 3's H3 (ranked #3 behind milestone 26's H1) asks whether
    `use_structure_tp`'s already-validated (`docs/
    PROFITABILITY_EXPERIMENT_REPORT.md` §12-14), already-known
    aggregate-delay-fragile (`docs/ROBUSTNESS_REPORT.md` Test 2, PF
    5.24 -> 0.16 at a 5-minute delay) exit family survives a 15-minute
    execution delay better in some market regimes than others --
    combining three already-built, already-independently-validated
    mechanisms (`--structure-tp`, `--tag-regimes`, `--delay-check`) that
    had never been run together before. New analysis-only harness
    `scripts/research_regime_delay.py` (+ 23 tests) joins `--tag-regimes`
    and `--delay-check` output per bucket, computing PF at
    `entry_delay_candles=0` and `=1` separately per regime bucket instead
    of only in aggregate -- `RiskManager.evaluate()`'s live
    sequential-approval logic untouched. **Unlike H1's 2-anchor
    requirement, H3's own pre-registered keep-rule requires 3 tested
    years** (2024/2025/2026, matching `docs/LEGACY_DELAY_ROBUSTNESS.md`'s
    standard) -- all three were run: BTCUSDT 15m, `--candles 3000
    --periods 6`, uncapped `--structure-tp --tag-regimes`, producing
    10/9/8 regime buckets respectively (fewer buckets in 2025/2024 purely
    a regime-occurrence artifact -- `range/high_volatility` and
    `strong_trend/low_volatility` had zero trades those years -- not a
    tool bug). **VERDICT: REJECT**, applying H3's own pre-registered
    keep-rule literally: "a regime bucket counts as a genuine
    delay-robust pocket only if it clears ... n>=20 trades on the delayed
    side, PF retention >=0.5, no sign flip, in AT LEAST 2 of the 3 tested
    years. If no bucket clears this bar in any year, REJECT ...
    outright." Across all 27 bucket-year cells (10+9+8), not one clears
    the bar in even a single year -- only ONE cell (2026
    `weak_trend/normal_volatility`, delayed N=20) reaches the n>=20
    delayed-side floor at all, and it fails outright on PF retention
    (0.170, needs >=0.5) with a sign flip. Since no bucket clears the bar
    even once, this does not reach the rule's own "directional lead"
    tier (1-of-3) -- a harder, cleaner zero than that. **Evidence-scarcity
    caveat, the substantive finding of this round**: 26 of the 27
    bucket-year cells never reach the n>=20 delayed-side threshold needed
    to evaluate the keep-rule meaningfully in the first place -- mirrors
    this platform's already-documented regime-bucket scarcity (`docs/
    REGIME_PERFORMANCE_ANALYSIS.md`: 8 of 9 buckets evidence-starved for
    Legacy's own signal stream) on a completely different exit-logic
    family. Honest framing: this REJECT is "insufficient data to test
    most buckets meaningfully" as much as it is "buckets were tested and
    failed" -- does not rule out a future round with more history/assets/
    shadow data surfacing a bucket that clears the floor and then passes
    or fails on its own merits. **Secondary, non-deciding observation**:
    the aggregate ("all") row's PF retention for `structure_tp` (0.080
    2026, 0.051 2025, 0.067 2024) runs ~2-3x HIGHER than Legacy's
    already-documented default-exit aggregate retention at the same
    anchors (2026: 0.023, 2025: 0.015, `docs/LEGACY_DELAY_ROBUSTNESS.md`;
    no prior 2024 default-exit delay-check to compare against). Both
    remain catastrophically below the 0.5 bar with a sign flip in all
    three years for `structure_tp` too -- a quantitative footnote, not
    evidence of practical delay-robustness, and it does not change the
    REJECT verdict -- it DOES reinforce, as a third independent data
    point alongside Legacy's own milestone 24 finding, that this
    platform's execution-delay fragility is STRUCTURAL across strategy/
    exit-logic variants tested so far, not specific to one exit-logic
    family. **Promotion path: NONE -- REJECT.** Legacy's live/paper
    trading behavior is completely unchanged: `RiskManager.evaluate()`,
    `scripts/run_paper.py`, `BacktestEngine` internals all byte-for-byte
    unchanged. No orders placed, no DB writes. **Full suite 739/739**
    (up from 716 -- 23 new `research_regime_delay` tests). Full report:
    `docs/H3_REGIME_DELAY_RESULTS.md`. Full rationale:
    `ENGINEERING_DECISIONS.md` #65.

28. **H2: passive limit-at-level entry as a delay-robust alternative --
    REJECTED, delay-robustness achieved cleanly but the entry model
    itself is unprofitable independent of delay** (2026-07-18):
    `docs/HYPOTHESES_ROUND_1.md` section 4's H2 (ranked #4, highest
    implementation cost of the five) asks whether a passive resting
    limit order at the structural entry zone (OB/FVG/sweep level,
    `docs/strategy_spec.md` §§2-5) -- instead of an immediate market
    fill -- is a genuinely delay-robust alternative entry model. Unlike
    H1/H3's pure research-aggregation harnesses, H2 required real new
    fill-timing logic: new opt-in `--limit-at-level` /
    `--limit-timeout-candles N` flags wired into
    `BacktestEngine.run()`/`entry_model.py`, default off and
    byte-identical when unset (confirmed by 2 dedicated regression
    tests in `backend/tests/test_backtest_engine.py`).
    `RiskManager.evaluate()`'s live sequential-approval logic and
    `scripts/run_paper.py` are untouched. **Disclosed implementation
    judgment calls**: the limit fill price is the zone level itself
    (`signal.entry_price`) with slippage applied identically to the
    existing immediate-fill path -- only WHEN/WHETHER the fill happens
    changed, never the price formula; `entry_delay_candles` was
    interpreted as placement/dispatch latency, shifting when the
    resting order's scan window starts while the timeout still measures
    window length from that point; unfilled/expired signals are not
    recorded as trades or losses, matching existing precedent for other
    filtered-out signal types. **Anchor**: BTCUSDT 15m, `--candles 3000
    --periods 6 --limit-at-level --limit-timeout-candles 4
    --walk-forward --delay-check`, all three years (2024/2025/2026), vs.
    the already-recorded Legacy market-order baseline
    (`docs/LEGACY_DELAY_ROBUSTNESS.md`). **Result**: -$744.13 (2026),
    -$727.22 (2025), -$895.05 (2024) Net Profit -- 96/51/64 trades
    (13-21% fewer than Legacy), 1/6, 0/6, 2/6 profitable periods,
    walk-forward FAILED all three years (degrading trends, losing
    streaks of 5/6/3); its OWN internal delay-gate retention (delay=0 vs
    delay=1 within the mechanism) PASSED cleanly all three years: PF
    retention 1.003/0.883/0.935, no sign flip. **VERDICT: REJECT**,
    applying H2's own pre-registered two-part keep-rule literally --
    both parts must hold for KEEP, either failing alone is REJECT.
    **Check 2 (delay-robustness) PASSES cleanly, 3/3 years** -- PF
    retention 1.003/0.883/0.935, no sign flip anywhere, genuinely and
    robustly solving the execution-delay fragility that both Legacy's
    default exit (retention 0.015-0.026) and `structure_tp` (milestone
    27, retention 0.051-0.080) failed catastrophically -- mechanistically
    sound, since a resting order's fill price does not depend on
    placement latency, only on whether/when price revisits the level.
    **Check 1 (cost-of-passivity) FAILS catastrophically, 0/3 years** --
    inverts sign in every single year (2026: +$3,400.62 -> -$744.13;
    2025: +$1,714.56 -> -$727.22; 2024: +$1,807.75 -> -$895.05). Check 1
    alone disqualifies. **Precision note, the substantive finding of
    this round**: this is NOT the same failure shape as "the ATR floor
    already showed" (the keep-rule's own analogy, fixing delay by mostly
    not trading) -- trade count drops only modestly (13-21% fewer than
    Legacy) while profitable-periods collapses almost entirely (1/6,
    0/6, 2/6 vs. Legacy's 6/6 in all three years) and walk-forward fails
    everywhere with elevated losing streaks -- too small a volume
    reduction to explain a swing from strongly profitable to net-loss on
    its own. The more precise finding: the retest-based passive-fill
    mechanism itself systematically selects for structurally worse trade
    outcomes, independent of delay entirely -- waiting for a retest of
    the zone edge appears to filter FOR setups that subsequently
    underperform (or filters OUT the immediate-continuation setups that
    drove Legacy's edge), not merely filter volume. A genuinely novel,
    third distinct failure mode among this platform's three tested
    delay-robustness fixes: ATR floor (thinned population, milestone
    20), entry-drift gate (inconsistent/partial,
    `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4), and now H2 (clean
    delay-robustness, but an unprofitable entry model independent of
    delay) -- a clean, well-differentiated addition to the evidence
    base, not a repeat of a known pattern. **Promotion path: NONE --
    REJECT.** Even a KEEP would have had a uniquely different promotion
    story per H2's own pre-registered text (a candle-only approximation
    of a resting limit order is not verified live limit-order
    behavior) -- moot here. Legacy's live/paper trading behavior is
    completely unchanged: `RiskManager.evaluate()`, `scripts/run_paper.py`,
    `BacktestEngine` internals all untouched, new flags default off and
    byte-identical when unset. No orders placed, no DB writes. **Full
    suite 748/748** (up from 739). Full report:
    `docs/H2_LIMIT_ENTRY_RESULTS.md`. Full rationale:
    `ENGINEERING_DECISIONS.md` #66.

29. **H5: session-conditional position sizing -- pre-registered in full,
    then REJECTED at its own Step 0 grounding gate** (2026-07-19):
    `docs/HYPOTHESES_ROUND_1.md` section 1's ranking table carried H5 as
    a one-line row only -- `CLAUDE.md` records that the operator/CTO
    explicitly declined to have its full spec fabricated after the fact.
    This round wrote H5's full pre-registration (new section 6:
    mechanism, grounding, pre-registered experiment, keep-rule, cost,
    promotion path), built entirely from evidence already committed to
    this repository, then ran the pre-registration's own **Step 0**
    precondition check in the same round -- before any
    `session_risk_scalar` sizing code was written. **What the
    pre-registration surfaced**: new supporting grounding (milestone 26's
    H1 finding that trade FREQUENCY matters more than per-trade
    selectivity on this platform, published a day after H5's original
    ranking); and a disclosed grounding gap -- H5's sole motivating
    evidence, `docs/ROBUSTNESS_REPORT.md` Test 6 (Asian PF 4.65 > London
    PF 2.41), was measured on BTCUSDT 5m against the `structure_tp`
    candidate, not the 15m Legacy candidate H5 would size. **Step 0**:
    new analysis-only harness `scripts/research_h5_step0_session_grounding.py`
    (+ 8 tests) buckets already-produced Legacy-baseline trades by UTC
    entry hour into Test 6's three session windows -- no new
    `BacktestEngine` parameter, no new CLI flag; `RiskManager.evaluate()`
    and `scripts/run_paper.py` untouched throughout. Ran BTCUSDT 15m
    2024/2025/2026 (plain Legacy default; trade counts 111/65/73
    confirmed exact matches to the already-published baseline before
    trusting the new bucketing logic). **Result**: gradient direction
    (Asian PF > London PF) held in only 1 of 3 years (2024) -- in 2026
    and 2025, including the platform's single most-evidenced anchor
    (2026, 111 trades), London's PF exceeded Asian's, the OPPOSITE of
    Test 6's finding. **VERDICT: REJECT at Step 0**, applying H5's own
    pre-registered gate literally (Asian PF > London PF required in
    >=2/3 years, both buckets n>=10) -- 1-of-3 is below the threshold.
    Per H5's own text this ends the hypothesis outright:
    `session_risk_scalar`/`--session-scaled-sizing` were never
    implemented, Step 1 never ran. **Substantive finding**: a
    session-quality gradient measured on one candidate/timeframe does not
    transfer to a different candidate/timeframe, even holding the asset
    and session-window convention fixed -- a standalone, disclosed
    caveat for any future hypothesis conditioning on Test 6's numbers.
    **Hypothesis Round 1 is now fully resolved**: H1 REJECT, H2 REJECT,
    H3 REJECT, H4 MIXED, H5 REJECT at Step 0 -- zero KEEPs. Legacy's
    live/paper trading behavior is completely unchanged; this round
    needed zero new engine parameters or CLI flags, unlike H1/H3/H4's
    harnesses. No orders placed, no DB writes. **Full suite 756/756**
    (up from 748). Full report: `docs/H5_SESSION_GROUNDING_RESULTS.md`.
    Full rationale: `ENGINEERING_DECISIONS.md` #67.

**Production-behavior note**: milestones 1-6 were purely additive/
observational. Milestone 7 was the FIRST to change actual paper-trading
sizing/rejection math (more conservative sizing in high volatility;
rejecting signals from an auto-disabled strategy); milestone 7b adds an
opt-in routing path that, in its default (off) configuration, changes
nothing further. Milestone 9's four new strategy modules are quarantined
and reachable only via `run_backtest.py --strategy`, so they change
NOTHING about paper/live trading -- milestone 10 evidenced them (all
failed, none promoted) without touching paper/live trading either.
Milestone 11's shadow recording is default-off and, even once enabled,
only observes -- it never places an order or influences selection. All
take effect only on the paper trader's next restart where applicable
(code changes do not affect the already-running process, PID 24616,
confirmed still running throughout every milestone; the live process was
NOT restarted this round). Legacy's own signal/entry/exit logic remains
completely untouched.

## Profitability sprint (2026-07-12, operator-directed autonomous session)

Paper trading started (Legacy engine, all experimental flags off,
19:29:11) and is running continuously against live OKX data -- 0 trades
so far as of this write-up (expected at this trade frequency, not an
error). In parallel, built a rigorous controlled-experiment harness
(`scripts/experiment_runner.py` -- fixed-anchor fetch shared across every
config, in-sample/held-out-out-of-sample split, JSON results ledger) and
tested every previously-unvalidated Legacy-pipeline flag against it.
**`use_structure_tp` clears the project's three-metric keep rule** (Net
Profit, Profit Factor, AND worst-period Drawdown all improve), confirmed
out-of-sample on held-out data -- the strongest single-experiment result
this project has produced, though still only 1 asset/1 time window
(cross-asset/cross-year validation is the recommended next step, not yet
run). `ob_fvg_confluence`/`premium_discount_filter`/the
`structure_tp`+`premium_discount_filter` combination were all tested and
rejected. A new opt-in `structure_tp_max_r` conservative-exit variant was
built and also clears the bar. **Production default is unchanged** --
Legacy stays the only production-approved configuration. Also closed 4
real paper-trading observability gaps (`Signal.rejection_reason`,
`Trade.exit_reason`/`r_multiple`/`strategy_config` -- were computed
in-process but never persisted) additively, without touching the running
process. Full detail: `docs/PROFITABILITY_EXPERIMENT_REPORT.md`,
`ENGINEERING_DECISIONS.md` #37-#40, `ROADMAP.md`.

## Cross-asset validation (2026-07-13, per-asset optimization round)

`use_structure_tp` promoted to documented CANDIDATE status (still opt-in,
still NOT a production default, paper trader still Legacy-only) for
**BTC and SOL** -- both out-of-sample confirmed. **XRP**: no candidate
(the capped-3R variant ties baseline drawdown rather than beating it).
**ETH**: no candidate across 2 time windows and 6 config variants --
diagnosed as a baseline-level regime characteristic in the tested
windows, not fixable by further tuning without curve-fitting. Ranking
now uses Net Profit/Profit Factor/Max Drawdown/Sharpe (walk-forward +
out-of-sample kept as gates ahead of the score, to prevent an unattended
candidate-generation loop from ranking a curve-fit winner #1). Full
detail: `docs/PROFITABILITY_EXPERIMENT_REPORT.md` section 12.

## Core rule completion (MVP) — ✅ COMPLETE (2026-07-12)

Operator directive (2026-07-11): before resuming any parameter
optimization/sweeps/multi-year backtests, finish these 5 core Jade
strategy rules, in this order. All 5 are now done; each item's docs
(this file, ROADMAP, ENGINEERING_DECISIONS) and a commit landed when it
shipped — this list remains the single source of truth for what's done.

| # | Rule | Status |
|---|---|---|
| 1 | Premium/Discount calculation from current swing range | ✅ Shipped — `app.strategy.premium_discount.calculate_premium_discount`, unit-tested, spec'd (`docs/strategy_spec.md` §8). Detection only when shipped; now also wired as an opt-in TP extension target (see #4) |
| 2 | Previous swing high/previous swing low detection | ✅ Shipped — `app.strategy.market_structure.find_previous_swing_high`/`find_previous_swing_low`, unit-tested, spec'd (§3) |
| 3 | OB + FVG confluence entry model | ✅ Shipped — opt-in `require_ob_fvg_confluence` on `build_entry_model` (default off), threaded through `SignalEngine`/`BacktestEngine`/`run_backtest.py --ob-fvg-confluence`, unit/integration-tested, spec'd (§6). Not yet A/B backtested |
| 4 | TP logic: previous high/low first, HTF-permitting extension to 0.5 equilibrium | ✅ Shipped — opt-in `use_structure_tp` on `build_entry_model` (default off, depended on #1 and #2), threaded through `SignalEngine`/`BacktestEngine`/`run_backtest.py --structure-tp`, unit/integration-tested, spec'd (§6, §8). Not yet A/B backtested |
| 5 | Equal High/Equal Low liquidity detection | ✅ Shipped — `app.strategy.liquidity.detect_equal_highs`/`detect_equal_lows`, unit-tested, spec'd (§2). Detection only; not yet wired into `SignalEngine` |

## Phase 1 gate status (operator scope lock)

Objective: build, validate, and prove ONE profitable JadeCap automated
trading system. Nothing else. See `ROADMAP.md`'s "Phase 2 (deferred)"
section for ideas explicitly out of scope until these 4 gates clear.

| Gate | Status |
|---|---|
| 1. Backtest | ✅ Complete — 4 assets x 2026, BTCUSDT also x 2025. Controlled parameter sweep complete, 4 tuned defaults adopted (+66.7% PnL vs. old defaults on BTC 2026) |
| 2. Walk-forward validation | ✅ CLOSED under BOTH the old and new (tuned) defaults — 24/24 periods profitable across all 4 assets each time, PnL improved on every asset under the new defaults (BTC +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%) |
| 3. Paper trading | ✅ Pipeline complete and running (`scripts/run_paper.py`), no real capital. Risk controls hardened (circuit breaker now auto-resets) |
| 4. Small live validation | ❌ Not started — requires operator-issued API keys + staged approval + real balance integration (`PLACEHOLDER_ACCOUNT_BALANCE` explicitly deferred here, operator decision). **Hardened 2026-07-17 (milestone 20, `docs/ATR_FLOOR_EVALUATION.md`)**: verified low-latency execution infrastructure (measured signal-to-fill latency, not assumed) is now an explicit prerequisite -- Legacy's backtested edge on the tested BTCUSDT window did not survive a 15-minute entry delay (PF 5.024->0.117, sign flip); walk-forward validity is unchanged, this is an execution-latency requirement, not a strategy invalidation. **Confirmed STRUCTURAL, not regime-specific, 2026-07-17 (milestone 24, `docs/LEGACY_DELAY_ROBUSTNESS.md`)**: the same delay gate FAILED on the independent 2025 BTCUSDT window too (retention 0.015, slightly worse than 2026's 0.023, sign flip) despite a materially different regime (65 vs 111 trades) -- the regime-specific hypothesis is falsified; this remains an execution-latency requirement, not a strategy invalidation |

## One-paragraph summary

JadeCap is a Smart-Money-Concepts (SMC/ICT-style) crypto trading bot
built as a **research platform first, execution platform second**. It
has a real Strategy Engine (HTF bias, liquidity sweep, CHOCH/MSS, FVG,
order block, zone-mitigation, confluence entry model), a real Risk
Engine (RR floor, daily/weekly loss limits, position sizing, circuit
breaker, all DB-persisted), a real Backtest Engine (deep OKX history via
paginated fetch, no-lookahead HTF cursor, real fee/slippage/PnL model,
out-of-sample period splitting), a real Paper Trading loop
(`scripts/run_paper.py`, open/close positions against a real OKX
candle feed, no real money), and a real Dashboard (all 5 endpoints
backed by live data). Live Trading is **entirely unimplemented**
(`NotImplementedError` stubs) and gated behind explicit operator
approval — this is by design, not an oversight.

## Layer-by-layer status

| Layer | Status | Notes |
|---|---|---|
| Data (candle fetch) | ✅ Complete | Real OKX public API, deep pagination via `/market/history-candles` (fixed a long-standing 300-candle cap bug), no API key needed. `fetch_ohlcv_history()` can now anchor a fetch to end at a specific past date (`end_time_ms`), enabling genuine cross-YEAR backtesting via `run_backtest.py --end-date` |
| Strategy Engine | ✅ Core rule MVP complete | Bias/sweep/CHOCH/FVG/OB/zone-mitigation/entry-model all real, all tested. Breaker Block detection wired in (opt-in, `use_breaker_block`, A/B tested — see findings below). Confluence-strength spec ambiguity RESOLVED — the existing looser rule (sweep OR CHOCH) is confirmed correct with A/B evidence; `require_full_confluence`/`--strict-confluence` available as an opt-in but not recommended. Core-rule constants TUNED via controlled parameter sweep (`entry_model._RR`=2.5, `_STOP_BUFFER`=0.0015, `order_block._LOOKBACK`=15, `_IMPULSE_MULT`=1.8 — all previously untuned defaults) — see `docs/parameter_sweep_report.md`. **All 5 MVP core rules now shipped** (Premium/Discount, previous swing high/low, OB+FVG confluence, structure-based TP, Equal High/Equal Low) — see "Core rule completion (MVP)" above. The two newest, `require_ob_fvg_confluence`/`use_structure_tp`, ship opt-in and default OFF pending A/B backtest evaluation, same discipline as `use_breaker_block` |
| Risk Engine | ✅ Complete | RR floor, daily/weekly loss limits, trades/day cap, position sizing, DB-persisted circuit breaker — all enforced in both paper AND backtest. Circuit breaker now auto-resets once a fresh daily/weekly check clears (previously a documented gap — see `ENGINEERING_DECISIONS.md` #16). Sizing/loss-limit math still keys off `PLACEHOLDER_ACCOUNT_BALANCE`, intentionally, until Phase 1 gate #4 |
| Backtest Engine | ✅ Complete, actively used for research | Real fee/slippage/PnL, no-lookahead HTF cursor, multi-period out-of-sample splitting (`--periods`, HTF fetch now correctly sized to the LTF request's real time span), time-anchored fetching (`--end-date`), walk-forward validation (`--walk-forward`, explicit PASS/FAIL criteria — PASSED for BTCUSDT baseline), opt-in break-even (`--breakeven`, A/B **no reliable direction across 4 assets OR across 2 years on the same asset — even flips sign on BTCUSDT alone**), opt-in Breaker Block entries (`--breaker-block`, A/B **mostly negative across assets, zero effect in the 2025 BTCUSDT window**), opt-in partial take-profit (`--partial-tp`, A/B **negative on all 4 tested assets AND both tested years on BTCUSDT — the most robust finding in the project**) |
| Paper Trading | ✅ Complete | Real open/close/PnL against live OKX data, no real capital. Break-even stop management is wired here too (`settings.ENABLE_BREAKEVEN`, off by default, PERMANENTLY -- see research findings below) — no reliable direction exists across assets OR across time (it flips sign on BTCUSDT alone between 2025 and 2026), so there is no direction to ever default toward. Breaker Block and partial-TP remain backtest-only (no positive evidence justifying paper trading). Live DB (`backend/paper_validation.db`) is now alembic-stamped at head `e3110e6a6b59` (milestone 8.1, 2026-07-16, `app.database.migrate_existing`) -- previously un-stamped since an early pre-alembic bootstrap, meaning a restart on current code would have crashed on the first trade INSERT; a restart is now safe |
| Portfolio/Journal | ✅ Complete | Real trade/signal persistence, daily/weekly/all-time reports |
| Dashboard | ✅ Complete | All 5 endpoints (`status`, `positions`, `logs`, `risk-status`, `bias`, `signals`) real, DB/live-computed |
| Live Trading | ❌ Not implemented, intentionally gated | `LiveBroker`, `exchange/okx_client.py`, `exchange/orangex_client.py` are all `NotImplementedError` stubs. Requires operator-approved API keys + staged approval before ANY code is written here |

## Test suite

366 backend tests, 0 known failures (363 + 3 new `structure_tp_max_r`
tests, 2026-07-12 profitability sprint -- see ENGINEERING_DECISIONS.md
#39/#40). Run: `cd backend &&
./.venv/Scripts/python.exe -m pytest -q`
(or the platform-appropriate venv path). No frontend test failures
(`npx tsc --noEmit` clean as of the last frontend-touching change).
`scripts/run_paper.py` itself has no direct pytest coverage (needs a live
network candle feed); its DB-backed logic (`TradeTracker.update_stop_loss`,
`_maybe_move_to_breakeven`) is instead verified via a real-temp-SQLite-DB
script exercising long/short/idempotency/disabled-gate paths end to end.

## Current research findings (the actual point of this project)

- **First Jade engine A/B result: bad, stays opt-in/off by default**
  (2026-07-12). The full Jade methodology (5 entry models, exit
  targets, HTF confluence, trendline, CRT, session bias -- see
  `ENGINEERING_DECISIONS.md` #23-#33) was wired end-to-end into
  `SignalEngine`/`BacktestEngine`/`scripts/run_paper.py` behind
  `use_jade_engine`/`settings.USE_JADE_ENGINE` (both default `False`)
  and A/B tested against the existing pipeline at this project's
  standard scale (BTCUSDT, `--candles 3000 --periods 6 --walk-forward`).
  **Result: 6 total trades vs. the legacy pipeline's 47 on the same
  data, 0/6 profitable periods vs. 6/6, -$77.28 total PnL vs. +$1,334.17,
  walk-forward FAILED vs. PASSED.** Not a marginal or mixed result.
  A real performance bug (unbounded displacement-candidate complexity)
  was also found and fixed along the way -- see
  `ENGINEERING_DECISIONS.md` #35/#36 for the full numbers, the
  (unconfirmed) hypothesis for the trade-count gap, and why this is
  disclosed as a real finding despite being only 1 asset/1 window so
  far. **Not recommended for use; `use_jade_engine` stays off.**
- **Deep-history backtesting works** (was capped at ~300 candles/~1 day
  until a real OKX pagination bug was fixed). This is the single most
  important infrastructure fix in the project's history — nothing about
  strategy validity could be assessed before it.
- **A real strategy bug was found and fixed**: `SignalEngine` could
  generate near-duplicate signals re-entering a zone price had already
  tested and failed at. Fixing it flipped a 28-trade BTCUSDT/15m sample
  from -$577.82/25% win rate to +$462.18/75% win rate.
- **Out-of-sample validation exists** (`--periods N`, splits fetched
  history into independent, non-overlapping chronological chunks) and
  has now been run on FOUR independent assets at 6-month/6-period scale
  (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT — all January-July 2026, genuinely
  varied conditions: win rates 40%-100%, trade counts 5-40 across
  periods and assets). The strategy's baseline (no experimental
  features) was **6 of 6 periods profitable on all four assets**.
- **Full rule-by-rule coverage audit exists**: `docs/strategy_coverage_audit.md`.
  Found three items implemented, unit-tested, but never wired into the
  live decision loop. **All three are now wired, A/B tested, and
  re-tested on four independent 6-month asset samples**:

  | Feature | BTCUSDT | ETHUSDT | SOLUSDT | XRPUSDT | Verdict |
  |---|---|---|---|---|---|
  | Break-even (`--breakeven`) | +9.2% | -1.9% | -4.8% | +5.4% | **No reliable direction — 2 of 4 positive, 2 of 4 negative** |
  | Breaker Block (`--breaker-block`) | -3.8% | -12.0% | -1.9% | +1.5% | **Mostly negative — 3 of 4 negative, 1 of 4 positive** |
  | Partial TP (`--partial-tp`) | -32.6% | -35.4% | -29.1% | -28.7% | **Negative on 4 of 4, 24 of 24 periods — the one solid finding** |

  - **Break-even**: positive on BTCUSDT (+13.5% small sample, +9.2%
    6-month) and XRPUSDT (+5.4%); negative on ETHUSDT (-1.9%) and
    SOLUSDT (-4.8%). A 3-asset run had suggested a negative lean (2 of 3
    negative); the 4th asset broke that lean rather than confirming it.
    **This reversal is itself the important finding**: an apparent trend
    from a small number of ASSETS (not periods) reverted to a coin flip
    with one more data point, the same failure mode
    `ENGINEERING_DECISIONS.md` entries #14/#15 already warned about for
    small period counts — it turns out to apply to small asset counts
    too. **Conclusion: no asset-agnostic direction exists** for this
    feature with the evidence gathered so far. This is why
    `ENABLE_BREAKEVEN` ships off by default PERMANENTLY, not
    provisionally pending more data — more assets in the same time
    window are unlikely to resolve a genuine coin flip; the useful next
    test is a different YEAR (see caveats below), not a 5th asset.
  - **Partial take-profit**: negative on all 4 assets, 24 of 24 tested
    periods worse, zero exceptions anywhere. -31.4%/-32.6% (BTC small/
    6-month), -35.4% (ETH), -29.1% (SOL), -28.7% (XRP). Mechanistic
    cause identified and holds on every asset: this strategy has a fixed
    2:1 RR and tends toward a high win rate — locking in half the
    position at 1R trades away half of every full winner's upside, while
    rarely protecting losers (which mostly never reach +1R before
    reversing to the stop). **The single most robust finding in the
    project — solid enough to actively recommend against, not just
    decline to recommend.**
  - **Breaker Block**: negative on 3 of 4 assets (-3.8% BTC, -12.0% ETH,
    -1.9% SOL), positive on 1 (+1.5% XRP). Mostly negative, no longer
    unanimous — "not recommended" still holds given the majority
    direction, but "negative on every tested asset" is no longer an
    accurate description of the evidence.

  All three kept opt-in and non-default in the Backtest Engine. Of the
  three, only break-even was ever wired into paper trading
  (`settings.ENABLE_BREAKEVEN`, off by default) — it shipped while its
  evidence still looked BTCUSDT-consistent; three subsequent validation
  rounds (ETHUSDT, SOLUSDT, XRPUSDT) revealed the true picture is a
  cross-asset coin flip. The off-by-default choice is now a settled
  design conclusion, not a placeholder waiting on more evidence: an
  operator who had defaulted it ON based on the BTCUSDT evidence alone
  would today be running a feature with literally no reliable expected
  sign on a randomly chosen asset.
- **Cross-YEAR validation now exists too, not just cross-asset**: a new
  `end_time_ms`/`--end-date` capability lets a backtest be anchored to
  end at a specific past date instead of always "now". First real use:
  BTCUSDT, same 6-month/6-period methodology, anchored to 2025-07-10
  instead of 2026-07-10. Baseline was still 6 of 6 periods profitable,
  but in a visibly different regime (67 total trades vs. many more in
  2026, one period had only 2 trades). **Break-even flips sign on
  BTCUSDT itself between the two years** (+9.2% in 2026, **-1.9%** in
  2025) — the single clearest piece of evidence in the project that this
  feature has no reliable direction along ANY tested dimension, asset or
  time. Breaker Block had exactly 0.0% effect in the 2025 window
  (identical to baseline in every period). Partial TP reproduced almost
  exactly across years (-32.6% in 2026 vs. -32.1% in 2025) — now
  confirmed negative across 4 assets in one time window AND 2 time
  windows on one asset, the strongest evidentiary base for any finding
  in this project.
- **Legacy's own delay fragility, cross-year checked, is STRUCTURAL --
  and its 2025 trade scarcity turns out to be a risk-cap effect, not a
  signal-drought** (milestone 24, 2026-07-17, full report `docs/
  LEGACY_DELAY_ROBUSTNESS.md`). The same cross-year discipline applied
  above to break-even/partial-TP/tuned-defaults was applied to milestone
  20b's own 2026 delay-gate finding: the identical BTC 2025 anchor
  FAILED the same gate, slightly worse (retention 0.015 vs. 2026's
  0.023) despite a materially different regime (65 vs. 111 trades) --
  falsifying the possibility that the 2026 collapse was regime-specific.
  Separately, milestone 23's risk-rejection counters (used for the first
  time in an evidence round) showed 2025's 65-trade count is NOT signal
  scarcity: 869 raw signals were generated, 804 (92.5%) rejected, and
  100% of fired rejection reasons were `trades_today 2 reached
  MAX_TRADES_PER_DAY 2`. This means the "Legacy trades too selectively"
  framing behind the evidence-starved regime buckets
  (`docs/REGIME_PERFORMANCE_ANALYSIS.md`) is substantially a
  `MAX_TRADES_PER_DAY=2` effect, not a property of signal generation
  itself -- recorded as an insight only; any change to that cap is an
  operator-gated risk-limit decision, not proposed here.
- **Walk-forward validation (Phase 1 gate #2) now exists as a formal,
  reusable artifact**: `run_backtest.py::walk_forward_report()` +
  `--walk-forward` evaluate a chronological period sequence against
  explicit criteria (>= 66% profitable periods, <= 2 consecutive losing
  periods, no >50% first-half-to-second-half PnL falloff) rather than
  just an aggregate sum — catching degradation trends and losing streaks
  an aggregate could hide. This is deliberately NOT a rolling
  parameter-refitting walk-forward (the strategy has no tunable
  parameters to refit yet — see `ENGINEERING_DECISIONS.md` #8); it's a
  genuine check that performance holds up moving forward through
  chronological time. **Real result: PASSED unanimously on all 4 tested
  assets** — BTC ($237->$408), ETH ($367->$541), SOL ($586->$814), XRP
  ($474->$476) all show 6/6 profitable periods, 0 losing streaks, and a
  second half that performed flat-or-better than the first. Zero
  degradation detected on any asset. Phase 1 gate #2 is now closed for
  the current asset set.
- **Controlled parameter sweep completed and adopted**: JadeCap's four
  core-rule constants (`entry_model._RR`/`_STOP_BUFFER`,
  `order_block._LOOKBACK`/`_IMPULSE_MULT`) were previously disclosed as
  "reasonable defaults, not tuned against real performance data". A
  one-at-a-time sweep (never a full grid — avoids the overfitting risk
  of testing 256 combinations at once), selecting candidates by
  robustness (walk-forward pass, meaningful trade count,
  profitable-period ratio and average-R both >= baseline) rather than
  highest profit, found a robust improvement for all four: `_RR`
  2.0->2.5, `_STOP_BUFFER` 0.001->0.0015, `_LOOKBACK` 10->15,
  `_IMPULSE_MULT` 1.5->1.8. Each cleared in-sample selection (BTCUSDT),
  held-out out-of-sample validation (never inspected during selection),
  AND cross-asset validation (ETHUSDT/SOLUSDT/XRPUSDT). Before adopting,
  the combined 4-parameter profile was ALSO checked against BTCUSDT
  anchored to 2025 (a cross-YEAR check, added beyond the operator's
  original sweep scope specifically because this project already found
  cross-asset robustness alone insufficient for break-even) — held up:
  +33.5% PnL, same profitable-period count. A final confirmatory run on
  this project's standard reporting scale (BTC 2026, `--periods 6
  --walk-forward`) showed **+66.7% PnL with walk-forward still PASSING
  cleanly** (0 losing streak, no degradation). Full methodology, every
  number, and explicitly stated caveats (the validation window is still
  only ~6 months plus one 2025 spot-check; interaction effects between
  the four parameters were only spot-checked, not fully swept) in
  `docs/parameter_sweep_report.md`. A real, if unplanned, finding along
  the way: `BacktestEngine`'s walk-forward scan is far worse than linear
  in period length (3000 candles ~88s vs. 1500 candles ~7s) — the
  initial sweep attempt at the usual 3000-candle scale ran 80+ minutes
  with zero visible output before being killed and redesigned.
- **Phase 1 gate #2 (walk-forward validation) fully re-closed under the
  new tuned defaults, all 4 assets**: the parameter sweep above only
  re-confirmed BTCUSDT at this project's standard reporting scale.
  Re-ran ETHUSDT/SOLUSDT/XRPUSDT the same way (`--candles 3000
  --periods 6 --walk-forward`) and all three **PASSED unanimously**:
  6/6 periods profitable each, 0 losing streaks, no degradation. PnL
  improved on every single asset vs. the old (untuned) defaults: BTC
  +66.7%, ETH +4.6%, SOL +32.6%, XRP +39.0%, combined +33.3%
  ($11708.78 -> $15607.93 across all 4 assets). At the time, this was
  the most thoroughly validated state JadeCap's core strategy had been
  in this project's history for the 2026 window specifically.
- **First full cross-year check (2025) on all 4 assets under the new
  tuned defaults — 8 of 9 combinations PASS, 1 real exception found**:
  extended the above to 2025 (`--end-date 2025-07-10`, same standard
  scale). ETHUSDT ($3090.03), SOLUSDT ($4289.78), and XRPUSDT ($4300.39)
  all **PASSED cleanly** — first time any of these three had been tested
  outside the 2026 window. BTCUSDT 2025 at this standard scale
  **FAILED its own walk-forward degradation check**: every one of the 6
  periods was individually profitable ($1714.56 total), so the
  aggregate/profitable-period criteria passed, but the second half's
  average PnL ($149.40) retained only 35.4% of the first half's
  ($422.13) — below the 50% retention threshold. This is a real,
  measured decline (Apr-Jun 2025 meaningfully weaker than Jan-Mar 2025
  under the new defaults specifically), not an artifact. Notably, this
  did NOT show up in the parameter sweep's own BTC-2025 spot-check
  (`docs/parameter_sweep_report.md` §6), which used smaller 1500-candle
  periods and a different period-boundary split — a real, informative
  example of walk-forward conclusions depending on the exact period
  granularity chosen, not just the underlying price data. Not treated
  as a reason to revert the new defaults (BTC 2025 remained net
  profitable throughout, and 8 of 9 standard-scale combinations passed
  cleanly) — but recorded as a genuine, disclosed caveat: the new
  defaults' robustness on BTCUSDT specifically is weaker across time
  than across assets. See `ROADMAP.md` for the natural follow-up
  (investigate whether this is new-defaults-specific or a genuine
  BTC-specific regime shift that the old defaults would show too).
- **Confluence-strength spec ambiguity resolved with real A/B evidence**:
  `docs/strategy_spec.md` section 6's prose previously read as requiring
  ALL of bias + sweep + CHOCH + FVG/OB in confluence; the actual code
  had always required only bias + (sweep OR CHOCH) + (FVG OR OB), a
  strictly looser bar (`docs/strategy_coverage_audit.md` row #9). Added
  opt-in `require_full_confluence` (`--strict-confluence`), A/B tested
  across all 4 assets, 6-month/6-period each: requiring BOTH sweep AND
  CHOCH cuts trade count 75.9% (457 -> 110 across the 4-asset sample)
  for a per-trade PnL only 3.8% different from the looser default --
  not meaningfully higher quality, just far fewer trades of the same
  quality, costing ~75% of total realized profit. **Resolved in favor
  of the existing looser implementation** -- the spec text itself was
  rewritten to state the confluence rule explicitly (sweep OR CHOCH),
  closing the ambiguity for good rather than leaving it open. This is
  the fourth time in this project that "does adding a stricter/more
  cautious rule actually help" was tested rather than assumed, and the
  fourth time the answer required real data to determine (break-even:
  yes on one asset, no on others; Breaker Block: mostly no; partial-TP:
  no; strict confluence: no).
- **Data-layer bug found and fixed along the way**: `scripts/run_backtest.py`
  requested the same candle COUNT for both LTF and HTF fetches, which
  for a large `--periods` request meant asking for years more HTF
  history than needed (18000 candles at `4h` = ~8.2 years vs. the ~187
  days actually needed). Fixed with `timeframe_to_timedelta()` +
  `htf_candle_count_for_span()`, which size the HTF request off the
  real time span the LTF request covers.

## Honest caveats (read before citing these results anywhere)

- 4 assets checked (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT), all large-cap
  tokens with broadly similar market beta — not a genuinely diverse
  asset set, and two of the three findings (break-even, Breaker Block)
  already show no unanimous direction even within this correlated set.
- Only 2 time windows checked at all (2025-07 and 2026-07, both anchored
  to BTCUSDT only) — every other asset (ETH/SOL/XRP) is still tested in
  the 2026 window alone. A 2024 window, or the 2025 window on the other
  three assets, remain untested.
- Per-period trade counts (2-40 across all samples so far, with the 2025
  BTCUSDT window's period 1 at just 2 trades) are still modest in
  places; win-rate confidence intervals remain wide, especially for the
  smaller-trade-count periods.
- `_RR`/`_STOP_BUFFER`/`_LOOKBACK`/`_IMPULSE_MULT` are now TUNED (2026-07-11
  controlled parameter sweep, `docs/parameter_sweep_report.md`) using the
  `--periods` tool's held-out-period discipline — validated across 2026
  AND 2025 on all 4 assets at this point (8 of 9 standard-scale
  combinations clean, 1 real BTCUSDT-2025 degradation exception, see
  above), still only 2 calendar years and 4 correlated large-cap assets
  though, and the one-at-a-time sweep methodology never tested
  interaction effects between the four parameters together (only a
  small number of confirmatory runs of the combined profile).
  `BREAKEVEN_TRIGGER_R`/
  `PARTIAL_TP_TRIGGER_R`/`PARTIAL_TP_PORTION` remain untuned, disclosed
  defaults — deliberately excluded from this round since they only affect
  the off-by-default experimental features (see `ROADMAP.md`). Any future
  parameter work must keep using the same held-out-period discipline or
  the entire point of the tooling is defeated.

**Conclusion: one finding is now solid across every dimension tested, two
are genuinely unresolved across every dimension tested — and
"unresolved" is itself a real, useful result, not a gap in the
process.** Partial-TP's negative verdict has now reproduced on 4
independent assets (24/24 periods) AND across 2 independent years on the
one asset checked both ways — as strong an evidentiary base as this
project has produced for anything, strong enough to actively recommend
against using it. Break-even and Breaker Block both show results with no
reliable direction along EITHER axis: break-even flips sign both across
assets (2 of 4 positive) and across time on the SAME asset (+9.2% to
-1.9% on BTCUSDT alone). This is the clearest demonstration in this
project so far of why small counts of ANYTHING (periods, assets, or now
time windows) can manufacture the appearance of a trend that isn't real.
See `ROADMAP.md` for what's next.
