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

| Extension | Why | Priority |
|---|---|---|
| **Per-strategy disable hook** | Section 6/Continuous Learning needs a way to tell the Risk Engine "strategy X is disabled, reject its signals" -- currently `RiskManager` has no concept of a signal's originating strategy at all. Minimal addition: `TradeSignal` (or the Strategy interface) carries a `strategy_name`, `RiskManager.evaluate()` gains an `is_strategy_disabled(name) -> bool` check. | High -- required before section 6's auto-disable is meaningful |
| **Correlated exposure check** | Only matters once MULTIPLE strategies can be concurrently active (not true today -- only `legacy` is ever selected per section 4.2). Prevents two strategies both opening a same-direction position on the same symbol simultaneously, double-risking the account on one correlated bet. | Low today, rises once section 4's selector becomes regime-conditioned across multiple live strategies |
| **Volatility-scaled position sizing** | `calculate_position_size` currently sizes purely off the signal's own entry/stop distance -- a `MarketRegime.volatility` input could scale the risk-percent DOWN in `high_volatility` regimes as an account-level safety measure, independent of any one strategy's own stop placement. | Medium -- genuinely useful, not blocking on anything else, can be built once the Regime Detector (section 2) exists |

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
| 1 | **Strategy Interface** (`Protocol` + Legacy/Jade adapters + registry) | none | ✅ DONE (2026-07-15), 7/7 tests passing, not yet committed |
| 2 | **Performance Database schema extensions** (section 6.2 columns + section 6.3 table, Alembic migration) | none (additive schema, same pattern as decision #40) | Next |
| 3 | **Market Regime Detector** (section 2 design, implemented) | none new (reuses existing detectors; ADX/MA/VWAP are the only genuinely new calculations) | After #2 |
| 4 | **Strategy Selection Engine** (`DefaultToLegacySelector`, section 4.2) — BUILT | #1 | After #3 |
| 5 | **MAE/MFE/latency tracking wired into paper trading** — BUILT | #2 | After #4 -- requires touching `scripts/run_paper.py`'s open-position-checking loop, more invasive than a schema change alone, sequenced after the lower-risk pieces |
| 6 | **Rolling metrics computation + auto-disable mechanism** — BUILT | #2, #5 (needs real MAE/MFE/latency-tagged data to be meaningful, not just PnL) | After #5 |
| 7 | **Risk Engine extensions** (per-strategy disable hook, volatility-scaled sizing) | #3 (volatility scaling needs regime output), #6 (disable hook needs something to disable strategies) | After #6 |
| 8 | **New strategy modules** (Trend Following, Range Trading, Breakout, Volatility Expansion) | #1 | Explicitly LAST -- per operator's "prefer structural improvements over parameter optimization" and "do not search for another trading strategy," building new strategy CONTENT is secondary to finishing the system that can host, select, evaluate, and retire strategies. Not started this round. |

**This session's scope**: milestones 1-3 (Strategy Interface, DB schema,
Regime Detector) are the target for this work session, matching the
operator's "begin implementation starting with the Strategy Interface"
instruction. Milestones 4+ continue in subsequent sessions.

**Commit discipline for every milestone**: full backend test suite run
and passing, paper trader health verified (still running, still
untouched), design decision recorded in `ENGINEERING_DECISIONS.md`,
commit message describing what changed and why, push to `origin/master`
-- the same discipline every prior commit in this session has already
followed, continued unchanged for this new phase of work.
