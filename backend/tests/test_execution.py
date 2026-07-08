"""Unit tests for the app.execution layer: safety_checks (blocks on
live-mode misconfiguration), PaperBroker fill/exit simulation,
OrderManager break-even/partial-TP lifecycle, and ExecutionEngine tying
them together.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.execution import safety_checks
from app.execution.execution_engine import ExecutionEngine
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker


@dataclass
class FakeSignal:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    rr: float = 2.0


@dataclass
class FakeRiskDecision:
    approved: bool
    reasons: list[str]


# --------------------------------------------------------------------------
# safety_checks
# --------------------------------------------------------------------------


@pytest.fixture()
def settings_obj():
    # Use the `settings` object app.execution.safety_checks actually holds
    # a reference to (not a fresh `from app.config import settings`), so
    # monkeypatching here is guaranteed to affect the module under test
    # even if some other test in this session has since re-imported
    # app.config into a different object (e.g. via DB-fixture module
    # purging in test_db_bootstrap.py).
    return safety_checks.settings


def test_safety_checks_blocks_live_mode_misconfiguration(monkeypatch, settings_obj):
    """TRADING_MODE == 'live' but LIVE_TRADING_ENABLED not set -> blocked,
    regardless of an otherwise-approved, well-formed signal.
    """
    monkeypatch.setattr(settings_obj, "TRADING_MODE", "live")
    monkeypatch.setattr(settings_obj, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(settings_obj, "MIN_RR", 2.0)

    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)
    decision = FakeRiskDecision(approved=True, reasons=[])

    is_safe, reason = safety_checks.verify_safe_to_trade(decision, signal)

    assert is_safe is False
    assert "live trading not allowed" in reason


def test_safety_checks_allows_paper_mode_with_approved_signal(monkeypatch, settings_obj):
    monkeypatch.setattr(settings_obj, "TRADING_MODE", "paper")
    monkeypatch.setattr(settings_obj, "MIN_RR", 2.0)

    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)
    decision = FakeRiskDecision(approved=True, reasons=[])

    is_safe, reason = safety_checks.verify_safe_to_trade(decision, signal)

    assert is_safe is True
    assert reason == "ok"


def test_safety_checks_blocks_unapproved_signal(monkeypatch, settings_obj):
    monkeypatch.setattr(settings_obj, "TRADING_MODE", "paper")
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)
    decision = FakeRiskDecision(approved=False, reasons=["rr too low"])

    is_safe, reason = safety_checks.verify_safe_to_trade(decision, signal)

    assert is_safe is False
    assert "did not approve" in reason


def test_safety_checks_blocks_when_exchange_unhealthy(monkeypatch, settings_obj):
    monkeypatch.setattr(settings_obj, "TRADING_MODE", "paper")
    monkeypatch.setattr(settings_obj, "MIN_RR", 2.0)
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)
    decision = FakeRiskDecision(approved=True, reasons=[])

    is_safe, reason = safety_checks.verify_safe_to_trade(decision, signal, exchange_healthy=False)

    assert is_safe is False
    assert "exchange not healthy" in reason


# --------------------------------------------------------------------------
# PaperBroker
# --------------------------------------------------------------------------


def test_paper_broker_fill_entry_long_applies_unfavorable_slippage():
    broker = PaperBroker()
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)

    fill = broker.fill_entry(signal)

    assert fill["fill_price"] > 100  # long: unfavorable = higher fill
    assert fill["order_id"]
    assert fill["fee_percent"] == 0.05


def test_paper_broker_fill_entry_short_applies_unfavorable_slippage():
    broker = PaperBroker()
    signal = FakeSignal(direction="short", entry_price=100, stop_loss=105, take_profit=90)

    fill = broker.fill_entry(signal)

    assert fill["fill_price"] < 100  # short: unfavorable = lower fill


def test_paper_broker_check_exit_long_stop_loss_triggers():
    broker = PaperBroker()
    position = {"direction": "long", "stop_loss": 95, "take_profit": 110}

    result = broker.check_exit(position, current_price=94)

    assert result == {"exit_price": 95, "reason": "stop_loss"}


def test_paper_broker_check_exit_long_take_profit_triggers():
    broker = PaperBroker()
    position = {"direction": "long", "stop_loss": 95, "take_profit": 110}

    result = broker.check_exit(position, current_price=111)

    assert result == {"exit_price": 110, "reason": "take_profit"}


def test_paper_broker_check_exit_none_when_price_between():
    broker = PaperBroker()
    position = {"direction": "long", "stop_loss": 95, "take_profit": 110}

    assert broker.check_exit(position, current_price=102) is None


def test_paper_broker_check_exit_short_mirrors_long():
    broker = PaperBroker()
    position = {"direction": "short", "stop_loss": 105, "take_profit": 90}

    assert broker.check_exit(position, current_price=106) == {"exit_price": 105, "reason": "stop_loss"}
    assert broker.check_exit(position, current_price=89) == {"exit_price": 90, "reason": "take_profit"}
    assert broker.check_exit(position, current_price=100) is None


# --------------------------------------------------------------------------
# OrderManager lifecycle
# --------------------------------------------------------------------------


def test_order_manager_place_entry_delegates_to_broker():
    manager = OrderManager(PaperBroker())
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)

    fill = manager.place_entry(signal)

    assert "order_id" in fill and "fill_price" in fill


def test_order_manager_move_to_breakeven_does_not_mutate_input():
    manager = OrderManager(PaperBroker())
    position = {"direction": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110}

    new_position = manager.move_to_breakeven(position)

    assert new_position["stop_loss"] == 100
    assert position["stop_loss"] == 95  # original untouched


def test_order_manager_handle_partial_tp_long_realizes_pnl():
    manager = OrderManager(PaperBroker())
    position = {
        "direction": "long",
        "entry_price": 100,
        "current_price": 110,
        "size": 10,
    }

    result = manager.handle_partial_tp(position, portion=0.5)

    assert result["closed_size"] == 5
    assert result["remaining_size"] == 5
    assert result["realized_pnl"] == 50  # (110-100) * 5


def test_order_manager_handle_partial_tp_short_realizes_pnl():
    manager = OrderManager(PaperBroker())
    position = {
        "direction": "short",
        "entry_price": 100,
        "current_price": 90,
        "size": 10,
    }

    result = manager.handle_partial_tp(position, portion=0.5)

    assert result["closed_size"] == 5
    assert result["remaining_size"] == 5
    assert result["realized_pnl"] == 50  # (100-90) * 5


# --------------------------------------------------------------------------
# ExecutionEngine
# --------------------------------------------------------------------------


def test_execution_engine_rejects_unapproved_signal():
    engine = ExecutionEngine()
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110)
    decision = FakeRiskDecision(approved=False, reasons=["rr below MIN_RR"])

    result = engine.execute(signal, decision)

    assert result.success is False
    assert result.order_id is None
    assert "not approved" in result.error


def test_execution_engine_executes_approved_signal_in_paper_mode(monkeypatch):
    # ExecutionEngine.execute() delegates the live-mode check to
    # app.execution.safety_checks, so mutate its actual `settings`
    # reference (see the `settings_obj` fixture above for why).
    monkeypatch.setattr(safety_checks.settings, "TRADING_MODE", "paper")
    monkeypatch.setattr(safety_checks.settings, "MIN_RR", 2.0)

    engine = ExecutionEngine()
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110, rr=2.5)
    decision = FakeRiskDecision(approved=True, reasons=[])

    result = engine.execute(signal, decision)

    assert result.success is True
    assert result.order_id is not None
    assert result.error is None


def test_execution_engine_blocks_when_live_trading_not_allowed(monkeypatch):
    monkeypatch.setattr(safety_checks.settings, "TRADING_MODE", "live")
    monkeypatch.setattr(safety_checks.settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(safety_checks.settings, "MIN_RR", 2.0)

    engine = ExecutionEngine()
    signal = FakeSignal(direction="long", entry_price=100, stop_loss=95, take_profit=110, rr=2.5)
    decision = FakeRiskDecision(approved=True, reasons=[])

    result = engine.execute(signal, decision)

    assert result.success is False
    assert "live trading not allowed" in result.error
