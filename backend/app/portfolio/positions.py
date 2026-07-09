"""
Milestone 3: real DB-backed position and bot-state helpers built on top of
app.database.session/models.

PositionTracker delegates to TradeTracker so the open-position dict shape
stays identical everywhere in the codebase (single source of truth for the
open-position query lives in trades.py).

Milestone 4 (capital-protection follow-up): DB-backed load/save helpers for
CircuitBreaker state (`load_circuit_breaker_state()` /
`save_circuit_breaker_state()`), following the same
get_or_create_bot_state()/update_bot_mode() pattern -- singleton
`bot_state` row, read/write via `session_scope()`. These are intentionally
plain functions operating on the DB row directly (not a CircuitBreaker
method) so `app.risk.circuit_breaker.CircuitBreaker` stays DB-decoupled and
usable standalone in unit tests, matching the execution/portfolio Iron Wall
decoupling pattern noted in HANDOFF.md.
"""

from __future__ import annotations

from datetime import datetime

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


def update_bot_mode(mode: str) -> dict:
    """
    Persist a new trading mode onto the singleton BotState row and return the
    updated row as a dict.

    Ensures a BotState row exists first (via get_or_create_bot_state(), which
    is idempotent), then opens a fresh session to update its `mode` column.
    Does not touch `live_enabled` or any other column — callers that need to
    gate/allow live trading enforce that separately before ever calling this.
    """
    get_or_create_bot_state()
    with session_scope() as db:
        state = db.execute(select(BotState)).scalars().first()
        state.mode = mode
        db.flush()
        return _row_to_dict(state)


def load_circuit_breaker_state() -> dict:
    """
    Return the persisted circuit-breaker fields off the singleton BotState
    row, as a plain dict: {"tripped": bool, "reason": str | None,
    "tripped_at": datetime | None}.

    Ensures a BotState row exists first (via get_or_create_bot_state(),
    which is idempotent) so this is always safe to call on a fresh DB (e.g.
    right after a process restart, before any trip/reset has ever
    happened) -- it returns the untripped defaults rather than raising.
    """
    get_or_create_bot_state()
    with session_scope() as db:
        state = db.execute(select(BotState)).scalars().first()
        return {
            "tripped": state.circuit_breaker_tripped,
            "reason": state.circuit_breaker_reason,
            "tripped_at": state.circuit_breaker_tripped_at,
        }


def save_circuit_breaker_state(
    tripped: bool,
    reason: str | None,
    tripped_at: datetime | None,
) -> dict:
    """
    Persist circuit-breaker fields onto the singleton BotState row and
    return the updated row as a dict.

    Ensures a BotState row exists first (via get_or_create_bot_state(),
    which is idempotent), then opens a fresh session to update the three
    circuit_breaker_* columns. Mirrors update_bot_mode()'s
    ensure-then-update shape. Called synchronously on every
    CircuitBreaker.trip()/.reset() (via the wrapper in
    app.risk.circuit_breaker) so a process restart can never silently lose
    a real trip.
    """
    get_or_create_bot_state()
    with session_scope() as db:
        state = db.execute(select(BotState)).scalars().first()
        state.circuit_breaker_tripped = tripped
        state.circuit_breaker_reason = reason
        state.circuit_breaker_tripped_at = tripped_at
        db.flush()
        return _row_to_dict(state)
