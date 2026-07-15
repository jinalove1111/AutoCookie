"""run_paper.py

Milestone 3: a single-pass paper-trading run through the full pipeline —
fetch real OKX candles, generate a signal, risk-evaluate it, execute it via
the (paper-only) ExecutionEngine, and persist the result.

Milestone 4: the single pass has been factored out into `run_once()` and
wrapped with an opt-in repeatable-loop CLI (`--iterations` /
`--interval-seconds`). Running the script with NO CLI args is unchanged from
Milestone 3 -- same single pass, same prints, same exit codes. Loop mode
reuses one `PersistentCircuitBreaker` instance across iterations, feeds it
into `RiskManager().evaluate(...)`, sends Telegram/Discord alerts on
executed trades, and trips the breaker if a daily-loss drawdown check
fails.

Milestone 4 follow-up (capital-protection): the loop-mode breaker is now
DB-backed (`app.risk.circuit_breaker.PersistentCircuitBreaker`, persisted
via `app.portfolio.positions.{load,save}_circuit_breaker_state`). On loop
startup, any prior tripped state is loaded from the DB and applied to the
in-memory breaker immediately; every trip()/reset() call persists
synchronously. This closes the gap where a process restart (crash,
redeploy, cron respawn) mid-trip previously came back untripped and
silently resumed trading.

Milestone 4 follow-up #2 (capital-protection, real daily/weekly PnL):
previously, `_check_drawdown_and_maybe_trip()` derived its "daily" PnL from
`TradeJournal().generate_journal_report()` -- an ALL-TIME, unfiltered
aggregate (mislabeled as daily), and `RiskManager().evaluate()` was never
passed `daily_pnl_percent`/`weekly_pnl_percent` at all (both silently
defaulted to 0.0, so the per-signal daily/weekly loss checks in
`DrawdownGuard` were dead code that could never reject a trade). Both call
sites now use `TradeJournal().generate_daily_report()` /
`generate_weekly_report()` (real UTC-calendar-day / ISO-calendar-week
scoped realized-PnL queries -- see `app/portfolio/journal.py`), converted
to percent-of-account via `_pnl_to_percent()`. `_check_drawdown_and_maybe_trip`
now trips the breaker on EITHER a daily OR a weekly breach (deliberate
choice, documented inline at the call site: a slower-building weekly loss
deserves the same alert-and-halt treatment as a same-day spike, since this
function is the only Telegram/Discord-alerting integration point in loop
mode -- relying on RiskManager's per-signal rejection alone would silently
reject every future signal without ever notifying the operator).

Is real daily/weekly RiskManager rejection sufficient protection for
SINGLE-PASS mode (`run_once()` called with no `circuit_breaker`, e.g. one
cron-triggered process per pass, with no persistent breaker at all)?
Conclusion: YES, for blocking further trades once a loss limit is real and
breached -- `daily_pnl_percent`/`weekly_pnl_percent` are now computed fresh
from the real DB on every single-pass invocation (not from in-process
memory), so protection does not depend on any state surviving between
process invocations; a losing streak keeps getting correctly re-detected
and re-rejected on every future pass for as long as it remains within the
UTC-day/ISO-week window, with no reliance on a circuit breaker being
"remembered". Remaining GAP, flagged (not fixed -- would require wiring
notifications into the rejection branch of `run_once`, additive scope
beyond this change): a single-pass rejection due to a real daily/weekly
loss breach is currently silent from an alerting standpoint -- it prints to
stdout and is visible in the returned summary dict/exit code, but no
Telegram/Discord alert fires (unlike loop mode's
`_check_drawdown_and_maybe_trip`). An operator running single-pass mode via
cron with no active log-watching would not be proactively notified that
trading has been (correctly) blocked by a real loss limit.

Zero live orders are ever placed here: ExecutionEngine is wired to a
PaperBroker by default, and TRADING_MODE defaults to "paper". The safety
guard below is defense-in-depth in case TRADING_MODE/LIVE_TRADING_ENABLED
are ever misconfigured to "live" for this script.

Exit codes (single-pass / default path, and each `run_once` call's own
outcome):
  0 -> normal outcomes: no signal generated, signal rejected by risk, or
       execution declined (all of these are safe, expected, non-error
       results of a single paper-trading pass).
  1 -> genuine failures: misconfigured live-trading guard tripped, network/
       data errors, or unexpected exceptions from any pipeline stage
       (including a trade being executed but failing to persist).

In loop mode (`--iterations > 1`), the overall process exit code is 0 as
long as the loop runs to completion or is cleanly interrupted (Ctrl+C);
individual iteration failures are reported inline but do not abort the loop
-- see `run_once`'s returned summary dict for per-iteration detail.

Simplifications noted inline where a frozen contract dependency doesn't yet
expose everything an ideal implementation would want (see comments below).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings

# --- Milestone-1 safety guard (defense in depth) ---
# This script is paper-only by design: nothing below ever routes to a live
# broker. Even so, never let it silently proceed if TRADING_MODE has been
# misconfigured to "live" without the explicit live-trading flag also being
# set (mirrors run_live.py's guard, inverted intent).
#
# This check deliberately runs immediately after importing only `settings`
# and BEFORE importing any other project module. Several downstream modules
# (app.portfolio.trades/journal -> app.database.session) construct a DB
# engine at import time and will raise on a misconfigured/empty
# DATABASE_URL; if the guard were placed after those imports, a
# misconfigured-live-mode run could crash with a confusing DB traceback
# instead of this clear, intentional refusal message.
if settings.TRADING_MODE == "live" and not settings.is_live_trading_allowed:
    print(
        "Refusing to run: TRADING_MODE is 'live' but live trading is not "
        "explicitly allowed (LIVE_TRADING_ENABLED is False). This script "
        "is paper-only; fix TRADING_MODE/.env before running it."
    )
    sys.exit(1)

from app.data.candle_fetcher import CandleFetcher
from app.execution.execution_engine import ExecutionEngine
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import FEE_PERCENT, PaperBroker
from app.notifications.discord import send_discord_alert
from app.notifications.telegram import send_telegram_alert
from app.portfolio.journal import TradeJournal
from app.portfolio.performance_snapshots import StrategyPerformanceEvaluator
from app.portfolio.positions import (
    load_circuit_breaker_state,
    save_circuit_breaker_state,
)
from app.portfolio.signals import SignalTracker
from app.portfolio.trades import TradeTracker
from app.risk.circuit_breaker import CircuitBreaker, PersistentCircuitBreaker
from app.risk.drawdown_guard import DrawdownGuard
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine

def _pnl_to_percent(pnl: float) -> float:
    """Convert an absolute realized-PnL figure into a percent-of-account
    figure, using `settings.PLACEHOLDER_ACCOUNT_BALANCE` (no real
    account-balance source exists yet -- see that setting's docstring in
    app/config.py, which is also the shared base
    `/dashboard/risk-status` uses, so the two stay comparable). Both
    `_check_drawdown_and_maybe_trip` and `run_once`'s `RiskManager.evaluate()`
    call need a percent, not an absolute PnL number; centralizing the
    conversion here keeps the two from silently drifting onto different
    formulas.
    """
    return (pnl / settings.PLACEHOLDER_ACCOUNT_BALANCE) * 100


def _compute_exit_pnl(position: dict, exit_price: float) -> float:
    """Compute realized PnL for closing `position` at `exit_price`.

    Deliberately mirrors `app.backtesting.backtest_engine.BacktestEngine.
    _simulate_trade`'s formula EXACTLY (same milestone's PnL/fee model,
    reused rather than re-derived to avoid a third, silently-divergent
    formula): PnL is the real price move times the real position size (not
    a percent-of-account approximation), minus a flat taker fee
    (`app.execution.paper_broker.FEE_PERCENT`) applied once per leg to that
    leg's actual notional (entry leg = size * entry_price, exit leg =
    size * exit_price).

    `position["entry_price"]` is expected to already be the broker's real
    (slippage-adjusted) fill price -- see the "5. Persist the executed
    trade" section below, which now records `result.fill_price` instead of
    the old `signal.entry_price` placeholder -- so this is a real
    round-trip PnL, not one anchored to a price that was never actually
    filled.
    """
    size = position["size"]
    entry_price = position["entry_price"]
    direction = position["direction"]
    fee_rate = FEE_PERCENT / 100

    if direction == "long":
        raw_pnl = size * (exit_price - entry_price)
    else:
        raw_pnl = size * (entry_price - exit_price)

    entry_fee = fee_rate * size * entry_price
    exit_fee = fee_rate * size * exit_price
    return raw_pnl - entry_fee - exit_fee


def _check_and_close_open_positions(current_price: float) -> list[int]:
    """Check every currently-open position against `current_price` via
    `PaperBroker().check_exit(...)` and close (via `TradeTracker().
    close_trade`) any that trigger a stop-loss or take-profit. Returns the
    list of trade ids closed this call.

    KNOWN LIMITATION (documented, not silently glossed over): `current_price`
    is a single point-in-time price (the most recently fetched LTF candle's
    CLOSE), not an intra-candle high/low scan like `BacktestEngine.
    _simulate_trade` does over historical OHLC. A stop-loss or take-profit
    level that was touched and reversed WITHIN a candle -- without that
    candle's own close being past the level -- will be missed here and only
    caught on a LATER pass, if/when price actually closes past the level.
    This is a real, accepted gap of close-driven (rather than tick- or
    intrabar-driven) paper exit checking, not a bug: a genuinely tick-level
    paper simulation would need a streaming price feed, out of scope here.
    """
    broker = PaperBroker()
    tracker = TradeTracker()
    closed_ids: list[int] = []

    for position in tracker.get_open_positions():
        exit_info = broker.check_exit(position, current_price)
        if exit_info is None:
            continue

        exit_price = exit_info["exit_price"]
        pnl = _compute_exit_pnl(position, exit_price)
        closed_at = datetime.now(timezone.utc)
        risk_per_unit = abs(position["entry_price"] - position["stop_loss"])
        r_multiple = (
            pnl / (risk_per_unit * position["size"])
            if risk_per_unit > 0 and position["size"] > 0
            else None
        )
        opened_at = position.get("opened_at")
        holding_time_seconds = (
            (closed_at - opened_at).total_seconds() if opened_at is not None else None
        )
        tracker.close_trade(
            position["id"],
            exit_price=exit_price,
            pnl=pnl,
            closed_at=closed_at,
            exit_reason=exit_info["reason"],
            r_multiple=r_multiple,
            holding_time_seconds=holding_time_seconds,
        )
        closed_ids.append(position["id"])
        print(
            f"Closed paper trade id={position['id']} ({position['symbol']} "
            f"{position['direction']}) via {exit_info['reason']}: "
            f"exit_price={exit_price:.6f} pnl={pnl:.6f}"
        )
        alert_message = (
            f"Paper trade closed: {position['direction']} {position['symbol']} "
            f"@ {exit_price:.6f} ({exit_info['reason']}, pnl={pnl:.2f}, "
            f"trade_id={position['id']})"
        )
        send_telegram_alert(alert_message)
        send_discord_alert(alert_message)

        # Adaptive platform milestone 6 (ENGINEERING_DECISIONS.md #48):
        # recompute this strategy's rolling performance snapshot every time
        # one of its trades closes -- the real "Continuous Learning" trigger
        # point (docs/ADAPTIVE_ARCHITECTURE.md section 1's feedback loop).
        # Best-effort/non-fatal, same pattern as every other observability
        # step in this module: a broken snapshot computation must not block
        # a real trade close that already happened.
        strategy_name = position.get("strategy_name")
        if strategy_name is not None:
            try:
                StrategyPerformanceEvaluator().evaluate_and_snapshot(
                    strategy_name, account_balance=settings.PLACEHOLDER_ACCOUNT_BALANCE
                )
            except Exception as exc:
                print(f"WARNING: strategy performance snapshot failed ({exc}).")

    return closed_ids


def _maybe_move_to_breakeven(current_price: float) -> list[int]:
    """No-op unless `settings.ENABLE_BREAKEVEN` is True (see app/config.py --
    this is the only paper-trading gate for the break-even feature; the
    A/B-tested trigger distance `settings.BREAKEVEN_TRIGGER_R` is shared
    with `BacktestEngine`'s own `use_breakeven` path so the two always
    agree on how far price must move before the stop is moved).

    For every open position whose stop hasn't already been moved to
    breakeven, computes the 1R trigger price from that position's
    ORIGINAL entry/stop distance and, once `current_price` reaches or
    passes it, moves `stop_loss` to `entry_price` via `TradeTracker().
    update_stop_loss`. Returns the list of trade ids moved this call.

    Ordering (deliberate, mirrors `BacktestEngine._simulate_trade`'s
    same-candle/same-pass conservative rule): this is called AFTER
    `_check_and_close_open_positions`, never before, in `run_once`. A
    pass that reaches the breakeven trigger price this same tick is
    exit-checked first against the OLD stop -- only a LATER pass sees the
    moved stop. This never optimistically "saves" a trade that also
    would have stopped out on the very same pass.

    Idempotency: rather than adding a new DB column to track whether a
    given trade already had its stop moved, "already moved" is inferred
    from the stop itself -- once `stop_loss` is at or past `entry_price`
    (>= for long, <= for short), the position is skipped. This is safe
    because a genuine signal's stop_loss can never legitimately equal (or
    be on the profit side of) its own entry_price to begin with (that
    would mean zero or negative risk), so this state is only ever reached
    via a prior breakeven move.

    The actual "what should the new stop be" computation delegates to
    `OrderManager.move_to_breakeven(position)` (this function only decides
    WHETHER/WHEN to call it) -- this is the reuse point
    `ENGINEERING_DECISIONS.md` entry #6 anticipated when break-even was
    first implemented inline inside `BacktestEngine`: `OrderManager`'s
    one-shot-call-against-a-DB-row contract fits naturally here, where
    positions genuinely are DB rows, unlike `BacktestEngine`'s tight
    per-candle scanning loop.
    """
    if not settings.ENABLE_BREAKEVEN:
        return []

    tracker = TradeTracker()
    order_manager = OrderManager(PaperBroker())
    moved_ids: list[int] = []

    for position in tracker.get_open_positions():
        entry_price = position["entry_price"]
        stop_loss = position["stop_loss"]
        direction = position["direction"]
        is_long = direction == "long"

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            continue

        already_at_breakeven = stop_loss >= entry_price if is_long else stop_loss <= entry_price
        if already_at_breakeven:
            continue

        trigger_price = (
            entry_price + settings.BREAKEVEN_TRIGGER_R * risk_per_unit
            if is_long
            else entry_price - settings.BREAKEVEN_TRIGGER_R * risk_per_unit
        )
        triggered = (
            current_price >= trigger_price if is_long else current_price <= trigger_price
        )
        if not triggered:
            continue

        new_position = order_manager.move_to_breakeven(position)
        tracker.update_stop_loss(position["id"], new_stop_loss=new_position["stop_loss"])
        moved_ids.append(position["id"])
        print(
            f"Moved paper trade id={position['id']} ({position['symbol']} "
            f"{direction}) stop_loss to breakeven @ {new_position['stop_loss']:.6f} "
            f"(trigger {trigger_price:.6f}, current_price {current_price:.6f})."
        )

    return moved_ids


def _update_excursion_tracking(current_price: float) -> list[int]:
    """Update `max_adverse_excursion`/`max_favorable_excursion` (adaptive
    platform milestone 5, ENGINEERING_DECISIONS.md #47) for every position
    still open after the exit-check/breakeven steps above, using
    `current_price` (the same close-price source `_check_and_close_open_
    positions`/`_maybe_move_to_breakeven` already use this pass).

    Called AFTER `_maybe_move_to_breakeven`, before the concurrency-guard
    re-query, in `run_once` -- MAE/MFE for a position that closed THIS
    pass is intentionally left as of its last observed open state (no
    further excursion can occur once a trade is closed), so this only
    ever touches positions genuinely still open. Best-effort per position:
    `TradeTracker.update_excursion` itself no-ops rather than raises on a
    since-closed/missing trade, so no additional error handling is needed
    here beyond the loop itself.
    """
    tracker = TradeTracker()
    updated_ids: list[int] = []
    for position in tracker.get_open_positions():
        tracker.update_excursion(position["id"], current_price)
        updated_ids.append(position["id"])
    return updated_ids


def _check_drawdown_and_maybe_trip(
    circuit_breaker: CircuitBreaker | PersistentCircuitBreaker,
) -> None:
    """Compute today's AND this week's real realized PnL% from the journal
    (UTC-calendar-day / ISO-calendar-week scoped -- see
    `app.portfolio.journal.TradeJournal.generate_daily_report`/
    `generate_weekly_report`) and trip `circuit_breaker` if EITHER the
    daily or the weekly loss limit has been breached.

    Design call (documented, not left implicit): this trips on a weekly
    breach too, not just daily. Reasoning: this function is the only
    Telegram/Discord-alerting integration point in loop mode. Relying on
    RiskManager's per-signal `weekly_pnl_percent` rejection alone (see
    `run_once` below) would still correctly BLOCK every future signal once
    a weekly loss limit is breached, but it would do so silently -- no
    alert would ever fire, unlike the same-day-spike case. A slower-building
    weekly loss deserves the same alert-and-halt treatment as a same-day
    spike, so both breaches trip the same persistent circuit breaker here.

    Only called in loop mode (a live `circuit_breaker` instance is supplied);
    never called on the default single-pass path, so it cannot change that
    path's behavior. Best-effort: any failure computing either PnL figure is
    reported and treated as 0.0% (no breach) rather than aborting the
    iteration -- this is an approximate, not production-grade, risk check
    (see settings.PLACEHOLDER_ACCOUNT_BALANCE in app/config.py).

    Auto-reset (Phase 1 risk-controls hardening -- previously a documented
    gap: `CircuitBreaker.reset()`'s own docstring used to say day-boundary
    auto-reset was "a future milestone's responsibility", and no
    operator-facing reset path existed at all, meaning a trip halted
    trading PERMANENTLY until someone manually edited the database). If
    `circuit_breaker` is currently tripped but THIS call's fresh
    daily/weekly checks BOTH pass, the breaker is reset here. This works
    correctly without any date-math of its own because
    `generate_daily_report()`/`generate_weekly_report()` are already
    UTC-calendar-day/ISO-calendar-week SCOPED -- once a new day/week
    genuinely begins, "today"/"this week"'s realized PnL naturally
    reflects only the new period, so a trip caused by a prior period's
    loss clears on its own the next time this runs, without needing to
    track "when was the trip" separately. An alert fires on auto-reset
    too (not just on trip), so an operator watching Telegram/Discord sees
    trading resume, not just that it stopped. Caveat, documented not
    hidden: this assumes every trip currently routes through THIS
    function (true today -- it's the only trip() call site in the
    codebase); if a future trip reason unrelated to daily/weekly drawdown
    is ever added (e.g. "exchange API failure", mentioned as a
    possibility in circuit_breaker.py's module docstring), auto-clearing
    it here based on drawdown alone would be wrong and this logic would
    need to become reason-aware first.
    """
    try:
        daily_report = TradeJournal().generate_daily_report()
        daily_pnl_percent = _pnl_to_percent(daily_report.get("total_pnl", 0.0))
    except Exception as exc:
        print(
            f"WARNING: could not compute daily PnL for drawdown check ({exc}); "
            "defaulting to 0.0%."
        )
        daily_pnl_percent = 0.0

    try:
        weekly_report = TradeJournal().generate_weekly_report()
        weekly_pnl_percent = _pnl_to_percent(weekly_report.get("total_pnl", 0.0))
    except Exception as exc:
        print(
            f"WARNING: could not compute weekly PnL for drawdown check ({exc}); "
            "defaulting to 0.0%."
        )
        weekly_pnl_percent = 0.0

    guard = DrawdownGuard()
    breaches: list[str] = []
    if not guard.check_daily_loss(daily_pnl_percent, settings.MAX_DAILY_LOSS_PERCENT):
        breaches.append(
            f"daily loss limit breached (daily PnL {daily_pnl_percent:.2f}%, "
            f"limit {settings.MAX_DAILY_LOSS_PERCENT}%)"
        )
    if not guard.check_weekly_loss(weekly_pnl_percent, settings.MAX_WEEKLY_LOSS_PERCENT):
        breaches.append(
            f"weekly loss limit breached (weekly PnL {weekly_pnl_percent:.2f}%, "
            f"limit {settings.MAX_WEEKLY_LOSS_PERCENT}%)"
        )

    if breaches:
        reason = "; ".join(breaches)
        circuit_breaker.trip(reason)
        message = f"Circuit breaker tripped: {reason}"
        print(f"ALERT: {message}")
        send_telegram_alert(message)
        send_discord_alert(message)
    elif circuit_breaker.is_tripped():
        prior_reason = circuit_breaker.reason
        circuit_breaker.reset()
        message = (
            f"Circuit breaker auto-reset: daily/weekly loss limits no longer "
            f"breached (daily PnL {daily_pnl_percent:.2f}%, weekly PnL "
            f"{weekly_pnl_percent:.2f}%; was tripped for: {prior_reason})"
        )
        print(f"ALERT: {message}")
        send_telegram_alert(message)
        send_discord_alert(message)


def run_once(
    circuit_breaker: CircuitBreaker | PersistentCircuitBreaker | None = None,
) -> dict[str, Any]:
    """Run exactly one paper-trading pass through the full pipeline.

    Returns a summary dict describing the outcome:
      {
        "signal_found": bool,
        "approved": bool | None,   # None if no signal was found
        "executed": bool | None,   # None if not approved / no signal
        "trade_id": int | None,
        "error": str | None,
        "exit_code": int,          # 0 = safe/expected outcome, 1 = genuine failure
        "positions_closed": list[int],   # trade ids closed by this pass's exit-check step
        "breakeven_moved": list[int],    # trade ids whose stop moved to breakeven this pass
                                          # (always [] unless settings.ENABLE_BREAKEVEN)
        "skipped_signal_generation": bool,  # True if the concurrency guard skipped
                                             # everything past the exit-check step
        "skipped_reason": str | None,       # why, when skipped_signal_generation is True
      }

    When `circuit_breaker` is None (the default -- used by the no-args
    single-pass path), behavior/prints/exit-code are byte-for-byte identical
    to Milestone 3's `main()` for the SIGNAL/RISK/EXECUTE portion. When a
    `circuit_breaker` is supplied (loop mode), an extra drawdown check runs
    first, and a Telegram/Discord alert fires after any successfully
    persisted trade.

    Dashboard follow-up (signal persistence): every genuinely generated
    signal (`signal_found` True) is now persisted via `SignalTracker()` as
    soon as it's generated (status="pending"), then updated to "rejected"/
    "approved"/"executed" as it moves through this function -- best-effort,
    same pattern as trades_today/daily_pnl_percent above (a broken
    persistence call is a loud WARNING, never a pipeline-blocking error).
    This is what `/dashboard/signals` now reads from; none of the returned
    summary dict's fields/semantics change.

    Milestone 4 follow-up #3 (paper trades actually closing -- see this
    module's own trade-persistence step and `_check_and_close_open_positions`
    above): EVERY call of `run_once()` -- single-pass AND each loop-mode
    iteration alike, never loop-mode-only -- now runs an exit-check step
    against every open position before doing anything else pipeline-wise,
    followed by a one-trade-open-at-a-time concurrency guard. Both were
    previously entirely absent: trades opened via `TradeTracker().
    record_trade(status="open")` but nothing ever checked them against a
    current price or closed them, so `TradeJournal`'s daily/weekly/all-time
    reports (and therefore the daily/weekly loss-limit circuit-breaker
    check above) could never see a realized loss -- a silent, total defeat
    of both reporting and capital protection in real operation. See
    `_check_and_close_open_positions`'s docstring for the accepted
    close-price-only (not intrabar) limitation of this check.

    Strategy coverage audit follow-up (break-even in paper trading): right
    after the exit-check step, every open position is also checked against
    a 1R break-even trigger (`_maybe_move_to_breakeven`, gated by
    `settings.ENABLE_BREAKEVEN`, off by default). This was the only one of
    three A/B-tested experimental execution features (break-even/
    breaker-block/partial-TP -- see docs/strategy_coverage_audit.md and
    CHANGELOG.md) that reproduced a positive backtest result on two
    independent samples, hence the only one wired into paper trading so
    far; the other two remain backtest-only until they show similar
    evidence.

    Concurrency-guard design call (documented, not implicit): if any
    position(s) remain open AFTER the exit-check step, this pass skips
    signal generation/risk/execution ENTIRELY for the rest of this call --
    mirrors `BacktestEngine`'s one-trade-open-at-a-time (no-overlap) model,
    the simplest choice that keeps real paper risk exposure consistent with
    what was actually backtested. When this happens, `signal_found`/
    `approved`/`executed` are left at their untouched defaults
    (False/None/None) -- deliberately identical to the existing "no signal
    generated this pass" case, since signal generation genuinely did not
    run either way; the NEW `skipped_signal_generation`/`skipped_reason`
    fields are what distinguish "guard skipped this pass" from "the
    strategy just found nothing" for any caller that cares about the
    difference, without changing the meaning callers already rely on for
    the three original fields.
    """
    summary: dict[str, Any] = {
        "signal_found": False,
        "approved": None,
        "executed": None,
        "trade_id": None,
        "error": None,
        "exit_code": 0,
        "positions_closed": [],
        "breakeven_moved": [],
        "skipped_signal_generation": False,
        "skipped_reason": None,
    }

    # --- 0. Drawdown/circuit-breaker check (loop mode only) ---
    if circuit_breaker is not None:
        _check_drawdown_and_maybe_trip(circuit_breaker)

    # --- 1. Fetch recent candles (LTF for structure/entries, HTF for bias) ---
    # Real HTF/LTF separation (docs/strategy_spec.md section 1): these must
    # be two genuinely distinct fetches, never the LTF series reused as HTF
    # -- that would defeat the entire point of the separation.
    try:
        candles = CandleFetcher().fetch_ohlcv(
            settings.SYMBOL, settings.DEFAULT_TIMEFRAME, limit=300
        )
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {settings.SYMBOL}: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if not candles:
        print(f"No candles returned for {settings.SYMBOL}/{settings.DEFAULT_TIMEFRAME}.")
        summary["error"] = "no candles returned"
        summary["exit_code"] = 1
        return summary

    # --- 1.5 Check open positions for a stop-loss/take-profit exit ---
    # Runs BEFORE signal generation (not after), and on EVERY pass
    # (single-pass and loop-mode alike, not loop-mode-only), so a position
    # that closes this pass frees capacity within the SAME pass rather than
    # forcing a wasted no-op pass first. Uses the LTF candle series just
    # fetched above -- the natural, already-available "current price"
    # source (its most recent candle's close) -- rather than firing a
    # separate price fetch. See `_check_and_close_open_positions`'s
    # docstring for the close-price-only (not intrabar high/low) limitation
    # of this check.
    try:
        current_price = candles[-1]["close"]
        closed_ids = _check_and_close_open_positions(current_price)
    except Exception as exc:
        print(f"ERROR: exit-check step failed: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    summary["positions_closed"] = closed_ids

    # --- 1.55 Move open positions' stops to breakeven, if triggered ---
    # Opt-in via settings.ENABLE_BREAKEVEN (default False -- see app/config.py
    # and _maybe_move_to_breakeven's docstring for the full rationale: this
    # is the only one of the three A/B-tested experimental features
    # (break-even/breaker-block/partial-TP) that reproduced a positive
    # result on two independent backtest samples, hence the only one wired
    # into paper trading so far). Deliberately AFTER the exit-check step
    # above (not before) so a position that reaches the breakeven trigger
    # price this same pass is still exit-checked against its OLD stop this
    # pass -- see that function's docstring for why.
    try:
        breakeven_moved_ids = _maybe_move_to_breakeven(current_price)
    except Exception as exc:
        print(f"ERROR: breakeven-move step failed: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    summary["breakeven_moved"] = breakeven_moved_ids

    # --- 1.58 Update MAE/MFE for still-open positions ---
    # Best-effort, non-fatal (adaptive platform milestone 5): a broken
    # excursion update must not block the real exit-check/breakeven/
    # signal/risk/execute pipeline, matching every other observability
    # step in this function (trades_today, daily/weekly PnL, above).
    try:
        _update_excursion_tracking(current_price)
    except Exception as exc:
        print(f"WARNING: MAE/MFE excursion update failed ({exc}).")

    # --- 1.6 Concurrency guard: at most one open position at a time ---
    # Re-queries open positions AFTER the exit-check step above (not
    # before), so a position that just closed this same pass correctly
    # frees capacity for a new signal in the SAME pass rather than needing
    # an extra pass. See this function's docstring for the full design
    # rationale and the summary-field semantics used when this trips.
    try:
        still_open = TradeTracker().get_open_positions()
    except Exception as exc:
        print(f"ERROR: could not query open positions for the concurrency guard: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if still_open:
        reason = (
            f"{len(still_open)} open position(s) remain after the exit-check "
            "step; skipping signal generation/risk/execution this pass "
            "(one-trade-open-at-a-time guard, mirroring BacktestEngine's "
            "no-overlap model)."
        )
        print(reason)
        summary["skipped_signal_generation"] = True
        summary["skipped_reason"] = reason
        return summary

    try:
        htf_candles = CandleFetcher().fetch_ohlcv(
            settings.SYMBOL, settings.HTF_TIMEFRAME, limit=300
        )
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch HTF candles for {settings.SYMBOL}: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if not htf_candles:
        print(f"No HTF candles returned for {settings.SYMBOL}/{settings.HTF_TIMEFRAME}.")
        summary["error"] = "no HTF candles returned"
        summary["exit_code"] = 1
        return summary

    # --- 2. Generate a signal ---
    # use_jade_engine: opt-in via settings.USE_JADE_ENGINE (default False --
    # see app/config.py's docstring on that setting for why this was wired
    # in before A/B evidence exists, unlike ENABLE_BREAKEVEN above).
    try:
        signal = SignalEngine().generate_signal(
            settings.SYMBOL, candles, htf_candles, use_jade_engine=settings.USE_JADE_ENGINE
        )
    except Exception as exc:
        print(f"ERROR: signal generation failed: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if signal is None:
        print("No signal generated this pass.")
        return summary

    summary["signal_found"] = True

    # Persist the signal as soon as it's generated (Dashboard follow-up):
    # `app.database.models.Signal`'s status column has always documented a
    # pending/approved/rejected/executed convention, and TradeSignal's own
    # docstring says it "matches the signals DB table", but nothing ever
    # actually wrote one -- /dashboard/signals returned a hardcoded empty
    # placeholder. Best-effort, same pattern as trades_today/daily_pnl_percent
    # above: a broken persistence call must not block the real fetch/risk/
    # execute pipeline, so failures are a loud WARNING (not a hard error),
    # and `signal_id` stays `None` (status updates below are skipped) rather
    # than raising.
    signal_id: int | None = None
    try:
        signal_id = SignalTracker().record_signal(signal)
    except Exception as exc:
        print(f"WARNING: could not persist signal ({exc}).")

    # --- 3. Risk-evaluate the signal ---
    # Real trades_today count (extra-credit path): derived from
    # TradeTracker.get_open_positions()/get_closed_trades(), both of which
    # are real DB-backed implementations. Falls back to 0 (with a warning,
    # not a hard failure) if this convenience query itself breaks, since a
    # broken count shouldn't block the core fetch/signal/risk/execute flow.
    try:
        trades_today = TradeTracker().count_trades_opened_today()
    except Exception as exc:
        print(f"WARNING: could not compute trades_today ({exc}); defaulting to 0.")
        trades_today = 0

    # Real daily/weekly realized-PnL% (capital-protection follow-up #2):
    # previously these were never passed here at all, so RiskManager's
    # DrawdownGuard daily/weekly checks silently defaulted to 0.0% and could
    # never reject a trade. Runs in BOTH single-pass and loop mode (this
    # code path is shared), unlike the circuit-breaker drawdown check above,
    # which is loop-mode only -- see the module docstring's "is that
    # sufficient for single-pass mode?" note for why this alone is judged
    # adequate protection for the single-pass path. Best-effort, same
    # fallback-to-0.0 pattern as trades_today above: a broken PnL query
    # shouldn't block the entire pipeline, but MUST be loud (not silent).
    try:
        daily_report = TradeJournal().generate_daily_report()
        daily_pnl_percent = _pnl_to_percent(daily_report.get("total_pnl", 0.0))
    except Exception as exc:
        print(f"WARNING: could not compute daily_pnl_percent ({exc}); defaulting to 0.0.")
        daily_pnl_percent = 0.0

    try:
        weekly_report = TradeJournal().generate_weekly_report()
        weekly_pnl_percent = _pnl_to_percent(weekly_report.get("total_pnl", 0.0))
    except Exception as exc:
        print(f"WARNING: could not compute weekly_pnl_percent ({exc}); defaulting to 0.0.")
        weekly_pnl_percent = 0.0

    try:
        risk_decision = RiskManager().evaluate(
            signal,
            daily_pnl_percent=daily_pnl_percent,
            weekly_pnl_percent=weekly_pnl_percent,
            trades_today=trades_today,
            circuit_breaker=circuit_breaker,
        )
    except Exception as exc:
        print(f"ERROR: risk evaluation failed: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if not risk_decision.approved:
        print("Signal rejected by risk manager:")
        for reason in risk_decision.reasons:
            print(f"  - {reason}")
        summary["approved"] = False
        summary["error"] = "; ".join(risk_decision.reasons)
        if signal_id is not None:
            try:
                SignalTracker().update_signal_status(
                    signal_id, "rejected", reason=summary["error"]
                )
            except Exception as exc:
                print(f"WARNING: could not update signal status to 'rejected' ({exc}).")
        return summary

    summary["approved"] = True
    if signal_id is not None:
        try:
            SignalTracker().update_signal_status(signal_id, "approved")
        except Exception as exc:
            print(f"WARNING: could not update signal status to 'approved' ({exc}).")

    # --- 4. Execute the approved signal (paper only) ---
    # latency_ms (adaptive platform milestone 5, ENGINEERING_DECISIONS.md
    # #47): wall-clock milliseconds this process itself spent inside the
    # execute() call. Disclosed scope: PaperBroker.execute() never makes a
    # real exchange API round-trip, so this measures the paper-trading
    # ENGINE's own processing latency (Python call + in-memory fill
    # simulation), not real exchange order latency -- a genuine, honest
    # measurement of what this pipeline actually does, not a stand-in for
    # a number this codebase has no way to produce yet.
    execute_started_at = time.monotonic()
    try:
        result = ExecutionEngine().execute(signal, risk_decision)
    except Exception as exc:
        print(f"ERROR: execution raised an exception: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary
    latency_ms = (time.monotonic() - execute_started_at) * 1000

    if not result.success:
        print(f"Execution declined: {result.error}")
        summary["executed"] = False
        summary["error"] = result.error
        return summary

    summary["executed"] = True
    if signal_id is not None:
        try:
            SignalTracker().update_signal_status(signal_id, "executed")
        except Exception as exc:
            print(f"WARNING: could not update signal status to 'executed' ({exc}).")

    # --- 5. Persist the executed trade ---
    # entry_price now records `result.fill_price` (the broker's real,
    # slippage-adjusted fill) so `_compute_exit_pnl` computes a genuine
    # round-trip PnL at close time -- see that function's docstring. Falls
    # back to the signal's planned entry_price only if fill_price is
    # somehow absent (defensive; PaperBroker.fill_entry always sets it on
    # a successful fill). Position sizing intentionally still keys off the
    # planned `signal.entry_price` (not the fill), mirroring
    # `BacktestEngine`'s own size-before-fill ordering: risk is sized
    # against the planned entry/stop distance before the fill/slippage is
    # known.
    #
    # fee: `ExecutionResult` now exposes `fee_percent` (PaperBroker's flat
    # taker-fee rate, e.g. 0.05 == 0.05%) -- previously not sourced from
    # ExecutionResult at all (hardcoded 0.0 here). Recorded as the
    # ENTRY-LEG fee in account-currency units (fee_rate * size * fill
    # price), the same per-leg-notional model `_compute_exit_pnl` above
    # uses for the matching exit leg at close time (see that function's
    # docstring). This column stays entry-leg-only even after close, since
    # `close_trade()` has no fee parameter to fold the exit-leg fee into it
    # too -- the ROUND-TRIP fee total instead lands inside `pnl` at close
    # time via `_compute_exit_pnl`.
    # slippage: the actual applied price-unit delta between the signal's
    # planned entry_price and the broker's real fill_price -- previously
    # the flat `SLIPPAGE_PERCENT` RATE constant was stored here directly,
    # which is a percentage, not a price-unit delta comparable to this
    # column's other float values. "How many price units did the fill move
    # against us" is the simplest, most directly inspectable definition
    # given no prior convention exists for this column.
    size = calculate_position_size(
        account_balance=settings.PLACEHOLDER_ACCOUNT_BALANCE,
        risk_percent=settings.RISK_PER_TRADE_PERCENT,
        entry=signal.entry_price,
        stop_loss=signal.stop_loss,
    )

    entry_price = result.fill_price if result.fill_price is not None else signal.entry_price
    fee_percent = result.fee_percent if result.fee_percent is not None else 0.0
    entry_fee = (fee_percent / 100) * size * entry_price
    slippage_amount = abs(entry_price - signal.entry_price)

    trade_data: dict[str, Any] = {
        "symbol": signal.symbol,
        "direction": signal.direction,
        "entry_price": entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "size": size,
        "leverage": 1.0,
        "fee": entry_fee,
        "slippage": slippage_amount,
        "status": "open",
        "mode": "paper",
        "opened_at": datetime.now(timezone.utc),
        "latency_ms": latency_ms,
        "strategy_name": "jade" if settings.USE_JADE_ENGINE else "legacy",
        "strategy_config": {
            "use_jade_engine": settings.USE_JADE_ENGINE,
            "enable_breakeven": settings.ENABLE_BREAKEVEN,
        },
    }

    try:
        trade_id = TradeTracker().record_trade(trade_data)
    except Exception as exc:
        # The order was already executed (result.success is True) but
        # persistence failed -- this is a genuine problem worth a loud,
        # non-zero-exit failure rather than a silently swallowed error.
        print(
            "ERROR: trade was executed (order_id="
            f"{result.order_id}) but recording it via TradeTracker failed: {exc}"
        )
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    summary["trade_id"] = trade_id

    # --- 5b. Notify (Telegram/Discord) on a successfully persisted trade ---
    # Both senders are safe no-ops when unconfigured/disabled and never
    # raise (frozen contract) -- called unconditionally, no extra gating.
    alert_message = (
        f"Paper trade executed: {signal.direction} {signal.symbol} "
        f"@ {entry_price} (trade_id={trade_id})"
    )
    send_telegram_alert(alert_message)
    send_discord_alert(alert_message)

    reason = (
        f"bias={signal.htf_bias} sweep={signal.sweep_type} "
        f"choch={signal.choch_detected}"
    )
    try:
        TradeJournal().log_trade_reason(trade_id, reason=reason)
    except Exception as exc:
        # The trade row already exists; journaling the reason is best-effort
        # context and its failure shouldn't be reported as if the trade
        # itself failed, but it must not be swallowed silently either.
        print(
            f"WARNING: trade {trade_id} recorded, but journaling the trade "
            f"reason failed: {exc}"
        )

    # --- 6. Final summary ---
    print("Paper trading pass complete:")
    print(f"  signal generated : yes ({signal.direction} {signal.symbol})")
    print("  risk approved     : yes")
    print(f"  executed          : yes (order_id={result.order_id})")
    print(f"  trade id          : {trade_id}")
    print(f"  reason            : {reason}")
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Paper-trading runner. With no args, makes exactly one pass "
            "(Milestone 3 behavior, unchanged). Pass --iterations > 1 to "
            "repeat the pass on a fixed interval (Milestone 4 loop mode)."
        )
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of passes to run. Default 1 (single-pass, unchanged behavior).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=60.0,
        help="Seconds to sleep between passes when --iterations > 1. Default 60.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()

    # Default path (no CLI args, or explicit --iterations 1): identical to
    # Milestone 3's single-pass main() -- same prints, same exit code.
    if args.iterations <= 1:
        summary = run_once()
        return summary["exit_code"]

    # --- Loop mode ---
    # One PersistentCircuitBreaker instance is created here and reused
    # (never recreated) across every run_once() call for the lifetime of
    # the loop. Its constructor loads any prior persisted trip from the DB
    # (app.portfolio.positions.load_circuit_breaker_state) and applies it
    # immediately, so a respawned process (crash, redeploy, cron respawn)
    # resumes with the breaker correctly tripped rather than silently
    # resuming trading. Every subsequent trip()/reset() call persists the
    # new state synchronously via save_circuit_breaker_state.
    circuit_breaker = PersistentCircuitBreaker(
        state_loader=load_circuit_breaker_state,
        state_saver=save_circuit_breaker_state,
    )
    if circuit_breaker.is_tripped():
        print(
            "Loop startup: circuit breaker restored from prior persisted "
            f"state -- tripped=True, reason={circuit_breaker.reason!r}, "
            f"tripped_at={circuit_breaker.tripped_at}."
        )
    completed = 0
    try:
        for i in range(args.iterations):
            print(
                f"--- Iteration {i + 1}/{args.iterations} "
                f"(circuit_breaker id={id(circuit_breaker)}, "
                f"tripped={circuit_breaker.is_tripped()}) ---"
            )
            run_once(circuit_breaker=circuit_breaker)
            completed += 1
            if i < args.iterations - 1:
                time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print(
            f"\nInterrupted: {completed}/{args.iterations} iteration(s) "
            "completed before Ctrl+C."
        )
        return 0

    print(f"Loop complete: {completed}/{args.iterations} iteration(s) completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
