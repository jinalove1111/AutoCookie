"""Signal persistence.

`app.database.models.Signal` has always documented a
pending/approved/rejected/executed `status` convention, and
`app.strategy.signal_engine.TradeSignal`'s docstring says it "matches the
`signals` DB table" -- but nothing ever actually persisted a generated
signal there; `/dashboard/signals` returned a hardcoded empty placeholder.
This module is what wires that up: callers (scripts/run_paper.py) persist
each real `TradeSignal` as soon as it's generated, then update its status
as it moves through Risk Engine approval and Execution.

Not imported by app.strategy.* -- the Strategy Engine stays DB-decoupled
(same Iron Wall pattern as execution/portfolio elsewhere in this
codebase); callers persist the TradeSignal after receiving it back.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.database.models import Signal
from app.portfolio.trades import _row_to_dict, session_scope


class SignalTracker:
    """Persists and queries generated trade signals via the `signals` table."""

    def record_signal(self, signal: Any) -> int:
        """Insert a new Signal row from a TradeSignal-shaped object (duck-typed
        -- matches `app.strategy.signal_engine.TradeSignal`'s fields
        exactly, see that dataclass's docstring) and return its integer id.
        """
        with session_scope() as db:
            row = Signal(
                symbol=signal.symbol,
                direction=signal.direction,
                timestamp=signal.timestamp,
                htf_bias=signal.htf_bias,
                sweep_type=signal.sweep_type,
                choch_detected=signal.choch_detected,
                fvg_zone=signal.fvg_zone,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                rr=signal.rr,
                status=signal.status,
            )
            db.add(row)
            db.flush()  # populate row.id (autoincrement PK) before commit
            signal_id = row.id
        return signal_id

    def update_signal_status(
        self, signal_id: int, status: str, reason: str | None = None
    ) -> None:
        """Update an existing Signal row's status. Raises ValueError if
        `signal_id` does not exist -- never silently no-ops (mirrors
        `TradeTracker.close_trade`'s contract).

        `reason` (optional, default `None` -- backward compatible):
        observability follow-up (2026-07-12 profitability sprint Phase E)
        -- when set (e.g. a rejected signal's `risk_decision.reasons`,
        joined), persists WHY into `rejection_reason`, so a later query
        over signals can recover it instead of only ever having appeared
        in that process's own stdout at the moment of rejection.
        """
        with session_scope() as db:
            row = db.get(Signal, signal_id)
            if row is None:
                raise ValueError(f"Signal id={signal_id} not found")
            row.status = status
            if reason is not None:
                row.rejection_reason = reason

    def get_recent_signals(self, limit: int = 20) -> list[dict]:
        """Return the most recent Signal rows (newest first, by `timestamp`)
        as plain dicts."""
        with session_scope() as db:
            rows = (
                db.execute(select(Signal).order_by(Signal.timestamp.desc()).limit(limit))
                .scalars()
                .all()
            )
            return [_row_to_dict(row) for row in rows]
