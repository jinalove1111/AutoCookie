"""API route tests via FastAPI TestClient against a fresh, real
(Alembic-migrated) temp SQLite DB. `/settings/mode` sequence
(backtest 200+persist, live 403+DB-unchanged, invalid 400, paper 200)
mirrors exactly what the prior manual audit verified by hand -- pinned
here as a regression test.
"""

from __future__ import annotations

import pytest


def test_dashboard_status_returns_default_bot_state(client):
    response = client.get("/dashboard/status")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "paper"  # Settings.TRADING_MODE default
    assert body["trading_allowed"] is True


def test_dashboard_positions_empty_on_fresh_db(client):
    response = client.get("/dashboard/positions")

    assert response.status_code == 200
    assert response.json() == []


def test_dashboard_logs_empty_on_fresh_db(client):
    response = client.get("/dashboard/logs")

    assert response.status_code == 200
    assert response.json() == []


def test_dashboard_bias_and_signals_still_placeholders(client):
    """Unlike /dashboard/risk-status (see below, now real -- wired in the
    same round of Dashboard work), /bias and /signals remain intentional
    placeholders: bias has no persisted live-strategy output to read, and
    no running process persists generated signals to the signals table yet.
    """
    bias = client.get("/dashboard/bias")
    assert bias.status_code == 200
    assert "note" in bias.json()

    signals = client.get("/dashboard/signals")
    assert signals.status_code == 200
    assert signals.json()["signals"] == []


def test_dashboard_risk_status_zero_on_fresh_db(client):
    """No trades at all yet -- both loss-used percentages and trades_today
    must be a real, computed 0 (not a hardcoded placeholder 0 -- see the
    seeded-loss test below for the case that actually distinguishes the
    two).
    """
    response = client.get("/dashboard/risk-status")

    assert response.status_code == 200
    body = response.json()
    assert body["daily_loss_used_percent"] == 0.0
    assert body["weekly_loss_used_percent"] == 0.0
    assert body["trades_today"] == 0
    assert body["note"] == ""


def test_dashboard_risk_status_reflects_real_seeded_loss(client):
    """A real closed, losing paper trade seeded via TradeTracker (same
    pattern as test_risk_daily_weekly_real_integration.py) must show up as
    real daily/weekly loss-used percent -- not the old hardcoded 0 -- and
    trades_today must reflect it too. Also proves a net-positive day
    reports 0% loss used (not a negative number) via the second trade.
    """
    from datetime import datetime, timezone

    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    now = datetime.now(timezone.utc)

    # -$150 on the $10,000 PLACEHOLDER_ACCOUNT_BALANCE = -1.5%.
    losing_id = tracker.record_trade(
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
    tracker.close_trade(losing_id, exit_price=85.0, pnl=-150.0, closed_at=now)

    response = client.get("/dashboard/risk-status")
    assert response.status_code == 200
    body = response.json()
    assert body["daily_loss_used_percent"] == pytest.approx(1.5)
    assert body["weekly_loss_used_percent"] == pytest.approx(1.5)
    assert body["trades_today"] == 1

    # A second, WINNING trade the same day -- net PnL today is now
    # -150 + 300 = +150 (net positive) -- must report 0% loss used, not a
    # negative percentage.
    winning_id = tracker.record_trade(
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
    tracker.close_trade(winning_id, exit_price=130.0, pnl=300.0, closed_at=now)

    response = client.get("/dashboard/risk-status")
    body = response.json()
    assert body["daily_loss_used_percent"] == 0.0
    assert body["weekly_loss_used_percent"] == 0.0
    assert body["trades_today"] == 2


def test_trades_open_and_closed_empty_on_fresh_db(client):
    assert client.get("/trades/open").json() == []
    assert client.get("/trades/closed").json() == []


def test_trades_get_by_id_404_when_not_found(client):
    response = client.get("/trades/999999")
    assert response.status_code == 404


def test_settings_mode_full_sequence_pinned_regression(client):
    """Exact sequence manually verified by the prior audit:
    backtest -> 200 + persisted, live -> 403 + DB unchanged,
    invalid -> 400, paper -> 200 + persisted.
    """
    # 1. backtest: 200, persists to DB.
    response = client.post("/settings/mode", json={"trading_mode": "backtest"})
    assert response.status_code == 200
    assert response.json() == {"trading_mode": "backtest", "applied": True}

    status = client.get("/dashboard/status").json()
    assert status["mode"] == "backtest"

    # 2. live: 403, DB unchanged (still backtest).
    response = client.post("/settings/mode", json={"trading_mode": "live"})
    assert response.status_code == 403
    assert "Live trading is not allowed" in response.json()["detail"]

    status = client.get("/dashboard/status").json()
    assert status["mode"] == "backtest"  # unchanged by the rejected request

    # 3. invalid value: 400.
    response = client.post("/settings/mode", json={"trading_mode": "nonsense"})
    assert response.status_code == 400
    assert "trading_mode must be one of" in response.json()["detail"]

    status = client.get("/dashboard/status").json()
    assert status["mode"] == "backtest"  # still unchanged

    # 4. paper: 200, persists to DB.
    response = client.post("/settings/mode", json={"trading_mode": "paper"})
    assert response.status_code == 200
    assert response.json() == {"trading_mode": "paper", "applied": True}

    status = client.get("/dashboard/status").json()
    assert status["mode"] == "paper"


def test_settings_get_mode_reflects_persisted_state(client):
    client.post("/settings/mode", json={"trading_mode": "backtest"})

    response = client.get("/settings/mode")

    assert response.status_code == 200
    body = response.json()
    assert body["trading_mode"] == "backtest"
    assert body["live_trading_enabled"] is False
    assert body["is_live_trading_allowed"] is False


def test_health_and_readiness_endpoints(client):
    health = client.get("/health/")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_root_endpoint_reports_trading_mode(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "jadecap-bot"
    assert "trading_mode" in body
