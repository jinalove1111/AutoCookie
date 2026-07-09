"""Order Block / Breaker Block detection.

Part of the Strategy Engine. Detects order block and breaker block zones used
as potential entry areas. Produces analysis data only — never places orders.
Any resulting signal is validated by the Risk Engine before reaching
Execution.

Impulse strength is measured against the average candle range of the prior
10 candles (a rolling window, not the whole series) so the "strong move"
threshold adapts to recent volatility instead of one fixed dataset-wide
average.
"""

from __future__ import annotations

from .utils import cf

# Neither constant is derived from backtesting/optimization -- both are
# reasonable starting defaults, not yet tuned against real performance
# data.
#
# _LOOKBACK = 10: a rolling window "long enough to average out single-candle
# noise, short enough to still track recent (not stale) volatility" -- 10
# was picked as a round-number compromise between those two pulls, not
# derived from a statistical test on real data.
_LOOKBACK = 10
# _IMPULSE_MULT = 1.5: the impulse candle's range must exceed the rolling
# average range by 50% to count as a "strong move" rather than ordinary
# chop -- 1.5x is an arbitrary round threshold chosen for the same reason
# (a plausible starting cutoff), not backtested/tuned.
_IMPULSE_MULT = 1.5


def _range(candle: object) -> float:
    return cf(candle, "high") - cf(candle, "low")


def _is_bullish(candle: object) -> bool:
    return cf(candle, "close") > cf(candle, "open")


def _is_bearish(candle: object) -> bool:
    return cf(candle, "close") < cf(candle, "open")


def detect_order_block(candles: list) -> dict | None:
    """Detect the most relevant (most recent) order block zone, or None."""
    found: dict | None = None

    for i in range(_LOOKBACK, len(candles)):
        window = candles[i - _LOOKBACK : i]
        avg_range = sum(_range(c) for c in window) / _LOOKBACK
        if avg_range <= 0:
            continue

        impulse_range = _range(candles[i])
        if impulse_range <= _IMPULSE_MULT * avg_range:
            continue

        if _is_bullish(candles[i]):
            for j in range(i - 1, -1, -1):
                if _is_bearish(candles[j]):
                    found = {
                        "type": "bullish",
                        "top": cf(candles[j], "high"),
                        "bottom": cf(candles[j], "low"),
                        "index": j,
                    }
                    break
        elif _is_bearish(candles[i]):
            for j in range(i - 1, -1, -1):
                if _is_bullish(candles[j]):
                    found = {
                        "type": "bearish",
                        "top": cf(candles[j], "high"),
                        "bottom": cf(candles[j], "low"),
                        "index": j,
                    }
                    break

    return found


def detect_breaker_block(candles: list) -> dict | None:
    """Detect the most relevant breaker block zone, or None.

    A breaker block is a former order block whose zone gets fully closed
    through (price closes past the far side) and is then retested from the
    other side; the same zone shape is returned with `type` flipped.
    """
    ob = detect_order_block(candles)
    if ob is None:
        return None

    ob_index = ob["index"]
    top = ob["top"]
    bottom = ob["bottom"]

    closed_through_idx = None
    for k in range(ob_index + 1, len(candles)):
        close = cf(candles[k], "close")
        if ob["type"] == "bullish" and close < bottom:
            closed_through_idx = k
            break
        if ob["type"] == "bearish" and close > top:
            closed_through_idx = k
            break

    if closed_through_idx is None:
        return None

    for m in range(closed_through_idx + 1, len(candles)):
        high = cf(candles[m], "high")
        low = cf(candles[m], "low")
        if ob["type"] == "bullish" and high >= bottom:
            return {"type": "bearish", "top": top, "bottom": bottom, "index": ob_index}
        if ob["type"] == "bearish" and low <= top:
            return {"type": "bullish", "top": top, "bottom": bottom, "index": ob_index}

    return None
