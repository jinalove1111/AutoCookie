"""Order Block / Breaker Block detection.

Part of the Strategy Engine. Detects order block and breaker block zones used
as potential entry areas. Produces analysis data only — never places orders.
Any resulting signal is validated by the Risk Engine before reaching
Execution.

Impulse strength is measured against the average candle range of the prior
15 candles (a rolling window, not the whole series) so the "strong move"
threshold adapts to recent volatility instead of one fixed dataset-wide
average.
"""

from __future__ import annotations

from .utils import cf

# TUNED (2026-07-11, Phase 1 controlled parameter sweep -- see
# docs/parameter_sweep_report.md, ENGINEERING_DECISIONS.md, and
# ROADMAP.md for the full methodology/evidence). A one-at-a-time sweep
# (holding entry_model._RR/_STOP_BUFFER and the other of these two
# constants at their defaults) found both values below robust across
# in-sample selection, held-out out-of-sample validation, cross-asset
# validation (ETHUSDT/SOLUSDT/XRPUSDT), AND a cross-YEAR check (BTCUSDT
# anchored to 2025) -- see entry_model.py's _RR docstring for why the
# cross-year check specifically mattered.
#
# _LOOKBACK = 15 (previously 10): a rolling window "long enough to
# average out single-candle noise, short enough to still track recent
# (not stale) volatility". The sweep tested 5/10/15/20 and found 15
# robust; 10 (the old default) itself remained a perfectly reasonable
# choice, but 15 showed consistently better per-trade quality (higher
# average R) across every validation stage without sacrificing trade
# count or profitable-period consistency.
_LOOKBACK = 15
# _IMPULSE_MULT = 1.8 (previously 1.5): the impulse candle's range must
# exceed the rolling average range by 80% (was 50%) to count as a
# "strong move" rather than ordinary chop -- a stricter confirmation bar
# than before. The sweep tested 1.2/1.5/1.8/2.1 and found 1.8 robust;
# 1.2 (looser) FAILED its own in-sample walk-forward check outright
# (more signals, but of measurably worse and less consistent quality).
_IMPULSE_MULT = 1.8


def _range(candle: object) -> float:
    return cf(candle, "high") - cf(candle, "low")


def _is_bullish(candle: object) -> bool:
    return cf(candle, "close") > cf(candle, "open")


def _is_bearish(candle: object) -> bool:
    return cf(candle, "close") < cf(candle, "open")


def detect_order_block(candles: list) -> dict | None:
    """Detect the most relevant (most recent) order block zone, or None.

    Returned dict includes `impulse_index` (the confirming impulse
    candle's index, separate from `index`, the base/zone candle) so
    callers can correctly check zone mitigation starting AFTER the
    impulse (see `app.strategy.utils.is_zone_mitigated`) -- checking from
    `index` (the base candle) instead would be wrong: the impulse candle
    that CONFIRMS an order block routinely originates from/overlaps the
    base candle's own range, which would make every fresh order block
    look immediately "mitigated" by its own confirming move.
    """
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
                        "impulse_index": i,
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
                        "impulse_index": i,
                    }
                    break

    return found


def detect_breaker_block(candles: list) -> dict | None:
    """Detect the most relevant breaker block zone, or None.

    A breaker block is a former order block whose zone gets fully closed
    through (price closes past the far side) and is then retested from the
    other side; the same zone shape is returned with `type` flipped.

    Returned dict includes `retest_index` (the candle that confirmed the
    retest, i.e. flipped this into a tradeable breaker) separate from
    `index` (the ORIGINAL order block's base candle) -- needed by callers
    doing zone-mitigation checking (see `app.strategy.utils.is_zone_mitigated`)
    so the "has this breaker already been retested AGAIN since it formed"
    window starts after the retest that confirmed it, not after the
    original (long since irrelevant) order block candle.
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
            return {
                "type": "bearish",
                "top": top,
                "bottom": bottom,
                "index": ob_index,
                "retest_index": m,
            }
        if ob["type"] == "bearish" and low <= top:
            return {
                "type": "bullish",
                "top": top,
                "bottom": bottom,
                "index": ob_index,
                "retest_index": m,
            }

    return None
