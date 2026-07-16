"""Tests for `app.portfolio.shadow_recorder.record_shadow_pass` (Milestone
11b, 2026-07-16 -- see that module's docstring for the "observability
only, quarantine intact" discipline, ENGINEERING_DECISIONS.md #53).

Uses the same real-migration-driven temp-DB fixtures
(`migrated_db`/`db_session`) `test_shadow_observability_schema.py` uses
for the schema itself -- this file proves the WRITE PATH on top of that
already-proven schema, not the schema again.

Strategy evaluation is exercised via monkeypatched
`app.portfolio.shadow_recorder.all_strategies` (not the real registry) --
the simplest honest way to deterministically prove: a non-None signal is
persisted with the right columns, a None return is skipped, a raising
strategy is counted as an error without blocking its siblings, and the
active strategy is excluded from evaluation entirely.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


def _make_regime(**overrides):
    from app.regime.regime_detector import MarketRegime

    kwargs = dict(
        trend="strong_trend",
        volatility="high_volatility",
        breakout=True,
        mean_reversion=False,
        liquidity_sweep_environment=True,
        metrics={"adx": 31.2, "atr": 145.6},
    )
    kwargs.update(overrides)
    return MarketRegime(**kwargs)


def _make_signal(**overrides):
    from app.strategy.signal_engine import TradeSignal

    kwargs = dict(
        symbol="BTCUSDT",
        direction="long",
        timestamp="2026-07-16T00:00:00Z",
        htf_bias="bullish",
        sweep_type="buy_side",
        choch_detected=True,
        fvg_zone={"top": 61300.0, "bottom": 61200.0},
        entry_price=61234.5,
        stop_loss=60800.0,
        take_profit=62500.0,
        rr=2.9,
        status="pending",
    )
    kwargs.update(overrides)
    return TradeSignal(**kwargs)


@dataclass
class _FakeStrategy:
    name: str
    version: str
    _outcome: str  # "signal" | "none" | "raise"

    def generate_signal(self, symbol, ltf_candles, htf_candles):
        if self._outcome == "signal":
            return _make_signal(symbol=symbol)
        if self._outcome == "none":
            return None
        raise RuntimeError(f"{self.name} blew up")


def _synthetic_candles(n: int = 5) -> list[dict]:
    return [
        {
            "timestamp": f"2026-07-16T00:0{i}:00Z",
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 10.0,
        }
        for i in range(n)
    ]


def test_record_shadow_pass_writes_one_regime_snapshot(migrated_db, monkeypatch):
    """(a) A real MarketRegime + synthetic candles writes exactly one
    RegimeSnapshot row. Strategy evaluation is monkeypatched to an empty
    registry so this test is isolated from any real strategy module's
    behavior on sparse synthetic candles.
    """
    import app.portfolio.shadow_recorder as shadow_recorder
    from app.database.models import RegimeSnapshot

    monkeypatch.setattr(shadow_recorder, "all_strategies", lambda: {})

    regime = _make_regime()
    candles = _synthetic_candles()

    result = shadow_recorder.record_shadow_pass(
        "BTCUSDT", "5m", candles, candles, regime, "legacy"
    )

    assert result["snapshot_written"] is True
    assert result["shadow_signals_written"] == 0
    assert result["strategies_evaluated"] == 0
    assert result["errors"] == 0

    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(RegimeSnapshot).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.symbol == "BTCUSDT"
        assert row.timeframe == "5m"
        assert row.trend == "strong_trend"
        assert row.volatility == "high_volatility"
        assert row.breakout is True
        assert row.mean_reversion is False
        assert row.liquidity_sweep_environment is True
        assert row.metrics == {"adx": 31.2, "atr": 145.6}
    finally:
        db.close()


def test_record_shadow_pass_evaluates_strategies_correctly(migrated_db, monkeypatch):
    """(b) Fake strategy registry proving: non-None persisted with correct
    columns, None skipped, raising strategy counted as an error without
    blocking others, and the active strategy is excluded entirely.
    """
    import app.portfolio.shadow_recorder as shadow_recorder
    from app.database.models import ShadowSignal

    fake_registry = {
        "signal_strategy": _FakeStrategy("signal_strategy", "2.1", "signal"),
        "none_strategy": _FakeStrategy("none_strategy", "1.0", "none"),
        "raising_strategy": _FakeStrategy("raising_strategy", "1.0", "raise"),
        "legacy": _FakeStrategy("legacy", "1.0", "signal"),  # active -- must be excluded
    }
    monkeypatch.setattr(shadow_recorder, "all_strategies", lambda: fake_registry)

    regime = _make_regime()
    candles = _synthetic_candles()

    result = shadow_recorder.record_shadow_pass(
        "BTCUSDT", "5m", candles, candles, regime, "legacy"
    )

    # 4 strategies registered, 1 excluded (active) -> 3 evaluated.
    assert result["strategies_evaluated"] == 3
    assert result["errors"] == 1
    assert result["shadow_signals_written"] == 1
    assert result["snapshot_written"] is True

    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(ShadowSignal).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.strategy_name == "signal_strategy"
        assert row.strategy_version == "2.1"
        assert row.direction == "long"
        assert row.entry_price == 61234.5
        assert row.stop_loss == 60800.0
        assert row.take_profit == 62500.0
        assert row.rr == 2.9
        assert row.market_regime == {
            "trend": "strong_trend",
            "volatility": "high_volatility",
            "breakout": True,
            "mean_reversion": False,
            "liquidity_sweep_environment": True,
            "metrics": {"adx": 31.2, "atr": 145.6},
        }
        # Promoted fields (symbol/direction/entry_price/stop_loss/take_profit/rr)
        # must NOT be duplicated inside signal_payload.
        assert "symbol" not in row.signal_payload
        assert "direction" not in row.signal_payload
        assert "entry_price" not in row.signal_payload
        assert "stop_loss" not in row.signal_payload
        assert "take_profit" not in row.signal_payload
        assert "rr" not in row.signal_payload
        assert row.signal_payload["htf_bias"] == "bullish"
        assert row.signal_payload["sweep_type"] == "buy_side"
        assert row.signal_payload["choch_detected"] is True
        assert row.signal_payload["status"] == "pending"
    finally:
        db.close()


def test_record_shadow_pass_none_regime_skips_snapshot_but_still_evaluates(
    migrated_db, monkeypatch
):
    """(c) regime=None -> no RegimeSnapshot row is written, but strategies
    are still evaluated (and any resulting ShadowSignal rows carry a NULL
    market_regime).
    """
    import app.portfolio.shadow_recorder as shadow_recorder
    from app.database.models import RegimeSnapshot, ShadowSignal

    fake_registry = {
        "signal_strategy": _FakeStrategy("signal_strategy", "1.0", "signal"),
        "legacy": _FakeStrategy("legacy", "1.0", "signal"),
    }
    monkeypatch.setattr(shadow_recorder, "all_strategies", lambda: fake_registry)

    candles = _synthetic_candles()

    result = shadow_recorder.record_shadow_pass(
        "BTCUSDT", "5m", candles, candles, None, "legacy"
    )

    assert result["snapshot_written"] is False
    assert result["strategies_evaluated"] == 1
    assert result["shadow_signals_written"] == 1
    assert result["errors"] == 0

    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        assert db.query(RegimeSnapshot).count() == 0
        rows = db.query(ShadowSignal).all()
        assert len(rows) == 1
        assert rows[0].market_regime is None
    finally:
        db.close()
