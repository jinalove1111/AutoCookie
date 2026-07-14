"""Integration test for app.strategy.signal_engine.SignalEngine: ties
bias/liquidity/structure/FVG/order-block detectors together into a real
TradeSignal, using an actual (uncensored) call through every real
sub-detector -- nothing here is mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.strategy.bias import detect_htf_bias
from app.strategy.market_structure import find_previous_swing_high
from app.strategy.premium_discount import calculate_premium_discount
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
    assert signal.rr == 2.5
    assert signal.status == "pending"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.fvg_zone is not None


def test_generate_signal_require_session_asian_allows_signal_inside_window():
    """require_session="asian" (opt-in, default None -- 2026-07-14
    continuous research mode, docs/CONTINUOUS_RESEARCH_LOG.md experiment
    3) must NOT reject an otherwise-valid signal whose current candle
    falls inside the Asian window (00:00-08:00 UTC, reused unmodified
    from session_liquidity.py)."""
    ltf_candles = _bullish_confluence_candles()
    ltf_candles[-1] = {**ltf_candles[-1], "timestamp": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)}
    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, _bullish_confluence_candles(), require_session="asian"
    )
    assert signal is not None
    assert signal.direction == "long"


def test_generate_signal_require_session_asian_rejects_signal_outside_window():
    """Same fixture, current candle moved to 12:00 UTC (London, not
    Asian) -- must reject even though every other confluence condition
    still holds."""
    ltf_candles = _bullish_confluence_candles()
    ltf_candles[-1] = {**ltf_candles[-1], "timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)}
    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, _bullish_confluence_candles(), require_session="asian"
    )
    assert signal is None


def test_generate_signal_require_session_gracefully_skipped_for_non_datetime_timestamp():
    """Every hand-built fixture in this file uses plain string timestamps
    (e.g. "t16") -- require_session must degrade to "not rejected" rather
    than crash, same convention as session_liquidity.py's other
    timestamp-aware code (ENGINEERING_DECISIONS.md #27)."""
    signal = SignalEngine().generate_signal(
        "BTCUSDT", _bullish_confluence_candles(), _bullish_confluence_candles(), require_session="asian"
    )
    assert signal is not None


def test_generate_signal_require_session_invalid_value_raises():
    with pytest.raises(ValueError):
        SignalEngine().generate_signal(
            "BTCUSDT", _bullish_confluence_candles(), _bullish_confluence_candles(), require_session="tokyo"
        )


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


# --- Breaker Block (opt-in via use_breaker_block, default False -- see
# docs/strategy_coverage_audit.md / docs/ROADMAP.md item #1) ---


def _bearish_breaker_setup_candles() -> list[dict]:
    """LTF series with a real bullish order block (base + confirming
    impulse) that is then closed through and retested from above --
    flipping it into a real BEARISH breaker block (`detect_breaker_block`)
    -- followed by a real buy_side liquidity sweep as the final candle.
    Deliberately has NO other unmitigated bullish/bearish FVG or order
    block: `detect_order_block` still finds the original (now-mitigated,
    per `is_zone_mitigated`) bullish OB, and there are no FVG-forming
    gaps anywhere in this series, so a signal can ONLY come from the
    breaker block when `use_breaker_block=True` -- proving it's a real,
    independent zone source, not incidental.
    """
    # 15 quiet candles (matching order_block._LOOKBACK=15), then the
    # base/impulse/close-through/retest sequence, then the sweep.
    candles = [candle(100, 101, 100, 100.5, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))  # bearish base candle -> bullish OB [99, 101]
    candles.append(candle(100, 111, 99, 110, "t16"))  # bullish impulse confirms the OB
    candles.append(candle(99.4, 99.5, 98.5, 98.6, "t17"))  # closes through bottom (99)
    candles.append(candle(98.6, 99.3, 98.5, 99.2, "t18"))  # retest -> confirms bearish breaker
    # buy_side sweep: wicks above the swing high at 111 (the impulse
    # candle itself) and closes back below it.
    candles.append(candle(110, 112, 105, 110, "t19"))
    return candles


def test_signal_engine_default_ignores_breaker_block():
    """Baseline/contrast: with `use_breaker_block` left at its default
    (`False`), a setup whose ONLY viable zone is a breaker block must
    produce no signal -- the original order block is independently
    mitigated (per the existing OB mitigation check), and there is no
    other zone available.
    """
    ltf_candles = _bearish_breaker_setup_candles()
    htf_candles = _htf_bearish_candles()

    signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)

    assert signal is None


def test_signal_engine_use_breaker_block_true_produces_a_real_short_signal():
    """The SAME setup as the contrast test above, only `use_breaker_block=True`
    -- must now produce a real short TradeSignal off the breaker block."""
    ltf_candles = _bearish_breaker_setup_candles()
    htf_candles = _htf_bearish_candles()

    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, use_breaker_block=True
    )

    assert isinstance(signal, TradeSignal)
    assert signal.direction == "short"
    assert signal.htf_bias == "bearish"
    assert signal.sweep_type == "buy_side"
    assert signal.entry_price == 99  # breaker block's bottom (short entry)
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price
    assert signal.fvg_zone == {
        "type": "bearish",
        "top": 101,
        "bottom": 99,
        "index": 15,
        "retest_index": 18,
    }


# --- require_full_confluence (opt-in strict-confluence mode, resolves
# the docs/strategy_spec.md section 6 spec/code ambiguity -- see
# entry_model.build_entry_model's docstring for the full rationale) ---


def test_signal_engine_require_full_confluence_rejects_sweep_only_real_setup():
    """`_bullish_confluence_candles()` is a REAL setup (through the actual
    detector pipeline, nothing mocked) that produces a signal via sweep
    alone -- `choch_detected` is False for this fixture (confirmed: the
    zigzag's structure never produces a bullish CHoCH here). Under the
    default (loose) confluence rule this signal fires normally (see
    test_signal_engine_generates_long_signal_on_real_confluence). Under
    require_full_confluence=True, the SAME real setup must produce NO
    signal, since choch is missing -- proving the parameter actually
    threads through the real detector pipeline, not just the isolated
    unit tests in test_strategy_entry_model.py.
    """
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()

    baseline_signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)
    assert baseline_signal is not None
    assert baseline_signal.choch_detected is False

    strict_signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, require_full_confluence=True
    )
    assert strict_signal is None


# --- require_ob_fvg_confluence (opt-in OB+FVG confluence mode -- changes
# zone selection from "either zone" to "both agree", see docs/ROADMAP.md
# "Core Rule MVP completion" item #3; see entry_model.build_entry_model's
# require_ob_fvg_confluence docstring for the full rationale) -------------


def test_signal_engine_require_ob_fvg_confluence_rejects_fvg_only_real_setup():
    """`_bullish_confluence_candles()` produces a real signal off its FVG
    alone -- `detect_order_block` finds no order block anywhere in this
    fixture (confirmed: no candle's range ever exceeds the impulse
    threshold against its own rolling lookback average). Under the
    default (loose) rule this signal fires normally (see
    test_signal_engine_generates_long_signal_on_real_confluence). Under
    require_ob_fvg_confluence=True, the SAME real setup must produce NO
    signal, since there is no matching order block -- proving the
    parameter actually threads through the real detector pipeline, not
    just the isolated unit tests in test_strategy_entry_model.py.
    """
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()

    baseline_signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)
    assert baseline_signal is not None

    strict_signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, require_ob_fvg_confluence=True
    )
    assert strict_signal is None


def _bullish_ob_and_fvg_confluence_candles() -> list[dict]:
    """LTF series with a REAL, unmitigated bullish order block AND a
    REAL, unmitigated bullish FVG both present at once (unlike
    `_bullish_confluence_candles()`, which only ever produces an FVG) --
    15 quiet candles (matching order_block._LOOKBACK=15), a base/impulse
    pair confirming a bullish order block, a small local pullback/rally
    that both re-triggers a second (still bullish, still matching)
    order block and forms a genuine local swing low, a later 3-candle
    leg that opens a bullish FVG well above that order block (so neither
    zone mitigates the other), and a final candle that wicks below the
    local swing low and closes back above it (a real sell-side sweep).
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))  # bearish base -> bullish OB [99, 101]
    candles.append(candle(100, 111, 99, 110, "t16"))  # bullish impulse confirms it
    candles.append(candle(110, 111, 109.5, 110.5, "t17"))
    candles.append(candle(110.5, 112, 110, 111.5, "t18"))
    candles.append(candle(111.5, 112, 108.5, 109, "t19"))  # local swing low forming ~108.5
    candles.append(candle(109, 111, 108.8, 110.5, "t20"))
    candles.append(candle(110.5, 114, 110, 113.5, "t21"))  # FVG prev (high 114)
    candles.append(candle(113.5, 116, 113, 115.5, "t22"))  # FVG middle (irrelevant to the gap)
    candles.append(candle(115.5, 119, 118, 118.5, "t23"))  # FVG next (low 118) -> bullish FVG [114, 118]
    # wicks below the local swing low (108.5 at index 19) but closes back above it.
    candles.append(candle(109.5, 110, 108, 109.8, "t24"))
    return candles


def test_signal_engine_require_ob_fvg_confluence_accepts_real_ob_and_fvg_both_present():
    """The SAME strict mode as the rejection test above, only now the LTF
    series has a genuinely matching order block AND FVG both present --
    must still produce a real long TradeSignal, proving the stricter mode
    narrows what's accepted without breaking the case it's designed to
    require.
    """
    ltf_candles = _bullish_ob_and_fvg_confluence_candles()
    htf_candles = _htf_bullish_candles()

    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, require_ob_fvg_confluence=True
    )

    assert isinstance(signal, TradeSignal)
    assert signal.direction == "long"
    assert signal.htf_bias == "bullish"
    assert signal.sweep_type == "sell_side"
    assert signal.stop_loss < signal.entry_price < signal.take_profit


# --- use_structure_tp (opt-in structure-based take-profit, see
# docs/ROADMAP.md "Core Rule MVP completion" item #4; see
# entry_model.build_entry_model's use_structure_tp docstring for the full
# rationale) -------------------------------------------------------------


def test_signal_engine_use_structure_tp_falls_back_to_fixed_rr_on_real_stale_structure():
    """`_bullish_confluence_candles()` is a REAL setup (through the actual
    detector pipeline, nothing mocked) whose own most-recent confirmed
    previous swing high (30) and premium/discount equilibrium (19.0) are
    BOTH already behind the eventual entry price (35, confirmed directly
    below) -- real, structurally stale detector output, not a missing
    one. use_structure_tp=True must fall back to the exact same fixed-RR
    signal as the default call, proving the parameter threads through the
    real detector pipeline (find_previous_swing_high/find_previous_swing_low/
    calculate_premium_discount) and degrades gracefully rather than
    corrupting a valid entry with a stale target.
    """
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()

    baseline_signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)
    assert baseline_signal is not None
    # Premise: real detector output on this fixture is already behind entry.
    assert find_previous_swing_high(ltf_candles)["price"] < baseline_signal.entry_price
    assert calculate_premium_discount(ltf_candles)["equilibrium"] < baseline_signal.entry_price

    structure_signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, use_structure_tp=True
    )

    assert structure_signal is not None
    assert structure_signal.take_profit == baseline_signal.take_profit
    assert structure_signal.rr == baseline_signal.rr == 2.5


def _htf_bearish_candles() -> list[dict]:
    """Real lower-highs/lower-lows zigzag (bearish bias, same shape
    verified directly in test_strategy_bias.py), independent series from
    the LTF fixture above."""
    highs = [10, 11, 30, 11, 9, 11, 25, 11, 9, 11, 20, 11, 9]
    lows = [8, 9, 15, 9, 6, 9, 18, 9, 3, 9, 22, 11, 12]
    return [candle((h + l) / 2, h, l, (h + l) / 2, f"h{i}") for i, (h, l) in enumerate(zip(highs, lows))]


# --- require_premium_discount_filter (opt-in entry-quality filter, see
# docs/strategy_spec.md section 8; see entry_model.build_entry_model's
# require_premium_discount_filter docstring for the full rationale) -------


def test_signal_engine_premium_discount_filter_unaffected_when_already_in_discount():
    """`_bullish_confluence_candles()` is a real long setup whose final
    (sweep) candle closes at 9.5, well below the real swing range's
    equilibrium (19.0, confirmed directly below) -- i.e. price is
    genuinely in the DISCOUNT half, exactly where a long is supposed to
    come from. Enabling the filter on this real setup must change
    nothing.
    """
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()

    baseline_signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)
    assert baseline_signal is not None
    assert calculate_premium_discount(ltf_candles)["zone"] == "discount"

    filtered_signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, require_premium_discount_filter=True
    )

    assert filtered_signal is not None
    assert filtered_signal.take_profit == baseline_signal.take_profit


def test_signal_engine_premium_discount_filter_rejects_real_long_from_premium():
    """SAME fixture shape, only the final (sweep) candle's close is
    raised to 25 (still wicks below the swing low at 6, still closes
    back above it -- a real sell-side sweep, unaffected) -- which pushes
    the real swing range's classification to PREMIUM (confirmed
    directly below: equilibrium is still 19.0, 25 > 19.0). The default
    call still produces a real long signal (buying the expensive half);
    require_premium_discount_filter=True must reject it.
    """
    highs = [10, 11, 20, 11, 9, 11, 25, 11, 9, 11, 30, 11, 9]
    lows = [8, 9, 15, 9, 5, 9, 18, 9, 8, 9, 22, 11, 12]
    ltf_candles = [
        candle((h + l) / 2, h, l, (h + l) / 2, f"t{i}") for i, (h, l) in enumerate(zip(highs, lows))
    ]
    ltf_candles.append(candle(31, 32, 29, 31, "t13"))
    ltf_candles.append(candle(31, 40, 30, 39, "t14"))
    ltf_candles.append(candle(39, 42, 35, 41, "t15"))
    ltf_candles.append(candle(9, 26, 6, 25, "t16"))  # sweep candle, closes at 25 (premium)
    htf_candles = ltf_candles

    premium_discount = calculate_premium_discount(ltf_candles)
    assert premium_discount["zone"] == "premium"
    assert premium_discount["equilibrium"] == 19.0

    baseline_signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)
    assert baseline_signal is not None
    assert baseline_signal.direction == "long"

    filtered_signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, require_premium_discount_filter=True
    )
    assert filtered_signal is None


# --- use_jade_engine (opt-in full Jade methodology path, see
# ENGINEERING_DECISIONS.md #34 for the full field-mapping rationale) -----


def _jade_ltf_order_block_fvg_candles() -> list[dict]:
    """Real OB+FVG-overlap fixture (verified in
    test_strategy_entry_point_engine.py/test_strategy_jade_trade_plan.py):
    confidence-5 order_block entry, zone [99, 101].
    """
    candles = [candle(100, 100.5, 99.5, 100.2, f"t{i}") for i in range(15)]
    candles.append(candle(101, 101, 99, 99, "t15"))
    candles.append(candle(100, 111, 99, 110, "t16"))
    candles.append(candle(97, 98, 96, 97.5, "tA"))
    candles.append(candle(97.5, 105, 97, 104, "tB"))
    candles.append(candle(104, 106, 100, 105, "tC"))
    candles.append(candle(100, 101, 99.5, 100, "tD"))
    return candles


def test_generate_signal_use_jade_engine_default_false_unaffected():
    """Default `use_jade_engine=False` must go through the exact
    legacy pipeline, unaffected by this parameter's mere existence --
    `jade_plan` on the returned signal must be `None`.
    """
    ltf_candles = _bullish_confluence_candles()
    htf_candles = _bullish_confluence_candles()

    signal = SignalEngine().generate_signal("BTCUSDT", ltf_candles, htf_candles)

    assert signal is not None
    assert signal.jade_plan is None


def test_generate_signal_use_jade_engine_produces_a_real_signal():
    ltf_candles = _jade_ltf_order_block_fvg_candles()
    htf_candles = _htf_bullish_candles()

    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, use_jade_engine=True
    )

    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"
    assert signal.htf_bias == "bullish"
    assert signal.sweep_type is None
    assert signal.choch_detected is False
    assert signal.fvg_zone == {"top": 101, "bottom": 99}
    assert signal.entry_price == 101
    assert signal.status == "pending"
    # Real ordering: this exact bug (take_profit landing on the wrong
    # side of entry_price) was caught and fixed during this integration.
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.rr == abs(signal.take_profit - signal.entry_price) / abs(
        signal.entry_price - signal.stop_loss
    )
    assert signal.jade_plan is not None
    assert signal.jade_plan["entry_model"] == "order_block"
    assert signal.jade_plan["confidence_score"] == 5


def test_generate_signal_use_jade_engine_none_when_no_entry_found():
    # Gently rising, heavily overlapping ranges: no entry model finds
    # anything -- same fixture used throughout entry_point_engine's own
    # "nothing matches" tests.
    ltf_candles = [
        candle(100 + i * 0.1, 100 + i * 0.1 + 1, 100 + i * 0.1 - 1, 100 + i * 0.1 + 0.5, f"t{i}")
        for i in range(20)
    ]
    signal = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, _htf_bullish_candles(), use_jade_engine=True
    )
    assert signal is None


def test_generate_signal_use_jade_engine_none_on_neutral_htf_bias():
    htf_candles = [candle(100, 100.5, 99.5, 100.2, f"h{i}") for i in range(20)]
    signal = SignalEngine().generate_signal(
        "BTCUSDT", _jade_ltf_order_block_fvg_candles(), htf_candles, use_jade_engine=True
    )
    assert signal is None


def test_generate_signal_use_jade_engine_ignores_legacy_only_parameters():
    """`use_jade_engine=True` bypasses the entire legacy pipeline, so
    legacy-only flags like `require_full_confluence` must have zero
    effect on the Jade path's result.
    """
    ltf_candles = _jade_ltf_order_block_fvg_candles()
    htf_candles = _htf_bullish_candles()

    plain = SignalEngine().generate_signal(
        "BTCUSDT", ltf_candles, htf_candles, use_jade_engine=True
    )
    with_legacy_flags = SignalEngine().generate_signal(
        "BTCUSDT",
        ltf_candles,
        htf_candles,
        use_jade_engine=True,
        require_full_confluence=True,
        require_ob_fvg_confluence=True,
        use_breaker_block=True,
    )

    assert plain.entry_price == with_legacy_flags.entry_price
    assert plain.take_profit == with_legacy_flags.take_profit
