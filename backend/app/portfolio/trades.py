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
        status="open", mode="paper", opened_at=now, strategy_config=None.

        `strategy_config` (optional, default `None`): a plain dict snapshot
        of which experimental flags were active when this trade was opened
        (e.g. `{"use_jade_engine": False, "enable_breakeven": False}`) --
        added so a later query over accumulated paper trades can tell which
        configuration produced which trade, since a config can change
        between one paper-trading run and the next (observability follow-up,
        2026-07-12 profitability sprint Phase E).

        `latency_ms` (optional, default `None` -- adaptive platform
        milestone 5, ENGINEERING_DECISIONS.md #47): wall-clock milliseconds
        the caller's execution step took, when supplied.

        `strategy_name` (optional, default `None` -- adaptive platform
        milestone 6, ENGINEERING_DECISIONS.md #48): which `Strategy`
        (`app.strategy.strategy_interface.AVAILABLE_STRATEGIES` key, e.g.
        "legacy"/"jade") produced this trade's signal. Needed for
        `app.portfolio.performance_snapshots` to group closed trades by
        strategy at all.
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
                strategy_config=trade_data.get("strategy_config"),
                latency_ms=trade_data.get("latency_ms"),
                strategy_name=trade_data.get("strategy_name"),
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
        exit_reason: str | None = None,
        r_multiple: float | None = None,
        holding_time_seconds: float | None = None,
    ) -> None:
        """
        Mark an existing Trade as closed: sets exit_price, pnl, status, and
        closed_at (defaulting to now). Raises ValueError if trade_id does
        not exist — never silently no-ops.

        `exit_reason`/`r_multiple` (both optional, default `None` --
        backward compatible with every existing caller): observability
        follow-up (2026-07-12 profitability sprint Phase E) so a closed
        trade's WHY (stop_loss/take_profit/breakeven/manual) and realized
        R multiple are queryable later, not just visible in that process's
        own stdout/alert at the moment of closing.

        `holding_time_seconds` (optional, default `None` -- adaptive
        platform milestone 5, ENGINEERING_DECISIONS.md #47): wall-clock
        seconds between `opened_at` and this close, when the caller
        supplies it (e.g. `scripts/run_paper.py`'s real
        `(closed_at - position["opened_at"]).total_seconds()`).
        """
        with session_scope() as db:
            trade = db.get(Trade, trade_id)
            if trade is None:
                raise ValueError(f"Trade id={trade_id} not found")
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.status = "closed"
            trade.closed_at = closed_at or datetime.now(timezone.utc)
            if exit_reason is not None:
                trade.exit_reason = exit_reason
            if r_multiple is not None:
                trade.r_multiple = r_multiple
            if holding_time_seconds is not None:
                trade.holding_time_seconds = holding_time_seconds

    def update_stop_loss(self, trade_id: int, new_stop_loss: float) -> None:
        """
        Update an OPEN trade's `stop_loss` (e.g. a break-even move --
        see `scripts/run_paper.py`'s `_maybe_move_to_breakeven`, the only
        real caller). Raises `ValueError` if `trade_id` does not exist or
        is not currently open -- moving the stop on an already-closed
        trade would silently do nothing useful and almost certainly
        indicates a caller bug, so this fails loudly rather than
        no-opping (same contract style as `close_trade`).
        """
        with session_scope() as db:
            trade = db.get(Trade, trade_id)
            if trade is None:
                raise ValueError(f"Trade id={trade_id} not found")
            if trade.status != "open":
                raise ValueError(
                    f"Trade id={trade_id} is not open (status={trade.status!r}); "
                    "cannot update stop_loss on a closed trade"
                )
            trade.stop_loss = new_stop_loss

    def update_excursion(self, trade_id: int, current_price: float) -> None:
        """
        Update an OPEN trade's `max_adverse_excursion`/`max_favorable_excursion`
        given `current_price` observed THIS pass -- adaptive platform
        milestone 5 (ENGINEERING_DECISIONS.md #47). Both are RUNNING
        MAXIMUMS in R-multiples of the trade's ORIGINAL risk distance
        (`abs(entry_price - stop_loss)`, the same convention `r_multiple`
        already uses at close) -- they only ever grow, never shrink, over
        a position's lifetime, matching the standard MAE/MFE definition
        (the worst/best unrealized excursion seen at any point while the
        trade was open).

        Best-effort, same "observability step, not a risk-relevant
        guarantee" contract as the caller's other per-pass bookkeeping:
        no-ops (does not raise) if `trade_id` is not open or has zero
        risk distance, rather than raising like `close_trade`/
        `update_stop_loss` (which failing loudly protects real capital
        actions; this is metadata).
        """
        with session_scope() as db:
            trade = db.get(Trade, trade_id)
            if trade is None or trade.status != "open":
                return
            risk_per_unit = abs(trade.entry_price - trade.stop_loss)
            if risk_per_unit <= 0:
                return

            if trade.direction == "long":
                excursion_r = (current_price - trade.entry_price) / risk_per_unit
            else:
                excursion_r = (trade.entry_price - current_price) / risk_per_unit

            if excursion_r > 0:
                if trade.max_favorable_excursion is None or excursion_r > trade.max_favorable_excursion:
                    trade.max_favorable_excursion = excursion_r
            elif excursion_r < 0:
                adverse = abs(excursion_r)
                if trade.max_adverse_excursion is None or adverse > trade.max_adverse_excursion:
                    trade.max_adverse_excursion = adverse

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

    def count_trades_opened_today(self) -> int:
        """Count open + closed trades whose `opened_at` falls on today's
        UTC date -- used by `RiskManager.evaluate()`'s `trades_today`
        (MAX_TRADES_PER_DAY) check and by `/dashboard/risk-status`, so both
        share one real, DB-backed count instead of each computing (or
        hardcoding) their own.
        """
        today = datetime.now(timezone.utc).date()
        rows = self.get_open_positions() + self.get_closed_trades()
        return sum(
            1
            for row in rows
            if row.get("opened_at") is not None and row["opened_at"].date() == today
        )
