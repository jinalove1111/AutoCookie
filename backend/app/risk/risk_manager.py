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
    ) -> RiskDecision:
        """Evaluate a trade signal and return an approval decision with reasons.

        All trade signals must pass through here before execution. Approval
        requires all of: SL exists, TP exists, RR >= MIN_RR, daily/weekly
        loss limits not breached, max trades/day not breached, and (if a
        `circuit_breaker` is supplied) the breaker not tripped. All failing
        checks are collected (no short-circuiting) so callers get the full
        list of reasons.

        `circuit_breaker` is optional and duck-typed: any object exposing
        `.is_tripped()` (and `.reason`) works. Defaults to `None`, which
        skips this check entirely — existing callers are unaffected.
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

        return RiskDecision(approved=len(reasons) == 0, reasons=reasons)
