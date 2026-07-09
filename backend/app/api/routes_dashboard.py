"""Dashboard endpoints — aggregate bot status/bias/signals/risk for the UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.data.candle_fetcher import CandleFetcher
from app.database.models import StrategyLog
from app.database.session import get_db
from app.portfolio.journal import TradeJournal
from app.portfolio.positions import get_or_create_bot_state
from app.portfolio.signals import SignalTracker
from app.portfolio.trades import TradeTracker
from app.strategy.bias import detect_htf_bias

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/status")
def get_bot_status() -> dict:
    """Return overall bot run state, sourced from the persisted bot_state row."""
    return get_or_create_bot_state()


@router.get("/bias")
def get_market_bias() -> dict:
    """Return current HTF/LTF market bias, computed live from real OKX
    candles via `detect_htf_bias()` (`app.strategy.bias`) -- read-only, no
    API key needed, the same live-fetch pattern `scripts/run_paper.py`/
    `run_backtest.py` already use.

    `ltf_bias` judgment call (documented, not silently invented): the real
    strategy design (`docs/strategy_spec.md`, `signal_engine.py`) only
    ever calls `detect_htf_bias()` on HTF candles -- there is no distinct
    "LTF bias" concept anywhere in the actual strategy (LTF candles feed
    sweep/CHoCH/FVG/order-block detectors instead). This field predates
    that design (an early API-contract field). Kept here for contract
    stability by reusing the SAME real, generic structural-bias algorithm
    on the LTF candle series -- a genuine "recent LTF swing-structure
    bias" reading, not fabricated data, but a distinct concept from the
    strategy's real HTF bias gate. Flagged in HANDOFF.md as worth an
    explicit design confirmation if this field's meaning matters
    downstream.

    Best-effort: a live fetch failure (network/exchange error) does not
    500 the dashboard -- returns "neutral"/"neutral" with a note
    describing the failure, mirroring `run_paper.py`'s established
    best-effort pattern for non-critical live data.
    """
    try:
        htf_candles = CandleFetcher().fetch_ohlcv(
            settings.SYMBOL, settings.HTF_TIMEFRAME, limit=300
        )
        ltf_candles = CandleFetcher().fetch_ohlcv(
            settings.SYMBOL, settings.DEFAULT_TIMEFRAME, limit=300
        )
    except Exception as exc:
        return {
            "symbol": settings.SYMBOL,
            "htf_bias": "neutral",
            "ltf_bias": "neutral",
            "note": f"live candle fetch failed: {exc}",
        }

    return {
        "symbol": settings.SYMBOL,
        "htf_bias": detect_htf_bias(htf_candles),
        "ltf_bias": detect_htf_bias(ltf_candles),
        "note": "",
    }


@router.get("/signals")
def get_recent_signals() -> dict:
    """Return the ~20 most recently generated signals (newest first),
    real and DB-backed via `SignalTracker` -- `scripts/run_paper.py` now
    persists every genuinely generated `TradeSignal` as soon as it's
    produced (status "pending"), then updates that status to "rejected"/
    "approved"/"executed" as it moves through Risk Engine approval and
    Execution, so `status` here reflects each signal's real outcome, not
    just that it was generated.
    """
    return {"signals": SignalTracker().get_recent_signals(limit=20), "note": ""}


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
