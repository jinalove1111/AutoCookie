"""VolatilityExpansionStrategy: squeeze -> expansion-bar entry.

Adaptive platform Milestone 9 (2026-07-16) -- the last of the "new
strategy modules" listed in docs/ADAPTIVE_ARCHITECTURE.md section 7,
milestone 8 ("New strategy modules: Trend Following, Range Trading,
Breakout, Volatility Expansion"), explicitly LAST on that roadmap per the
operator's "prefer structural improvements over parameter optimization...
building new strategy CONTENT is secondary to finishing the system that
can host, select, evaluate, and retire strategies." That hosting system
(Strategy Interface, Selection Engine, Risk Engine hooks, Performance
Database tracking) is already built; this is strategy-CONTENT layered on
top of it, same as its Trend Following / Range Trading / Breakout
siblings in this package.

DISCLOSURE (per this repo's "evidence over assumption" discipline,
docs/ADAPTIVE_ARCHITECTURE.md / ENGINEERING_DECISIONS.md): the squeeze
percentile floor, the 2.0x ATR expansion-bar threshold, and the fixed
2.5R target below are the standard, textbook volatility-expansion
("squeeze then breakout") ruleset as commonly described in
technical-analysis literature -- DISCLOSED, NOT TUNED. None of it has
been backtested or optimized against this platform's own data. This is a
starting point for the Strategy Selection Engine to route to and the
Performance Database to evaluate on real results, not a claim that these
particular numbers are good.

Reuses `app.regime.regime_detector.volatility_percentile` (the squeeze
read) and `app.strategy.utils.average_true_range` (the expansion-bar
read) rather than reimplementing either indicator -- same reuse
discipline every other module in this package already follows. This
strategy passes a narrower `percentile_window` (50, not
`volatility_percentile`'s own 100 default) so the squeeze read stays
responsive to recent LTF volatility regime shifts rather than a full
100-reading history; that window choice is itself a plain, disclosed
parameter pick, not a tuned one.

Detection only -- never places orders, the same contract every other
Strategy module (strategy_interface.py) and detector in this package
already follows. Not registered in strategy_interface.AVAILABLE_STRATEGIES
-- that wiring is a separate integration step.
"""

from __future__ import annotations

from app.regime.regime_detector import volatility_percentile

from .bias import detect_htf_bias
from .signal_engine import TradeSignal
from .utils import average_true_range, cf

_VOL_LOOKBACK = 20
_PERCENTILE_WINDOW = 50
_SQUEEZE_PERCENTILE_CEILING = 0.25  # bottom 25% of recent vol history = compressed
_ATR_LOOKBACK = 14
_EXPANSION_ATR_MULTIPLIER = 2.0
_RR = 2.5
_MIN_CANDLES = _VOL_LOOKBACK + _PERCENTILE_WINDOW + 2  # +1 for volatility_percentile's own
# minimum, +1 because the squeeze read excludes the current (most recent) candle


def _is_squeezed(prior_candles: list) -> bool:
    """True if `volatility_percentile` on `prior_candles` (everything
    BEFORE the current candle) ranks in the bottom
    `_SQUEEZE_PERCENTILE_CEILING` of its own recent history -- i.e.
    volatility was compressed going into the current candle. False (not
    None) whenever the helper itself returns None (insufficient history),
    matching this module's "return None generously" contract at the
    caller."""
    vp = volatility_percentile(
        prior_candles, vol_lookback=_VOL_LOOKBACK, percentile_window=_PERCENTILE_WINDOW
    )
    return vp is not None and vp <= _SQUEEZE_PERCENTILE_CEILING


def _true_range(current, prev_close: float) -> float:
    high = cf(current, "high")
    low = cf(current, "low")
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


class VolatilityExpansionStrategy:
    """Squeeze (compressed realized volatility, bottom 25th percentile of
    its own recent history) followed by an expansion bar (true range >=
    2.0x ATR(14), both measured on the candles BEFORE the current one) --
    the expansion candle's own direction sets the trade direction, its
    opposite extreme sets the stop, and a fixed 2.5R sets the target. See
    module docstring for the disclosed-not-tuned status of every
    threshold used here. Detection only -- never places orders.
    """

    name = "volatility_expansion"
    version = "1.0"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        """Return an expansion-bar `TradeSignal`, or None generously --
        insufficient history, a `volatility_percentile`/`average_true_range`
        None result, no squeeze, no expansion bar, a doji expansion candle,
        or a zero/negative stop distance. Never raises on short/odd input.
        """
        if len(ltf_candles) < _MIN_CANDLES:
            return None

        prior_candles = ltf_candles[:-1]
        if not _is_squeezed(prior_candles):
            return None

        prior_atr = average_true_range(prior_candles, lookback=_ATR_LOOKBACK)
        if prior_atr is None or prior_atr <= 0:
            return None

        current = ltf_candles[-1]
        prev_close = cf(ltf_candles[-2], "close")
        true_range = _true_range(current, prev_close)
        if true_range < _EXPANSION_ATR_MULTIPLIER * prior_atr:
            return None

        open_ = cf(current, "open")
        close = cf(current, "close")
        if close > open_:
            direction = "long"
        elif close < open_:
            direction = "short"
        else:
            return None  # doji -- no clear expansion direction

        entry_price = close
        if direction == "long":
            stop_loss = cf(current, "low")
            risk = entry_price - stop_loss
            if risk <= 0:
                return None
            take_profit = entry_price + _RR * risk
        else:
            stop_loss = cf(current, "high")
            risk = stop_loss - entry_price
            if risk <= 0:
                return None
            take_profit = entry_price - _RR * risk

        rr = abs(take_profit - entry_price) / risk

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            timestamp=cf(current, "timestamp"),
            htf_bias=detect_htf_bias(htf_candles),
            sweep_type=None,
            choch_detected=False,
            fvg_zone=None,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr=rr,
            status="pending",
        )
