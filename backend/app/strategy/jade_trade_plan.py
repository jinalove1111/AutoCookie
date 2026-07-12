"""Jade Trade Plan — composes the standalone Jade modules into one result.

`entry_point_engine`, `exit_point_engine`, and `htf_ltf_confluence` are
each independently built and independently tested (ENGINEERING_DECISIONS.md
#23/#24/#25), but until now had no caller connecting them -- a real
caller wanting a full trade plan (entry + targets + HTF confirmation)
had to invoke all three separately and stitch the results together
itself. `build_trade_plan` is that composition: it reuses all three
unmodified, in a fixed pipeline, and adds no detection logic of its own.

HTF Bias Engine wiring (operator directive, 2026-07-12, "Continue ...
1. HTF Bias Engine"): `detect_htf_bias` (`bias.py`) already existed and
was already tested before this module was written -- the actual gap
this closes is that nothing in the new Jade pipeline ever CALLED it;
every Jade module took `bias` as an opaque caller-supplied string
(matching `entry_model.build_entry_model`'s own convention). This is
the one place in the Jade pipeline that computes bias itself, the same
way `SignalEngine.generate_signal` computes it once at the top of ITS
own pipeline and threads it down -- see ENGINEERING_DECISIONS.md #29.

Deliberately still NOT wired into `SignalEngine`/paper trading -- same
"detection-only until a wiring decision is made deliberately" status as
every Jade module before it (see ENGINEERING_DECISIONS.md #23's
"Status" section). See ENGINEERING_DECISIONS.md #28 for why composition
happens here instead of inside `entry_point_engine.find_entry_point`
itself.

Extended (operator directive, 2026-07-12, "6. Any remaining Jade
methodology required for signal generation") to also attach trendline,
CRT, and session-bias context -- see ENGINEERING_DECISIONS.md #33 for
why these three are attached as purely INFORMATIONAL extra fields
(never gating, same discipline as `htf_confluence`) rather than treated
as additional entry requirements.
"""

from __future__ import annotations

from .bias import detect_htf_bias
from .crt import detect_crt_from_previous_candle
from .entry_point_engine import find_entry_point
from .exit_point_engine import find_exit_targets
from .htf_ltf_confluence import evaluate_htf_ltf_confluence
from .session_bias import session_bias_agreement
from .trendline import detect_trendline, detect_trendline_break, detect_trendline_liquidity_sweep


def _safe_session_bias_agreement(candles: list) -> dict | None:
    """`session_bias_agreement` (like every `session_liquidity.py`-based
    detector) needs `timestamp` as a real `datetime` -- see
    `entry_point_engine._session_high_low`'s identical rationale
    (ENGINEERING_DECISIONS.md #27) for why a non-parseable timestamp
    degrades to "unavailable" here too, rather than raising.
    """
    try:
        return session_bias_agreement(candles)
    except (AttributeError, TypeError):
        return None


def build_trade_plan(ltf_candles: list, htf_candles: list) -> dict | None:
    """Build one full Jade trade plan, or `None` if no bias/entry model
    finds a valid setup.

    Pipeline (each step reuses its own module unmodified):
    0. `detect_htf_bias(htf_candles)` -- bias is computed HERE, from the
       real HTF series, not caller-supplied (see module docstring). Per
       `find_entry_point`'s own contract, `"neutral"` bias always
       produces no entry -- checked explicitly here so a neutral HTF
       read short-circuits before any of the other 3 detectors run,
       rather than relying on `find_entry_point` to reject it 5 separate
       times (once per model).
    1. `find_entry_point(ltf_candles, bias)` -- the entry candidate
       (direction, entry model, entry zone, stop loss, confidence, etc).
    2. `find_exit_targets(ltf_candles, direction, entry_price)` --
       take-profit targets, where `entry_price` is the entry zone's
       MIDPOINT (same convention `htf_ltf_confluence` already uses for
       the identical "a zone, but this function needs one price" need --
       see ENGINEERING_DECISIONS.md #25).
    3. `evaluate_htf_ltf_confluence(direction, entry_zone, htf_candles)`
       -- how much the HTF series confirms this specific entry.
    4. `detect_trendline`/`detect_trendline_break`/`detect_trendline_
       liquidity_sweep` on `ltf_candles`, using whichever direction
       ("support" for a long, "resistance" for a short) matches the
       entry -- is there a live trendline dynamic (a break or a
       liquidity sweep) around this exact entry.
    5. `detect_crt_from_previous_candle(ltf_candles)` -- same-timeframe
       CRT reading (does the last candle manipulate/distribute the
       immediately preceding one's range).
    6. `session_bias_agreement(ltf_candles)` -- whether the two most
       recently completed sessions agree on direction (gracefully
       `None` if `ltf_candles` timestamps aren't real `datetime`s, e.g.
       hand-built test fixtures -- see `_safe_session_bias_agreement`).

    Returns the entry result dict (all of `find_entry_point`'s own
    fields, unchanged) with six additional keys: `htf_bias`,
    `exit_targets`, `htf_confluence`, `trendline_signal` (`None`, or
    `{"trendline", "break", "liquidity_sweep"}`), `crt_signal` (`None`,
    or the `detect_crt` result dict), and `session_bias`. None of these
    3 additions can reject the trade -- purely informational, same
    discipline as `htf_confluence` (see ENGINEERING_DECISIONS.md #33).
    """
    bias = detect_htf_bias(htf_candles)
    if bias == "neutral":
        return None

    entry = find_entry_point(ltf_candles, bias)
    if entry is None:
        return None

    entry_zone = entry["entry_zone"]
    entry_price = (entry_zone["top"] + entry_zone["bottom"]) / 2

    exit_targets = find_exit_targets(ltf_candles, entry["direction"], entry_price)["targets"]
    htf_confluence = evaluate_htf_ltf_confluence(entry["direction"], entry_zone, htf_candles)

    trendline_direction = "support" if entry["direction"] == "long" else "resistance"
    trendline = detect_trendline(ltf_candles, trendline_direction)
    trendline_signal = None
    if trendline is not None:
        trendline_signal = {
            "trendline": trendline,
            "break": detect_trendline_break(ltf_candles, trendline),
            "liquidity_sweep": detect_trendline_liquidity_sweep(ltf_candles, trendline),
        }

    crt_signal = detect_crt_from_previous_candle(ltf_candles)
    session_bias = _safe_session_bias_agreement(ltf_candles)

    return {
        **entry,
        "htf_bias": bias,
        "exit_targets": exit_targets,
        "htf_confluence": htf_confluence,
        "trendline_signal": trendline_signal,
        "crt_signal": crt_signal,
        "session_bias": session_bias,
    }
