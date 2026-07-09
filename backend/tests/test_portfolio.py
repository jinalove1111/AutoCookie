"""Tests for app.portfolio.{trades,positions,journal} against a real
(migrated, temp) SQLite database -- insert/query round-trips, not mocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


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


def test_trade_tracker_count_trades_opened_today_counts_open_and_closed(migrated_db):
    """Moved here (was a private `_count_trades_opened_today` helper in
    scripts/run_paper.py) so /dashboard/risk-status can share the same
    real, DB-backed count RiskManager's MAX_TRADES_PER_DAY check uses,
    rather than each computing (or hardcoding) its own.
    """
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    # Opened today, still open -- counts.
    tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "size": 1.0,
            "mode": "paper",
            "opened_at": now,
        }
    )
    # Opened today, now closed -- still counts (opened_at, not status, is
    # what matters for "how many trades did we open today").
    closed_today_id = tracker.record_trade(
        {
            "symbol": "ETHUSDT",
            "direction": "short",
            "entry_price": 3000.0,
            "stop_loss": 3100.0,
            "take_profit": 2800.0,
            "size": 1.0,
            "mode": "paper",
            "opened_at": now,
        }
    )
    tracker.close_trade(closed_today_id, exit_price=2900.0, pnl=100.0, closed_at=now)
    # Opened yesterday -- must NOT count toward today's total.
    tracker.record_trade(
        {
            "symbol": "SOLUSDT",
            "direction": "long",
            "entry_price": 50.0,
            "stop_loss": 48.0,
            "take_profit": 55.0,
            "size": 1.0,
            "mode": "paper",
            "opened_at": yesterday,
        }
    )

    assert tracker.count_trades_opened_today() == 2


def test_trade_tracker_close_trade_raises_for_unknown_id(migrated_db):
    import pytest

    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    with pytest.raises(ValueError, match="not found"):
        tracker.close_trade(999999, exit_price=100.0, pnl=0.0)


class _FakeTradeSignal:
    """Duck-typed stand-in for app.strategy.signal_engine.TradeSignal --
    SignalTracker.record_signal() only reads attributes, matching the real
    dataclass's field names exactly (see that class's own docstring: "matches
    the signals DB table").
    """

    def __init__(self, ts, status="pending", direction="long", rr=2.5):
        self.symbol = "BTCUSDT"
        self.direction = direction
        self.timestamp = ts
        self.htf_bias = "bullish"
        self.sweep_type = "sell_side"
        self.choch_detected = True
        self.fvg_zone = {"top": 101.0, "bottom": 100.0}
        self.entry_price = 100.0
        self.stop_loss = 95.0
        self.take_profit = 110.0
        self.rr = rr
        self.status = status


def test_signal_tracker_record_and_query_round_trip(migrated_db):
    from app.portfolio.signals import SignalTracker

    now = datetime.now(timezone.utc)
    signal_id = SignalTracker().record_signal(_FakeTradeSignal(ts=now))

    assert isinstance(signal_id, int)

    recent = SignalTracker().get_recent_signals()
    assert len(recent) == 1
    assert recent[0]["id"] == signal_id
    assert recent[0]["symbol"] == "BTCUSDT"
    assert recent[0]["status"] == "pending"
    assert recent[0]["rr"] == 2.5
    assert recent[0]["fvg_zone"] == {"top": 101.0, "bottom": 100.0}


def test_signal_tracker_update_status_transitions(migrated_db):
    from app.portfolio.signals import SignalTracker

    tracker = SignalTracker()
    signal_id = tracker.record_signal(_FakeTradeSignal(ts=datetime.now(timezone.utc)))

    tracker.update_signal_status(signal_id, "approved")
    assert tracker.get_recent_signals()[0]["status"] == "approved"

    tracker.update_signal_status(signal_id, "executed")
    assert tracker.get_recent_signals()[0]["status"] == "executed"


def test_signal_tracker_update_status_raises_for_unknown_id(migrated_db):
    import pytest

    from app.portfolio.signals import SignalTracker

    with pytest.raises(ValueError, match="not found"):
        SignalTracker().update_signal_status(999999, "rejected")


def test_signal_tracker_get_recent_signals_newest_first_and_limited(migrated_db):
    from app.portfolio.signals import SignalTracker

    tracker = SignalTracker()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        tracker.record_signal(_FakeTradeSignal(ts=base + timedelta(minutes=i)))

    recent = tracker.get_recent_signals(limit=3)
    assert len(recent) == 3
    # Newest (highest offset) timestamp first.
    assert recent[0]["timestamp"] > recent[1]["timestamp"] > recent[2]["timestamp"]


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


def _seed_closed_trade(tracker, *, pnl: float, opened_at: datetime, closed_at: datetime) -> int:
    """Helper: record + immediately close a paper trade with explicit
    opened_at/closed_at timestamps, for date-boundary tests below."""
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
            "opened_at": opened_at,
        }
    )
    tracker.close_trade(trade_id, exit_price=100 + pnl, pnl=pnl, closed_at=closed_at)
    return trade_id


def test_generate_journal_report_date_scoped_requires_both_or_neither_bound(migrated_db):
    import pytest

    from app.portfolio.journal import TradeJournal

    journal = TradeJournal()
    now = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="together"):
        journal.generate_journal_report(start=now)
    with pytest.raises(ValueError, match="together"):
        journal.generate_journal_report(end=now)


def test_generate_journal_report_date_scoped_rejects_naive_datetimes(migrated_db):
    import pytest

    from app.portfolio.journal import TradeJournal

    journal = TradeJournal()
    naive = datetime(2026, 1, 1)

    with pytest.raises(ValueError, match="timezone-aware"):
        journal.generate_journal_report(start=naive, end=naive)


def test_generate_daily_report_excludes_other_days_and_open_trades(migrated_db):
    """Proves the UTC-calendar-day boundary: a loss from 8 days ago and a
    loss closed "tomorrow" must NOT count toward "today", and an open
    (never-closed) trade must not count at all -- only the trade closed
    inside today's UTC window counts.
    """
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    journal = TradeJournal()

    as_of = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    today_start = datetime(2026, 1, 14, 0, 0, 0, 0, tzinfo=timezone.utc)
    today_end = datetime(2026, 1, 14, 23, 59, 59, 999999, tzinfo=timezone.utc)
    yesterday_end = datetime(2026, 1, 13, 23, 59, 59, 999999, tzinfo=timezone.utc)
    tomorrow_start = datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    eight_days_ago = as_of - timedelta(days=8)

    # In-window: exactly at the start and end instants of today's UTC day.
    _seed_closed_trade(tracker, pnl=-10.0, opened_at=today_start, closed_at=today_start)
    _seed_closed_trade(tracker, pnl=-5.0, opened_at=today_start, closed_at=today_end)
    # Out-of-window: 1 microsecond before today, 1 second into tomorrow,
    # and 8 days in the past -- all with large losses, so a boundary bug
    # would be impossible to miss in the assertion below.
    _seed_closed_trade(tracker, pnl=-1000.0, opened_at=yesterday_end, closed_at=yesterday_end)
    _seed_closed_trade(tracker, pnl=-1000.0, opened_at=tomorrow_start, closed_at=tomorrow_start)
    _seed_closed_trade(tracker, pnl=-1000.0, opened_at=eight_days_ago, closed_at=eight_days_ago)
    # Never closed -- must not count toward a realized-PnL window at all.
    tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
            "opened_at": today_start,
        }
    )

    report = journal.generate_daily_report(as_of=as_of)

    assert report["total_trades"] == 2
    assert report["total_pnl"] == -15.0

    # All-time default report (no args) is unaffected -- still all-time.
    all_time = journal.generate_journal_report()
    assert all_time["total_trades"] == 6  # 5 closed + 1 open


def test_generate_weekly_report_respects_iso_week_boundary(migrated_db):
    """Proves the ISO-calendar-week boundary (Monday 00:00:00 UTC through
    Sunday 23:59:59.999999 UTC): a loss closed 1 microsecond before this
    week's Monday, and one closed exactly at next Monday 00:00:00, must
    NOT count -- only trades closed inside [this Monday, this Sunday] do.
    """
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    journal = TradeJournal()

    # 2026-01-14 is a Wednesday; its ISO week runs Mon 2026-01-12 through
    # Sun 2026-01-18 (verified independently, not derived from the
    # production formula under test).
    as_of = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    week_start = datetime(2026, 1, 12, 0, 0, 0, 0, tzinfo=timezone.utc)
    week_end = datetime(2026, 1, 18, 23, 59, 59, 999999, tzinfo=timezone.utc)
    prev_week_end = datetime(2026, 1, 11, 23, 59, 59, 999999, tzinfo=timezone.utc)
    next_week_start = datetime(2026, 1, 19, 0, 0, 0, tzinfo=timezone.utc)

    _seed_closed_trade(tracker, pnl=-30.0, opened_at=week_start, closed_at=week_start)
    _seed_closed_trade(tracker, pnl=-20.0, opened_at=week_start, closed_at=week_end)
    _seed_closed_trade(tracker, pnl=-1000.0, opened_at=prev_week_end, closed_at=prev_week_end)
    _seed_closed_trade(tracker, pnl=-1000.0, opened_at=next_week_start, closed_at=next_week_start)

    report = journal.generate_weekly_report(as_of=as_of)

    assert report["total_trades"] == 2
    assert report["total_pnl"] == -50.0


def test_generate_daily_report_all_zero_when_nothing_closed_today(migrated_db):
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    journal = TradeJournal()

    as_of = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    eight_days_ago = as_of - timedelta(days=8)
    _seed_closed_trade(tracker, pnl=-500.0, opened_at=eight_days_ago, closed_at=eight_days_ago)

    report = journal.generate_daily_report(as_of=as_of)

    assert report == {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0}
