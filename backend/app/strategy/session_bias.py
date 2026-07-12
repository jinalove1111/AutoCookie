"""Jade Session Bias.

Distinct from `session_liquidity.py` (session HIGH/LOW as resting
liquidity levels): this module reports the DIRECTIONAL bias each
completed session itself printed -- did that session's own price action
close higher or lower than it opened. Reuses `session_liquidity.py`'s
`asian_session_high_low`/`london_session_high_low` unmodified (their
`window_start`/`window_end` fields are exactly what's needed to find
that session's own first/last candle) rather than re-deriving session
boundaries a second time.

No spec document defines Jade's exact session-bias methodology; per
operator instruction (2026-07-12: "if any ambiguity exists, implement
the most reasonable ICT/Jade interpretation and document it in
ENGINEERING_DECISIONS.md instead of waiting for approval"), the design
below is that interpretation -- see ENGINEERING_DECISIONS.md #30 for
the full rationale, including why this module deliberately stops at
reporting each session's own observed bias and does NOT attempt to
predict one session's move from another's (e.g. "Asian bullish predicts
London bullish") -- that would be an unevidenced trading rule, not a
definition.
"""

from __future__ import annotations

from .session_liquidity import asian_session_high_low, london_session_high_low
from .utils import cf


def _session_bias_from_window(candles: list, high_low: dict | None) -> str | None:
    if high_low is None:
        return None
    window = [
        c for c in candles
        if high_low["window_start"] <= cf(c, "timestamp") <= high_low["window_end"]
    ]
    if not window:
        return None
    window = sorted(window, key=lambda c: cf(c, "timestamp"))
    open_price = cf(window[0], "open")
    close_price = cf(window[-1], "close")

    if close_price > open_price:
        return "bullish"
    if close_price < open_price:
        return "bearish"
    return "neutral"


def asian_session_bias(candles: list) -> str | None:
    """`"bullish"`/`"bearish"`/`"neutral"` bias printed by the most
    recently COMPLETED Asian session (its first candle's `open` vs. its
    last candle's `close`), or `None` if no completed Asian session
    exists in `candles` yet (mirrors `session_liquidity`'s own `None`
    convention for "nothing found").
    """
    return _session_bias_from_window(candles, asian_session_high_low(candles))


def london_session_bias(candles: list) -> str | None:
    """Mirrors `asian_session_bias` for the London session."""
    return _session_bias_from_window(candles, london_session_high_low(candles))


def session_bias_agreement(candles: list) -> dict:
    """Report whether the most recently completed Asian and London
    sessions agree on direction -- a simple observed FACT about the two
    sessions' own printed bias, not a prediction about what either
    session implies for future price action (see module docstring for
    why this module stops there).

    Returns `{"asian_bias", "london_bias", "agrees"}` -- `agrees` is
    `True` only when both are non-`None` and equal (bullish+bullish or
    bearish+bearish); `False` otherwise, including when either session
    hasn't completed yet or came back `"neutral"`.
    """
    asian = asian_session_bias(candles)
    london = london_session_bias(candles)
    agrees = asian is not None and london is not None and asian == london and asian != "neutral"
    return {"asian_bias": asian, "london_bias": london, "agrees": agrees}
