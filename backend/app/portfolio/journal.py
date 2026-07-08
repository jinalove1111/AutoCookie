"""
Milestone 3: real persistence for the trade journal -- logging the reasoning
behind trades and generating aggregate paper-trading reports -- backed by
app.database.session/models.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database.models import StrategyLog, Trade
from app.portfolio.trades import session_scope

logger = logging.getLogger(__name__)


class TradeJournal:
    """Journals trade decisions and produces aggregate paper-trading reports."""

    def log_trade_reason(self, trade_id: int, reason: str) -> None:
        """
        Insert a StrategyLog row documenting why `trade_id` was opened.

        StrategyLog has no trade_id FK (only signal_id), so trade_id is
        stashed inside candle_context (JSON) to avoid a schema mismatch:
        module="execution", decision="trade_opened",
        candle_context={"trade_id": trade_id}.
        """
        with session_scope() as db:
            log = StrategyLog(
                module="execution",
                decision="trade_opened",
                reason=reason,
                candle_context={"trade_id": trade_id},
                timestamp=datetime.now(timezone.utc),
            )
            db.add(log)

    def save_chart_snapshot(self, trade_id: int, snapshot: Any) -> None:
        """
        Deferred past Milestone 3: there is no chart-snapshot table/column
        yet. Cleanly no-ops (logs at debug level) rather than raising, since
        this method is now reachable from the real paper-trading flow.
        """
        logger.debug(
            "save_chart_snapshot is a no-op in Milestone 3 (trade_id=%s); "
            "chart snapshot persistence is deferred to a later milestone.",
            trade_id,
        )

    def generate_journal_report(self) -> dict:
        """
        Aggregate paper-mode (mode == "paper") trades into:
          {"total_trades": int, "win_rate": float, "total_pnl": float}

        win_rate is the fraction of CLOSED trades with pnl > 0 (among closed
        trades only). total_pnl sums pnl over closed trades, treating a None
        pnl as 0. Returns all zeros when there are no trades (no division
        error).
        """
        with session_scope() as db:
            rows = db.execute(select(Trade).where(Trade.mode == "paper")).scalars().all()
            total_trades = len(rows)
            closed = [row for row in rows if row.status == "closed"]
            wins = sum(1 for row in closed if (row.pnl or 0) > 0)
            total_pnl = sum(row.pnl or 0.0 for row in closed)
            win_rate = (wins / len(closed)) if closed else 0.0
            return {
                "total_trades": total_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
            }
