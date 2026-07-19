# Adaptive Trading Platform — Design Document

Operator directive (2026-07-15): objective changes from "find one
perfect strategy" to "build an adaptive trading system that survives
changing market conditions." This is the complete design deliverable
requested before further implementation: architecture, Market Regime
Detector, Strategy Interface, Strategy Selection Engine, Risk Engine,
Performance Database schema, and an implementation roadmap with
milestones.

**Unchanged throughout, no exceptions**: Legacy stays the untouched
production baseline. Paper trading keeps running exactly as it has.
Nothing in this document authorizes touching either without a separate,
explicit, later decision.

---

## 1. Overall system architecture

```
                    ┌─────────────────────┐
                    │     Market Data      │  app.data.candle_fetcher
                    │  (OKX, deep history)  │  app.data.data_normalizer
                    └──────────┬───────────┘
                               │  ltf_candles, htf_candles
                               ▼
                    ┌─────────────────────┐
                    │  Market Regime       │  NEW: app.regime.regime_detector
                    │  Detector             │  (section 2)
                    └──────────┬───────────┘
                               │  MarketRegime (trend / volatility / event flags)
                               ▼
                    ┌─────────────────────┐
                    │  Strategy Selection   │  NEW: app.strategy.selector
                    │  Engine                │  (section 4)
                    └──────────┬───────────┘
                               │  selects one Strategy from the registry
                               ▼
          ┌────────────────────┴────────────────────┐
          │        AVAILABLE_STRATEGIES (registry)    │
          │  ┌───────────────┐   ┌───────────────┐    │
          │  │ Strategy A     │   │ Strategy B     │  … │  app.strategy.strategy_interface
          │  │ Legacy         │   │ Jade           │    │  (section 3 — BUILT)
          │  └───────────────┘   └───────────────┘    │
          └────────────────────┬────────────────────┘
                               │  TradeSignal | None
                               ▼
                    ┌─────────────────────┐
                    │   Risk Engine         │  app.risk.* (EXISTING, extended)
                    │                        │  (section 5)
                    └──────────┬───────────┘
                               │  RiskDecision (approved/rejected)
                               ▼
                    ┌─────────────────────┐
                    │     Execution         │  app.execution.* (EXISTING, unchanged)
                    └──────────┬───────────┘
                               │  ExecutionResult
                               ▼
                    ┌─────────────────────┐
                    │  Performance          │  app.portfolio.* + app.database.models
                    │  Evaluation            │  (section 6, EXTENDED)
                    └──────────┬───────────┘
                               │  regime-tagged, strategy-tagged trade history
                               ▼
                    ┌─────────────────────┐
                    │  Continuous Learning  │  NEW: rolling metrics + auto-disable
                    │                        │  feeds back into Strategy Selection
                    └──────────┬───────────┘
                               │
                               └──────────────► (loops back into Strategy Selection Engine)
```

**Design principle governing every box above**: every stage that already
exists (Market Data, Risk Engine, Execution) is REUSED, not rebuilt. Every
stage that's new (Regime Detector, Strategy Selection, Continuous
Learning) is built as an ADDITIVE layer that wraps or observes existing
code rather than modifying it. This mirrors the project's own established
discipline (`ENGINEERING_DECISIONS.md` #10: opt-in flags before default
changes) applied to a system-level pivot instead of a single parameter.

**Data flow contract between stages** (so each stage can be built/tested
independently):

| From | To | Contract |
|---|---|---|
| Market Data | Regime Detector | `ltf_candles: list`, `htf_candles: list` (existing shape, unchanged) |
| Regime Detector | Strategy Selector | `MarketRegime` dataclass (section 2) |
| Strategy Selector | Strategy module | none -- selector just picks which `Strategy.generate_signal()` to call |
| Strategy module | Risk Engine | `TradeSignal \| None` (existing shape, unchanged) |
| Risk Engine | Execution | `RiskDecision` (existing shape, unchanged) |
| Execution | Performance Evaluation | `ExecutionResult` + regime/strategy tags (section 6) |
| Performance Evaluation | Continuous Learning | queryable trade history (SQL, via existing `TradeTracker`-style access) |
| Continuous Learning | Strategy Selector | per-regime, per-strategy rolling metrics + disabled-strategy list |

---

## 2. Market Regime Detector

### 2.1 Design principle: composite, not a single flat label

The operator's list (Strong Trend / Weak Trend / Range / High Volatility
/ Low Volatility / Breakout / Mean Reversion / Liquidity Sweep
Environment) mixes states that are naturally MUTUALLY EXCLUSIVE (a market
can't be both "Strong Trend" and "Range" at once) with states that can
CO-OCCUR (a "Strong Trend" can also be "High Volatility"; a "Breakout"
is a moment-in-time event that can happen inside either a trend or a
range). Forcing all eight into one flat label would either lose
information (which one wins when two are simultaneously true?) or
require an arbitrary priority order with no objective basis. Instead:

```python
@dataclass
class MarketRegime:
    trend: str          # "strong_trend" | "weak_trend" | "range" -- mutually exclusive
    volatility: str      # "high_volatility" | "normal_volatility" | "low_volatility" -- mutually exclusive
    breakout: bool        # event flag, can co-occur with any trend/volatility state
    mean_reversion: bool  # event flag
    liquidity_sweep_environment: bool  # event flag
    metrics: dict[str, float]  # every raw metric that produced this classification, for audit/backtest
```

This is itself an objective, testable design: `trend` and `volatility`
are always exactly one value each (a real classification), and the three
event flags are independent booleans computed from their own objective
thresholds.

### 2.2 Objective metrics, mapped to what already exists vs. what's new

| Metric | Status | Source |
|---|---|---|
| ATR | ✅ built | `app.strategy.utils.average_true_range` (added 2026-07-14, experiment 6) |
| Realized volatility | ✅ built | `scripts/robustness_report.py::_realized_volatility` -- needs promoting to a shared `app.strategy.utils` function (currently script-local) |
| Swing structure / HH-HL-LH-LL | ✅ built | `app.strategy.market_structure.find_swing_highs`/`find_swing_lows` already produce the swing points; HH/HL/LH/LL is a direct comparison of consecutive swing values, not yet extracted as a labeled function |
| Liquidity sweep frequency | ✅ built | `app.strategy.liquidity.detect_liquidity_sweep`, `detect_equal_highs`/`detect_equal_lows` -- regime detector counts recent firings over a lookback window |
| Market structure breaks (CHOCH/BOS) | ✅ built | `app.strategy.market_structure.detect_choch_mss`/`detect_bos` |
| FVG density | ✅ built | `app.strategy.fvg.detect_fair_value_gap` -- regime detector counts gaps per lookback window |
| Order block quality | 🟡 partial | `app.strategy.order_block.detect_order_block` exists; "quality" scoring (e.g. impulse strength) would reuse `entry_point_engine._displacement_strength`'s existing logic (decision #23), not a new concept |
| ADX | ❌ new | Standard trend-strength indicator (+DI/-DI/smoothed directional movement) -- not yet in this codebase. Operator explicitly named it; standard, not a new indicator by any reasonable reading. |
| Distance from Moving Average | ❌ new | Needs a simple moving-average calculation (SMA or EMA over N periods) -- standard, small |
| VWAP | ❌ new | Needs a volume-weighted average price calculation -- OKX candles carry `volume`, so the raw input exists; the calculation itself is new but standard |
| Volume | ✅ available | OKX candles already carry `volume` (see `app.database.models.Candle`) |
| Volume Delta (buy vs. sell volume) | ⚠️ constrained | OKX's public candle endpoint returns TOTAL volume per candle, not a buy/sell split -- computing a true volume delta would need tick-level trade data, a genuinely different (and currently unused) data source. Disclosed limitation, not silently assumed available -- deferred until/unless tick data is added as a new market-data source. |
| Session statistics | ✅ built | `app.strategy.session_liquidity`/`session_bias` already compute session-anchored highs/lows and directional bias |

### 2.3 Classification logic (disclosed thresholds, not yet backtest-tuned)

Consistent with this project's own established pattern (`entry_model._RR`/
`_STOP_BUFFER` shipped as "reasonable, disclosed, not-yet-tuned defaults"
before their 2026-07-11 sweep, `ENGINEERING_DECISIONS.md` #18) --
thresholds below are standard textbook values, explicitly flagged as a
starting point for future evidence-based tuning, not values discovered by
backtesting:

- **Trend** (via ADX, standard convention): ADX >= 25 -> `strong_trend`;
  15 <= ADX < 25 -> `weak_trend`; ADX < 15 -> `range`. Cross-checked
  against swing structure (a `strong_trend` classification additionally
  requires the last 3 confirmed swing points to be monotonic -- HH+HL for
  up, LH+LL for down -- so a high ADX driven by one violent, structurally
  incoherent move doesn't alone qualify).
- **Volatility**: realized volatility (already-built function) compared
  against its OWN rolling percentile over a lookback window (e.g. 100
  periods) -- `>= 75th percentile` -> `high_volatility`,
  `<= 25th percentile` -> `low_volatility`, else `normal_volatility`.
  Percentile-relative (not an absolute threshold) so the same
  classification logic works across assets with very different baseline
  volatility, without per-asset hardcoded numbers.
- **Breakout**: current close beyond the highest-high/lowest-low of the
  preceding N candles (Donchian-channel convention, standard), AND
  volume above its own rolling average -- a break with no volume
  confirmation is not flagged.
- **Mean reversion**: distance from a moving average (new metric) exceeds
  a stdev-based threshold (e.g. 2 standard deviations of recent
  closes-from-MA distance) WITHOUT a concurrent `strong_trend`
  classification -- an extreme reading during a genuine strong trend is a
  continuation signal, not a reversion setup, so the two are deliberately
  exclusive in this rule.
- **Liquidity sweep environment**: 2 or more confirmed sweeps
  (`detect_liquidity_sweep` and/or equal-high/low sweeps) within the most
  recent N candles -- a single sweep is normal market noise; a cluster of
  them is what this flag is meant to capture.

### 2.4 Output is always audit-able

Every `MarketRegime` instance carries its own `metrics` dict (the raw
ADX/volatility percentile/distance-from-MA/etc. values that produced the
classification) -- so a later backtest or live-trading review can always
answer "why was this classified as X" without re-deriving it, matching
this project's "no black-box classification" discipline already
established for `detect_htf_bias`/`calculate_premium_discount`/etc.
(every existing detector returns its own reasoning, never just a label).

---

## 3. Strategy Interface — BUILT (2026-07-15)

Already implemented and tested (`backend/app/strategy/strategy_interface.py`,
`backend/tests/test_strategy_interface.py`, 7/7 passing) as of this
design document. Specification, for completeness:

```python
@runtime_checkable
class Strategy(Protocol):
    name: str
    def generate_signal(self, symbol: str, ltf_candles: list, htf_candles: list) -> TradeSignal | None: ...
```

- **`Protocol`, not an ABC** -- structural typing lets both Legacy
  (`entry_model.build_entry_model`, a free function) and Jade
  (`jade_trade_plan.build_trade_plan`, a different free function with a
  different internal shape) conform without restructuring either one
  around a shared base class they were never designed for.
- **Adapters wrap, never modify.** `LegacyStrategy`/`JadeStrategy` both
  delegate to the ALREADY-EXISTING `SignalEngine.generate_signal(...,
  use_jade_engine=...)` integration point (`ENGINEERING_DECISIONS.md`
  #34) -- zero new trading logic, proven by tests asserting the adapter's
  output is byte-identical to calling `SignalEngine` directly.
- **`AVAILABLE_STRATEGIES` registry**: a plain `dict[str, Strategy]`
  (`{"legacy": LegacyStrategy(), "jade": JadeStrategy()}`), not a class --
  the Strategy Selection Engine (section 4) is what will decide which
  entry to use; this registry only answers "what exists and conforms."
- **Return contract unchanged**: `TradeSignal | None`, the exact same
  type every existing caller (Risk Engine, backtest engine, paper
  trading) already consumes -- a `Strategy` is a drop-in replacement for
  "however `SignalEngine` currently decides what to call," not a new
  data contract downstream code needs to learn.

---

## 4. Strategy Selection Engine (BUILT)

**Status**: `app.strategy.selector.StrategySelector` (Protocol) +
`DefaultToLegacySelector`, implemented exactly as specified below. See
`ENGINEERING_DECISIONS.md` #46. One deliberate refinement over the
signature below: `select()`'s `regime` parameter is typed
`MarketRegime | None`, since `detect_market_regime()` (section 2) can
return `None` below its minimum candle-history floor -- a real case the
selector's caller can hit.

**Milestone 7b update (operator directive, 2026-07-16, ENGINEERING_DECISIONS.md
#50): wired live into `scripts/run_paper.py`, behind `settings.
USE_STRATEGY_SELECTOR` (default `False`)**. A second selector,
`ConfigurableFallbackSelector`, was added specifically for this wiring --
`DefaultToLegacySelector` was deliberately NOT used here, since routing
through it would have silently made `settings.USE_JADE_ENGINE` (a
documented operator override) permanently inert for paper trading.
`ConfigurableFallbackSelector` honors `use_jade_engine` (a caller-computed
value, read from `settings.USE_JADE_ENGINE`) as an explicit override,
otherwise deterministically falls back to `legacy` -- regime is recorded
via `select_with_reason()` -> `SelectionDecision` for observability
(logs + `Trade.strategy_config`) but never influences the choice; no
automatic regime-based switching exists yet. `False` (the default)
reproduces the exact pre-existing direct-`SignalEngine` call path,
byte-for-byte -- verified by a regression test proving the selector
path's own default output is identical to calling `SignalEngine`
directly. See decision #50 for the full design and how to enable/disable.

### 4.1 Interface

```python
class StrategySelector(Protocol):
    def select(self, regime: MarketRegime, available: dict[str, Strategy]) -> Strategy: ...
```

### 4.2 Initial implementation: deterministic, honest about having no data yet

Per the operator's own instruction ("initially use deterministic rules...
later this can evolve into machine learning"), and per this project's
"evidence over assumption" discipline: the FIRST deterministic policy
cannot claim per-regime performance evidence that doesn't exist yet (no
regime-tagged trade history has ever been collected -- section 6 is what
starts collecting it). The honest initial rule:

```python
class DefaultToLegacySelector:
    """Selects `legacy` unconditionally, regardless of regime, until real
    regime-tagged performance data (section 6) exists to justify anything
    else. This is deliberately NOT a sophisticated regime-conditioned
    rule table populated with guessed mappings -- inventing "Strong Trend
    -> Strategy C" associations with zero evidence would be exactly the
    "evidence over assumption" violation this project's entire discipline
    exists to prevent, applied at the architecture level instead of the
    parameter level.
    """
    def select(self, regime: MarketRegime, available: dict[str, Strategy]) -> Strategy:
        return available["legacy"]
```

This is intentionally the least interesting possible Strategy Selector --
which is the point. It makes the SYSTEM real (every downstream stage --
Risk Engine, Execution, Performance Evaluation, Continuous Learning --
now has a genuine Strategy Selection stage to integrate with) without
fabricating strategy-selection intelligence that hasn't been earned by
evidence. It also means: turning this system on changes NOTHING about
production behavior on day one (still always Legacy), satisfying "keep
Legacy unchanged as the production baseline" literally, not just in
spirit.

### 4.3 Evolution path (not built yet, sequenced after real data exists)

1. **Rule table, evidence-populated**: once section 6's performance
   database has enough regime-tagged trades per strategy (a real sample
   size threshold, not a guess -- this project's own established floor
   for trusting a result is 20+ trades, see `experiment_runner.
   MIN_TRADES_FOR_CONFIDENCE`), a `RollingPerformanceSelector` can pick
   `argmax` strategy by (e.g.) rolling expectancy within each regime,
   falling back to `legacy` whenever a regime has insufficient data for
   any strategy.

   **Status update (milestone 12, evidence round 2, 2026-07-16)**: this
   data requirement is now quantified, not just described. Running a
   `RollingPerformanceSelector` against the current regime-tagged
   backtest dataset (BTCUSDT 15m, single window) shows only 1 of 9
   regime buckets (`weak_trend/normal_volatility`) clears the n>=20
   floor on both Legacy and an experimental strategy -- the other 8
   would fall back to `legacy` purely on insufficient data. At Legacy's
   own observed trade rate (111 trades/6 months on this asset), it would
   take multiple such windows to fill the remaining buckets from Legacy
   trade history alone -- confirming milestone 11's shadow-mode
   recording (which accumulates at pass speed, not trade speed) as the
   faster path once enabled. See `ENGINEERING_DECISIONS.md` #54.

   **Status update (milestones 13-16, 2026-07-16): the rest of this
   evolution step is now BUILT.** `RollingPerformanceSelector` (item 1
   above) exists, is tested, and consumes a real rolling evidence layer
   (`app.portfolio.rolling_regime_performance.collect_regime_evidence()`,
   milestone 15) fed by two independent, never-blended sources: live
   trade history (`Trade.market_regime`/`r_multiple`, populated since
   milestone 7) and resolved shadow signals (`ShadowSignal.outcome`,
   milestone 14 -- outcome resolution wired into `run_paper.py` behind
   the existing `ENABLE_SHADOW_STRATEGY_SIGNALS` flag, so shadow
   evidence can now accumulate to a real tp/sl/expired outcome, not just
   a captured signal). `scripts/shadow_status.py` (milestone 13) and
   `scripts/selector_dry_run.py` (milestone 16) are read-only tools
   (`mode=ro` SQLite) for checking data sufficiency and selector output
   respectively, without touching anything live. A dry run on a scratch,
   head-migrated database reproduced milestone 12's own prediction
   exactly: `legacy` in all 10 buckets (9 regime + untagged), all via the
   unmeasured-baseline fallback -- confirming the selector's logic is
   sound but that sufficient evidence still does not exist yet. **The
   selector remains unwired into `scripts/run_paper.py` by design** --
   `AVAILABLE_STRATEGIES` and both production selectors
   (`DefaultToLegacySelector`, `ConfigurableFallbackSelector`) are
   untouched. What remains before this evolution step could be
   considered complete in practice, not just in code: (i) time for
   shadow/live data to accumulate past the 20-sample floor in more
   buckets, (ii) an operator evidence review once it does, (iii) an
   explicit operator decision to wire `RollingPerformanceSelector` in.
   See `ENGINEERING_DECISIONS.md` #55, #56.
2. **ML-based selection**: explicitly deferred, not scoped further here
   -- the operator named it as a future direction, not a current
   requirement, and building it before step 1 has real data to learn
   from would be building a model with nothing to fit.

---

## 5. Risk Engine

### 5.1 What already exists (unchanged, reused as-is)

| Component | Location | Role |
|---|---|---|
| `RiskManager.evaluate()` | `app.risk.risk_manager` | Approves/rejects a `TradeSignal` -- RR floor, daily/weekly loss limits, trades/day cap. Already strategy-agnostic (takes a signal, not a strategy reference). |
| `DrawdownGuard` | `app.risk.drawdown_guard` | Daily/weekly loss-limit checks |
| `CircuitBreaker`/`PersistentCircuitBreaker` | `app.risk.circuit_breaker` | Account-wide trading halt, DB-persisted, auto-resets (`ENGINEERING_DECISIONS.md` #16) |
| `calculate_position_size` | `app.risk.position_sizing` | Risk-percent-of-account sizing from entry/stop distance |

This layer already satisfies the operator's "Risk Management is
independent from strategies" requirement -- it was built that way from
the start of this project (decision precedent: `RiskManager.evaluate()`
has never taken a strategy identity as input, only a signal's own
entry/stop/rr).

### 5.2 Extensions needed for a multi-strategy system

| Extension | Why | Priority | Status |
|---|---|---|---|
| **Per-strategy disable hook** | Section 6/Continuous Learning needs a way to tell the Risk Engine "strategy X is disabled, reject its signals" -- currently `RiskManager` has no concept of a signal's originating strategy at all. Minimal addition: `TradeSignal` (or the Strategy interface) carries a `strategy_name`, `RiskManager.evaluate()` gains an `is_strategy_disabled(name) -> bool` check. | High -- required before section 6's auto-disable is meaningful | **BUILT** -- `evaluate()` gains `strategy_disabled: bool` (a caller-computed value, not a lookup inside `app.risk` -- see ENGINEERING_DECISIONS.md #49 for why) |
| **Correlated exposure check** | Only matters once MULTIPLE strategies can be concurrently active (not true today -- only `legacy` is ever selected per section 4.2). Prevents two strategies both opening a same-direction position on the same symbol simultaneously, double-risking the account on one correlated bet. | Low today, rises once section 4's selector becomes regime-conditioned across multiple live strategies | Not built -- still not true today, deliberately deferred (decision #49) |
| **Volatility-scaled position sizing** | `calculate_position_size` currently sizes purely off the signal's own entry/stop distance -- a `MarketRegime.volatility` input could scale the risk-percent DOWN in `high_volatility` regimes as an account-level safety measure, independent of any one strategy's own stop placement. | Medium -- genuinely useful, not blocking on anything else, can be built once the Regime Detector (section 2) exists | **BUILT** -- `calculate_position_size(..., volatility: str \| None)`, 0.5x scalar in `high_volatility`, disclosed-not-tuned |

None of these are blocking for the Strategy Interface milestone (section
3, already done) or the Regime Detector milestone (section 2, next) --
sequenced later in the roadmap (section 7) for exactly that reason.

---

## 6. Performance Database schema

### 6.1 What already exists

`Trade` table (`app.database.models.Trade`) already has, as of
`ENGINEERING_DECISIONS.md` #40 (2026-07-14): `entry_price`, `stop_loss`,
`take_profit`, `exit_price`, `size`, `pnl`, `fee`, `slippage`, `status`,
`mode`, `opened_at`, `closed_at`, `exit_reason`, `r_multiple`,
`strategy_config` (JSON, currently holds `{use_jade_engine, enable_breakeven}`).

### 6.2 New columns needed (additive, nullable, same migration discipline as decision #40)

| Column | Type | Purpose |
|---|---|---|
| `market_regime` | JSON | The full `MarketRegime` (trend/volatility/flags/metrics) at signal time -- NOT just a label, the whole audit-able classification (section 2.4) |
| `strategy_name` | String | Explicit, queryable strategy identifier (`"legacy"`/`"jade"`/future) -- promotes the existing `strategy_config` JSON's implicit info into a real indexed column for fast per-strategy rollups |
| `holding_time_seconds` | Float, nullable | `closed_at - opened_at` in seconds -- derivable from existing columns, but stored explicitly so rolling-metrics queries (section 6.3) don't need to recompute it per row |
| `max_adverse_excursion` | Float, nullable | Worst unrealized loss (in price units or %) reached while the trade was open, before it closed -- NOT currently tracked anywhere; requires the execution/paper-trading loop to check open positions against intra-trade price extremes, not just at close (a real, new tracking requirement, not a schema-only change) |
| `max_favorable_excursion` | Float, nullable | Best unrealized profit reached while open -- same tracking requirement as MAE |
| `latency_ms` | Float, nullable | Time between signal generation and order fill confirmation -- directly motivated by `docs/ROBUSTNESS_REPORT.md` test 2's execution-delay finding; for PAPER trading this will typically be small/synthetic, but the column exists so LIVE trading (Phase 1 gate #4, still gated) has somewhere real to record it from day one |

### 6.3 New table: `strategy_performance_snapshots`

Rolling metrics, computed periodically (not per-trade) -- "Every strategy
continuously tracks: Rolling Win Rate, Rolling Profit Factor, Rolling
Expectancy, Rolling Drawdown, Rolling Sharpe, Rolling Sortino, Rolling
Recovery Factor. If a strategy deteriorates beyond predefined thresholds,
the system automatically disables it."

```
strategy_performance_snapshots
  id                  PK
  strategy_name        String, indexed
  market_regime         String, indexed, nullable (NULL = all-regime aggregate row)
  window_trades         Integer          -- how many trades this snapshot covers
  computed_at            DateTime, indexed
  win_rate                Float
  profit_factor            Float
  expectancy                Float
  max_drawdown               Float
  sharpe                      Float
  sortino                      Float
  recovery_factor                Float
  is_disabled                     Boolean, default False
  disabled_reason                  String, nullable
```

**Why a snapshot table, not just querying `Trade` live every time**:
rolling metrics need a consistent, replayable definition of "the window"
(e.g. last 30 trades, or last 30 days) -- computing them fresh on every
read risks two different call sites disagreeing about what "current"
means. A snapshot table makes each evaluation a discrete, timestamped,
auditable event (same "don't fabricate an answer, show your work"
principle as section 2.4's regime metrics).

**Auto-disable rule** (initial, disclosed-not-tuned, same discipline as
every other new threshold in this document): a strategy is marked
`is_disabled=True` when its most recent snapshot shows profit_factor < 1
AND win_rate below its own historical baseline by more than some
delta -- exact thresholds deferred to when real data exists to validate
them against, per section 4.2's same "don't invent evidence" principle.
Until then, `is_disabled` simply defaults to `False` for every strategy
and the column exists so the mechanism is ready the moment real data
justifies using it.

---

## 7. Implementation roadmap with milestones

Each milestone is independently committable, independently testable, and
does not depend on a LATER milestone to be safe/useful on its own.

| # | Milestone | Depends on | Status |
|---|---|---|---|
| 1 | **Strategy Interface** (`Protocol` + Legacy/Jade adapters + registry) | none | ✅ DONE (2026-07-15), 7/7 tests passing |
| 2 | **Performance Database schema extensions** (section 6.2 columns + section 6.3 table, Alembic migration) | none (additive schema, same pattern as decision #40) | ✅ DONE (commit 7489c3e) |
| 3 | **Market Regime Detector** (section 2 design, implemented) | none new (reuses existing detectors; ADX/MA/VWAP are the only genuinely new calculations) | ✅ DONE (commit b415ff6) |
| 4 | **Strategy Selection Engine** (`DefaultToLegacySelector`, section 4.2) | #1 | ✅ DONE (commit 2d55d68) |
| 5 | **MAE/MFE/latency tracking wired into paper trading** | #2 | ✅ DONE (commit 5e065f8) |
| 6 | **Rolling metrics computation + auto-disable mechanism** | #2, #5 (needs real MAE/MFE/latency-tagged data to be meaningful, not just PnL) | ✅ DONE (commit 7b0b868) |
| 7 | **Risk Engine extensions** (per-strategy disable hook, volatility-scaled sizing) | #3 (volatility scaling needs regime output), #6 (disable hook needs something to disable strategies) | ✅ DONE (commits b015785, 6ff2f6f) |
| 8.1 | **Live paper-DB migration to schema head** (`app.database.migrate_existing`, fingerprint-detect + stamp + upgrade) | #2 | ✅ DONE (2026-07-16) -- see `ENGINEERING_DECISIONS.md` #51 |
| 8 | **New strategy modules** (Trend Following, Range Trading, Breakout, Volatility Expansion) | #1 | ✅ DONE 2026-07-16 -- implemented AND quarantined in `EXPERIMENTAL_STRATEGIES` (`app.strategy.experimental`), zero backtest evidence yet, **NOT production candidates**. See `ENGINEERING_DECISIONS.md` #52. |
| 10 | **Evidence round 1** (backtest evaluation of the four milestone-8/9 experimental strategies vs. Legacy baseline) | #8 | ✅ DONE 2026-07-16 -- BTCUSDT 15m, 5 runs on identical candles. All four FAILED walk-forward; **none promoted**. `breakout` clearly dead; `volatility_expansion` least-bad (3/6 profitable periods). Full report: `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`. |
| 11 | **Shadow-mode observability** (`regime_snapshots` + `shadow_signals` tables, `app.portfolio.shadow_recorder`) | #2, #3, #4 | ✅ DONE 2026-07-16 -- default-off (`ENABLE_SHADOW_STRATEGY_SIGNALS=False`); records a regime snapshot every paper pass plus what every non-active registered strategy would have signaled. Unblocks this section's (4.3) data requirement once enabled and given time to accumulate. See `ENGINEERING_DECISIONS.md` #53. |
| 12 | **Regime-tagged backtesting + per-regime performance analytics + evidence round 2** (`BacktestEngine.run(tag_regimes=True)`, `app.backtesting.regime_analysis`, `scripts/analyze_regime_performance.py`) | #3, #8, #10 | ✅ DONE 2026-07-16 -- thesis unsupported on this evidence: BTCUSDT single-window backtest shows no regime bucket where an experimental strategy credibly beats Legacy (only bucket with n>=20 both sides: Legacy +$26.28 expectancy/PF 3.30 vs best experimental +$4.29/PF 1.23), and Legacy routes 9/9 buckets today (8 by insufficient-data fallback, 1 by argmax). See `ENGINEERING_DECISIONS.md` #54, full report `docs/REGIME_PERFORMANCE_ANALYSIS.md` (final). |
| 13 | **Shadow-data status tool** (`scripts/shadow_status.py`, `app.portfolio.shadow_status`) | #11 | ✅ DONE 2026-07-16 -- read-only (`mode=ro` SQLite URI) report of snapshot stats, per-(strategy,bucket) shadow-signal counts, and distance to the 20-sample routability floor; discloses that signal counts alone are necessary-not-sufficient for routability. See `ENGINEERING_DECISIONS.md` #55(a). |
| 14 | **Shadow outcome resolution** (migration `65aba13281ad`, `app.portfolio.shadow_resolver`) | #11 | ✅ DONE 2026-07-16 -- `ShadowSignal` gains `outcome`/`resolved_at`/`resolved_r`; `resolve_open_shadow_signals()` walks post-capture candles, SL-before-TP within a candle (mirrors `BacktestEngine._simulate_trade`), 7-day expiry, wired into `run_paper.py` behind the existing shadow flag. Simulated fills only, no fees/slippage. A production JSON-serialization bug (datetime in a JSON column, raise outside the per-strategy guard) was found and fixed in the same round. See `ENGINEERING_DECISIONS.md` #55(b)-(d). |
| 15 | **Rolling per-regime evidence layer** (`app.portfolio.rolling_regime_performance`) | #14 | ✅ DONE 2026-07-16 -- `collect_regime_evidence()` returns per-(strategy, bucket, source) cells, shadow and live sources kept permanently separate (never averaged). See `ENGINEERING_DECISIONS.md` #55(e). |
| 16 | **`RollingPerformanceSelector`** (`app.strategy.selector`, `scripts/selector_dry_run.py`) | #15 | ✅ DONE 2026-07-16, **built but NOT wired** -- unmeasured-baseline fallback, live-precedence, strict-inequality qualification, disclosed non-significance. Dry run against a scratch DB reproduced the predicted "legacy in all 10 buckets" result from milestone 12. Wiring into `run_paper.py` deferred to a future, evidence-gated operator decision. See `ENGINEERING_DECISIONS.md` #56. |
| 17 | **Multi-symbol shadow collection + daily CTO reporting** (`settings.SHADOW_SYMBOLS`, `scripts/cto_report.py`, `app.portfolio.cto_report`) | #11, #13, #15, #16 | ✅ DONE 2026-07-16 -- evidence-throughput multiplication (17a: extra symbols shadow-evaluated by all six registered strategies, since none is active there) plus a daily CTO reporting tool (17b: 8 sections, never-fabricate fallbacks, mechanical bottleneck rule). First live run: 28 regime snapshots (3 buckets), 0 sufficient evidence cells. See `ENGINEERING_DECISIONS.md` #57. |
| 18 | **Research round 1's top-3 adopted** (`docs/RESEARCH_ROUND_1.md`; `run_backtest.py --delay-check`, RiskManager ATR stop floor, shadow-fill resolution v2) | #10, #14, #15 | ✅ DONE 2026-07-16 -- 18a: `--delay-check` promotion gate (zero-delay vs `entry_delay_candles=1` on identical candles, `pf_retention >= 0.5` + no sign flip, honest `passed=None` on insufficient data); 18b: caller-computed `stop_distance_atr_mult`/`min_stop_atr_mult` in `RiskManager.evaluate()` (`settings.MIN_STOP_ATR_MULT` default 0.0 = disabled, A/B evidence required before enabling); 18c: migration `6b085b904777` + v2 resolver (1-candle-delayed fill, fees/slippage, gap handling; `resolution_model` tags the regime, `collect_regime_evidence` counts v2 rows only). 652/652. See `ENGINEERING_DECISIONS.md` #58. |
| 19 | **Performance round 1: backtester quadratic-scan fix** (`order_block.py::detect_order_block` reverse-scan early-exit) | none (internal algorithmic fix, no interface change) | ✅ DONE 2026-07-16 -- profiling (prior session) diagnosed `detect_order_block` at 62.6% of backtest runtime (log-log scaling exponent ~2.26 across 500-3000 candles); fixed by scanning newest-to-oldest and returning the first qualifying match, provably identical to the old forward scan's "last match survives" result. Verified bit-identical via a 5,200-case property test against a verbatim reference copy of the old implementation (now a permanent regression test) plus a real-data golden run across 4 flag combinations, which required patching `detect_order_block` in 3 separate module namespaces that each bind it at import (`signal_engine`, `entry_point_engine`, `htf_ltf_confluence`). Window-capping history was rejected as behavior-unsafe; a rolling-window-sum micro-optimization was tried and dropped for failing the bit-identical bar (float add/subtract is not associativity-safe). Measured 2.28-2.39x speedup (1000 candles 4.32s->1.81s, 2000 candles 16.15s->7.09s) -- Milestone-10-style evidence rounds drop from ~40 to ~17 minutes. 653/653. Fix B (incremental zone-mitigation caching for `is_zone_mitigated`, the remaining ~22%) deferred, revisit only if this speedup proves insufficient. See `ENGINEERING_DECISIONS.md` #59. |
| 20 | **ATR stop-distance floor made A/B-testable, then REJECTED on evidence** (`BacktestEngine.run(min_stop_atr_mult=...)` + `run_backtest.py --min-stop-atr`) | #7 (milestone 18b's `RiskManager` floor), #18a (delay-check gate used as the evidence criterion) | ✅ DONE 2026-07-17 -- 20a wired the milestone 18b floor for A/B testing (disabled path proven byte-identical via a fake-`RiskManager` kwargs-leak test), 7 new tests, 669/669. 20b ran the pre-declared evidence round on the standard BTCUSDT 15m anchor: baseline (floor off) 111 trades/+$3,400.62/6/6/walk-forward PASSED but delay-check FAILED (PF retention 0.023, sign flip); `--min-stop-atr 1.5` 60 trades (-46%)/+$1,113.35 (-67%)/3/6/walk-forward FAILED/retention only 0.079 (still 6x below the 0.5 criterion, sign flip remains); 2.0x deliberately not run (CTO early stop, dead-config discipline). **Verdict: floor REJECTED as a delay-robustness fix -- `MIN_STOP_ATR_MULT` stays 0.0 everywhere.** Headline finding: production Legacy itself fails the 1-candle (15-minute) delay gate on this window, previously unknown -- read as "edge lives inside a sub-15-minute execution window," not a seconds-scale latency failure; verified low-latency execution is now an explicit hard prerequisite for `docs/live_trading_checklist.md` gate #4. Full evidence: `docs/ATR_FLOOR_EVALUATION.md` (final). See `ENGINEERING_DECISIONS.md` #60. |
| 22 | **Performance round 2: FVG mitigation-scan quadratic term eliminated** (`signal_engine._select_unmitigated_fvg_zones` + `fvg.find_latest_unmitigated_fvg_zone`) | #19 (milestone 19's deferred Fix B, now corrected and closed) | ✅ DONE 2026-07-17 -- milestone 19's round-1 deferral assumption ("Fix B needs cross-step state inside a stateless `SignalEngine`") is CORRECTED: consumer-semantics analysis found `build_entry_model` only ever uses the highest-index FVG zone matching `bias` (`wanted_type` provably collapses to `bias`), so an M19-style fused reverse scan with early exit sufficed -- no stateful caching needed. `is_zone_mitigated` calls 965,864->11,141 (~87x fewer); FVG chain 22.2%->1.68% of runtime; n=1000 1.81x, n=2000 2.36x measured. Verified bit-identical via the same M19 battery (two 5,200-case property tests + a 4-flag-combo golden run); only one namespace binds the touched code (unlike M19's three). `detect_fair_value_gap` itself untouched -- its other consumers (`entry_point_engine`, `htf_ltf_confluence`) need the full zone list. Combined with M19, evidence rounds are now ~5x faster than pre-M19. 692/692. Full report: `docs/PERFORMANCE_M22.md`. See `ENGINEERING_DECISIONS.md` #61(a). |
| 23 | **Risk-rejection observability** (`BacktestResult.risk_rejections`) | #20 (closes the instrumentation gap decision #60 flagged) | ✅ DONE 2026-07-17 (committed `3e508d8`) -- `BacktestResult.risk_rejections` (`{total_signals, approved, rejected, by_reason}`), purely observational: counts the same `risk_decision` `BacktestEngine.run()` already computes, never changes control flow. Multi-reason rejections increment multiple `by_reason` keys, so `sum(by_reason) >= rejected` by design. Default-populated on every path (incl. the below-`MIN_CANDLES` early return). `run_backtest.py` prints per-period lines only when nonzero, plus one always-printed aggregate line. 690/690 at commit. See `ENGINEERING_DECISIONS.md` #61(b). |
| 24 | **Cross-year evidence round on Legacy's own delay fragility** (same standard BTC 2025 anchor every prior cross-year round uses, `--walk-forward --delay-check`) | #18a (delay-check gate), #20 (the 2026 finding being tested), #23 (rejection instrumentation used for the first time in an evidence round) | ✅ DONE 2026-07-17 -- applied the house cross-year discipline to the platform's own headline finding rather than exempting it. 2025: baseline PF 4.593 -> delayed PF 0.068, retention 0.015 (worse than 2026's 0.023), sign flip, delay gate FAILED; walk-forward FAILED on the known, previously-documented BTC-2025 degradation (reproduced to the cent, correctly attributed as not a new finding). **VERDICT: STRUCTURAL** -- fails both tested years, slightly worse in 2025 despite a materially different regime (65 vs 111 trades); regime-dependent hypothesis falsified. Gate #4's requirement note upgrades to "structural property, confirmed across two independent years (2025, 2026) on BTCUSDT" -- requirement substance unchanged. Second finding: 2025's low trade count is not signal drought -- 869 raw signals, 804 (92.5%) rejected, 100% of fired reasons `trades_today 2 reached MAX_TRADES_PER_DAY 2`; recorded as an insight (any cap change is an operator-gated risk-limit decision), not acted on. Operational: ~11 min wall time vs ~3h05m pre-milestone-22, validating the M19+M22 performance work in production use. Full report: `docs/LEGACY_DELAY_ROBUSTNESS.md`. See `ENGINEERING_DECISIONS.md` #62. |
| 25 | **Hypothesis Agent + first pre-registered experiment (H4 position-sizing parity)** (operating model formally expanded to a research-company loop -- Research/Hypothesis/Experiment/Evaluation/Ranking/Promotion/Shadow/Regime/Risk/Monitoring/QA/Performance/Documentation/CTO) | #20, #23, #24 (the evidence base H4 audits), #7 (Milestone 7's volatility-scaled sizing, live since 2026-07-15 but never threaded through `BacktestEngine`) | ✅ DONE 2026-07-18 -- `docs/HYPOTHESES_ROUND_1.md`: 5 pre-registered hypotheses (mechanism + citation + keep-rule declared before any run), 7 rejected directions logged. H4 (ranked #1, cost 1) ran first: closed the verified gap where every backtest number in this platform's evidence base was computed at a uniform 1.0x sizing scalar while paper trading has run a 0.5x high-volatility scalar since Milestone 7. New opt-in `--vol-scaled-sizing` flag, 3-year BTCUSDT comparison (`docs/H4_SIZING_PARITY_RESULTS.md`). **VERDICT: MIXED** -- the pre-registered keep-rule's 3 branches did not resolve to a single answer across 2024/2025/2026 (2024 matched "confirmed improvement," 2025 matched "nothing moves," 2026 alone triggered "materially degrades"); applied literally, not softened toward a cleaner story -- the first real test of this project's pre-registration discipline against a keep-rule that didn't cleanly resolve. Operator-relevant finding disclosed, no recommendation made (same operator-gated boundary as `MAX_TRADES_PER_DAY`, decision #62): the live 0.5x scalar costs real PnL in at least one tested year (2026, -14.4%) without a proportionate drawdown benefit. Footnote check: `docs/LEGACY_DELAY_ROBUSTNESS.md`'s STRUCTURAL verdict confirmed unaffected (all deltas <=0.002, noise). 701/701. See `ENGINEERING_DECISIONS.md` #63. |
| 26 | **H1: quality-ranked signal selection within the fixed `MAX_TRADES_PER_DAY` cap** (`docs/HYPOTHESES_ROUND_1.md` §2, ranked #2 behind H4) | #25 (Hypothesis Round 1's pre-registered experiment/keep-rule), #62 (the cap-rejection finding H1 tests without touching the cap itself) | ✅ DONE 2026-07-18 -- new research-only harness `scripts/research_signal_selection.py` (+ 15 tests) re-batches each simulated day's full signal supply and ranks by a disclosed-not-tuned score (`rr`, `rr_confluence`), taking only the top-`MAX_TRADES_PER_DAY` by score; `RiskManager.evaluate()`'s live sequential-approval logic untouched. Baseline reproduction confirmed exactly on both anchors before trusting the comparison. **VERDICT: REJECT for both variants** -- `rr` wins Profit Factor in both anchors (+6.5% 2026, +138.3% 2025) but LOSES Net Profit in both (-24.1% 2026, -4.1% 2025), disqualified by the rule's own "wins on PF but not Net Profit, is REJECT" clause; `rr_confluence` loses both metrics in both anchors outright. Unlike Milestone 25's H4 (genuinely MIXED), H1's keep-rule resolves cleanly. **Mechanism**: both ranked variants realize far fewer trades under the same fixed cap (2026: 82/77 vs. 111; 2025: 43/46 vs. 65) -- day-clustering causes the second-ranked candidate's window to overlap the still-open first trade and be skipped, so quality-ranking trades throughput for selectivity, and the throughput loss costs more Net Profit than the selectivity gain recovers. Confirms Legacy's edge scales more with trade frequency than per-trade selection quality on this platform, and confirms the cap-rejection opportunity (decision #62) requires raising the cap itself (still operator-gated) rather than smarter selection within it. Disclosed, un-root-caused PF-methodology discrepancy vs. published baseline PF flagged as a standing follow-up (does not affect the verdict). 716/716. See `ENGINEERING_DECISIONS.md` #64, full report `docs/H1_SIGNAL_SELECTION_RESULTS.md`. |
| 27 | **H3: regime-conditional delay survival of the `structure_tp` family** (`docs/HYPOTHESES_ROUND_1.md` §3, ranked #3 behind H1) | #26 (Hypothesis Round 1's remaining pre-registered experiments), #18a (`--delay-check`), #12 (`--tag-regimes`) -- H3 joins two already-independently-validated flags, never run together before | ✅ DONE 2026-07-18 -- new analysis-only harness `scripts/research_regime_delay.py` (+ 23 tests) joins `--tag-regimes` and `--delay-check` output per regime bucket (`entry_delay_candles=0` vs `=1`), computing PF retention/sign-flip per bucket instead of only in aggregate; `RiskManager.evaluate()`'s live sequential-approval logic untouched. Unlike H1's 2-anchor requirement, H3's own keep-rule requires 3 tested years -- ran BTCUSDT 15m 2024/2025/2026 (10/9/8 regime buckets respectively, fewer buckets in 2024/2025 purely a regime-occurrence artifact, not a tool bug). **VERDICT: REJECT** -- across all 27 bucket-year cells, not one clears the pre-registered bar (n>=20 delayed-side trades, PF retention >=0.5, no sign flip) in even a single year, let alone the required 2-of-3; only one cell (2026 `weak_trend/normal_volatility`) reaches n>=20 at all, and it still fails on retention (0.170) with a sign flip. **Evidence-scarcity caveat, the substantive finding**: 26 of 27 bucket-year cells never reach the n>=20 delayed-side floor needed to test the rule meaningfully -- mirrors this platform's already-documented regime-bucket scarcity (`docs/REGIME_PERFORMANCE_ANALYSIS.md`, 8 of 9 buckets evidence-starved for Legacy's own signal stream) on a different exit-logic family; this REJECT is "insufficient data" as much as "buckets failed." Secondary footnote: aggregate ("all") PF retention (0.080/0.051/0.067 across 2026/2025/2024) runs ~2-3x higher than Legacy's own default-exit aggregate retention at the same anchors but remains catastrophically below 0.5 with a sign flip in all three years -- a third data point that this platform's execution-delay fragility is structural across strategy variants, not one exit family. 739/739. See `ENGINEERING_DECISIONS.md` #65, full report `docs/H3_REGIME_DELAY_RESULTS.md`. |
| 28 | **H2: passive limit-at-level entry as a delay-robust alternative to immediate market entry** (`docs/HYPOTHESES_ROUND_1.md` §4, ranked #4 -- highest implementation cost of the five) | #27 (Hypothesis Round 1's remaining pre-registered experiments), #20 (the already-REJECTED ATR floor, the mechanism H2 must not be confused with) -- H2 is the first of the five hypotheses requiring real new fill-timing logic, not a research-aggregation layer atop existing flags | ✅ DONE 2026-07-18 -- new opt-in CLI flags `--limit-at-level` / `--limit-timeout-candles N` wired into `BacktestEngine.run()`/`entry_model.py`: rest a limit order at the structural OB/FVG/sweep zone edge instead of an immediate market fill, filled only on a subsequent candle's retest within a bounded timeout, default off and byte-identical when unset (confirmed by 2 dedicated regression tests). `RiskManager.evaluate()` and `scripts/run_paper.py` untouched. Ran BTCUSDT 15m 2024/2025/2026 (`--candles 3000 --periods 6 --limit-at-level --limit-timeout-candles 4 --walk-forward --delay-check`) vs. the already-recorded Legacy market-order baseline. **VERDICT: REJECT** -- applying H2's own pre-registered two-part keep-rule literally (both parts must hold): **Check 2 (delay-robustness) PASSES cleanly, 3/3 years** (PF retention 1.003/0.883/0.935, no sign flip), genuinely solving the delay fragility both Legacy's default exit and `structure_tp` failed catastrophically; **Check 1 (cost-of-passivity) FAILS, 0/3 years**, inverting sign in every year (2026 +$3,400.62 -> -$744.13; 2025 +$1,714.56 -> -$727.22; 2024 +$1,807.75 -> -$895.05). Check 1 alone disqualifies. **Precision note, the substantive finding**: NOT the same failure shape as the ATR floor's own analogy ("fixed delay by mostly not trading") -- trade count drops only modestly (13-21% fewer than Legacy) while profitable-periods collapses almost entirely (1/6, 0/6, 2/6 vs. Legacy's 6/6) and walk-forward fails everywhere; the retest-based passive-fill mechanism itself systematically selects for structurally worse trade outcomes, independent of delay -- a genuinely novel, third distinct failure mode among this platform's tested delay-robustness fixes. Promotion path NONE (REJECT; even a KEEP would not have substituted for Phase-1 gate #4's measured-latency requirement, per H2's own pre-registered text). 748/748. See `ENGINEERING_DECISIONS.md` #66, full report `docs/H2_LIMIT_ENTRY_RESULTS.md`. |
| 29 | **H5: session-conditional position sizing -- pre-registered in full, then REJECTED at its own Step 0 grounding gate** (`docs/HYPOTHESES_ROUND_1.md` §6, ranked #5 -- the last unresolved hypothesis, previously only a ranking-table row per `CLAUDE.md`'s caution against fabricating its spec) | #28 (Hypothesis Round 1's last remaining hypothesis), #64 (Milestone 26's H1 finding, new supporting grounding published a day after H5's original ranking) | ✅ DONE 2026-07-19 -- wrote H5's full pre-registration (mechanism, grounding, pre-registered experiment, keep-rule, cost, promotion path) built entirely from evidence already on record, then ran the pre-registration's own Step 0 precondition check in the same round: does the session profit-factor gradient `docs/ROBUSTNESS_REPORT.md` Test 6 found (Asian PF 4.65 > London PF 2.41, measured on BTCUSDT 5m against the `structure_tp` candidate) replicate on the candidate/timeframe H5 would size (BTCUSDT 15m, Legacy default exit)? New analysis-only harness `scripts/research_h5_step0_session_grounding.py` (+ 8 tests) buckets already-produced Legacy-baseline trades by UTC entry hour into Test 6's three session windows -- no new `BacktestEngine` parameter, no new CLI flag; `RiskManager.evaluate()` and `scripts/run_paper.py` untouched. Ran BTCUSDT 15m 2024/2025/2026 (plain Legacy default, trade counts 111/65/73 confirmed exact matches to the already-published baseline). **VERDICT: REJECT at Step 0** -- the gradient direction (Asian PF > London PF) holds in only 1 of 3 years (2024) against the required >=2/3; in 2026 and 2025, including the platform's single most-evidenced anchor (2026, 111 trades), London's PF exceeds Asian's, the OPPOSITE of Test 6's finding. Per H5's own pre-registered text this ends the hypothesis outright -- `session_risk_scalar`/`--session-scaled-sizing` were never implemented, Step 1 never ran. **Substantive finding**: a session-quality gradient measured on one candidate/timeframe does not transfer to a different candidate/timeframe even on the same asset and session-window convention -- a standalone, disclosed caveat for future hypotheses conditioning on Test 6's numbers. **Hypothesis Round 1 is now fully resolved**: H1 REJECT, H2 REJECT, H3 REJECT, H4 MIXED, H5 REJECT at Step 0 -- zero KEEPs. 756/756. See `ENGINEERING_DECISIONS.md` #67, full report `docs/H5_SESSION_GROUNDING_RESULTS.md`. |
| 30 | **Hypothesis Round 2 opened; H6 root-causes Jade's signal scarcity -- REJECTED** (`docs/HYPOTHESES_ROUND_2.md` §2, ranked #1 of 3 candidate directions) | #29 (Round 1 fully resolved, freeing capacity for a new round), #36 (the disclosed, unconfirmed same-bar-retracement hypothesis this round tests directly) | ✅ DONE 2026-07-19 -- opened Round 2 scoped to the adaptive platform's actual objective (a working second strategy) rather than a sixth Legacy-delay-fragility patch. **Self-correction disclosed, not hidden**: a prior-session ROADMAP.md claim that Jade "has never been benchmarked end-to-end" was wrong (decision #36 already ran that exact comparison and it lost badly, 6 vs 47 trades) -- caught before Round 2 duplicated it, corrected in the same round. H6 instead targets decision #36's own named next step: does the same-bar-retracement requirement on 3 of Jade's 5 entry models (FVG/Order Block/Breaker Block) dominantly explain the scarcity? New analysis-only harness `scripts/research_h6_jade_scarcity_diagnosis.py` (+ 17 tests) walks every candle calling Jade's own entry-model evaluators directly and unmodified -- no trade ever executed, `RiskManager.evaluate()`/`scripts/run_paper.py` untouched. Ran BTCUSDT 15m 2024/2025/2026, 53,910 total steps. **VERDICT: REJECTED** -- aggregate `no_matching_zone` (12,481) outweighs `zone_exists_not_retraced` (2,710) by 4.61x, clearing the pre-registered threshold; Order Block (2.42x) and Breaker Block (17.07x) both independently clear it too, not an aggregation artifact. **Substantive finding**: the aggregate masks per-model heterogeneity -- FVG is essentially unconstrained (candidate_found 97.6% of zone-checked steps) because Jade never invalidates a zone on retest and searches the full candle history each step, while Order Block/Breaker Block are genuinely zone-scarce. **Larger, disclosed-not-chased finding**: 8,312 `signal_would_generate` steps vastly exceed decision #36's 6 actual trades, but this is explicitly NOT a missed-opportunity signal -- this harness doesn't track open-trade state, Jade's own no-invalidation design overcounts distinct opportunities, and `RiskManager.evaluate()` gating was out of scope; flagged as a well-grounded H7 candidate for a future round. 773/773. See `ENGINEERING_DECISIONS.md` #68, full report `docs/H6_JADE_SCARCITY_RESULTS.md`. |
| 31 | **Strategic research review (H1-H6) + H7: RiskManager/pipeline-gating attribution for Jade -- Jade's real bottleneck is RR geometry, not the shared cap** (`docs/RESEARCH_STRATEGY_REVIEW.md`, `docs/HYPOTHESES_ROUND_2.md` §3, ranked #1 of 6 directions) | #30 (H6's own disclosed, unmeasured 8,312-vs-6 gap this hypothesis attributes) | ✅ DONE 2026-07-19 -- preceded by a strategic review across all six prior hypotheses (H1-H6): 5 cross-cutting patterns extracted (throughput beats selectivity; regime/session hypotheses are data-starved by construction; motivating evidence must be re-verified on the target candidate; a narrowly-scoped hypothesis can miss the real driver in an adjacent stage; every REJECT/MIXED has been mechanistically explained), 6 future directions ranked by ROI, 3 paths explicitly eliminated (a fifth Legacy delay-fragility fix; further data-starved regime/session hypotheses; a `MAX_TRADES_PER_DAY` cap-relaxation study even in disclosed backtest-only form). H7 ran the #1-ranked direction: new thin wrapper `scripts/research_h7_jade_risk_attribution.py` (+ 7 tests) reuses `run_backtest.py`'s own already-existing `run_backtest(..., use_jade_engine=True)`/`aggregate_risk_rejections()` verbatim -- zero new production code, `BacktestResult.risk_rejections` (Milestone 23) simply predates decision #36's original A/B test by 5 days. Ran BTCUSDT 15m 2024/2025/2026: 8,021 signals reached `RiskManager.evaluate()` (96.5% of H6's own step count -- open-trade/zone-persistence branch cleanly REJECTED), 99.3% rejected, only 57 approved. **Keep-rule design flaw caught and disclosed, not hidden**: the literal rule mechanically resolves RISK_GATING_DOMINANT (`MAX_TRADES_PER_DAY` is the single most frequent EXACT reason string), but RR-below-minimum reasons embed their numeric value per string and fragment across thousands of near-unique keys while the cap reason never varies -- re-pooled by category, RR-below-minimum is 92.3% of all rejection-reason instances vs. the cap's 7.3%. **Substantive finding**: unlike Legacy (100% cap-driven per decision #62), Jade's real bottleneck is a reward:risk GEOMETRY problem -- its stop/target construction was never swept/tuned the way Legacy's `_RR`/`_STOP_BUFFER` were. Two independently-built strategies, two different bottlenecks -- a disclosed, platform-level finding for the Strategy Selection Engine question, not the "shared cap" unification originally sought. 780/780. See `ENGINEERING_DECISIONS.md` #69, full report `docs/H7_JADE_RISK_ATTRIBUTION_RESULTS.md`. |
| 32 | **H8: validating Jade's RR-geometry bottleneck -- structural on stop_model, and a real bug found in Milestone 30's own harness** (`docs/HYPOTHESES_ROUND_2.md` §4) | #31 (H7's RR-geometry finding this hypothesis validates) | ✅ DONE 2026-07-19 -- operator directive: "proceed with H8... focus on validating the newly identified reward-risk geometry bottleneck." New analysis-only harness `scripts/research_h8_jade_rr_sensitivity.py` (+ 9 tests) sweeps every already-existing `stop_model` value (FVG: aggressive/moderate/conservative; Breaker: aggressive/conservative) and every already-computed exit-target rank against production's actual default combination -- zero new production code, `find_entry_point`'s own selection called once per step (unaffected by stop_model choice, verified by code inspection). Ran BTCUSDT 15m 2024/2025/2026, 8,340 baseline candidates. **Result**: baseline qualify rate (RR>=2.0) 0.95% -- confirms H7 at the candidate level. Isolating stop_model alone (target held at TP1): 0.92-0.95%, **no meaningful difference** (94.0% of selected steps have no `stop_model` parameter at all). Isolating target-index alone (stop held at aggressive): TP1 0.95% -> TP6 26.35%, monotonic -- **all the movement is target-index, not stop_model**. Literal keep-rule verdict: PARAMETER_SENSITIVE -- but NOT endorsed: RR is a distance ratio, not a probability, and a farther target mechanically inflates RR with no regard for whether price is more likely to reach it, plausibly trading RR for win rate in a way this hypothesis cannot see. **Honest reading**: on the question H7 actually raised (does an existing stop_model choice help), the answer is STRUCTURAL -- no. **A real bug found in Milestone 30's own harness, disclosed and corrected, not hidden**: H8's pooled selection distribution (`premium_discount` 44.5%, `liquidity_raid` 33.8%, `fair_value_gap` 0.2%) directly contradicts Milestone 30's reported distribution (`fair_value_gap` 76.4%, `liquidity_raid` 0%) -- root cause, H6's own harness reimplemented `find_entry_point`'s selection using its own dict iteration order instead of calling the real function directly, so ties among the 3 models sharing confidence_score=4 broke differently than production's real tie order. **Milestone 30's own PRIMARY VERDICT is unaffected** (computed per-model, independent of selection order); only its narrative "FVG dominates" finding is superseded. Correction notice added to the top of `docs/H6_JADE_SCARCITY_RESULTS.md` itself, not a silent rewrite. 789/789. See `ENGINEERING_DECISIONS.md` #70, full report `docs/H8_JADE_RR_SENSITIVITY_RESULTS.md`. |
| 33 | **Validation Phase begins: paper-trading pipeline verification -- critical exit-check bug found, Gate #4 latency infrastructure confirmed absent, timeframe-config ambiguity surfaced** (`docs/PAPER_TRADING_VALIDATION_REPORT.md`) | #(phase transition review, `docs/PHASE_TRANSITION_REVIEW.md`) | ✅ DONE 2026-07-19 -- per the phase transition review's own recommendation, verifies the paper-trading pipeline end-to-end instead of opening a ninth hypothesis. 3 new additive, read-only tools: `scripts/measure_pipeline_latency.py`, `scripts/verify_signal_to_fill.py`, and the first-ever automated test for `scripts/run_paper.py`'s own orchestration logic (`backend/tests/test_run_paper_exit_check.py`). `RiskManager.evaluate()`/`scripts/run_paper.py` read and run, never modified. **Finding #1 (CRITICAL)**: `_check_and_close_open_positions()` crashes (`TypeError`, naive-vs-aware datetime subtraction -- SQLite silently drops `Trade.opened_at`'s declared timezone-awareness on round-trip) the first time a real trade's stop-loss/take-profit is actually reached on a later pass -- the crash happens BEFORE `close_trade()` runs, so the position never closes, and `run_once()`'s own concurrency guard then skips ALL future signal generation while any position stays open. **Would permanently halt the paper trader the first time it triggers in real production.** Reproduced twice independently against a throwaway temp DB; added as a permanent `xfail` regression test; not fixed (gated file, requires operator sign-off). **Finding #2 (CRITICAL, unresolved)**: cannot confirm which timeframe production has actually used -- `DEFAULT_TIMEFRAME` defaults to `5m` (confirmed live too) while nearly all delay-fragility safety research (Gate #4's evidentiary basis) was conducted at `15m`; the real `.env` is gitignored and unavailable. **Finding #3**: Gate #4's "measured signal-to-fill latency" cannot be produced by the current architecture at all -- `PaperBroker` makes no real exchange API round-trip whatsoever (verified by source inspection), an infrastructure gap not a measurement gap. **Finding #4**: paper-trading process not observably running (~29-30h stale). **Finding #5**: `strategy_logs`/`risk_events` are real DB tables nothing writes to. **Finding #6**: signal->risk->execute->persist math verified correct via real hand-checked reproduction (fill price/size/fee/slippage all matched exactly); concurrency-guard verification inconclusive, blocked by Finding #1. **Latency measured** (scope-limited per Finding #3): OKX fetch round-trip median 107.3ms/p95 195.8ms; full `run_once()` pipeline median 235.8ms/p95 745.2ms, all 10 live passes exit_code=0. Full suite 789 passed, 1 xfailed, 0 unexpected failures. No orders placed, no production code modified. See `ENGINEERING_DECISIONS.md` #71, full report `docs/PAPER_TRADING_VALIDATION_REPORT.md`. |
| 34 | **Finding #1 fixed (operator-approved): exit-check no longer halts the paper trader** | #33 | ✅ DONE 2026-07-19 -- `_check_and_close_open_positions()` normalizes `opened_at` to UTC-aware before the `holding_time_seconds` subtraction, per explicit operator sign-off. Bookkeeping-only; `PaperBroker.check_exit()`/`SignalEngine.generate_signal()`/`RiskManager.evaluate()` untouched. Original `xfail` test replaced with two independently-passing tests (forced take-profit close, forced stop-loss close). Full suite 791/791, 0 xfailed. Findings #2-#5 remain open. See `ENGINEERING_DECISIONS.md` #72, `docs/PAPER_TRADING_VALIDATION_REPORT.md` (updated in place with a correction banner). |
| 35 | **CTO platform evaluation: CI pipeline stood up, dormant exchange-abstraction layer surfaced, 11 improvements ranked** (`docs/CTO_PLATFORM_EVALUATION.md`) | #34 | ✅ DONE 2026-07-19 -- full-platform survey (strategy layer, adaptive-platform infrastructure, validation findings, plus previously-uncovered ground: frontend, API layer, CI/dev-infra, exchange/execution abstraction layer). **Two things newly surfaced**: no CI pipeline existed (791 tests, entirely manually run); a dormant, 100%-`NotImplementedError` exchange-abstraction layer (`BaseExchange`/`OkxClient`/`OrangexClient`/`LiveBroker`, zero references, zero tests) that already defines the exact interface Finding #3's missing order-placement infrastructure needs -- building it means filling in an existing contract, not designing a new one; it also duplicates `CandleFetcher`'s already-working job through a separate class hierarchy. 11 improvements ranked by Impact/Cost/Risk/Long-term-Value across Immediate/Short-term/Long-term. **Top-ranked, raised for approval, not started**: real signal-to-fill latency measurement infrastructure (fill in `OkxClient`/`LiveBroker` against OKX's demo-trading API, a new standalone harness only, never `run_paper.py`'s live path) -- requires real credentials and an architecture decision. **Done autonomously** (safe, zero production-behavior touch): CI pipeline (`.github/workflows/backend-tests.yml`); a permanent warning comment on `Settings.DEFAULT_TIMEFRAME` cross-referencing Finding #2 (comment only, value unchanged). Full suite 791/791 unchanged before/after. `RiskManager.evaluate()`/`scripts/run_paper.py` untouched. H9 (a genuinely constructive Jade hypothesis) remains available but not auto-started, per the standing no-new-hypotheses-without-a-clear-gap instruction. See `ENGINEERING_DECISIONS.md` #73, full report `docs/CTO_PLATFORM_EVALUATION.md`. |
| 36 | **Five-priority CTO round: Exchange Layer roadmap, research-platform ranking, OSS comparison, infra touch-up, CI failure investigated** (`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`, `docs/RESEARCH_PLATFORM_ROI_RANKING.md`, `docs/OSS_AGENT_ARCHITECTURE_COMPARISON.md`, `docs/EXPERIMENT_INDEX.md`, `docs/HYPOTHESIS_BACKLOG.md`) | #35 | ✅ DONE 2026-07-19 -- **P1**: production-ready Exchange Layer roadmap (planning only, not implemented), reusing `BaseExchange`/`OkxClient`/`OrangexClient`/`LiveBroker` verbatim. Found `LiveBroker`'s stub methods don't match what `ExecutionEngine`/`OrderManager` call -- fix is an adapter wrapping `BaseExchange`, not a redesign; its own docstring already implied this. 9 areas covered across a 4-phase, each-its-own-approval rollout. **P2**: research-platform-specific top-10 ROI ranking (distinct from milestone 35's whole-platform one). Implemented the 2 safe Immediate items: `docs/EXPERIMENT_INDEX.md` (every hypothesis H1-H8 indexed) and `docs/HYPOTHESIS_BACKLOG.md` (every available candidate indexed) -- both directly serve "never duplicate completed work" at the tooling level. `scripts/shadow_status.py` checked first, already covers shadow-monitoring, not re-proposed. **P3**: OSS comparison grounded in a live 2026 web search. Multi-agent-team frameworks (MetaGPT/ChatDev/CrewAI) duplicate the existing `.claude/` harness -- not adopted. LangGraph-style durable state is arguably outperformed by this project's own append-only docs for its specific cross-session audit-trail need -- not adopted. One genuinely missing capability found: debate-based verification for keep-rule results (H7/H8's own findings already demonstrate its value manually) -- recommended as a process convention, not a new dependency. **P4**: `CLAUDE.md` milestone count (28->35) and doc pointers updated (narrow edit); memory updated (new `gated-file-discipline.md`); agent definitions reviewed, no changes warranted. **CI found failing, investigated not hidden**: milestone 35's new workflow fails at "Run test suite," exit code 1 -- dependency-drift hypothesis tested directly and ruled out (a fresh venv matching CI's exact `pytest==8.4.2` still passes 791/791 locally); failure is Linux/GitHub-Actions-specific, needs authenticated access (`gh`/PAT) to diagnose further. **P5**: no hypothesis fabricated, Legacy remains the only production engine. **Flagged, not acted on**: relaunching the paper trader -- memory documents this as expected/standing-authorized maintenance and milestone 34's fix removes the one blocker, but not done unilaterally given this session's consistent sign-off requirement for anything touching `run_paper.py`'s running state. `RiskManager.evaluate()`/`scripts/run_paper.py` untouched. See `ENGINEERING_DECISIONS.md` #74. |
| 37 | **Paper trader restarted and lifecycle-verified (operator-approved); Exchange Layer Phase 0 implemented read-only-and-mocked; a genuinely missing health-check tool built; CI diagnosis gap closed structurally** (`scripts/verify_signal_to_fill.py`, `backend/app/exchange/okx_client.py`, `scripts/measure_exchange_readonly_latency.py`, `scripts/paper_trader_health_check.py`, `.github/workflows/backend-tests.yml`) | #75 | ✅ DONE 2026-07-19 -- **Restart + lifecycle**: relaunched `scripts/run_paper.py` (migration head applied first), clean startup, no crashes. Re-ran `scripts/verify_signal_to_fill.py`, found and fixed a real bug in the tool itself (hardcoded synthetic take-profit price had drifted below real BTC market price, spuriously failing its own concurrency-guard check via a genuine market TP hit) -- 21/21 checks pass after the fix, confirming signal generation/order flow/SL-TP/no-duplicate-positions all work correctly. Graceful shutdown/restart recovery confirmed by reading existing `KeyboardInterrupt`/`PersistentCircuitBreaker` handling (not modified). **CI**: three independent local reproductions (dev venv; a fresh venv matching today's exact `requirements.txt` resolution, surfacing a real `pytest-asyncio` major-version drift 0.26.0 vs. dev's 1.4.0, tested directly and still passing; a genuinely fresh `git clone` into a new venv) all pass 791/791 on Windows -- root cause still unreachable without authenticated GitHub access. Structural fix instead of a guess-fix: workflow now tees pytest's real output into `$GITHUB_STEP_SUMMARY`, visible via the public unauthenticated check-runs API for every future run. **Exchange Layer Phase 0**: `OkxClient.fetch_ohlcv`/`get_balance`/`get_open_positions` implemented with real OKX v5 HMAC-SHA256 auth (verified against OKX's live docs, correcting a header-name inaccuracy in the roadmap doc). `place_order`/`cancel_order` remain unimplemented (Phase 1, separate gate). 17 new tests, all mocked, zero real network calls, no real credentials used. Standalone measurement harness built and confirmed to correctly refuse without real credentials. **Monitoring**: `scripts/paper_trader_health_check.py` (read-only liveness check -- circuit breaker/freshness/open-position anomaly), 14 new tests, confirmed HEALTHY against the live DB. Detection only, no auto-restart. `RiskManager.evaluate()`/`scripts/run_paper.py` untouched; no real credentials used; no live trading enabled. See `ENGINEERING_DECISIONS.md` #75. |
| 38 | **CI-visibility fix corrected (Milestone 37's own fix didn't actually work); health-check `--watch` mode deployed; operational runbook and OKX Demo resumption checklist written** (`.github/workflows/backend-tests.yml`, `scripts/paper_trader_health_check.py`, `docs/PAPER_TRADER_RUNBOOK.md`, `docs/OKX_DEMO_RESUMPTION_CHECKLIST.md`) | #76 | ✅ DONE 2026-07-19 -- operator: OKX Demo credentials still unavailable, do not block on exchange connectivity, proceed with highest-ROI credential-free work (paper-trading reliability -> monitoring/failure-detection -> decision logs/recovery checkpoints -> unresolved test/CI/doc issues -> OKX resumption checklist). **Priority 4 surfaced first, out of order**: checked whether milestone 37's CI fix (tee pytest output into `$GITHUB_STEP_SUMMARY`) had actually worked once GitHub's rate limit reset -- it had not, `output.summary` was still `null`. Root cause found directly: `$GITHUB_STEP_SUMMARY` populates the run's web-UI Summary tab (React-rendered, confirmed via WebFetch returning a client-side loading error), a different surface from a check run's `output` field, which the public unauthenticated check-runs API actually exposes. Real fix: publishes a separate purpose-built check run (`pytest-failure-detail`, `actions/github-script@v7`, `github.rest.checks.create`) with the real pytest tail, using the workflow's own auto-provisioned `GITHUB_TOKEN` (not an operator secret; `permissions: checks: write` added). Recorded explicitly as a fix that shipped without independently verifying the exact API surface it claimed to populate. **P1/P2**: `scripts/paper_trader_health_check.py` gains `--watch` mode -- transition-only + heartbeat alert logging, DB-open failure treated as UNHEALTHY not a crash, smoke-tested then deployed as a real background process alongside the paper trader. 5 new tests. **P3**: `docs/PAPER_TRADER_RUNBOOK.md` -- symptom->diagnosis->action table plus an explicit "does NOT authorize touching gated files" section. **P5**: `docs/OKX_DEMO_RESUMPTION_CHECKLIST.md` -- what's done, exact resume steps, what Phase 0 does NOT unlock. `OrangexClient` re-confirmed untouched (no production references, no business need). `RiskManager.evaluate()`/`scripts/run_paper.py` untouched; no real credentials used; no live trading enabled; no destructive actions (DB accessed via `mode=ro` throughout). Full suite 827/827 (822+5). See `ENGINEERING_DECISIONS.md` #76. |
| 39 | **The real root cause of the CI failure, found and fixed -- a genuine Windows-vs-Linux `pathlib` bug in five separate `scripts/` entry points, not a dependency mystery after all** (`scripts/_cli_path_utils.py`) | #77 | ✅ DONE 2026-07-20 -- verified milestone 38's own CI fix first rather than assuming it worked: once GitHub's rate limit reset, checked commit `ad2aaa9`'s check-runs directly -- this time the corrected mechanism worked, the real pytest traceback was readable for the first time across four milestones. **Real failure**: `tests/test_cto_report.py`'s `windows_backslash` regression test -- "2 failed, 825 passed" (827 total, matching this project's own local count exactly). Reproduced locally in isolation first (both variants passed on Windows) before touching code. **Root cause, read directly**: `scripts/cto_report.py` line 625, `Path(args.db_path)` -- `pathlib.Path(raw)` only treats `\` as a separator on Windows; on the real Linux CI runner a backslash is a literal filename character, silently resolving to the WRONG, nonexistent file and degrading the evidence section. Fully explains the three-milestone CI mystery: every prior local reproduction ran on Windows, where this bug is structurally invisible -- dependency drift was never the cause. **Systemic**: grepped `scripts/` before fixing, found 5 call sites sharing the pattern (`cto_report.py`, `selector_dry_run.py`, `shadow_status.py`, `migrate_paper_db.py`, `paper_trader_health_check.py`); CI's own failure summary confirmed a second test failing on the identical bug (`test_selector_dry_run.py`). Fixed once in new `scripts/_cli_path_utils.py::normalize_db_path_arg`, all 5 scripts updated to import it instead of duplicating logic. New `backend/tests/test_cli_path_utils.py` (5 tests). All 5 scripts smoke-tested against the real live DB. `RiskManager.evaluate()`/`scripts/run_paper.py` untouched; no real credentials used; no live trading; no destructive actions; no architecture redesign. Full suite 832/832 (827+5). See `ENGINEERING_DECISIONS.md` #77. |

**This session's scope**: all 9 milestones on this roadmap (1 through 8,
plus 8.1) are now built and committed. Milestone 8 (new strategy modules)
shipped as four disclosed-not-tuned, detection-only modules living in a
separate quarantine registry (`EXPERIMENTAL_STRATEGIES`) -- reachable only
via `scripts/run_backtest.py --strategy NAME` for backtest evaluation, not
consulted by either configured selector (`DefaultToLegacySelector`,
`ConfigurableFallbackSelector`) and therefore invisible to paper/live
trading. Promotion of any of the four into `AVAILABLE_STRATEGIES` requires
real backtest/walk-forward evidence first -- the natural next step, not
yet performed (see `ROADMAP.md`). **Update 2026-07-16**: that evidence
now exists (row 10 above) -- all four failed, none promoted. Row 11
(shadow-mode observability) is a separate, additive track that starts
accumulating the regime-tagged data this roadmap's section 4.3 needs,
independent of any individual experimental strategy's fate.

**Commit discipline for every milestone**: full backend test suite run
and passing, paper trader health verified (still running, still
untouched), design decision recorded in `ENGINEERING_DECISIONS.md`,
commit message describing what changed and why, push to `origin/master`
-- the same discipline every prior commit in this session has already
followed, continued unchanged for this new phase of work.

**Operating model, updated 2026-07-16 (operator directive)**: with rows
1-16 above complete, this roadmap's role changes from "queue of
milestones to finish" to "evidence base a CTO-driven, continuously
operating process consults." Specialist-agent roles (CTO/Research/
Strategy/Backtest/Risk/Monitoring/QA/Performance) now select the next
milestone by bottleneck analysis against this document and the live
evidence tables, rather than asking what to build next; the CTO stops
only for architectural decisions, credentials, production deployment, or
destructive actions. Promotion gates (row-16-and-earlier discipline:
significant edge, positive expectancy, lower drawdown, sufficient
sample, multi-market, regime validation) are unchanged and never
bypassed -- Legacy remains the only production engine under this model,
exactly as before it. A daily morning CTO report (`scripts/cto_report.py`,
row 17) is now standing practice. See `ENGINEERING_DECISIONS.md` #57.
