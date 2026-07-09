# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
