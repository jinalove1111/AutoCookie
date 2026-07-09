# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
