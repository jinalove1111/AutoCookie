"""Tests for scripts/research_regime_delay.py (H3 experiment harness,
docs/HYPOTHESES_ROUND_1.md section 3). scripts/ is a sibling directory to
backend/, not a package under it, so it's added to sys.path explicitly
here -- same pattern test_run_backtest.py / test_research_signal_selection.py
already use.

All fixtures are synthetic, hand-computed trade dicts -- every expected
number below (baseline_pf/delayed_pf/pf_retention/sign_flip/passed/
meets_keep_bar) is verified by hand against the actual arithmetic, matching
test_regime_analysis.py's own "no invented statistics" discipline. No real
BacktestEngine/network call anywhere in this file -- the per-bucket join
(`per_bucket_delay_retention`) is pure, I/O-free, and is the primary target
of this file; `_parse_args` is covered by a couple of network-free smoke
tests, same convention test_run_backtest.py already uses for run_backtest.py's
own CLI parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_regime_delay import (  # noqa: E402
    MAX_PF_DEGRADATION_DEFAULT,
    _parse_args,
    group_trades_by_regime,
    per_bucket_delay_retention,
    render_report,
)

from app.backtesting.regime_analysis import (  # noqa: E402
    ALL_BUCKET,
    MIN_TRADES_FOR_CONFIDENCE,
    UNTAGGED_BUCKET,
)
from run_backtest import delay_robustness_report  # noqa: E402


def _regime(trend: str, volatility: str) -> dict:
    return {
        "trend": trend,
        "volatility": volatility,
        "breakout": False,
        "mean_reversion": False,
        "liquidity_sweep_environment": False,
        "metrics": {},
    }


def _trade(pnl: float, regime: dict | None = "MISSING") -> dict:
    """`regime="MISSING"` (the default, a sentinel -- not a real regime
    value) omits the `"market_regime"` key entirely, matching an untagged
    run. Pass `regime=None` for a tagged run whose classification came back
    `None`, or a real dict from `_regime()`. Same convention
    test_regime_analysis.py's own `_trade()` helper already uses."""
    trade = {"pnl": pnl}
    if regime != "MISSING":
        trade["market_regime"] = regime
    return trade


# --- group_trades_by_regime --------------------------------------------------


def test_group_trades_by_regime_splits_by_bucket():
    trades = [
        _trade(10, _regime("weak_trend", "normal_volatility")),
        _trade(-5, _regime("weak_trend", "normal_volatility")),
        _trade(20, _regime("strong_trend", "high_volatility")),
    ]
    buckets = group_trades_by_regime(trades)
    assert set(buckets) == {"weak_trend/normal_volatility", "strong_trend/high_volatility"}
    assert len(buckets["weak_trend/normal_volatility"]) == 2
    assert len(buckets["strong_trend/high_volatility"]) == 1


def test_group_trades_by_regime_untagged_bucket():
    trades = [_trade(10), _trade(-5, regime=None)]
    buckets = group_trades_by_regime(trades)
    assert set(buckets) == {UNTAGGED_BUCKET}
    assert len(buckets[UNTAGGED_BUCKET]) == 2


def test_group_trades_by_regime_empty_list_returns_empty_dict():
    assert group_trades_by_regime([]) == {}


# --- per_bucket_delay_retention: core retention math -------------------------


def test_per_bucket_delay_retention_bucket_with_trades_on_both_sides():
    weak = _regime("weak_trend", "normal_volatility")
    # Baseline: gross_profit 300, gross_loss 100 -> PF 3.0
    baseline = [_trade(200, weak), _trade(100, weak), _trade(-100, weak)]
    # Delayed: gross_profit 60, gross_loss 40 -> PF 1.5 -> retention 1.5/3.0 = 0.5
    delayed = [_trade(60, weak), _trade(-40, weak)]

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]

    assert row["baseline_trades"] == 3
    assert row["delayed_trades"] == 2
    assert row["baseline_pf"] == 3.0
    assert row["delayed_pf"] == 1.5
    assert row["pf_retention"] == 0.5
    assert row["sign_flip"] is False
    assert row["insufficient_data"] is False
    assert row["passed"] is True  # 0.5 >= default 0.5 threshold, no sign flip


def test_per_bucket_delay_retention_bucket_below_threshold_fails():
    strong = _regime("strong_trend", "high_volatility")
    baseline = [_trade(500, strong), _trade(-100, strong)]  # PF 5.0
    delayed = [_trade(16, strong), _trade(-100, strong)]  # PF 0.16 -> retention 0.032

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["strong_trend/high_volatility"]

    assert row["baseline_pf"] == 5.0
    assert row["delayed_pf"] == 0.16
    assert row["pf_retention"] == 0.16 / 5.0
    assert row["passed"] is False
    assert row["meets_keep_bar"] is False


# --- per_bucket_delay_retention: zero-trades edge cases (no crash, no fake ratio) --


def test_per_bucket_delay_retention_zero_delayed_side_is_insufficient_not_fabricated():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = [_trade(100, weak), _trade(-50, weak)]
    delayed: list[dict] = []  # this bucket never appears on the delayed side at all

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]

    assert row["baseline_trades"] == 2
    assert row["delayed_trades"] == 0
    assert row["insufficient_data"] is True
    assert row["passed"] is None
    assert row["pf_retention"] is None  # never a fabricated 0.0 or 1.0
    assert row["reason"] is not None
    assert row["meets_keep_bar"] is False  # never crashes, never fabricated True


def test_per_bucket_delay_retention_zero_baseline_side_is_insufficient_not_fabricated():
    weak = _regime("weak_trend", "normal_volatility")
    baseline: list[dict] = []
    delayed = [_trade(10, weak)]

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]

    assert row["baseline_trades"] == 0
    assert row["delayed_trades"] == 1
    assert row["insufficient_data"] is True
    assert row["passed"] is None
    assert row["pf_retention"] is None
    assert row["meets_keep_bar"] is False


def test_per_bucket_delay_retention_bucket_present_in_baseline_only_still_reported():
    range_regime = _regime("range", "low_volatility")
    baseline = [_trade(5, range_regime)]
    delayed: list[dict] = []

    report = per_bucket_delay_retention(baseline, delayed)
    # The bucket must still appear (never silently dropped), even though the
    # delayed side contributed nothing.
    assert "range/low_volatility" in report
    assert report["range/low_volatility"]["baseline_trades"] == 1
    assert report["range/low_volatility"]["delayed_trades"] == 0


# --- per_bucket_delay_retention: formula parity with delay_robustness_report ------


def test_per_bucket_delay_retention_matches_delay_robustness_report_formula_exactly():
    """The per-bucket PF-retention math must be the exact SAME formula
    run_backtest.delay_robustness_report() already uses at the aggregate
    level, scoped to a filtered subset -- not a second, independently
    reimplemented formula that could silently drift from it."""
    weak = _regime("weak_trend", "normal_volatility")
    baseline_trades = [_trade(120, weak), _trade(-40, weak), _trade(30, weak)]
    delayed_trades = [_trade(50, weak), _trade(-60, weak)]

    report = per_bucket_delay_retention(baseline_trades, delayed_trades)
    row = report["weak_trend/normal_volatility"]

    # Compute the SAME comparison independently, directly via
    # delay_robustness_report on hand-built BacktestResult-shaped stand-ins
    # (same duck-typing convention test_run_backtest.py's own
    # `_delay_result()` helper uses) over the identical trade lists.
    baseline_stub = SimpleNamespace(
        total_trades=len(baseline_trades),
        total_pnl=sum(t["pnl"] for t in baseline_trades),
        trades=baseline_trades,
    )
    delayed_stub = SimpleNamespace(
        total_trades=len(delayed_trades),
        total_pnl=sum(t["pnl"] for t in delayed_trades),
        trades=delayed_trades,
    )
    expected = delay_robustness_report(baseline_stub, delayed_stub)

    assert row["baseline_pf"] == expected["baseline_pf"]
    assert row["delayed_pf"] == expected["delayed_pf"]
    assert row["pf_retention"] == expected["pf_retention"]
    assert row["sign_flip"] == expected["sign_flip"]
    assert row["passed"] == expected["passed"]


def test_per_bucket_delay_retention_custom_max_pf_degradation_threshold():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = [_trade(200, weak), _trade(-100, weak)]  # PF 2.0
    delayed = [_trade(120, weak), _trade(-100, weak)]  # PF 1.2 -> retention 0.6

    default_report = per_bucket_delay_retention(baseline, delayed)
    assert default_report["weak_trend/normal_volatility"]["passed"] is True  # 0.6 >= 0.5

    strict_report = per_bucket_delay_retention(baseline, delayed, max_pf_degradation=0.9)
    assert strict_report["weak_trend/normal_volatility"]["passed"] is False  # 0.6 < 0.9


# --- meets_keep_bar: n floor, sign-flip, and untagged/all exclusion ---------------


def _n_trades(pnl: float, regime: dict, n: int) -> list[dict]:
    return [_trade(pnl, regime) for _ in range(n)]


def test_meets_keep_bar_true_when_n_pf_and_sign_all_clear():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = _n_trades(10, weak, 20)  # 20 wins, gross_profit 200, no losses -> PF inf
    delayed = _n_trades(5, weak, 20)  # 20 wins, no losses -> PF inf, retention 1.0

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]
    assert row["delayed_trades"] == 20
    assert row["pf_retention"] == 1.0
    assert row["passed"] is True
    assert row["meets_keep_bar"] is True


def test_meets_keep_bar_false_when_delayed_n_below_floor():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = _n_trades(10, weak, 19)  # all wins, PF inf
    delayed = _n_trades(10, weak, 19)  # all wins, PF inf, retention 1.0, but n=19 < 20

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]
    assert row["delayed_trades"] == 19
    assert row["passed"] is True
    assert row["meets_keep_bar"] is False  # n floor not cleared


def test_meets_keep_bar_respects_custom_min_bucket_n():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = _n_trades(10, weak, 10)
    delayed = _n_trades(10, weak, 10)  # PF inf both sides, retention 1.0, n=10

    default_report = per_bucket_delay_retention(baseline, delayed)
    assert default_report["weak_trend/normal_volatility"]["meets_keep_bar"] is False  # 10 < 20

    loosened_report = per_bucket_delay_retention(baseline, delayed, min_bucket_n=10)
    assert loosened_report["weak_trend/normal_volatility"]["meets_keep_bar"] is True


def test_meets_keep_bar_false_for_untagged_bucket_even_if_otherwise_clears():
    baseline = [_trade(10) for _ in range(25)]  # untagged (missing key), n=25
    delayed = [_trade(10) for _ in range(25)]  # untagged, all wins, n=25, PF inf, retention 1.0

    report = per_bucket_delay_retention(baseline, delayed)
    row = report[UNTAGGED_BUCKET]
    assert row["delayed_trades"] == 25
    assert row["passed"] is True
    assert row["meets_keep_bar"] is False  # untagged is never a real regime bucket


def test_meets_keep_bar_false_for_sign_flip_even_with_sufficient_n_and_retention():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = _n_trades(10, weak, 25)  # total_pnl +250, profitable
    delayed = _n_trades(-10, weak, 25)  # total_pnl -250, a sign flip

    report = per_bucket_delay_retention(baseline, delayed)
    row = report["weak_trend/normal_volatility"]
    assert row["sign_flip"] is True
    assert row["passed"] is False
    assert row["meets_keep_bar"] is False


# --- "all" aggregate cross-check row ------------------------------------------


def test_all_bucket_row_present_and_sums_across_buckets():
    weak = _regime("weak_trend", "normal_volatility")
    strong = _regime("strong_trend", "high_volatility")
    baseline = [_trade(100, weak), _trade(-20, weak), _trade(200, strong)]
    delayed = [_trade(50, weak), _trade(80, strong), _trade(-10, strong)]

    report = per_bucket_delay_retention(baseline, delayed)
    assert ALL_BUCKET in report
    all_row = report[ALL_BUCKET]
    assert all_row["baseline_trades"] == 3
    assert all_row["delayed_trades"] == 3
    assert all_row["meets_keep_bar"] is False  # never a real bucket, never counted


def test_all_bucket_never_counts_toward_keep_bar_even_with_qualifying_totals():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = _n_trades(10, weak, 25)
    delayed = _n_trades(10, weak, 25)  # would qualify per-bucket AND in aggregate

    report = per_bucket_delay_retention(baseline, delayed)
    assert report["weak_trend/normal_volatility"]["meets_keep_bar"] is True
    assert report[ALL_BUCKET]["meets_keep_bar"] is False


# --- per_bucket_delay_retention: sample-size floor default --------------------


def test_default_min_bucket_n_matches_project_wide_confidence_floor():
    assert MIN_TRADES_FOR_CONFIDENCE == 20


# --- render_report -------------------------------------------------------------


def test_render_report_ascii_only_and_all_bucket_last():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = [_trade(10, weak)]
    delayed = [_trade(-5, weak)]
    report = per_bucket_delay_retention(baseline, delayed)

    table = render_report(report)
    assert table.isascii()
    lines = [ln for ln in table.splitlines() if ln.startswith("|") and "Bucket" not in ln and "---" not in ln]
    assert lines[-1].startswith(f"| {ALL_BUCKET} ")
    assert "weak_trend/normal_volatility" in table


def test_render_report_empty_report_header_only_never_raises():
    table = render_report({})
    lines = [ln for ln in table.splitlines() if ln.strip()]
    assert len(lines) == 2  # header + separator, no data rows
    assert table.startswith("| Bucket |")


def test_render_report_insufficient_data_bucket_shown_not_hidden():
    weak = _regime("weak_trend", "normal_volatility")
    baseline = [_trade(10, weak)]
    delayed: list[dict] = []
    report = per_bucket_delay_retention(baseline, delayed)

    table = render_report(report)
    lines = [ln for ln in table.splitlines() if "weak_trend/normal_volatility" in ln]
    assert len(lines) == 1
    assert "INSUFFICIENT DATA" in lines[0]


# --- CLI parsing (network-free smoke tests) -------------------------------------


def test_parse_args_defaults():
    args = _parse_args([])
    assert args.max_pf_degradation == MAX_PF_DEGRADATION_DEFAULT
    assert args.min_bucket_n == MIN_TRADES_FOR_CONFIDENCE
    assert args.end_date is None


def test_parse_args_overrides():
    args = _parse_args(
        [
            "--symbol", "ETHUSDT",
            "--timeframe", "5m",
            "--candles", "1000",
            "--periods", "2",
            "--end-date", "2025-07-10",
            "--max-pf-degradation", "0.75",
            "--min-bucket-n", "15",
        ]
    )
    assert args.symbol == "ETHUSDT"
    assert args.timeframe == "5m"
    assert args.candles == 1000
    assert args.periods == 2
    assert args.end_date == "2025-07-10"
    assert args.max_pf_degradation == 0.75
    assert args.min_bucket_n == 15
