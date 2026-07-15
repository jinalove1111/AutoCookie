"""Trend Following Strategy Module (adaptive platform Milestone 9,
2026-07-16 -- docs/ADAPTIVE_ARCHITECTURE.md section 7, Milestone 8 slot:
"New strategy modules (Trend Following, Range Trading, Breakout,
Volatility Expansion) ... building new strategy CONTENT"). Conforms to
the Strategy Protocol (`strategy_interface.Strategy`): `name`, `version`,
`generate_signal(symbol, ltf_candles, htf_candles) -> TradeSignal | None`.

DISCLOSED, NOT TUNED (docs/ADAPTIVE_ARCHITECTURE.md "evidence over
assumption" discipline -- same status `entry_model._RR`/`_STOP_BUFFER`
carried before their 2026-07-11 sweep, ENGINEERING_DECISIONS.md #18, and
the same status `regime_detector.py`'s own ADX/volatility thresholds
still carry today): every threshold below -- the ADX floor, the
pullback-to-MA proximity window, the ATR stop buffer, the fixed 2.5R
target -- is a plain, standard textbook trend-following rule, picked for
plausibility only. NONE of it has been backtested or optimized against
this project's own data yet; that is future work, once the (already
built) Strategy Selection Engine has routed real volume through this
module and there is real regime-tagged trade history to validate a
change against, instead of by assumption.

Detection only -- same "never places orders" contract every other
strategy module and `SignalEngine.generate_signal` already documents.
Any resulting signal is validated by the Risk Engine before it ever
reaches Execution.

Reuses `regime_detector`'s pure helpers (`simple_moving_average`,
`average_directional_index`, `swing_trend_direction`) and
`market_structure`/`utils` (`find_previous_swing_low`/`_high`,
`average_true_range`, `cf`) -- no indicator is reimplemented here.
"""

from __future__ import annotations

from app.regime.regime_detector import (
    average_directional_index,
    simple_moving_average,
    swing_trend_direction,
)
from app.strategy.market_structure import find_previous_swing_high, find_previous_swing_low
from app.strategy.signal_engine import TradeSignal
from app.strategy.utils import average_true_range, cf

# Weak-trend ADX floor for THIS strategy's own filter -- deliberately a
# separate constant from `regime_detector._ADX_WEAK_TREND` (15.0, that
# module's own floor for a different question, "is this a trend at all
# for regime-classification purposes"). This strategy additionally
# requires HTF/LTF trend AGREEMENT (see `generate_signal`), so it uses
# its own, stricter literal floor of 20 -- disclosed, not tuned, per the
# module docstring; `regime_detector` does not export a constant at this
# exact value, so it is not reused here.
_ADX_FLOOR = 20.0
_SMA_LOOKBACK = 20
_ADX_LOOKBACK = 14
_ATR_LOOKBACK = 14
_PULLBACK_LOOKBACK = 5
_PULLBACK_ATR_MULTIPLIER = 0.5
_STOP_ATR_BUFFER = 0.25
_STOP_ATR_FALLBACK_MULTIPLIER = 1.5
_RR = 2.5


def _pullback_touched_ma(recent_candles: list, sma: float, atr: float) -> bool:
    """True if any candle's [low, high] range came within
    `_PULLBACK_ATR_MULTIPLIER * atr` of `sma` -- the "pullback" half of
    the pullback-resumption entry trigger (see module docstring)."""
    threshold = _PULLBACK_ATR_MULTIPLIER * atr
    for c in recent_candles:
        if cf(c, "low") - threshold <= sma <= cf(c, "high") + threshold:
            return True
    return False


class TrendFollowingStrategy:
    """Textbook trend-following module: HTF swing-trend + LTF SMA(20)
    side + ADX floor agreement, pullback-to-SMA(20) resumption trigger,
    ATR-based stop, fixed 2.5R target. See module docstring for the
    "disclosed, not tuned" status of every threshold used here.
    Detection only -- never places orders.
    """

    name = "trend_following"
    version = "1.0"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        if not ltf_candles or not htf_candles:
            return None
        if len(ltf_candles) < _PULLBACK_LOOKBACK:
            return None

        htf_trend = swing_trend_direction(htf_candles)
        if htf_trend not in ("up", "down"):
            return None

        ltf_sma = simple_moving_average(ltf_candles, _SMA_LOOKBACK)
        adx = average_directional_index(ltf_candles, _ADX_LOOKBACK)
        atr = average_true_range(ltf_candles, _ATR_LOOKBACK)
        if ltf_sma is None or adx is None or atr is None:
            return None
        if adx < _ADX_FLOOR:
            return None

        last = ltf_candles[-1]
        last_close = cf(last, "close")
        last_open = cf(last, "open")

        if htf_trend == "up":
            direction = "long"
            if not (last_close > ltf_sma and last_close > last_open):
                return None
        else:
            direction = "short"
            if not (last_close < ltf_sma and last_close < last_open):
                return None

        if not _pullback_touched_ma(ltf_candles[-_PULLBACK_LOOKBACK:], ltf_sma, atr):
            return None

        entry_price = last_close

        if direction == "long":
            swing_low = find_previous_swing_low(ltf_candles)
            stop_loss = (
                swing_low["price"] - _STOP_ATR_BUFFER * atr
                if swing_low is not None
                else entry_price - _STOP_ATR_FALLBACK_MULTIPLIER * atr
            )
            risk = entry_price - stop_loss
            if risk <= 0:
                return None
            take_profit = entry_price + _RR * risk
        else:
            swing_high = find_previous_swing_high(ltf_candles)
            stop_loss = (
                swing_high["price"] + _STOP_ATR_BUFFER * atr
                if swing_high is not None
                else entry_price + _STOP_ATR_FALLBACK_MULTIPLIER * atr
            )
            risk = stop_loss - entry_price
            if risk <= 0:
                return None
            take_profit = entry_price - _RR * risk

        rr = abs(take_profit - entry_price) / abs(entry_price - stop_loss)

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            timestamp=cf(ltf_candles[-1], "timestamp"),
            htf_bias="bullish" if htf_trend == "up" else "bearish",
            sweep_type=None,
            choch_detected=False,
            fvg_zone=None,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr=rr,
            status="pending",
        )
