"""Execution Engine.

Part of the Execution layer. Only accepts signals already approved by
RiskManager — it must never evaluate risk itself. Places entry/SL/TP via
OrderManager and reports the outcome.

ExecutionEngine does not touch the database and does not import anything
from app.portfolio.* — persistence is the caller's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.execution import safety_checks
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker


@dataclass
class ExecutionResult:
    """Outcome of attempting to execute an approved trade signal."""

    success: bool
    order_id: str | None
    error: str | None


class ExecutionEngine:
    """Executes trade signals that have already been approved by RiskManager."""

    def __init__(self, broker=None) -> None:
        """`broker` is any object exposing fill_entry/check_exit (duck-typed).
        If not given, constructs its own PaperBroker internally."""
        self.broker = broker if broker is not None else PaperBroker()
        self.order_manager = OrderManager(self.broker)

    def execute(self, signal, risk_decision) -> ExecutionResult:
        """Execute an approved signal and return the resulting order outcome.

        `risk_decision` is RiskDecision-shaped (attributes: approved,
        reasons) — duck-typed, not imported from app.risk.
        """
        if not risk_decision.approved:
            reasons = "; ".join(risk_decision.reasons)
            return ExecutionResult(
                success=False,
                order_id=None,
                error=f"signal not approved: {reasons}",
            )

        is_safe, reason = safety_checks.verify_safe_to_trade(risk_decision, signal)
        if not is_safe:
            return ExecutionResult(success=False, order_id=None, error=reason)

        fill = self.order_manager.place_entry(signal)

        return ExecutionResult(success=True, order_id=fill["order_id"], error=None)
