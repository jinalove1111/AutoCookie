"""Dashboard endpoints — aggregate bot status/bias/signals/risk for the UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import StrategyLog
from app.database.session import get_db
from app.portfolio.journal import TradeJournal
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
    """Return current risk budget usage, computed from real closed paper
    trades via `TradeJournal`'s UTC-day/ISO-week windowed reports -- the
    same real daily/weekly PnL% `RiskManager.evaluate()` and the loop-mode
    circuit breaker already use (see docs/risk_rules.md). Percent
    conversion uses `settings.PLACEHOLDER_ACCOUNT_BALANCE`, the same fixed
    base `scripts/run_paper.py`'s `_pnl_to_percent()` uses, so this figure
    stays comparable to what actually drove any loss-limit reject.

    "Loss used" is the magnitude of a NEGATIVE daily/weekly PnL% (0 if
    today/this week is net-positive so far -- a profit means none of the
    loss budget has been consumed; this endpoint reports usage, not raw
    PnL, so it never goes negative).
    """
    daily_report = TradeJournal().generate_daily_report()
    weekly_report = TradeJournal().generate_weekly_report()

    daily_pnl_percent = (daily_report["total_pnl"] / settings.PLACEHOLDER_ACCOUNT_BALANCE) * 100
    weekly_pnl_percent = (weekly_report["total_pnl"] / settings.PLACEHOLDER_ACCOUNT_BALANCE) * 100

    return {
        "daily_loss_used_percent": max(0.0, -daily_pnl_percent),
        "weekly_loss_used_percent": max(0.0, -weekly_pnl_percent),
        "trades_today": TradeTracker().count_trades_opened_today(),
        "note": "",
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
