# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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

### Known gap (blocker, flagged for follow-up)
- `backend/app/backtesting/backtest_engine.py` (out of scope for this
  change) still calls `generate_signal()` with the old single-series
  signature inside its walk-forward loop, so a full `scripts/run_backtest.py`
  run currently fails fast with a clear `TypeError` (exit code 1) rather
  than silently misbehaving. Fixing it requires `BacktestEngine` to walk
  two timestamp-aligned candle series (LTF + HTF) in sync — a nontrivial
  design change belonging to `backend/app/backtesting/`, not touched here.

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
