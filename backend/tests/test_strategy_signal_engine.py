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
    verified in test_strategy_bias.py), then a FRESH impulsive leg that
    creates a bullish FVG nothing else retraces before the final sweep
    candle (see `app.strategy.utils.is_zone_mitigated` -- a zigzag's own
    oscillation legitimately retraces through every gap it creates, which
    is why the zigzag's OWN internal FVGs don't survive to be usable here;
    this fresh trailing leg is deliberately appended, not part of the
    zigzag's regular oscillation), and a final candle that wicks below a
    recent swing low and closes back above it (a real sell-side liquidity
    sweep, the kind of reversal signal that pairs with a bullish bias).
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    candles = [candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))]
    candles.append(candle(31, 32, 29, 31, "t13"))  # fresh leg: prev
    candles.append(candle(31, 40, 30, 39, "t14"))  # fresh leg: impulse
    candles.append(candle(39, 42, 35, 41, "t15"))  # fresh leg: next -> bullish FVG [32, 35]
    # wicks below the swing low at index 8 (value 8) but closes back above it.
    candles.append(candle(9, 10, 6, 9.5, "t16"))
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


def test_signal_engine_refuses_to_re_signal_a_zone_price_has_already_retested():
    """Real regression test for the zone-mitigation fix: reproduces the
    exact real-world pattern found in a live deep backtest (see
    CHANGELOG.md/HANDOFF.md) where ~36% of trades in one sample were
    EXACT duplicate re-entries of a setup that had just been stopped out
    of -- the same still-visible FVG kept re-qualifying as "the most
    recent zone" on the next walk-forward step, even though price had
    already traded back through it.

    Same fixture as the test above (which proves a fresh zone DOES
    signal), extended by two more candles: one that retests the exact
    same FVG zone [32, 35] (simulating price returning to the level after
    a stop-out), then another sweep-shaped candle (mirroring what a real
    walk-forward re-evaluation looks like). Bias/sweep-type conditions are
    otherwise identical to the signal above -- the ONLY thing that changed
    is the zone has now been touched by an intervening candle. Must
    return None, not a second identical-looking signal.
    """
    ltf_candles = _bullish_confluence_candles() + [
        candle(33, 34, 32.5, 33.5, "t17"),  # retests the FVG zone [32, 35]
        candle(9, 10, 6, 9.5, "t18"),  # another sweep-shaped candle
    ]

    signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, ltf_candles)

    assert signal is None


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
