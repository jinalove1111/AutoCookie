"""RangeTradingStrategy (adaptive platform Milestone 9, 2026-07-16):
mean-reversion range fade, the "Range Trading" entry in
docs/ADAPTIVE_ARCHITECTURE.md section 7 milestone 8's "New strategy
modules" list (Trend Following, Range Trading, Breakout, Volatility
Expansion) -- explicitly LAST on that roadmap, per the operator's "prefer
structural improvements over parameter optimization" instruction: this is
new strategy CONTENT, secondary to the selection/evaluation/retirement
system already built (milestones 1-8.1).

Conforms to the `Strategy` Protocol (`strategy_interface.py`) -- detection
only, NEVER places orders. Not registered in `AVAILABLE_STRATEGIES`
(strategy_interface.py); wiring a new module into that registry is a
separate integration step, same discipline `strategy_interface.py`'s own
docstring already follows for Legacy/Jade.

DISCLOSED, NOT TUNED (same "evidence over assumption" discipline as
`regime_detector.py`'s own module docstring and every threshold in
docs/ADAPTIVE_ARCHITECTURE.md): the lookback, ADX cutoff, range-edge
percentile, and stop/target multipliers below are textbook range-fade
rules, not backtest-validated parameters. Future work: tune once enough
regime-tagged trade history exists to evaluate a change against, not by
assumption (docs/ADAPTIVE_ARCHITECTURE.md section 6).

Reuses `average_directional_index` (app.regime.regime_detector) and
`average_true_range`/`cf` (app.strategy.utils) rather than reimplementing
either indicator -- same reuse discipline `regime_detector.py` itself
follows for ATR/swing structure/liquidity sweeps.
"""

from __future__ import annotations

from app.regime.regime_detector import average_directional_index
from app.strategy.bias import detect_htf_bias
from app.strategy.signal_engine import TradeSignal
from app.strategy.utils import average_true_range, cf

# Disclosed, standard textbook thresholds -- NOT backtest-tuned, see
# module docstring.
_RANGE_LOOKBACK = 40
_ADX_TRENDING_CUTOFF = 20.0
_ATR_LOOKBACK = 14
_MIN_RANGE_WIDTH_ATR_MULTIPLE = 2.0
_EDGE_PERCENTILE = 0.15  # bottom/top 15% of the range qualifies as a fade zone
_STOP_ATR_MULTIPLE = 0.5
_MIN_RR = 2.0  # this platform's RiskManager rejects rr < 2; see generate_signal


def _range_bounds(ltf_candles: list) -> tuple[float, float] | None:
    """(range_low, range_high) over the most recent `_RANGE_LOOKBACK`
    candles, or None if there isn't enough history."""
    if len(ltf_candles) < _RANGE_LOOKBACK:
        return None
    window = ltf_candles[-_RANGE_LOOKBACK:]
    highs = [cf(c, "high") for c in window]
    lows = [cf(c, "low") for c in window]
    return min(lows), max(highs)


def _fade_direction(close: float, range_low: float, range_high: float) -> str | None:
    """"long" if `close` sits in the bottom `_EDGE_PERCENTILE` of the
    range, "short" if it sits in the top `_EDGE_PERCENTILE`, else None
    (the middle 70% is no setup)."""
    width = range_high - range_low
    if width <= 0:
        return None
    position = (close - range_low) / width
    if position <= _EDGE_PERCENTILE:
        return "long"
    if position >= 1.0 - _EDGE_PERCENTILE:
        return "short"
    return None


class RangeTradingStrategy:
    """Mean-reversion range fade: qualifies a non-trending (low-ADX),
    sufficiently wide range on the LTF, then fades price back toward the
    opposite extreme when the current close sits in the outer edge of
    that range. See module docstring for the disclosed-not-tuned ruleset.
    """

    name = "range_trading"
    version = "1.0"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        """Return a fade `TradeSignal`, or None generously -- insufficient
        history, a trending market (ADX >= cutoff or unavailable), a range
        too narrow to trade, a close in the middle of the range, or a
        setup whose honest rr falls below 2.0 (this platform's
        RiskManager rejects rr < 2, so only signals that CAN pass are
        emitted here). Never raises on short/odd input; detection only,
        never places orders.
        """
        if not ltf_candles:
            return None

        bounds = _range_bounds(ltf_candles)
        if bounds is None:
            return None
        range_low, range_high = bounds

        adx = average_directional_index(ltf_candles, lookback=_ATR_LOOKBACK)
        if adx is None or adx >= _ADX_TRENDING_CUTOFF:
            return None

        atr = average_true_range(ltf_candles, lookback=_ATR_LOOKBACK)
        if atr is None or atr <= 0:
            return None

        width = range_high - range_low
        if width < _MIN_RANGE_WIDTH_ATR_MULTIPLE * atr:
            return None

        close = cf(ltf_candles[-1], "close")
        direction = _fade_direction(close, range_low, range_high)
        if direction is None:
            return None

        entry_price = close
        if direction == "long":
            stop_loss = range_low - _STOP_ATR_MULTIPLE * atr
            take_profit = range_high
            stop_distance = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            stop_loss = range_high + _STOP_ATR_MULTIPLE * atr
            take_profit = range_low
            stop_distance = stop_loss - entry_price
            reward = entry_price - take_profit

        if stop_distance <= 0:
            return None
        rr = reward / stop_distance
        if rr < _MIN_RR:
            return None

        htf_reference = htf_candles if htf_candles else ltf_candles
        htf_bias = detect_htf_bias(htf_reference)

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            timestamp=cf(ltf_candles[-1], "timestamp"),
            htf_bias=htf_bias,
            sweep_type=None,
            choch_detected=False,
            fvg_zone=None,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr=rr,
            status="pending",
        )
