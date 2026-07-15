"""Unit tests for app.risk.drawdown_guard.DrawdownGuard and
app.risk.position_sizing.calculate_position_size -- the two small
building blocks RiskManager composes."""

from __future__ import annotations

from app.risk.drawdown_guard import DrawdownGuard
from app.risk.position_sizing import calculate_position_size, volatility_risk_scalar


def test_drawdown_guard_daily_loss_within_limit_allows_trading():
    guard = DrawdownGuard()
    assert guard.check_daily_loss(daily_pnl=-0.5, max_daily_loss_percent=1.0) is True


def test_drawdown_guard_daily_loss_at_limit_blocks_trading():
    guard = DrawdownGuard()
    assert guard.check_daily_loss(daily_pnl=-1.0, max_daily_loss_percent=1.0) is False


def test_drawdown_guard_positive_pnl_never_blocks():
    guard = DrawdownGuard()
    assert guard.check_daily_loss(daily_pnl=5.0, max_daily_loss_percent=1.0) is True


def test_drawdown_guard_weekly_loss_beyond_limit_blocks_trading():
    guard = DrawdownGuard()
    assert guard.check_weekly_loss(weekly_pnl=-4.0, max_weekly_loss_percent=3.0) is False


def test_drawdown_guard_weekly_loss_within_limit_allows_trading():
    guard = DrawdownGuard()
    assert guard.check_weekly_loss(weekly_pnl=-2.0, max_weekly_loss_percent=3.0) is True


def test_calculate_position_size_basic_math():
    # risk_amount = 10000 * (1/100) = 100; per_unit_risk = |100-95| = 5 -> size = 20
    size = calculate_position_size(account_balance=10000, risk_percent=1, entry=100, stop_loss=95)
    assert size == 20.0


def test_calculate_position_size_zero_when_entry_equals_stop_loss():
    size = calculate_position_size(account_balance=10000, risk_percent=1, entry=100, stop_loss=100)
    assert size == 0.0


def test_volatility_risk_scalar_halves_for_high_volatility():
    assert volatility_risk_scalar("high_volatility") == 0.5


def test_volatility_risk_scalar_unchanged_for_normal_and_low_volatility():
    assert volatility_risk_scalar("normal_volatility") == 1.0
    assert volatility_risk_scalar("low_volatility") == 1.0


def test_volatility_risk_scalar_defaults_to_unchanged_for_none_and_unknown():
    assert volatility_risk_scalar(None) == 1.0
    assert volatility_risk_scalar("not_a_real_regime_label") == 1.0


def test_calculate_position_size_unaffected_when_volatility_omitted():
    # Byte-for-byte identical to pre-milestone-7 behavior when the new
    # parameter isn't passed at all.
    size = calculate_position_size(account_balance=10000, risk_percent=1, entry=100, stop_loss=95)
    assert size == 20.0


def test_calculate_position_size_scales_down_in_high_volatility():
    size = calculate_position_size(
        account_balance=10000, risk_percent=1, entry=100, stop_loss=95, volatility="high_volatility"
    )
    assert size == 10.0  # half of the unscaled 20.0


def test_calculate_position_size_unchanged_in_normal_volatility():
    size = calculate_position_size(
        account_balance=10000, risk_percent=1, entry=100, stop_loss=95, volatility="normal_volatility"
    )
    assert size == 20.0
