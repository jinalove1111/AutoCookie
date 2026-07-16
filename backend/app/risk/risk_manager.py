"""Risk Manager — the single gate every trade signal must pass through.

Part of the Risk Engine. Sits between Strategy and Execution. All trade
signals must pass through here before execution. Approval requires all of:
SL exists, TP exists, RR >= MIN_RR, daily/weekly loss limits not breached,
max trades/day not breached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.config import settings
from app.risk.drawdown_guard import DrawdownGuard


@runtime_checkable
class SignalLike(Protocol):
    """Structural shape a signal must satisfy to be risk-evaluated.

    Matches `app.strategy.signal_engine.TradeSignal` without importing it,
    to avoid a strategy -> risk cross-import / tight coupling.
    """

    stop_loss: float | None
    take_profit: float | None
    rr: float


@dataclass
class RiskDecision:
    """Outcome of a risk evaluation for a single trade signal."""

    approved: bool
    reasons: list[str] = field(default_factory=list)


class RiskManager:
    """Validates trade signals against risk rules before they reach Execution."""

    def evaluate(
        self,
        signal: SignalLike,
        daily_pnl_percent: float = 0.0,
        weekly_pnl_percent: float = 0.0,
        trades_today: int = 0,
        circuit_breaker: object | None = None,
        strategy_disabled: bool = False,
        stop_distance_atr_mult: float | None = None,
        min_stop_atr_mult: float = 0.0,
    ) -> RiskDecision:
        """Evaluate a trade signal and return an approval decision with reasons.

        All trade signals must pass through here before execution. Approval
        requires all of: SL exists, TP exists, RR >= MIN_RR, daily/weekly
        loss limits not breached, max trades/day not breached, (if a
        `circuit_breaker` is supplied) the breaker not tripped, the
        originating strategy not auto-disabled, and (if the ATR floor gate
        is enabled) the stop distance not tighter than the floor. All
        failing checks are collected (no short-circuiting) so callers get
        the full list of reasons.

        `circuit_breaker` is optional and duck-typed: any object exposing
        `.is_tripped()` (and `.reason`) works. Defaults to `None`, which
        skips this check entirely — existing callers are unaffected.

        `strategy_disabled` (optional, default `False` -- adaptive platform
        milestone 7's Risk Engine disable hook, `docs/ADAPTIVE_ARCHITECTURE.md`
        section 5.2, ENGINEERING_DECISIONS.md #49): a plain, CALLER-computed
        boolean, not a lookup performed here -- `app.risk` has no import
        dependency on `app.portfolio`/`app.database` anywhere in this
        package (verified: `drawdown_guard.py`/`circuit_breaker.py` have
        none either), and this keeps that layering intact. The caller
        (`scripts/run_paper.py`) computes it via `StrategyPerformanceEvaluator.
        is_strategy_disabled(strategy_name)` and passes the result in,
        exactly the same "pre-computed value, not looked up here" pattern
        `daily_pnl_percent`/`weekly_pnl_percent`/`trades_today` already use
        (those are computed from `TradeJournal`/`TradeTracker` by the
        caller too, never queried inside this method).

        `stop_distance_atr_mult` / `min_stop_atr_mult` (Milestone 18b,
        docs/RESEARCH_ROUND_1.md recommendation #2, docs/ROBUSTNESS_REPORT.md):
        a minimum stop-distance-as-ATR-multiple floor. The robustness report
        traced the dead candidate's failure to a root cause: its stop
        averaged just 0.17-0.23% of price, tighter than routine
        single-candle movement, so ANY execution delay invalidated its risk
        geometry. Standard practice per Wilder-convention literature is
        stops of 1.5-3.0x ATR. Following decision #49's pattern exactly,
        this gate is entirely CALLER-computed: `RiskManager` never reads
        `settings` for this threshold and never computes ATR itself. The
        caller computes `abs(entry - stop) / atr` and passes it as
        `stop_distance_atr_mult`; `min_stop_atr_mult` is the caller's
        chosen floor (typically `settings.MIN_STOP_ATR_MULT`, default
        `0.0` -- see `app/config.py`). Gate logic:
        - `min_stop_atr_mult <= 0.0` (the default): gate is disabled,
          no check performed, identical to pre-Milestone-18b behavior.
        - `min_stop_atr_mult > 0.0` and `stop_distance_atr_mult is None`
          (caller could not compute ATR, e.g. insufficient candle
          history): WARN-and-allow, no rejection. Missing measurement is
          not evidence of a tight stop, matching this repo's best-effort
          observability discipline elsewhere (e.g. shadow-mode signals).
        - `min_stop_atr_mult > 0.0` and `stop_distance_atr_mult` is
          present and `< min_stop_atr_mult`: rejected with reason
          `"stop_distance_below_atr_floor"`. Boundary convention (matches
          `MIN_RR`'s `rr < settings.MIN_RR` gate above): exactly at the
          floor PASSES, strictly below REJECTS.
        """
        reasons: list[str] = []
        guard = DrawdownGuard()

        if not getattr(signal, "stop_loss", None):
            reasons.append("stop_loss is missing")
        if not getattr(signal, "take_profit", None):
            reasons.append("take_profit is missing")

        rr = getattr(signal, "rr", None)
        if rr is None or rr < settings.MIN_RR:
            reasons.append(
                f"rr {rr} is below required MIN_RR {settings.MIN_RR}"
            )

        if not guard.check_daily_loss(daily_pnl_percent, settings.MAX_DAILY_LOSS_PERCENT):
            reasons.append(
                f"daily loss {daily_pnl_percent}% breaches MAX_DAILY_LOSS_PERCENT "
                f"{settings.MAX_DAILY_LOSS_PERCENT}%"
            )

        if not guard.check_weekly_loss(weekly_pnl_percent, settings.MAX_WEEKLY_LOSS_PERCENT):
            reasons.append(
                f"weekly loss {weekly_pnl_percent}% breaches MAX_WEEKLY_LOSS_PERCENT "
                f"{settings.MAX_WEEKLY_LOSS_PERCENT}%"
            )

        if trades_today >= settings.MAX_TRADES_PER_DAY:
            reasons.append(
                f"trades_today {trades_today} reached MAX_TRADES_PER_DAY "
                f"{settings.MAX_TRADES_PER_DAY}"
            )

        if circuit_breaker is not None and circuit_breaker.is_tripped():
            reasons.append(
                f"circuit breaker tripped: {circuit_breaker.reason}"
            )

        if strategy_disabled:
            reasons.append(
                "originating strategy is currently auto-disabled "
                "(rolling profit factor at or below threshold)"
            )

        if min_stop_atr_mult > 0.0:
            if stop_distance_atr_mult is None:
                # Caller couldn't compute ATR (e.g. insufficient candle
                # history) -- WARN-and-allow: missing measurement is not
                # evidence of a tight stop. See evaluate()'s docstring.
                pass
            elif stop_distance_atr_mult < min_stop_atr_mult:
                reasons.append("stop_distance_below_atr_floor")

        return RiskDecision(approved=len(reasons) == 0, reasons=reasons)
