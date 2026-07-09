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
from app.notifications.discord import send_discord_alert
from app.notifications.telegram import send_telegram_alert
from app.portfolio.journal import TradeJournal
from app.portfolio.positions import (
    load_circuit_breaker_state,
    save_circuit_breaker_state,
)
from app.portfolio.trades import TradeTracker
from app.risk.circuit_breaker import CircuitBreaker, PersistentCircuitBreaker
from app.risk.drawdown_guard import DrawdownGuard
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine

# No real account-balance source exists yet (Milestone 3 scope). Using a
# fixed placeholder for position sizing until a real equity/balance feed
# lands. Milestone 4 reuses the same placeholder to turn the journal's
# total_pnl into an approximate daily PnL percentage for the drawdown check.
PLACEHOLDER_ACCOUNT_BALANCE = 10000.0


def _count_trades_opened_today(tracker: TradeTracker) -> int:
    """Count open + closed trades whose opened_at falls on today's UTC date.

    TradeTracker.get_open_positions()/get_closed_trades() have landed with
    real DB-backed implementations, so we use them for a real trades_today
    count (rather than a hardcoded 0) to feed RiskManager's
    MAX_TRADES_PER_DAY check accurately.
    """
    today = datetime.now(timezone.utc).date()
    rows = tracker.get_open_positions() + tracker.get_closed_trades()
    return sum(
        1
        for row in rows
        if row.get("opened_at") is not None and row["opened_at"].date() == today
    )


def _check_drawdown_and_maybe_trip(
    circuit_breaker: CircuitBreaker | PersistentCircuitBreaker,
) -> None:
    """Approximate today's realized PnL% from the journal and trip `circuit_breaker`
    if the daily loss limit has been breached.

    Only called in loop mode (a live `circuit_breaker` instance is supplied);
    never called on the default single-pass path, so it cannot change that
    path's behavior. Best-effort: any failure computing the PnL estimate is
    reported and treated as 0.0% (no breach) rather than aborting the
    iteration -- this is an approximate, not production-grade, risk check.
    """
    try:
        report = TradeJournal().generate_journal_report()
        daily_pnl_percent = (
            report.get("total_pnl", 0.0) / PLACEHOLDER_ACCOUNT_BALANCE
        ) * 100
    except Exception as exc:
        print(
            f"WARNING: could not compute daily PnL for drawdown check ({exc}); "
            "defaulting to 0.0%."
        )
        daily_pnl_percent = 0.0

    if not DrawdownGuard().check_daily_loss(
        daily_pnl_percent, settings.MAX_DAILY_LOSS_PERCENT
    ):
        reason = "daily loss limit breached"
        circuit_breaker.trip(reason)
        message = (
            f"Circuit breaker tripped: {reason} (daily PnL "
            f"{daily_pnl_percent:.2f}%, limit {settings.MAX_DAILY_LOSS_PERCENT}%)"
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
      }

    When `circuit_breaker` is None (the default -- used by the no-args
    single-pass path), behavior/prints/exit-code are byte-for-byte identical
    to Milestone 3's `main()`. When a `circuit_breaker` is supplied (loop
    mode), an extra drawdown check runs first, and a Telegram/Discord alert
    fires after any successfully persisted trade.
    """
    summary: dict[str, Any] = {
        "signal_found": False,
        "approved": None,
        "executed": None,
        "trade_id": None,
        "error": None,
        "exit_code": 0,
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
    try:
        signal = SignalEngine().generate_signal(settings.SYMBOL, candles, htf_candles)
    except Exception as exc:
        print(f"ERROR: signal generation failed: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if signal is None:
        print("No signal generated this pass.")
        return summary

    summary["signal_found"] = True

    # --- 3. Risk-evaluate the signal ---
    # Real trades_today count (extra-credit path): derived from
    # TradeTracker.get_open_positions()/get_closed_trades(), both of which
    # are real DB-backed implementations. Falls back to 0 (with a warning,
    # not a hard failure) if this convenience query itself breaks, since a
    # broken count shouldn't block the core fetch/signal/risk/execute flow.
    try:
        trades_today = _count_trades_opened_today(TradeTracker())
    except Exception as exc:
        print(f"WARNING: could not compute trades_today ({exc}); defaulting to 0.")
        trades_today = 0

    try:
        risk_decision = RiskManager().evaluate(
            signal, trades_today=trades_today, circuit_breaker=circuit_breaker
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
        return summary

    summary["approved"] = True

    # --- 4. Execute the approved signal (paper only) ---
    try:
        result = ExecutionEngine().execute(signal, risk_decision)
    except Exception as exc:
        print(f"ERROR: execution raised an exception: {exc}")
        summary["error"] = str(exc)
        summary["exit_code"] = 1
        return summary

    if not result.success:
        print(f"Execution declined: {result.error}")
        summary["executed"] = False
        summary["error"] = result.error
        return summary

    summary["executed"] = True

    # --- 5. Persist the executed trade ---
    # ExecutionResult only exposes success/order_id/error (no fill price),
    # so entry_price falls back to the signal's planned entry_price as a
    # reasonable approximation rather than an actual fill price. Similarly,
    # fee/slippage/leverage are not sourced from ExecutionResult or
    # TradeSignal (neither carries them), so they are recorded as 0.0/1.0
    # placeholders below -- a real fee/slippage/leverage feed is out of
    # scope for this milestone.
    size = calculate_position_size(
        account_balance=PLACEHOLDER_ACCOUNT_BALANCE,
        risk_percent=settings.RISK_PER_TRADE_PERCENT,
        entry=signal.entry_price,
        stop_loss=signal.stop_loss,
    )

    trade_data: dict[str, Any] = {
        "symbol": signal.symbol,
        "direction": signal.direction,
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "size": size,
        "leverage": 1.0,
        "fee": 0.0,
        "slippage": 0.0,
        "status": "open",
        "mode": "paper",
        "opened_at": datetime.now(timezone.utc),
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
        f"@ {signal.entry_price} (trade_id={trade_id})"
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
