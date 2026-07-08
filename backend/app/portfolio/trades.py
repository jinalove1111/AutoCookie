"""
Milestone 3: real persistence for tracking closed trades and recording new
trades, backed by app.database.session/models.

Also hosts the shared DB-session-scope contextmanager and row->dict helper
used by the sibling modules in this package (positions.py, journal.py) so
the open/commit/rollback/close pattern stays in one place.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Trade
from app.database.session import SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Open a real DB session (via app.database.session.SessionLocal), yield it,
    commit on success, roll back on error, and always close.

    Mirrors the open/try/finally shape of app.database.session.get_db(), with
    commit/rollback added on top since these are one-shot reads/writes (not a
    FastAPI request-scoped dependency where the caller controls commits).
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _row_to_dict(row: Any) -> dict:
    """Convert a SQLAlchemy ORM row into a plain, JSON-serializable dict."""
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class TradeTracker:
    """Persists and queries executed trades via the `trades` table."""

    def record_trade(self, trade_data: dict) -> int:
        """
        Insert a new Trade row from `trade_data` and return its integer id.

        `trade_data` keys map directly to Trade columns. Optional keys fall
        back to defaults: leverage=1.0, fee=0.0, slippage=0.0,
        status="open", mode="paper", opened_at=now.
        """
        with session_scope() as db:
            trade = Trade(
                symbol=trade_data["symbol"],
                direction=trade_data["direction"],
                entry_price=trade_data["entry_price"],
                stop_loss=trade_data["stop_loss"],
                take_profit=trade_data["take_profit"],
                size=trade_data["size"],
                leverage=trade_data.get("leverage", 1.0),
                fee=trade_data.get("fee", 0.0),
                slippage=trade_data.get("slippage", 0.0),
                status=trade_data.get("status", "open"),
                mode=trade_data.get("mode", "paper"),
                opened_at=trade_data.get("opened_at") or datetime.now(timezone.utc),
            )
            db.add(trade)
            db.flush()  # populate trade.id (autoincrement PK) before commit
            trade_id = trade.id
        return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        closed_at: datetime | None = None,
    ) -> None:
        """
        Mark an existing Trade as closed: sets exit_price, pnl, status, and
        closed_at (defaulting to now). Raises ValueError if trade_id does
        not exist — never silently no-ops.
        """
        with session_scope() as db:
            trade = db.get(Trade, trade_id)
            if trade is None:
                raise ValueError(f"Trade id={trade_id} not found")
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.status = "closed"
            trade.closed_at = closed_at or datetime.now(timezone.utc)

    def get_open_positions(self) -> list[dict]:
        """Return all Trade rows with status == 'open' as plain dicts."""
        with session_scope() as db:
            rows = db.execute(select(Trade).where(Trade.status == "open")).scalars().all()
            return [_row_to_dict(row) for row in rows]

    def get_closed_trades(self) -> list[dict]:
        """Return all Trade rows with status == 'closed' as plain dicts."""
        with session_scope() as db:
            rows = db.execute(select(Trade).where(Trade.status == "closed")).scalars().all()
            return [_row_to_dict(row) for row in rows]
