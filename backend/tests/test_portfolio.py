"""Tests for app.portfolio.{trades,positions,journal} against a real
(migrated, temp) SQLite database -- insert/query round-trips, not mocks.
"""

from __future__ import annotations


def test_trade_tracker_record_and_query_round_trip(migrated_db):
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.5,
            "mode": "paper",
        }
    )

    assert isinstance(trade_id, int)

    open_positions = tracker.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0]["id"] == trade_id
    assert open_positions[0]["symbol"] == "BTCUSDT"
    assert open_positions[0]["status"] == "open"
    # defaults applied
    assert open_positions[0]["leverage"] == 1.0
    assert open_positions[0]["fee"] == 0.0

    assert tracker.get_closed_trades() == []


def test_trade_tracker_close_trade_moves_between_lists(migrated_db):
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    trade_id = tracker.record_trade(
        {
            "symbol": "ETHUSDT",
            "direction": "short",
            "entry_price": 3000.0,
            "stop_loss": 3100.0,
            "take_profit": 2800.0,
            "size": 2.0,
            "mode": "paper",
        }
    )

    tracker.close_trade(trade_id, exit_price=2850.0, pnl=300.0)

    assert tracker.get_open_positions() == []
    closed = tracker.get_closed_trades()
    assert len(closed) == 1
    assert closed[0]["exit_price"] == 2850.0
    assert closed[0]["pnl"] == 300.0
    assert closed[0]["status"] == "closed"
    assert closed[0]["closed_at"] is not None


def test_trade_tracker_close_trade_raises_for_unknown_id(migrated_db):
    import pytest

    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    with pytest.raises(ValueError, match="not found"):
        tracker.close_trade(999999, exit_price=100.0, pnl=0.0)


def test_position_tracker_delegates_to_trade_tracker(migrated_db):
    from app.portfolio.positions import PositionTracker
    from app.portfolio.trades import TradeTracker

    TradeTracker().record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 50000,
            "stop_loss": 49000,
            "take_profit": 52000,
            "size": 0.1,
        }
    )

    positions = PositionTracker().get_open_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "BTCUSDT"


def test_get_or_create_bot_state_is_idempotent(migrated_db):
    from app.portfolio.positions import get_or_create_bot_state

    first = get_or_create_bot_state()
    second = get_or_create_bot_state()

    assert first["id"] == second["id"]
    assert first["mode"] == second["mode"]


def test_update_bot_mode_persists_new_mode(migrated_db):
    from app.portfolio.positions import get_or_create_bot_state, update_bot_mode

    get_or_create_bot_state()
    updated = update_bot_mode("backtest")

    assert updated["mode"] == "backtest"

    # Re-fetch confirms it actually persisted, not just returned in-memory.
    refetched = get_or_create_bot_state()
    assert refetched["mode"] == "backtest"


def test_trade_journal_log_trade_reason_and_aggregate_report(migrated_db):
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    journal = TradeJournal()

    win_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
        }
    )
    tracker.close_trade(win_id, exit_price=110, pnl=10.0)

    loss_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
        }
    )
    tracker.close_trade(loss_id, exit_price=95, pnl=-5.0)

    journal.log_trade_reason(win_id, "bullish confluence: sweep + FVG + CHOCH")

    report = journal.generate_journal_report()

    assert report["total_trades"] == 2
    assert report["win_rate"] == 0.5
    assert report["total_pnl"] == 5.0


def test_trade_journal_report_all_zero_when_no_trades(migrated_db):
    from app.portfolio.journal import TradeJournal

    report = TradeJournal().generate_journal_report()

    assert report == {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0}


def test_trade_journal_save_chart_snapshot_is_a_safe_noop(migrated_db):
    from app.portfolio.journal import TradeJournal

    # Must not raise even though there is no chart-snapshot table/column yet.
    TradeJournal().save_chart_snapshot(trade_id=1, snapshot={"any": "data"})
