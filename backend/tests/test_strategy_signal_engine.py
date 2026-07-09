"""Integration test for app.strategy.signal_engine.SignalEngine: ties
bias/liquidity/structure/FVG/order-block detectors together into a real
TradeSignal, using an actual (uncensored) call through every real
sub-detector -- nothing here is mocked.
"""

from __future__ import annotations

from app.strategy.bias import detect_htf_bias
from app.strategy.signal_engine import SignalEngine, TradeSignal


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _bullish_confluence_candles() -> list[dict]:
    """A zigzag series with higher-highs/higher-lows (bullish bias,
    verified in test_strategy_bias.py) plus a final candle that wicks
    below a recent swing low and closes back above it (a real sell-side
    liquidity sweep, the kind of reversal signal that pairs with a
    bullish bias), and several bullish FVGs formed along the way by the
    zigzag's impulsive legs.
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    # wicks below the swing low at index 8 (value 8) but closes back above it.
    candles.append(candle(9, 10, 6, 9.5, "t13"))
    return candles


def _ltf_neutral_with_bullish_setup_candles() -> list[dict]:
    """A LOWER-highs/lower-lows zigzag (the same shape as
    test_strategy_bias.py's bearish fixture) with a final impulsive leg
    appended that creates a real sell-side liquidity sweep and a real
    bullish FVG -- but the appended tail also pulls the series' OWN
    swing-based bias reading down to "neutral" (verified below), i.e.
    NOT bullish. This is deliberate: it proves that when this series is
    used as `ltf_candles` and a genuinely separate bullish series is used
    as `htf_candles`, a resulting "long" signal can only be explained by
    `detect_htf_bias` having been called on the HTF series -- not on this
    one (see test below).
    """
    highs = [10, 11, 30, 11, 9, 11, 25, 11, 9, 11, 20, 11, 9]
    lows = [8, 9, 15, 9, 6, 9, 18, 9, 3, 9, 22, 11, 12]
    base = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    tail = [
        candle(11, 12, 10, 11.5, "t13"),
        candle(11.5, 20, 11, 19, "t14"),  # impulsive bullish leg -> bullish FVG vs t13/t15
        candle(19, 21, 18, 20, "t15"),
        candle(10, 10.5, 5, 9.5, "t16"),  # wicks below a recent swing low, closes back above -> sell_side sweep
    ]
    return base + tail


def _htf_bullish_candles() -> list[dict]:
    """A genuinely separate higher-highs/higher-lows zigzag (bullish bias,
    same shape/verification approach as test_strategy_bias.py's bullish
    fixture, but its own distinct list of candle dicts/timestamps).
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"h{i}") for i, (h, l) in enumerate(zip(highs, lows))]


def test_signal_engine_generates_long_signal_on_real_confluence():
    engine = SignalEngine()
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()
    signal = engine.generate_signal("BTCUSDT", ltf_candles, htf_candles)

    assert isinstance(signal, TradeSignal)
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"
    assert signal.htf_bias == "bullish"
    assert signal.sweep_type == "sell_side"
    assert signal.rr == 2.0
    assert signal.status == "pending"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.fvg_zone is not None


def test_signal_engine_uses_htf_bias_not_ltf_implied_bias():
    """Real regression test for HTF/LTF separation (the actual bug being
    fixed): `ltf_candles` here has a real sell-side sweep and a real
    bullish FVG, but its OWN swing-structure bias is "neutral", not
    "bullish" -- confirmed directly below. If `generate_signal` still fed
    this same list to `detect_htf_bias` (the pre-fix bug: one series used
    for everything), bias would come out "neutral", `build_entry_model`
    would reject it (`bias not in ("bullish", "bearish")`), and no signal
    would be produced. Pairing it with a genuinely separate, bullish
    `htf_candles` series must still produce a real "long" TradeSignal
    whose `htf_bias` is "bullish" -- which can only happen if bias was
    computed from `htf_candles`, not `ltf_candles`. A test that merely
    renamed the old single-series call to use one list for both params
    would not catch a regression back to the old shared-list behavior;
    this one does, because the LTF series alone is deliberately NOT
    bullish.
    """
    ltf_candles = _ltf_neutral_with_bullish_setup_candles()
    htf_candles = _htf_bullish_candles()

    # Sanity checks establishing the premise: the two series really do
    # disagree on bias when evaluated independently.
    assert detect_htf_bias(ltf_candles) == "neutral"
    assert detect_htf_bias(htf_candles) == "bullish"

    signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)

    assert isinstance(signal, TradeSignal)
    assert signal.htf_bias == "bullish"
    assert signal.direction == "long"
    assert signal.sweep_type == "sell_side"


def test_signal_engine_returns_none_on_empty_ltf_candles():
    assert SignalEngine().generate_signal("BTCUSDT", [], _htf_bullish_candles()) is None


def test_signal_engine_returns_none_on_empty_htf_candles():
    assert SignalEngine().generate_signal("BTCUSDT", _bullish_confluence_candles(), []) is None


def test_signal_engine_returns_none_when_no_confluence():
    # A flat, featureless series: no bias, no sweep/choch, no zones.
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(20)]
    assert SignalEngine().generate_signal("BTCUSDT", candles, candles) is None
