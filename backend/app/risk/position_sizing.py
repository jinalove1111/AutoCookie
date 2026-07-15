"""Position sizing.

Part of the Risk Engine. Computes trade size from account balance, risk
percent, and the entry/stop-loss distance. Must never be bypassed by
Execution — all sizing decisions originate here.
"""

from __future__ import annotations

# Adaptive platform milestone 7 (docs/ADAPTIVE_ARCHITECTURE.md section
# 5.2, ENGINEERING_DECISIONS.md #49): scales risk-percent DOWN in
# high-volatility regimes, an account-level safety measure independent of
# any one strategy's own stop placement. Disclosed-not-tuned (same status
# as _STOP_BUFFER/_RR before their 2026-07-11 sweep, decision #18): 0.5 is
# a reasonable, conservative starting halving factor, not backtest-derived.
# `low_volatility` intentionally does NOT scale UP (1.0, unchanged) --
# the spec only calls for scaling DOWN as a safety measure, not for
# increasing risk when conditions look calm (calm can precede a breakout).
_VOLATILITY_RISK_SCALARS = {
    "high_volatility": 0.5,
    "normal_volatility": 1.0,
    "low_volatility": 1.0,
}
_DEFAULT_VOLATILITY_RISK_SCALAR = 1.0


def volatility_risk_scalar(volatility: str | None) -> float:
    """Maps a `MarketRegime.volatility` label (a plain string, not the
    dataclass itself -- keeps `app.risk` decoupled from `app.regime`'s
    types, same duck-typing philosophy `RiskManager`'s `SignalLike`
    Protocol already uses) to a risk-percent multiplier. `None` (regime
    unavailable/not computed) or an unrecognized label both fall back to
    `_DEFAULT_VOLATILITY_RISK_SCALAR` (1.0, unchanged behavior) rather
    than raising -- this is a safety SCALE-DOWN, never a hard gate, so
    missing information must never block sizing entirely.
    """
    if volatility is None:
        return _DEFAULT_VOLATILITY_RISK_SCALAR
    return _VOLATILITY_RISK_SCALARS.get(volatility, _DEFAULT_VOLATILITY_RISK_SCALAR)


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
    volatility: str | None = None,
) -> float:
    """Calculate position size (in units) from account balance, risk percent, and entry/SL distance.

    ``risk_amount = account_balance * (risk_percent / 100)`` is the absolute
    currency amount the account is willing to lose on this trade.
    ``per_unit_risk = abs(entry - stop_loss)`` is the price distance risked
    per unit. Position size is ``risk_amount / per_unit_risk``.

    Returns ``0.0`` (instead of raising) when ``entry == stop_loss``, since a
    zero-risk-per-unit trade cannot be sized.

    `volatility` (optional, default `None` -- adaptive platform milestone
    7): a `MarketRegime.volatility` label. When supplied, `risk_amount` is
    scaled by `volatility_risk_scalar(volatility)` before sizing -- `None`
    (the default) applies a 1.0 scalar, byte-for-byte identical to this
    function's behavior before this parameter existed. Every existing
    caller that never passes `volatility` is unaffected.
    """
    risk_amount = account_balance * (risk_percent / 100) * volatility_risk_scalar(volatility)
    per_unit_risk = abs(entry - stop_loss)
    if per_unit_risk == 0:
        return 0.0
    return risk_amount / per_unit_risk
