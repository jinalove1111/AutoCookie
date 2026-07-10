"""Tests for scripts/run_backtest.py's pure, network-free helper
functions (split_into_periods, walk_forward_report). scripts/ is a
sibling directory to backend/, not a package under it, so it's added to
sys.path explicitly here -- these functions were previously verified
only via real manual CLI runs (see CHANGELOG.md/HANDOFF.md), with no
pytest coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_backtest import split_into_periods, walk_forward_report  # noqa: E402


def _result(pnl: float):
    """Minimal stand-in for BacktestResult -- walk_forward_report only
    reads `.total_pnl`."""
    return SimpleNamespace(total_pnl=pnl)


# --- split_into_periods ------------------------------------------------


def test_split_into_periods_one_period_returns_all_candles_unsplit():
    candles = list(range(10))
    assert split_into_periods(candles, periods=1) == [candles]


def test_split_into_periods_divides_evenly():
    candles = list(range(9))
    chunks = split_into_periods(candles, periods=3)
    assert chunks == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]


def test_split_into_periods_remainder_goes_to_last_chunk():
    candles = list(range(10))
    chunks = split_into_periods(candles, periods=3)
    # 10 // 3 == 3, so chunks 1-2 get 3 each, last chunk absorbs the remainder (4).
    assert chunks == [[0, 1, 2], [3, 4, 5], [6, 7, 8, 9]]
    assert sum(len(c) for c in chunks) == len(candles)


# --- walk_forward_report -------------------------------------------------


def test_walk_forward_report_passes_when_consistently_profitable():
    results = [_result(p) for p in [100, 120, 90, 110, 105, 95]]
    wf = walk_forward_report(results)

    assert wf["periods"] == 6
    assert wf["profitable_periods"] == 6
    assert wf["profitable_ratio"] == 1.0
    assert wf["max_losing_streak"] == 0
    assert wf["degrading"] is False
    assert wf["passed"] is True


def test_walk_forward_report_fails_on_low_profitable_ratio():
    # 2 of 6 profitable = 33% < default 66% criterion.
    results = [_result(p) for p in [100, -50, -50, 100, -50, -50]]
    wf = walk_forward_report(results)

    assert wf["profitable_ratio"] == pytest.approx(2 / 6)
    assert wf["passed"] is False


def test_walk_forward_report_fails_on_losing_streak():
    # 6 of 9 profitable (66.7% >= 66% ratio criterion passes), but 3
    # consecutive losses violates the default max_losing_streak=2
    # criterion even though the ratio criterion alone would pass.
    results = [_result(p) for p in [100, 100, 100, -10, -10, -10, 100, 100, 100]]
    wf = walk_forward_report(results)

    assert wf["profitable_ratio"] >= 0.66
    assert wf["max_losing_streak"] == 3
    assert wf["passed"] is False


def test_walk_forward_report_flags_degradation_from_positive_first_half():
    # First half avg = 100, second half avg = 40 -- a 60% falloff, past
    # the 50%-retention threshold.
    results = [_result(p) for p in [100, 100, 100, 40, 40, 40]]
    wf = walk_forward_report(results)

    assert wf["first_half_avg_pnl"] == pytest.approx(100.0)
    assert wf["second_half_avg_pnl"] == pytest.approx(40.0)
    assert wf["degrading"] is True
    assert wf["passed"] is False


def test_walk_forward_report_does_not_flag_mild_decline_as_degrading():
    # Second half retains more than 50% of the first half's average --
    # not flagged as degrading even though it's somewhat lower.
    results = [_result(p) for p in [100, 100, 100, 80, 80, 80]]
    wf = walk_forward_report(results)

    assert wf["degrading"] is False


def test_walk_forward_report_odd_period_count_excludes_middle_from_halves():
    # 5 periods: half = 2. First half = periods[:2], second half = periods[3:5]
    # (index 2, the middle period, is excluded from both).
    results = [_result(p) for p in [100, 100, 999, 50, 50]]
    wf = walk_forward_report(results)

    assert wf["first_half_avg_pnl"] == pytest.approx(100.0)
    assert wf["second_half_avg_pnl"] == pytest.approx(50.0)


def test_walk_forward_report_raises_for_fewer_than_two_periods():
    with pytest.raises(ValueError, match="at least 2 periods"):
        walk_forward_report([_result(100)])
