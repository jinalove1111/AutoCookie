"""Position sizing stub.

Part of the Risk Engine. Computes trade size from account balance, risk
percent, and the entry/stop-loss distance. Must never be bypassed by
Execution — all sizing decisions originate here.
"""

from __future__ import annotations


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
) -> float:
    """Calculate position size (in units) from account balance, risk percent, and entry/SL distance.

    ``risk_amount = account_balance * (risk_percent / 100)`` is the absolute
    currency amount the account is willing to lose on this trade.
    ``per_unit_risk = abs(entry - stop_loss)`` is the price distance risked
    per unit. Position size is ``risk_amount / per_unit_risk``.

    Returns ``0.0`` (instead of raising) when ``entry == stop_loss``, since a
    zero-risk-per-unit trade cannot be sized.
    """
    risk_amount = account_balance * (risk_percent / 100)
    per_unit_risk = abs(entry - stop_loss)
    if per_unit_risk == 0:
        return 0.0
    return risk_amount / per_unit_risk
