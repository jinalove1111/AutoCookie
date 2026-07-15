"""Tests for app.strategy.volatility_expansion.VolatilityExpansionStrategy
(adaptive platform Milestone 9, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
section 7 milestone 8's "New strategy modules" list): squeeze -> expansion
-bar entry, detection only.

Fixtures are synthetic and deterministic, built to exercise the module's
own thresholds directly rather than relying on any historical/real data:

- `_squeeze_prior_candles`: an oscillating price series whose per-candle
  amplitude DECAYS from `start_amp` down toward ~0 across the window, so
  `volatility_percentile` (computed on 21-candle sliding sub-windows) is
  monotonically decreasing -- the most recent reading ends up ranking at
  (or near) the 0th percentile of its own history, i.e. a genuine squeeze
  by the module's own bottom-25th-percentile rule.
- `_flat_prior_candles`: the same oscillation shape but with CONSTANT
  amplitude (no decay), so every sliding-window volatility reading is
  equal and the most recent reading ranks at the TOP of its own history
  (percentile 1.0) -- deliberately NOT a squeeze, used to prove the
  precondition is actually enforced.

Both were verified directly against `volatility_percentile` before use
here (0.0 and 1.0 respectively, with the module's own `vol_lookback=20`,
`percentile_window=50`), not assumed.
"""

from __future__ import annotations

from app.strategy.strategy_interface import Strategy
from app.strategy.volatility_expansion import VolatilityExpansionStrategy


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


def _squeeze_prior_candles(n: int = 71, start_amp: float = 5.0, prefix: str = "p") -> list[dict]:
    """71 candles (the module's own minimum for a non-None
    `volatility_percentile` read at `vol_lookback=20`/`percentile_window=50`)
    with decaying oscillation amplitude -- a genuine volatility squeeze
    into the most recent candle, verified as such (percentile 0.0) before
    use in these tests.
    """
    candles = []
    price = 100.0
    for i in range(n):
        amplitude = max(0.01, start_amp * (1 - i / n))
        direction = 1 if i % 2 == 0 else -1
        move = direction * amplitude
        open_ = price
        close = price + move
        high = max(open_, close) + 0.01
        low = min(open_, close) - 0.01
        candles.append(candle(open_, high, low, close, f"{prefix}{i}"))
        price = close
    return candles


def _flat_prior_candles(n: int = 71, amp: float = 2.0, prefix: str = "f") -> list[dict]:
    """Same shape as `_squeeze_prior_candles` but constant amplitude --
    deliberately NOT a squeeze (verified percentile 1.0), used to prove
    the squeeze precondition is enforced rather than always satisfied.
    """
    candles = []
    price = 100.0
    for i in range(n):
        direction = 1 if i % 2 == 0 else -1
        move = direction * amp
        open_ = price
        close = price + move
        high = max(open_, close) + 0.01
        low = min(open_, close) - 0.01
        candles.append(candle(open_, high, low, close, f"{prefix}{i}"))
        price = close
    return candles


def test_squeeze_then_bullish_expansion_bar_produces_long_signal():
    prior = _squeeze_prior_candles()
    last_close = prior[-1]["close"]
    # true range ~3.2, comfortably >= 2.0 * ATR(14) (~0.55) on the prior tail
    expansion = candle(last_close, last_close + 3.1, last_close - 0.1, last_close + 3.0, "cur")
    ltf = prior + [expansion]

    signal = VolatilityExpansionStrategy().generate_signal("BTCUSDT", ltf, [])

    assert signal is not None
    assert signal.direction == "long"
    assert signal.status == "pending"
    assert signal.entry_price == expansion["close"]
    assert signal.stop_loss == expansion["low"]
    assert signal.take_profit > signal.entry_price
    assert signal.rr == 2.5
    assert signal.timestamp == "cur"


def test_squeeze_then_bearish_expansion_bar_produces_short_signal():
    prior = _squeeze_prior_candles(prefix="q")
    last_close = prior[-1]["close"]
    expansion = candle(last_close, last_close + 0.1, last_close - 3.1, last_close - 3.0, "cur2")
    ltf = prior + [expansion]

    signal = VolatilityExpansionStrategy().generate_signal("BTCUSDT", ltf, [])

    assert signal is not None
    assert signal.direction == "short"
    assert signal.status == "pending"
    assert signal.entry_price == expansion["close"]
    assert signal.stop_loss == expansion["high"]
    assert signal.take_profit < signal.entry_price
    assert signal.rr == 2.5


def test_expansion_bar_without_preceding_squeeze_returns_none():
    """Same big expansion bar as the passing cases, but the prior history
    has CONSTANT (not decaying) amplitude -- not a squeeze by the
    module's own bottom-25th-percentile rule -- so no signal fires."""
    prior = _flat_prior_candles()
    last_close = prior[-1]["close"]
    expansion = candle(last_close, last_close + 3.1, last_close - 0.1, last_close + 3.0, "cur3")
    ltf = prior + [expansion]

    assert VolatilityExpansionStrategy().generate_signal("BTCUSDT", ltf, []) is None


def test_squeeze_without_expansion_bar_returns_none():
    """Genuine squeeze precondition met, but the current candle's true
    range is far too small to qualify as an expansion bar."""
    prior = _squeeze_prior_candles(prefix="s")
    last_close = prior[-1]["close"]
    small = candle(last_close, last_close + 0.15, last_close - 0.15, last_close + 0.1, "cur4")
    ltf = prior + [small]

    assert VolatilityExpansionStrategy().generate_signal("BTCUSDT", ltf, []) is None


def test_insufficient_history_returns_none():
    ltf = _flat_prior_candles(n=10)
    assert VolatilityExpansionStrategy().generate_signal("BTCUSDT", ltf, []) is None


def test_empty_candles_does_not_raise():
    assert VolatilityExpansionStrategy().generate_signal("BTCUSDT", [], []) is None


def test_volatility_expansion_strategy_satisfies_the_protocol():
    assert isinstance(VolatilityExpansionStrategy(), Strategy)


def test_volatility_expansion_strategy_name_and_version():
    strategy = VolatilityExpansionStrategy()
    assert strategy.name == "volatility_expansion"
    assert strategy.version == "1.0"
