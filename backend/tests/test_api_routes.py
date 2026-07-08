"""API route tests via FastAPI TestClient against a fresh, real
(Alembic-migrated) temp SQLite DB. `/settings/mode` sequence
(backtest 200+persist, live 403+DB-unchanged, invalid 400, paper 200)
mirrors exactly what the prior manual audit verified by hand -- pinned
here as a regression test.
"""

from __future__ import annotations


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


def test_dashboard_bias_and_signals_and_risk_status_placeholders(client):
    bias = client.get("/dashboard/bias")
    assert bias.status_code == 200
    assert "note" in bias.json()

    signals = client.get("/dashboard/signals")
    assert signals.status_code == 200
    assert signals.json()["signals"] == []

    risk_status = client.get("/dashboard/risk-status")
    assert risk_status.status_code == 200
    assert "note" in risk_status.json()


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
