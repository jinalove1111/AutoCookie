"""Tests for scripts/parameter_sweep.py's pure metric functions
(profit_factor, expectancy, average_r). scripts/ is a sibling directory
to backend/, so it's added to sys.path explicitly here, matching
test_run_backtest.py's existing pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from parameter_sweep import average_r, expectancy, profit_factor  # noqa: E402


def _trade(pnl: float, size: float = 1.0, risk_per_unit: float = 10.0) -> dict:
    return {"pnl": pnl, "size": size, "risk_per_unit": risk_per_unit}


# --- profit_factor ----------------------------------------------------------


def test_profit_factor_computes_gross_profit_over_gross_loss():
    trades = [_trade(100), _trade(50), _trade(-40), _trade(-20)]
    # gains = 150, losses = 60 -> 2.5
    assert profit_factor(trades) == pytest.approx(2.5)


def test_profit_factor_none_when_no_trades_at_all():
    assert profit_factor([]) is None


def test_profit_factor_infinite_when_wins_but_zero_losses():
    trades = [_trade(100), _trade(50)]
    assert profit_factor(trades) == float("inf")


def test_profit_factor_none_when_all_trades_are_exactly_zero():
    trades = [_trade(0), _trade(0)]
    assert profit_factor(trades) is None


# --- expectancy --------------------------------------------------------------


def test_expectancy_is_mean_pnl_per_trade():
    trades = [_trade(100), _trade(-50), _trade(30)]
    assert expectancy(trades) == pytest.approx(80 / 3)


def test_expectancy_zero_for_empty_trade_list():
    assert expectancy([]) == 0.0


# --- average_r ----------------------------------------------------------------


def test_average_r_normalizes_pnl_by_risk_amount():
    # trade 1: risk_amount = size(1) * risk_per_unit(10) = 10, pnl=20 -> R=2.0
    # trade 2: risk_amount = size(2) * risk_per_unit(5) = 10, pnl=-10 -> R=-1.0
    trades = [
        _trade(20, size=1.0, risk_per_unit=10.0),
        _trade(-10, size=2.0, risk_per_unit=5.0),
    ]
    assert average_r(trades) == pytest.approx((2.0 + -1.0) / 2)


def test_average_r_skips_trades_with_no_usable_risk_per_unit():
    trades = [
        _trade(20, size=1.0, risk_per_unit=10.0),  # R=2.0
        {"pnl": 999, "size": 1.0, "risk_per_unit": 0.0},  # excluded: risk_per_unit == 0
        {"pnl": 999, "size": 1.0, "risk_per_unit": None},  # excluded: no risk_per_unit
    ]
    assert average_r(trades) == pytest.approx(2.0)


def test_average_r_none_when_no_trade_has_usable_risk_data():
    trades = [{"pnl": 100, "size": 1.0, "risk_per_unit": 0.0}]
    assert average_r(trades) is None
