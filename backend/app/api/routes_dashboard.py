"""Dashboard endpoints — aggregate bot status/bias/signals/risk for the UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import StrategyLog
from app.database.session import get_db
from app.portfolio.positions import get_or_create_bot_state
from app.portfolio.trades import TradeTracker

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/status")
def get_bot_status() -> dict:
    """Return overall bot run state, sourced from the persisted bot_state row."""
    return get_or_create_bot_state()


@router.get("/bias")
def get_market_bias() -> dict:
    """Return current HTF/LTF market bias.

    Not yet wired to live strategy state: the strategy engine is a stateless
    set of functions this milestone and has no persisted bias output to read.
    """
    return {
        "symbol": "BTCUSDT",
        "htf_bias": "neutral",
        "ltf_bias": "neutral",
        "note": "not yet wired to live strategy state",
    }


@router.get("/signals")
def get_recent_signals() -> dict:
    """Return recent generated signals.

    Not yet wired to live strategy state: signal generation is not persisted
    to the signals table by any running process this milestone.
    """
    return {"signals": [], "note": "not yet wired to live strategy state"}


@router.get("/positions")
def get_open_positions() -> list:
    """Return currently open positions from the trades table."""
    return TradeTracker().get_open_positions()


@router.get("/risk-status")
def get_risk_status() -> dict:
    """Return current risk budget usage.

    Not yet wired to live strategy state: the risk engine is a stateless set
    of functions this milestone and has no persisted risk-budget output to read.
    """
    return {
        "daily_loss_used_percent": 0,
        "weekly_loss_used_percent": 0,
        "trades_today": 0,
        "note": "not yet wired to live strategy state",
    }


@router.get("/logs")
def get_recent_logs(db: Session = Depends(get_db)) -> list:
    """Return the last ~20 strategy_logs rows, most recent first."""
    rows = db.execute(
        select(StrategyLog).order_by(StrategyLog.timestamp.desc()).limit(20)
    ).scalars().all()

    return [
        {
            "id": row.id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "module": row.module,
            "decision": row.decision,
            "reason": row.reason,
            "candle_context": row.candle_context,
            "signal_id": row.signal_id,
        }
        for row in rows
    ]
