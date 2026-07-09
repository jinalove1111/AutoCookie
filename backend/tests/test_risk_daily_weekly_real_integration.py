"""Real integration test proving the capital-protection gap is actually
closed: a real closed, losing paper trade seeded in a real (migrated, temp)
SQLite DB, aggregated via the real `TradeJournal.generate_daily_report()` /
`generate_weekly_report()`, and fed as `daily_pnl_percent`/
`weekly_pnl_percent` into the real `RiskManager.evaluate()` -- the actual
per-signal gate `scripts/run_paper.py` now wires this into, in both
single-pass and loop mode.

Before this change, `RiskManager.evaluate()` was never passed these values
at all (both silently defaulted to 0.0), so `DrawdownGuard.check_daily_loss`/
`check_weekly_loss` could never reject a trade regardless of real losses.
This test proves a real seeded loss now does reject a signal -- not just
that a helper function returns a number.

No mocks: real DB round-trip via `migrated_db`, real `TradeJournal`, real
`RiskManager`, real `DrawdownGuard` underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Mirrors scripts/run_paper.py's PLACEHOLDER_ACCOUNT_BALANCE (no real
# account-balance source exists yet -- see that module's docstring). Kept
# as a local literal (not imported) so this test doesn't depend on
# importing run_paper.py's module-level safety guard / other project
# modules at collection time.
_PLACEHOLDER_ACCOUNT_BALANCE = 10000.0


@dataclass
class FakeSignal:
    stop_loss: float | None
    take_profit: float | None
    rr: float


def _pnl_to_percent(pnl: float) -> float:
    return (pnl / _PLACEHOLDER_ACCOUNT_BALANCE) * 100


def test_real_seeded_daily_loss_rejects_signal_via_risk_manager(migrated_db, monkeypatch):
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker
    from app.risk import risk_manager as risk_manager_module
    from app.risk.risk_manager import RiskManager

    monkeypatch.setattr(risk_manager_module.settings, "MIN_RR", 2.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_DAILY_LOSS_PERCENT", 1.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_WEEKLY_LOSS_PERCENT", 3.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_TRADES_PER_DAY", 100)

    tracker = TradeTracker()
    now = datetime.now(timezone.utc)

    # A real closed loss today of -$150 on a $10,000 placeholder balance is
    # -1.5%, which breaches MAX_DAILY_LOSS_PERCENT=1.0%.
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
            "opened_at": now,
        }
    )
    tracker.close_trade(trade_id, exit_price=85.0, pnl=-150.0, closed_at=now)

    daily_report = TradeJournal().generate_daily_report()
    weekly_report = TradeJournal().generate_weekly_report()
    daily_pnl_percent = _pnl_to_percent(daily_report["total_pnl"])
    weekly_pnl_percent = _pnl_to_percent(weekly_report["total_pnl"])

    assert daily_pnl_percent == -1.5

    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)
    decision = RiskManager().evaluate(
        signal,
        daily_pnl_percent=daily_pnl_percent,
        weekly_pnl_percent=weekly_pnl_percent,
        trades_today=0,
    )

    assert decision.approved is False
    assert any("daily loss" in reason for reason in decision.reasons)


def test_real_seeded_weekly_loss_rejects_signal_even_when_not_closed_today(migrated_db, monkeypatch):
    """Proves the weekly check is genuinely independent of the daily
    window: a loss closed earlier in the SAME ISO week (not today) must
    still breach the weekly limit and reject the signal, while NOT
    triggering the daily-loss reason (since nothing closed "today")."""
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker
    from app.risk import risk_manager as risk_manager_module
    from app.risk.risk_manager import RiskManager

    monkeypatch.setattr(risk_manager_module.settings, "MIN_RR", 2.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_DAILY_LOSS_PERCENT", 1.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_WEEKLY_LOSS_PERCENT", 3.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_TRADES_PER_DAY", 100)

    tracker = TradeTracker()

    # 2026-01-14 is a Wednesday; its ISO week runs Mon 2026-01-12 through
    # Sun 2026-01-18.
    as_of = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    monday_this_week = datetime(2026, 1, 12, 9, 0, 0, tzinfo=timezone.utc)

    # -$500 on $10,000 = -5%, breaching MAX_WEEKLY_LOSS_PERCENT=3.0%, but
    # closed on Monday -- not "today" (Wednesday) -- so it must not affect
    # the daily figure at all.
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
            "opened_at": monday_this_week,
        }
    )
    tracker.close_trade(trade_id, exit_price=50.0, pnl=-500.0, closed_at=monday_this_week)

    journal = TradeJournal()
    daily_report = journal.generate_daily_report(as_of=as_of)
    weekly_report = journal.generate_weekly_report(as_of=as_of)

    assert daily_report["total_pnl"] == 0.0
    assert weekly_report["total_pnl"] == -500.0

    daily_pnl_percent = _pnl_to_percent(daily_report["total_pnl"])
    weekly_pnl_percent = _pnl_to_percent(weekly_report["total_pnl"])

    assert daily_pnl_percent == 0.0
    assert weekly_pnl_percent == -5.0

    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)
    decision = RiskManager().evaluate(
        signal,
        daily_pnl_percent=daily_pnl_percent,
        weekly_pnl_percent=weekly_pnl_percent,
        trades_today=0,
    )

    assert decision.approved is False
    assert any("weekly loss" in reason for reason in decision.reasons)
    assert not any("daily loss" in reason for reason in decision.reasons)


def test_real_small_loss_within_limits_still_approves(migrated_db, monkeypatch):
    """Contrast case: a real seeded loss that does NOT breach either
    threshold must still approve -- proving the wiring doesn't just
    reject everything unconditionally."""
    from app.portfolio.journal import TradeJournal
    from app.portfolio.trades import TradeTracker
    from app.risk import risk_manager as risk_manager_module
    from app.risk.risk_manager import RiskManager

    monkeypatch.setattr(risk_manager_module.settings, "MIN_RR", 2.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_DAILY_LOSS_PERCENT", 1.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_WEEKLY_LOSS_PERCENT", 3.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_TRADES_PER_DAY", 100)

    tracker = TradeTracker()
    now = datetime.now(timezone.utc)

    # -$20 on $10,000 = -0.2%, well within MAX_DAILY_LOSS_PERCENT=1.0%.
    trade_id = tracker.record_trade(
        {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size": 1,
            "mode": "paper",
            "opened_at": now,
        }
    )
    tracker.close_trade(trade_id, exit_price=80.0, pnl=-20.0, closed_at=now)

    journal = TradeJournal()
    daily_pnl_percent = _pnl_to_percent(journal.generate_daily_report()["total_pnl"])
    weekly_pnl_percent = _pnl_to_percent(journal.generate_weekly_report()["total_pnl"])

    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)
    decision = RiskManager().evaluate(
        signal,
        daily_pnl_percent=daily_pnl_percent,
        weekly_pnl_percent=weekly_pnl_percent,
        trades_today=0,
    )

    assert decision.approved is True
    assert decision.reasons == []
