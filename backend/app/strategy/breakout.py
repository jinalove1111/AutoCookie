"""BreakoutStrategy: Donchian-channel breakout with confirmation.

Adaptive platform Milestone 9 (2026-07-16) -- the first of the "new
strategy modules" listed in docs/ADAPTIVE_ARCHITECTURE.md section 7,
milestone 8 ("New strategy modules: Trend Following, Range Trading,
Breakout, Volatility Expansion"), explicitly the LAST item on that
roadmap per the operator's "prefer structural improvements over
parameter optimization... building new strategy CONTENT is secondary to
finishing the system that can host, select, evaluate, and retire
strategies." That hosting system (Strategy Interface, Selection Engine,
Risk Engine hooks, Performance Database tracking) is now built, so this
is the first strategy-CONTENT milestone layered on top of it.

DISCLOSURE (per this repo's "evidence over assumption" discipline,
docs/ADAPTIVE_ARCHITECTURE.md / ENGINEERING_DECISIONS.md): every
threshold below (20-candle channel, 1x ATR body OR 1.5x volume
confirmation, 0.5x ATR stop buffer, 2.5 fixed R:R target) is the
standard, textbook Donchian-channel-breakout ruleset as commonly
described in technical-analysis literature -- DISCLOSED, NOT TUNED. None
of it has been backtested or optimized against this platform's own data.
This is a starting point for the Strategy Selection Engine to route to
and the Performance Database to evaluate on real results, not a claim
that these particular numbers are good. Same posture as every other
"initial, disclosed-not-tuned" threshold already in this codebase (e.g.
section 6.3's auto-disable rule).

The channel/volume-confirmation shape follows
app.regime.regime_detector.is_breakout's existing Donchian-style design
(current close beyond the prior N-candle high/low, gated on volume) --
that function is reused conceptually rather than imported: it only
returns a bool, not the channel/volume values this strategy needs to
build entry/stop/target, so the same approach is reimplemented as a
module-private helper below. Its slicing convention
(`candles[-(lookback + 1):-1]`, excluding the current candle) is kept
deliberately identical to avoid behavioral drift between the two.

Detection only -- never places orders, the same contract every other
Strategy module (strategy_interface.py) and detector in this package
already follows. Not registered in
strategy_interface.AVAILABLE_STRATEGIES -- that wiring is a separate
integration step.
"""

from __future__ import annotations

from .bias import detect_htf_bias
from .signal_engine import TradeSignal
from .utils import average_true_range, cf

_CHANNEL_LOOKBACK = 20
_ATR_LOOKBACK = 14
_BODY_ATR_CONFIRM_MULTIPLIER = 1.0
_VOLUME_CONFIRM_MULTIPLIER = 1.5
_STOP_ATR_BUFFER_MULTIPLIER = 0.5
_RR = 2.5


def _donchian_channel(candles: list, lookback: int = _CHANNEL_LOOKBACK):
    """(channel_high, channel_low, prior_candles) over the `lookback`
    candles immediately BEFORE the current (most recent) one -- same
    exclude-the-current-candle slicing as
    app.regime.regime_detector.is_breakout."""
    prior = candles[-(lookback + 1) : -1]
    channel_high = max(cf(c, "high") for c in prior)
    channel_low = min(cf(c, "low") for c in prior)
    return channel_high, channel_low, prior


def _is_confirmed(current, atr: float, channel_candles: list) -> bool:
    """Body >= 1x ATR(14) OR current volume > 1.5x the average volume of
    the same channel-window candles -- either is sufficient. A close
    beyond the channel with a tiny body AND unremarkable volume is not a
    confirmed breakout, just noise poking through the channel edge."""
    body = abs(cf(current, "close") - cf(current, "open"))
    if body >= _BODY_ATR_CONFIRM_MULTIPLIER * atr:
        return True
    avg_volume = sum(cf(c, "volume") for c in channel_candles) / len(channel_candles)
    current_volume = cf(current, "volume")
    return avg_volume > 0 and current_volume > _VOLUME_CONFIRM_MULTIPLIER * avg_volume


class BreakoutStrategy:
    """Donchian-channel breakout with ATR/volume confirmation (see module
    docstring for the full "disclosed-not-tuned" disclosure). Conforms to
    the Strategy Protocol (strategy_interface.py)."""

    name = "breakout"
    version = "1.0"

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        if len(ltf_candles) < _CHANNEL_LOOKBACK + 1:
            return None

        atr = average_true_range(ltf_candles, lookback=_ATR_LOOKBACK)
        if atr is None:
            return None

        current = ltf_candles[-1]
        channel_high, channel_low, channel_candles = _donchian_channel(ltf_candles)
        close = cf(current, "close")

        if close > channel_high:
            direction = "long"
        elif close < channel_low:
            direction = "short"
        else:
            return None

        if not _is_confirmed(current, atr, channel_candles):
            return None

        entry_price = close
        if direction == "long":
            stop_loss = channel_high - _STOP_ATR_BUFFER_MULTIPLIER * atr
            risk = entry_price - stop_loss
            if risk <= 0:
                return None
            take_profit = entry_price + _RR * risk
        else:
            stop_loss = channel_low + _STOP_ATR_BUFFER_MULTIPLIER * atr
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
