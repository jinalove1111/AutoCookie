"""Tests for scripts/research_h6_jade_scarcity_diagnosis.py (H6 diagnostic
harness, docs/HYPOTHESES_ROUND_2.md section 2). scripts/ is a sibling
directory to backend/, not a package under it -- same sys.path pattern
test_research_h5_step0_session_grounding.py / test_research_regime_delay.py
already use.

Pure, I/O-free unit tests for `_same_bar_reject_bucket` (the same-bar
classification every Order Block/Breaker Block step depends on),
`_fvg_bucket` (FVG's own version, needed because `_evaluate_fair_value_gap`'s
reject reason conflates "no zone" and "zone not retraced" into one string),
and `compute_verdict` (H6's pre-registered keep-rule arithmetic). No real
network/candle-fetch call anywhere in this file -- `main()`/`_run_anchor`
(the fetch/walk loop) is exercised only manually via the real script run
recorded in docs/H6_JADE_SCARCITY_RESULTS.md, mirroring
test_research_regime_delay.py's own scope split.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_h6_jade_scarcity_diagnosis import (  # noqa: E402
    _fvg_bucket,
    _same_bar_reject_bucket,
    compute_verdict,
)


def candle(open_: float, high: float, low: float, close: float, ts: str) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "timestamp": ts}


# --- _same_bar_reject_bucket --------------------------------------------------


def test_same_bar_reject_bucket_none_reason_is_candidate_found():
    assert _same_bar_reject_bucket(None) == "candidate_found"


def test_same_bar_reject_bucket_no_matching_order_block():
    assert _same_bar_reject_bucket("no matching order block") == "no_matching_zone"


def test_same_bar_reject_bucket_no_matching_breaker_block():
    assert _same_bar_reject_bucket("no matching breaker block") == "no_matching_zone"


def test_same_bar_reject_bucket_not_retraced_order_block():
    assert (
        _same_bar_reject_bucket("price has not retraced into the order block yet")
        == "zone_exists_not_retraced"
    )


def test_same_bar_reject_bucket_not_retraced_breaker_block():
    assert (
        _same_bar_reject_bucket("price has not retraced into the breaker block yet")
        == "zone_exists_not_retraced"
    )


def test_same_bar_reject_bucket_bias_invalid_fallback():
    assert _same_bar_reject_bucket("bias is neutral or invalid") == "bias_invalid"


# --- _fvg_bucket ----------------------------------------------------------


def _bullish_fvg_base() -> list[dict]:
    # candle[0].high (11) < candle[2].low (13) -> a bullish FVG zone [11, 13],
    # same fixture pattern test_strategy_fvg.py's own bullish-clear-gap test
    # uses.
    return [
        candle(10, 11, 9, 10, "t0"),
        candle(10, 15, 10, 14, "t1"),
        candle(14, 16, 13, 15, "t2"),
    ]


def test_fvg_bucket_no_matching_zone_when_no_gap_exists():
    candles = [candle(10, 11, 9, 10, f"t{i}") for i in range(4)]  # overlapping ranges, no gap
    bucket, result = _fvg_bucket(candles, "bullish")
    assert bucket == "no_matching_zone"
    assert result is None


def test_fvg_bucket_zone_exists_not_retraced_when_last_candle_is_elsewhere():
    # t3 is placed BELOW the [11, 13] zone (no overlap) and deliberately does
    # NOT form a second bullish FVG with (t1, t2) -- t1.high (15) is not below
    # t3.low (4), so the only bullish zone in scope is still the original
    # [11, 13] one, and it goes unretested by this last candle. (t1, t2, t3)
    # does form a BEARISH gap instead, which _fvg_bucket's own type filter
    # (wanted_type="bullish") correctly ignores.
    candles = _bullish_fvg_base() + [candle(5, 6, 4, 5, "t3")]
    bucket, result = _fvg_bucket(candles, "bullish")
    assert bucket == "zone_exists_not_retraced"
    assert result is None


def test_fvg_bucket_candidate_found_when_last_candle_retests_zone():
    candles = _bullish_fvg_base() + [candle(12, 13, 11, 12, "t3")]  # overlaps [11, 13]
    bucket, result = _fvg_bucket(candles, "bullish")
    assert bucket == "candidate_found"
    assert result is not None
    assert result["entry_model"] == "fair_value_gap"


# --- compute_verdict --------------------------------------------------------


def test_compute_verdict_confirmed_when_not_retraced_dominates():
    assert compute_verdict(agg_no_zone=5, agg_not_retraced=10) == "CONFIRMED"


def test_compute_verdict_rejected_when_no_zone_dominates():
    assert compute_verdict(agg_no_zone=10, agg_not_retraced=5) == "REJECTED"


def test_compute_verdict_inconclusive_when_neither_dominates():
    assert compute_verdict(agg_no_zone=10, agg_not_retraced=15) == "INCONCLUSIVE"


def test_compute_verdict_confirmed_at_exact_2x_boundary():
    assert compute_verdict(agg_no_zone=5, agg_not_retraced=10) == "CONFIRMED"


def test_compute_verdict_rejected_at_exact_2x_boundary():
    assert compute_verdict(agg_no_zone=10, agg_not_retraced=5) == "REJECTED"


def test_compute_verdict_both_zero_is_inconclusive():
    assert compute_verdict(agg_no_zone=0, agg_not_retraced=0) == "INCONCLUSIVE"


def test_compute_verdict_only_not_retraced_present_is_confirmed():
    assert compute_verdict(agg_no_zone=0, agg_not_retraced=3) == "CONFIRMED"


def test_compute_verdict_only_no_zone_present_is_rejected():
    assert compute_verdict(agg_no_zone=3, agg_not_retraced=0) == "REJECTED"
