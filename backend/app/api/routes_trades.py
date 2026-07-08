"""Trade history endpoints — list open/closed trades. No order placement here."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.portfolio.trades import TradeTracker

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/open")
def list_open_trades() -> list:
    """Return currently open trades from the trades table."""
    return TradeTracker().get_open_positions()


@router.get("/closed")
def list_closed_trades() -> list:
    """Return closed/historical trades from the trades table."""
    return TradeTracker().get_closed_trades()


@router.get("/{trade_id}")
def get_trade(trade_id: str) -> dict:
    """Return a single trade's detail by id; 404 if not found in open or closed trades."""
    tracker = TradeTracker()
    all_trades = tracker.get_open_positions() + tracker.get_closed_trades()

    for trade in all_trades:
        if str(trade.get("id")) == str(trade_id):
            return trade

    raise HTTPException(status_code=404, detail=f"Trade '{trade_id}' not found")
