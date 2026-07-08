"""
Milestone 3: real DB-backed position and bot-state helpers built on top of
app.database.session/models.

PositionTracker delegates to TradeTracker so the open-position dict shape
stays identical everywhere in the codebase (single source of truth for the
open-position query lives in trades.py).
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.database.models import BotState
from app.portfolio.trades import TradeTracker, _row_to_dict, session_scope


class PositionTracker:
    """Queries currently open positions by delegating to TradeTracker."""

    def get_open_positions(self) -> list[dict]:
        """Return open positions; same dict shape as TradeTracker.get_open_positions()."""
        return TradeTracker().get_open_positions()


def get_or_create_bot_state() -> dict:
    """
    Return the first BotState row as a dict, creating a default row (seeded
    from app.config.settings) if none exists yet.

    Idempotent across calls: a second call returns the SAME row, never a
    duplicate.
    """
    with session_scope() as db:
        state = db.execute(select(BotState)).scalars().first()
        if state is None:
            state = BotState(
                mode=settings.TRADING_MODE,
                live_enabled=settings.LIVE_TRADING_ENABLED,
                daily_pnl=0.0,
                weekly_pnl=0.0,
                current_drawdown=0.0,
                trading_allowed=True,
            )
            db.add(state)
            db.flush()
        return _row_to_dict(state)
