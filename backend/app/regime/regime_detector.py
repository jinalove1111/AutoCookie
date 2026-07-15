"""Market Regime Detector (operator directive, 2026-07-15,
docs/ADAPTIVE_ARCHITECTURE.md section 2): classifies market state into
OBJECTIVE, measurable dimensions -- trend strength, volatility, and
independent event flags (breakout, mean reversion, liquidity sweep
environment) -- never a subjective label. See that document for the full
design rationale (composite output, disclosed-not-tuned thresholds,
every classification carries its own raw metrics for audit -- the same
"show your work, never fabricate an answer" discipline every other
detector in `app.strategy` already follows).

Reuses existing detectors wherever they already exist (ATR, swing
structure, liquidity sweeps/equal-highs-lows) -- only ADX, moving
average/distance-from-MA, and VWAP are new calculations here, and all
three are standard, textbook technical-analysis measures, not novel
indicators (the operator's own instruction named ADX and VWAP directly).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from app.strategy.liquidity import detect_equal_highs, detect_equal_lows, detect_liquidity_sweep
from app.strategy.market_structure import find_swing_highs, find_swing_lows
from app.strategy.utils import average_true_range, cf

# Disclosed, standard textbook thresholds -- NOT backtest-tuned, same
# "reasonable default, explicitly flagged as a starting point" status
# entry_model._RR/_STOP_BUFFER had before their 2026-07-11 sweep
# (ENGINEERING_DECISIONS.md #18). Future work: tune these once enough
# regime-tagged trade history exists (docs/ADAPTIVE_ARCHITECTURE.md
# section 6) to evaluate a change against, not by assumption.
_ADX_STRONG_TREND = 25.0
_ADX_WEAK_TREND = 15.0
_VOLATILITY_HIGH_PERCENTILE = 0.75
_VOLATILITY_LOW_PERCENTILE = 0.25
_MEAN_REVERSION_STDEV_THRESHOLD = 2.0
_LIQUIDITY_SWEEP_ENVIRONMENT_MIN_COUNT = 2


@dataclass
class MarketRegime:
    """Composite classification -- `trend`/`volatility` are each exactly
    one value (a real, mutually-exclusive classification); the three
    flags are independent booleans that can co-occur with any
    trend/volatility combination or each other. `metrics` carries every
    raw value that produced this classification, for audit -- see module
    docstring.
    """

    trend: str  # "strong_trend" | "weak_trend" | "range"
    volatility: str  # "high_volatility" | "normal_volatility" | "low_volatility"
    breakout: bool
    mean_reversion: bool
    liquidity_sweep_environment: bool
    metrics: dict = field(default_factory=dict)


def simple_moving_average(candles: list, lookback: int = 20) -> float | None:
    """Plain SMA of `close` over the most recent `lookback` candles.
    Returns `None` below the minimum history, same discipline as
    `average_true_range`.
    """
    if len(candles) < lookback:
        return None
    closes = [cf(c, "close") for c in candles[-lookback:]]
    return sum(closes) / len(closes)


def distance_from_ma(candles: list, lookback: int = 20) -> float | None:
    """Current close's distance from its own SMA, as a signed fraction of
    the MA (positive = above, negative = below)."""
    ma = simple_moving_average(candles, lookback)
    if ma is None or ma == 0:
        return None
    return (cf(candles[-1], "close") - ma) / ma


def vwap(candles: list, lookback: int = 20) -> float | None:
    """Volume-weighted average price over the most recent `lookback`
    candles. Typical price = (high+low+close)/3, the standard VWAP
    convention when tick-level trade prices aren't available (only OHLCV
    candles are, in this codebase)."""
    if len(candles) < lookback:
        return None
    window = candles[-lookback:]
    total_volume = sum(cf(c, "volume") for c in window)
    if total_volume <= 0:
        return None
    weighted = sum(
        ((cf(c, "high") + cf(c, "low") + cf(c, "close")) / 3) * cf(c, "volume") for c in window
    )
    return weighted / total_volume


def realized_volatility(candles: list, lookback: int = 20) -> float | None:
    """Population stdev of consecutive-candle percent returns over the
    most recent `lookback` candles -- same convention as
    `calculate_sharpe_ratio` (no annualization, disclosed as such).
    """
    if len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1):]
    closes = [cf(c, "close") for c in window]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    return statistics.pstdev(returns) if len(returns) > 1 else None


def volatility_percentile(
    candles: list, vol_lookback: int = 20, percentile_window: int = 100
) -> float | None:
    """Percentile rank (0.0-1.0) of the CURRENT realized volatility
    relative to its own rolling history over `percentile_window` prior
    readings -- percentile-RELATIVE, not an absolute threshold, so the
    same classification logic works across assets with very different
    baseline volatility without per-asset hardcoded numbers (section 2.3
    of docs/ADAPTIVE_ARCHITECTURE.md).
    """
    needed = vol_lookback + percentile_window
    if len(candles) < needed + 1:
        return None
    vol_series = []
    for i in range(len(candles) - percentile_window, len(candles) + 1):
        v = realized_volatility(candles[:i], lookback=vol_lookback)
        if v is not None:
            vol_series.append(v)
    if len(vol_series) < 2:
        return None
    current = vol_series[-1]
    prior = vol_series[:-1]
    return sum(1 for v in prior if v <= current) / len(prior)


def average_directional_index(candles: list, lookback: int = 14) -> float | None:
    """Standard ADX (Wilder's +DM/-DM/TR smoothing). Needs
    `2*lookback + 1` candles for a stable reading. Simplification,
    disclosed not hidden: the final DX->ADX step here is a plain trailing
    average of the last `lookback` DX values rather than Wilder's own
    exact recursive smoothing formula for that specific step -- a
    reasonable, standard approximation, not textbook-exact Wilder
    smoothing end to end.
    """
    if len(candles) < lookback * 2 + 1:
        return None

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high, low = cf(candles[i], "high"), cf(candles[i], "low")
        prev_high, prev_low = cf(candles[i - 1], "high"), cf(candles[i - 1], "low")
        prev_close = cf(candles[i - 1], "close")
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    def wilder_smooth(values: list[float], period: int) -> list[float]:
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + v)
        return smoothed

    smoothed_tr = wilder_smooth(true_ranges, lookback)
    smoothed_plus_dm = wilder_smooth(plus_dm, lookback)
    smoothed_minus_dm = wilder_smooth(minus_dm, lookback)

    dx_values: list[float] = []
    for tr, pdm, mdm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm):
        if tr == 0:
            continue
        plus_di = 100 * (pdm / tr)
        minus_di = 100 * (mdm / tr)
        di_sum = plus_di + minus_di
        dx_values.append(0.0 if di_sum == 0 else 100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < lookback:
        return None
    return sum(dx_values[-lookback:]) / lookback


def swing_trend_direction(candles: list) -> str | None:
    """"up" if the last 2 confirmed swing highs AND the last 2 confirmed
    swing lows are BOTH ascending (a coherent HH+HL structure); "down"
    for the mirror (LH+LL); `None` if there aren't enough confirmed
    swings yet or the pattern is mixed (not a coherent directional
    structure) -- cross-checks the ADX-based trend reading against real
    swing structure (section 2.3: "a high ADX driven by one violent,
    structurally incoherent move" should not alone qualify as
    `strong_trend`).
    """
    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = (cf(candles[i], "high") for i in highs[-2:])
    l1, l2 = (cf(candles[i], "low") for i in lows[-2:])
    if h2 > h1 and l2 > l1:
        return "up"
    if h2 < h1 and l2 < l1:
        return "down"
    return None


def liquidity_sweep_count(candles: list, lookback: int = 20) -> int:
    """How many liquidity-sweep events fired within the most recent
    `lookback` candles. `detect_liquidity_sweep` is point-in-time (only
    checks whether the LAST candle in the list it's given is a sweep), so
    counting occurrences across a window means re-checking with each
    candle in turn as the temporary "last" one -- the same re-scanning
    pattern `BacktestEngine`'s walk-forward loop already uses elsewhere
    in this codebase.
    """
    if len(candles) < lookback + 5:
        return 0
    start = len(candles) - lookback
    return sum(1 for i in range(start, len(candles)) if detect_liquidity_sweep(candles[: i + 1]) is not None)


def equal_level_sweep_count(candles: list, lookback: int = 20) -> int:
    """Equal-highs/equal-lows pairs whose more recent swing point falls
    within the last `lookback` candles -- resting liquidity pools formed
    recently, contributing to a "liquidity sweep environment" alongside
    actual sweep events (section 2.3)."""
    if len(candles) < lookback + 5:
        return 0
    threshold_index = len(candles) - lookback
    zones = detect_equal_highs(candles) + detect_equal_lows(candles)
    return sum(1 for z in zones if z["second_index"] >= threshold_index)


def is_breakout(candles: list, channel_lookback: int = 20, volume_lookback: int = 20) -> bool:
    """Donchian-channel-style breakout: current close beyond the
    highest-high/lowest-low of the preceding `channel_lookback` candles,
    AND current volume above its own recent average -- a break with no
    volume confirmation is not flagged (section 2.3)."""
    needed = max(channel_lookback, volume_lookback) + 1
    if len(candles) < needed:
        return False
    prior = candles[-(channel_lookback + 1) : -1]
    channel_high = max(cf(c, "high") for c in prior)
    channel_low = min(cf(c, "low") for c in prior)
    current_close = cf(candles[-1], "close")
    current_volume = cf(candles[-1], "volume")
    recent_volumes = [cf(c, "volume") for c in candles[-(volume_lookback + 1) : -1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0.0
    broke_out = current_close > channel_high or current_close < channel_low
    volume_confirmed = avg_volume > 0 and current_volume > avg_volume
    return broke_out and volume_confirmed


def is_mean_reversion(candles: list, ma_lookback: int = 20, stdev_threshold: float = _MEAN_REVERSION_STDEV_THRESHOLD) -> bool:
    """True if the current distance-from-MA exceeds `stdev_threshold`
    standard deviations of its OWN recent history -- an extreme,
    self-relative reading (percentile-style, same reasoning as
    `volatility_percentile`), not an absolute distance threshold. Does
    NOT check trend state itself -- the caller (`detect_market_regime`)
    combines this with the trend classification per section 2.3's
    "not concurrent with strong_trend" rule.
    """
    if len(candles) < ma_lookback * 2:
        return False
    distances = []
    for i in range(ma_lookback, len(candles) + 1):
        window = candles[i - ma_lookback : i]
        ma = simple_moving_average(window, ma_lookback)
        if ma is None or ma == 0:
            continue
        distances.append((cf(window[-1], "close") - ma) / ma)
    if len(distances) < 2:
        return False
    current = distances[-1]
    historical = distances[:-1]
    stdev = statistics.pstdev(historical) if len(historical) > 1 else None
    if not stdev:
        return False
    return abs(current) > stdev_threshold * stdev


def detect_market_regime(candles: list) -> MarketRegime | None:
    """Classify the market state as of `candles[-1]` into the composite
    `MarketRegime` (section 2.1). Returns `None` if there isn't enough
    history for a trustworthy classification (ADX and volatility
    percentile are the two REQUIRED inputs; the rest degrade gracefully)
    -- same "insufficient structure, don't fabricate an answer"
    discipline as every other detector in this project.
    """
    adx = average_directional_index(candles)
    vol_pct = volatility_percentile(candles)
    if adx is None or vol_pct is None:
        return None

    atr = average_true_range(candles)
    swing_dir = swing_trend_direction(candles)
    dist_ma = distance_from_ma(candles)
    vwap_value = vwap(candles)

    if adx >= _ADX_STRONG_TREND and swing_dir is not None:
        trend = "strong_trend"
    elif adx >= _ADX_WEAK_TREND:
        trend = "weak_trend"
    else:
        trend = "range"

    if vol_pct >= _VOLATILITY_HIGH_PERCENTILE:
        volatility = "high_volatility"
    elif vol_pct <= _VOLATILITY_LOW_PERCENTILE:
        volatility = "low_volatility"
    else:
        volatility = "normal_volatility"

    breakout = is_breakout(candles)
    mean_reversion = is_mean_reversion(candles) and trend != "strong_trend"
    sweep_env = (
        liquidity_sweep_count(candles) + equal_level_sweep_count(candles)
    ) >= _LIQUIDITY_SWEEP_ENVIRONMENT_MIN_COUNT

    return MarketRegime(
        trend=trend,
        volatility=volatility,
        breakout=breakout,
        mean_reversion=mean_reversion,
        liquidity_sweep_environment=sweep_env,
        metrics={
            "adx": adx,
            "atr": atr,
            "volatility_percentile": vol_pct,
            "swing_trend_direction": swing_dir,
            "distance_from_ma": dist_ma,
            "vwap": vwap_value,
        },
    )
