"""Unit tests for app.risk.risk_manager.RiskManager: the single gate
every trade signal must pass through. Covers RR pass/fail, daily/weekly
loss blocking, max-trades-per-day blocking, optional circuit_breaker
blocking, and that all failing checks are collected (no
short-circuiting).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.risk import risk_manager as risk_manager_module
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.risk_manager import RiskManager


@dataclass
class FakeSignal:
    stop_loss: float | None
    take_profit: float | None
    rr: float


@pytest.fixture()
def risk_manager() -> RiskManager:
    return RiskManager()


@pytest.fixture(autouse=True)
def _default_risk_settings(monkeypatch: pytest.MonkeyPatch):
    """Pin the risk thresholds this test file assumes, regardless of
    whatever env vars happen to be active, via the real settings
    singleton `app.risk.risk_manager` imports.

    `risk_manager_module` is bound at module-import (collection) time,
    the same moment `RiskManager` itself was bound above -- so this is
    guaranteed to be the exact `settings` object `RiskManager.evaluate()`
    reads, even if some other test in this session later purges/re-
    imports `app.risk.risk_manager` into a different module object (see
    DB fixtures in conftest.py / test_db_bootstrap.py).
    """
    monkeypatch.setattr(risk_manager_module.settings, "MIN_RR", 2.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_DAILY_LOSS_PERCENT", 1.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_WEEKLY_LOSS_PERCENT", 3.0)
    monkeypatch.setattr(risk_manager_module.settings, "MAX_TRADES_PER_DAY", 2)


def test_approves_signal_meeting_every_rule(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, daily_pnl_percent=0.0, weekly_pnl_percent=0.0, trades_today=0)

    assert decision.approved is True
    assert decision.reasons == []


def test_rejects_signal_below_min_rr(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=101, rr=1.0)

    decision = risk_manager.evaluate(signal)

    assert decision.approved is False
    assert any("rr" in reason for reason in decision.reasons)


def test_rejects_signal_missing_stop_loss_or_take_profit(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=None, take_profit=None, rr=2.5)

    decision = risk_manager.evaluate(signal)

    assert decision.approved is False
    assert "stop_loss is missing" in decision.reasons
    assert "take_profit is missing" in decision.reasons


def test_rejects_when_daily_loss_limit_breached(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, daily_pnl_percent=-1.5)

    assert decision.approved is False
    assert any("daily loss" in reason for reason in decision.reasons)


def test_rejects_when_weekly_loss_limit_breached(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, weekly_pnl_percent=-3.2)

    assert decision.approved is False
    assert any("weekly loss" in reason for reason in decision.reasons)


def test_rejects_when_max_trades_per_day_reached(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, trades_today=2)

    assert decision.approved is False
    assert any("trades_today" in reason for reason in decision.reasons)


def test_rejects_when_circuit_breaker_tripped(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)
    breaker = CircuitBreaker()
    breaker.trip("daily loss limit hit")

    decision = risk_manager.evaluate(signal, circuit_breaker=breaker)

    assert decision.approved is False
    assert any("circuit breaker tripped" in reason for reason in decision.reasons)
    assert "daily loss limit hit" in decision.reasons[0]


def test_circuit_breaker_not_checked_when_omitted(risk_manager: RiskManager):
    """circuit_breaker defaults to None, which must skip the check
    entirely (existing callers unaffected)."""
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, circuit_breaker=None)

    assert decision.approved is True


def test_collects_all_failing_reasons_without_short_circuiting(risk_manager: RiskManager):
    """A signal that fails RR, both loss limits, max trades, AND the
    circuit breaker should report ALL five reasons, not just the first.
    """
    signal = FakeSignal(stop_loss=95, take_profit=96, rr=0.1)
    breaker = CircuitBreaker()
    breaker.trip("exchange outage")

    decision = risk_manager.evaluate(
        signal,
        daily_pnl_percent=-2.0,
        weekly_pnl_percent=-5.0,
        trades_today=3,
        circuit_breaker=breaker,
    )

    assert decision.approved is False
    assert len(decision.reasons) == 5


def test_rejects_when_strategy_disabled(risk_manager: RiskManager):
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal, strategy_disabled=True)

    assert decision.approved is False
    assert any("auto-disabled" in reason for reason in decision.reasons)


def test_strategy_disabled_not_checked_when_omitted(risk_manager: RiskManager):
    """strategy_disabled defaults to False, which must skip the rejection
    entirely (existing callers unaffected)."""
    signal = FakeSignal(stop_loss=95, take_profit=110, rr=2.5)

    decision = risk_manager.evaluate(signal)

    assert decision.approved is True
