"""Safety checks.

Part of the Execution layer. Verifies preconditions before any order is
placed. This check is real and correct now because it also gates
LiveBroker in a future milestone (defense in depth), even though this
project runs in PAPER_MODE by default.
"""

from __future__ import annotations

from app.config import settings


def verify_safe_to_trade(risk_decision, signal, exchange_healthy: bool = True) -> tuple[bool, str]:
    """Check live-trading safety preconditions and return (is_safe, reason).

    `risk_decision` and `signal` are duck-typed (RiskDecision-shaped and
    TradeSignal-shaped respectively) — this module does not import
    app.risk or app.strategy.
    """
    if settings.TRADING_MODE == "live" and not settings.is_live_trading_allowed:
        return False, "live trading not allowed by config"

    if not risk_decision.approved:
        return False, "risk manager did not approve signal"

    if not getattr(signal, "stop_loss", None):
        return False, "signal missing stop_loss"

    if not getattr(signal, "take_profit", None):
        return False, "signal missing take_profit"

    if getattr(signal, "rr", 0) < settings.MIN_RR:
        return False, f"rr below MIN_RR ({settings.MIN_RR})"

    if not exchange_healthy:
        return False, "exchange not healthy"

    return True, "ok"
