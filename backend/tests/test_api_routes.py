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


def test_dashboard_signals_empty_on_fresh_db(client):
    response = client.get("/dashboard/signals")
    assert response.status_code == 200
    body = response.json()
    assert body["signals"] == []
    assert body["note"] == ""


def test_dashboard_signals_reflects_real_seeded_signal_and_status(client):
    """A real signal seeded via SignalTracker (mirroring what
    scripts/run_paper.py now does on every real pass) must show up through
    the live endpoint, newest first, with its real status -- not the old
    hardcoded empty placeholder.
    """
    from datetime import datetime, timezone

    from app.portfolio.signals import SignalTracker

    class _FakeTradeSignal:
        def __init__(self, symbol, direction, rr, ts):
            self.symbol = symbol
            self.direction = direction
            self.timestamp = ts
            self.htf_bias = "bullish"
            self.sweep_type = "sell_side"
            self.choch_detected = True
            self.fvg_zone = None
            self.entry_price = 100.0
            self.stop_loss = 95.0
            self.take_profit = 110.0
            self.rr = rr
            self.status = "pending"

    now = datetime.now(timezone.utc)
    tracker = SignalTracker()
    signal_id = tracker.record_signal(
        _FakeTradeSignal(symbol="BTCUSDT", direction="long", rr=3.0, ts=now)
    )
    tracker.update_signal_status(signal_id, "executed")

    response = client.get("/dashboard/signals")
    assert response.status_code == 200
    body = response.json()
    assert len(body["signals"]) == 1
    assert body["signals"][0]["id"] == signal_id
    assert body["signals"][0]["symbol"] == "BTCUSDT"
    assert body["signals"][0]["status"] == "executed"
    assert body["note"] == ""


def _bias_candle(high: float, low: float, ts) -> dict:
    from datetime import datetime, timedelta, timezone

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mid = (high + low) / 2
    return {
        "open": mid,
        "high": high,
        "low": low,
        "close": mid,
        "timestamp": base + timedelta(minutes=ts),
    }


# Same shapes test_strategy_bias.py uses directly against detect_htf_bias --
# reused here as fixtures fed through the live HTTP endpoint instead.
_BULLISH_HIGHS = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
_BULLISH_LOWS = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
_BEARISH_HIGHS = [10, 11, 30, 11, 9, 11, 25, 11, 9, 11, 20, 11, 9]
_BEARISH_LOWS = [8, 9, 15, 9, 6, 9, 18, 9, 3, 9, 22, 11, 12]


def _bullish_candles() -> list:
    return [_bias_candle(h, l, i) for i, (h, l) in enumerate(zip(_BULLISH_HIGHS, _BULLISH_LOWS))]


def _bearish_candles() -> list:
    return [_bias_candle(h, l, i) for i, (h, l) in enumerate(zip(_BEARISH_HIGHS, _BEARISH_LOWS))]


class _FakeCandleFetcherDistinctByTimeframe:
    """Returns a DIFFERENT real candle series depending on which timeframe
    is requested -- proves htf_bias/ltf_bias are each computed from their
    OWN independently-fetched series (not the same series reused for
    both), mirroring the real HTF/LTF-separation regression proof used
    elsewhere in this suite (test_strategy_signal_engine.py).
    """

    def __init__(self, htf_timeframe: str, htf_candles: list, ltf_candles: list):
        self._htf_timeframe = htf_timeframe
        self._htf_candles = htf_candles
        self._ltf_candles = ltf_candles

    def fetch_ohlcv(self, symbol, timeframe, limit=300):
        return self._htf_candles if timeframe == self._htf_timeframe else self._ltf_candles


class _FakeCandleFetcherAlwaysFails:
    def fetch_ohlcv(self, symbol, timeframe, limit=300):
        raise ConnectionError("simulated OKX outage")


def test_dashboard_bias_computes_real_htf_and_ltf_bias_independently(client, monkeypatch):
    import app.api.routes_dashboard as routes_dashboard

    fake = _FakeCandleFetcherDistinctByTimeframe(
        htf_timeframe=routes_dashboard.settings.HTF_TIMEFRAME,
        htf_candles=_bullish_candles(),
        ltf_candles=_bearish_candles(),
    )
    monkeypatch.setattr(routes_dashboard, "CandleFetcher", lambda: fake)

    response = client.get("/dashboard/bias")
    assert response.status_code == 200
    body = response.json()
    assert body["htf_bias"] == "bullish"
    assert body["ltf_bias"] == "bearish"  # proves it's NOT just htf_bias duplicated
    assert body["note"] == ""
    assert body["symbol"] == routes_dashboard.settings.SYMBOL


def test_dashboard_bias_degrades_gracefully_on_fetch_failure(client, monkeypatch):
    """A live OKX fetch failure must not 500 the dashboard -- returns
    neutral/neutral with a note describing the failure instead."""
    import app.api.routes_dashboard as routes_dashboard

    monkeypatch.setattr(routes_dashboard, "CandleFetcher", _FakeCandleFetcherAlwaysFails)

    response = client.get("/dashboard/bias")
    assert response.status_code == 200
    body = response.json()
    assert body["htf_bias"] == "neutral"
    assert body["ltf_bias"] == "neutral"
    assert "simulated OKX outage" in body["note"]


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
