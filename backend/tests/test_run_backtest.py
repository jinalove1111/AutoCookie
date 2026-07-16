"""Tests for scripts/run_backtest.py's pure, network-free helper
functions (split_into_periods, walk_forward_report). scripts/ is a
sibling directory to backend/, not a package under it, so it's added to
sys.path explicitly here -- these functions were previously verified
only via real manual CLI runs (see CHANGELOG.md/HANDOFF.md), with no
pytest coverage.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_backtest import (  # noqa: E402
    delay_robustness_report,
    split_into_periods,
    walk_forward_report,
)


def _result(pnl: float):
    """Minimal stand-in for BacktestResult -- walk_forward_report only
    reads `.total_pnl`."""
    return SimpleNamespace(total_pnl=pnl)


def _delay_result(pnls: list[float]):
    """Minimal stand-in for BacktestResult -- delay_robustness_report reads
    `.total_trades`, `.total_pnl`, and `.trades` (a list of dicts with a
    "pnl" key, matching the real BacktestResult/calculate_profit_factor
    contract -- see app.backtesting.backtest_engine.BacktestResult and
    app.backtesting.performance.calculate_profit_factor)."""
    trades = [{"pnl": p} for p in pnls]
    return SimpleNamespace(total_trades=len(trades), total_pnl=sum(pnls), trades=trades)


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


# --- delay_robustness_report ---------------------------------------------


def test_delay_robustness_report_clean_pass():
    # baseline: gross_profit=200, gross_loss=-50 -> PF=4.0, total_pnl=150.
    baseline = _delay_result([100, 100, -50])
    # delayed: gross_profit=160, gross_loss=-50 -> PF=3.2, total_pnl=110.
    delayed = _delay_result([80, 80, -50])
    report = delay_robustness_report(baseline, delayed)

    assert report["baseline_pf"] == pytest.approx(4.0)
    assert report["delayed_pf"] == pytest.approx(3.2)
    assert report["pf_retention"] == pytest.approx(0.8)
    assert report["sign_flip"] is False
    assert report["insufficient_data"] is False
    assert report["passed"] is True


def test_delay_robustness_report_fails_on_pf_degradation_below_threshold():
    # baseline: gross_profit=200, gross_loss=-10 -> PF=20.0.
    baseline = _delay_result([100, 100, -10])
    # delayed: gross_profit=20, gross_loss=-10 -> PF=2.0, still net
    # profitable (total_pnl=10 > 0, so this is NOT a sign flip) but
    # retention = 2.0/20.0 = 0.1, well below the default 0.5 criterion --
    # mirrors docs/ROBUSTNESS_REPORT.md test 2's material PF collapse.
    delayed = _delay_result([10, 10, -10])
    report = delay_robustness_report(baseline, delayed)

    assert report["baseline_pf"] == pytest.approx(20.0)
    assert report["delayed_pf"] == pytest.approx(2.0)
    assert report["pf_retention"] == pytest.approx(0.1)
    assert report["sign_flip"] is False
    assert report["passed"] is False


def test_delay_robustness_report_fails_on_sign_flip_even_with_retention_at_threshold():
    # baseline: gross_profit=100, gross_loss=-50 -> PF=2.0, total_pnl=50 (profitable).
    baseline = _delay_result([100, -50])
    # delayed: gross_profit=50, gross_loss=-50 -> PF=1.0, total_pnl=0
    # (NOT profitable). Retention = 1.0/2.0 = 0.5 -- exactly meets the
    # default max_pf_degradation criterion -- but the sign-flip check
    # alone must still fail this, isolating sign_flip as the cause.
    delayed = _delay_result([50, -50])
    report = delay_robustness_report(baseline, delayed)

    assert report["pf_retention"] == pytest.approx(0.5)
    assert report["sign_flip"] is True
    assert report["passed"] is False


def test_delay_robustness_report_zero_trades_is_insufficient_not_a_crash_or_fake_pass():
    baseline = _delay_result([100, -50])
    delayed = _delay_result([])  # no trades at all under delay
    report = delay_robustness_report(baseline, delayed)

    assert report["delayed_trades"] == 0
    assert report["insufficient_data"] is True
    assert report["passed"] is None
    assert report["pf_retention"] is None
    assert report["sign_flip"] is None
    assert "zero trades" in report["reason"]


def test_delay_robustness_report_both_zero_trades_is_insufficient():
    baseline = _delay_result([])
    delayed = _delay_result([])
    report = delay_robustness_report(baseline, delayed)

    assert report["insufficient_data"] is True
    assert report["passed"] is None


def test_delay_robustness_report_guards_division_by_zero_baseline_pf():
    # All baseline trades break exactly even -> gross_profit=0,
    # gross_loss=0 -> calculate_profit_factor returns 0.0 (not an
    # exception) -- delay_robustness_report must not divide by that zero.
    baseline = _delay_result([0, 0, 0])
    delayed = _delay_result([10, -5])
    report = delay_robustness_report(baseline, delayed)

    assert report["baseline_pf"] == 0.0
    assert report["pf_retention"] is None
    assert report["passed"] is None
    assert report["insufficient_data"] is True
    assert "undefined" in report["reason"]


def test_delay_robustness_report_both_infinite_pf_no_degradation():
    # Baseline and delayed both have zero losing trades -> PF is inf for
    # both -- retention should read as "no degradation" (1.0), not NaN
    # from an inf/inf division.
    baseline = _delay_result([100, 50])
    delayed = _delay_result([80, 40])
    report = delay_robustness_report(baseline, delayed)

    assert math.isinf(report["baseline_pf"])
    assert math.isinf(report["delayed_pf"])
    assert report["pf_retention"] == pytest.approx(1.0)
    assert report["sign_flip"] is False
    assert report["passed"] is True


def test_delay_robustness_report_infinite_baseline_finite_delayed_reads_as_full_degradation():
    # Baseline has zero losing trades (PF=inf); delayed has real losses
    # (finite PF). finite/inf must resolve to 0.0, not crash or hang.
    baseline = _delay_result([100, 50])
    delayed = _delay_result([50, -40])
    report = delay_robustness_report(baseline, delayed)

    assert math.isinf(report["baseline_pf"])
    assert report["pf_retention"] == pytest.approx(0.0)
    assert report["passed"] is False


def test_delay_robustness_report_custom_max_pf_degradation_threshold():
    baseline = _delay_result([100, 100, -50])  # PF=4.0
    delayed = _delay_result([100, -50])  # gross_profit=100, gross_loss=-50 -> PF=2.0
    # retention = 2.0/4.0 = 0.5, fails the stricter 0.9 threshold passed here.
    report = delay_robustness_report(baseline, delayed, max_pf_degradation=0.9)

    assert report["pf_retention"] == pytest.approx(0.5)
    assert report["passed"] is False
    assert report["criteria"]["max_pf_degradation"] == 0.9
