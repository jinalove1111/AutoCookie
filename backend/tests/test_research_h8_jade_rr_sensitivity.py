"""Tests for scripts/research_h8_jade_rr_sensitivity.py (H8 diagnostic
harness, docs/HYPOTHESES_ROUND_2.md section 4). scripts/ is a sibling
directory to backend/, not a package under it -- same sys.path pattern
every other research-script test file in this suite already uses.

Pure, I/O-free unit tests for `compute_verdict` (H8's pre-registered
keep-rule arithmetic) and `stop_loss_for_choice`'s no-stop_model-parameter
fallback (Order Block/Premium-Discount/Liquidity Raid always return the
already-computed default, regardless of `stop_choice` -- a trivial,
unconditional early return that needs no detector fixture to verify).
`stop_loss_for_choice`'s FVG/Breaker Block re-evaluation paths and
`_run_anchor`/`main()` (the fetch/walk loop) are exercised only manually
via the real script run recorded in
docs/H8_JADE_RR_SENSITIVITY_RESULTS.md, mirroring every other research
harness test file's scope split in this suite -- `_evaluate_fair_value_gap`/
`_evaluate_breaker_block` are themselves already covered by
test_strategy_fvg.py/test_strategy_order_block.py, and H8 calls them
completely unmodified.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_h8_jade_rr_sensitivity import compute_verdict, stop_loss_for_choice  # noqa: E402


# --- compute_verdict --------------------------------------------------------


def test_structural_when_best_alt_below_quarter():
    assert compute_verdict(baseline_qualify_rate=0.05, best_alt_qualify_rate=0.10) == "STRUCTURAL"


def test_structural_at_exact_below_boundary():
    assert compute_verdict(baseline_qualify_rate=0.01, best_alt_qualify_rate=0.2499) == "STRUCTURAL"


def test_parameter_sensitive_when_best_alt_clears_floor_and_doubles_baseline():
    assert compute_verdict(baseline_qualify_rate=0.10, best_alt_qualify_rate=0.30) == "PARAMETER_SENSITIVE"


def test_parameter_sensitive_at_exact_2x_boundary():
    assert compute_verdict(baseline_qualify_rate=0.15, best_alt_qualify_rate=0.30) == "PARAMETER_SENSITIVE"


def test_inconclusive_when_best_alt_clears_floor_but_not_double_baseline():
    assert compute_verdict(baseline_qualify_rate=0.20, best_alt_qualify_rate=0.30) == "INCONCLUSIVE"


def test_parameter_sensitive_when_baseline_is_zero_and_best_alt_clears_floor():
    # baseline=0 -> 2x baseline is 0, so any best_alt >= 0.25 clears both conditions.
    assert compute_verdict(baseline_qualify_rate=0.0, best_alt_qualify_rate=0.25) == "PARAMETER_SENSITIVE"


# --- stop_loss_for_choice: no-stop_model-parameter fallback -----------------


def test_order_block_always_falls_back_to_default_stop_loss():
    for choice in ("aggressive", "moderate", "conservative"):
        result = stop_loss_for_choice(
            "order_block", ltf_slice=[], bias="bullish", default_stop_loss=100.0, stop_choice=choice
        )
        assert result == 100.0


def test_premium_discount_always_falls_back_to_default_stop_loss():
    for choice in ("aggressive", "moderate", "conservative"):
        result = stop_loss_for_choice(
            "premium_discount", ltf_slice=[], bias="bullish", default_stop_loss=42.5, stop_choice=choice
        )
        assert result == 42.5


def test_liquidity_raid_always_falls_back_to_default_stop_loss():
    for choice in ("aggressive", "moderate", "conservative"):
        result = stop_loss_for_choice(
            "liquidity_raid", ltf_slice=[], bias="bearish", default_stop_loss=7.0, stop_choice=choice
        )
        assert result == 7.0
