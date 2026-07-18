"""Tests for scripts/research_h7_jade_risk_attribution.py (H7 diagnostic
harness, docs/HYPOTHESES_ROUND_2.md section 3). scripts/ is a sibling
directory to backend/, not a package under it -- same sys.path pattern
every other research-script test file in this suite already uses.

Pure, I/O-free unit tests for `compute_verdict` (H7's pre-registered
keep-rule arithmetic). No real network/candle-fetch/backtest call
anywhere in this file -- `main()`/`_run_anchor` (the fetch/backtest loop)
is exercised only manually via the real script run recorded in
docs/H7_JADE_RISK_ATTRIBUTION_RESULTS.md, mirroring every other research
harness test file's scope split in this suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_h7_jade_risk_attribution import compute_verdict  # noqa: E402


def test_risk_gating_dominant_when_high_reject_rate_and_cap_reason():
    risk_gating, persistence, verdict = compute_verdict(
        reject_rate=0.8, top_reject_reason="trades_today 2 reached MAX_TRADES_PER_DAY 2", pct_of_h6_would_generate=60.0
    )
    assert risk_gating is True
    assert persistence is False
    assert verdict == "RISK_GATING_DOMINANT"


def test_not_risk_gating_dominant_when_top_reason_is_not_the_cap():
    risk_gating, _, verdict = compute_verdict(
        reject_rate=0.9, top_reject_reason="RR 1.2 below minimum 2.0", pct_of_h6_would_generate=60.0
    )
    assert risk_gating is False
    assert verdict == "NEITHER"


def test_not_risk_gating_dominant_when_reject_rate_below_half():
    risk_gating, _, verdict = compute_verdict(
        reject_rate=0.3, top_reject_reason="trades_today 2 reached MAX_TRADES_PER_DAY 2", pct_of_h6_would_generate=60.0
    )
    assert risk_gating is False
    assert verdict == "NEITHER"


def test_persistence_dominant_when_total_signals_small_share_of_h6():
    _, persistence, verdict = compute_verdict(
        reject_rate=0.1, top_reject_reason="RR 1.2 below minimum 2.0", pct_of_h6_would_generate=10.0
    )
    assert persistence is True
    assert verdict == "OPEN_TRADE_PERSISTENCE_DOMINANT"


def test_persistence_not_dominant_at_25_percent_boundary():
    _, persistence, verdict = compute_verdict(
        reject_rate=0.1, top_reject_reason=None, pct_of_h6_would_generate=25.0
    )
    assert persistence is False
    assert verdict == "NEITHER"


def test_both_dominant_reported_honestly():
    risk_gating, persistence, verdict = compute_verdict(
        reject_rate=0.9, top_reject_reason="trades_today 2 reached MAX_TRADES_PER_DAY 2", pct_of_h6_would_generate=10.0
    )
    assert risk_gating is True
    assert persistence is True
    assert verdict == "BOTH"


def test_no_reject_reason_never_confirms_risk_gating():
    risk_gating, _, verdict = compute_verdict(
        reject_rate=1.0, top_reject_reason=None, pct_of_h6_would_generate=90.0
    )
    assert risk_gating is False
    assert verdict == "NEITHER"
