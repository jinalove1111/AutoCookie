"""Tests for app.backtesting.regime_analysis's pure functions
(regime_bucket / aggregate_by_regime / comparison_table).

All fixtures are synthetic, hand-computed trade dicts -- every expected
number below (win_rate/expectancy/profit_factor/total_pnl/sufficient_sample)
is verified by hand against the actual arithmetic, per this module's own
"no invented statistics" discipline. No real BacktestEngine/network call
anywhere in this file -- regime_analysis is pure, I/O-free.
"""

from __future__ import annotations

from app.backtesting.regime_analysis import (
    ALL_BUCKET,
    MIN_TRADES_FOR_CONFIDENCE,
    UNTAGGED_BUCKET,
    aggregate_by_regime,
    comparison_table,
    regime_bucket,
)


def _regime(trend: str, volatility: str, **flags) -> dict:
    return {
        "trend": trend,
        "volatility": volatility,
        "breakout": flags.get("breakout", False),
        "mean_reversion": flags.get("mean_reversion", False),
        "liquidity_sweep_environment": flags.get("liquidity_sweep_environment", False),
        "metrics": {},
    }


def _trade(pnl: float, regime: dict | None = "MISSING") -> dict:
    """`regime="MISSING"` (the default, a sentinel -- not a real regime
    value) omits the `"market_regime"` key entirely, matching an
    untagged run. Pass `regime=None` for a tagged run whose
    classification came back `None`, or a real dict from `_regime()`."""
    trade = {"pnl": pnl}
    if regime != "MISSING":
        trade["market_regime"] = regime
    return trade


# --- regime_bucket ---------------------------------------------------------


def test_regime_bucket_tagged_trade_combines_trend_and_volatility():
    trade = _trade(100, _regime("strong_trend", "high_volatility"))
    assert regime_bucket(trade) == "strong_trend/high_volatility"


def test_regime_bucket_different_trend_volatility_pair():
    trade = _trade(100, _regime("range", "low_volatility"))
    assert regime_bucket(trade) == "range/low_volatility"


def test_regime_bucket_market_regime_none_is_untagged():
    trade = _trade(100, regime=None)
    assert "market_regime" in trade  # key present, value None
    assert regime_bucket(trade) == UNTAGGED_BUCKET


def test_regime_bucket_missing_key_is_untagged():
    trade = _trade(100)  # no "market_regime" key at all
    assert "market_regime" not in trade
    assert regime_bucket(trade) == UNTAGGED_BUCKET


def test_regime_bucket_none_and_missing_key_produce_identical_bucket():
    assert regime_bucket(_trade(1, regime=None)) == regime_bucket(_trade(1))


# --- aggregate_by_regime: arithmetic (hand-computed) ------------------------


def _mixed_trades() -> list[dict]:
    """3 buckets, hand-computed expectations documented inline below."""
    return [
        # strong_trend/high_volatility: pnl [100, -50] -> 2 trades, 1 win
        _trade(100, _regime("strong_trend", "high_volatility")),
        _trade(-50, _regime("strong_trend", "high_volatility")),
        # range/low_volatility: pnl [30] -> 1 trade, 1 win, zero losses (inf PF)
        _trade(30, _regime("range", "low_volatility")),
        # untagged (missing key): pnl [-10] -> 1 trade, 0 wins
        _trade(-10),
    ]


def test_aggregate_by_regime_bucket_row_arithmetic():
    rows = aggregate_by_regime(_mixed_trades(), "legacy")
    by_bucket = {r["bucket"]: r for r in rows}

    st = by_bucket["strong_trend/high_volatility"]
    assert st["strategy"] == "legacy"
    assert st["trades"] == 2
    assert st["wins"] == 1
    assert st["win_rate"] == 0.5
    assert st["total_pnl"] == 50  # 100 + -50
    assert st["expectancy"] == 25.0  # 50 / 2
    assert st["profit_factor"] == 2.0  # gross_profit 100 / gross_loss 50
    assert st["sufficient_sample"] is False  # 2 < 20

    rl = by_bucket["range/low_volatility"]
    assert rl["trades"] == 1
    assert rl["wins"] == 1
    assert rl["win_rate"] == 1.0
    assert rl["total_pnl"] == 30
    assert rl["expectancy"] == 30.0
    assert rl["profit_factor"] == float("inf")  # zero losses, some profit
    assert rl["sufficient_sample"] is False

    untagged = by_bucket[UNTAGGED_BUCKET]
    assert untagged["trades"] == 1
    assert untagged["wins"] == 0
    assert untagged["win_rate"] == 0.0
    assert untagged["total_pnl"] == -10
    assert untagged["expectancy"] == -10.0
    assert untagged["profit_factor"] == 0.0  # zero profit, has loss
    assert untagged["sufficient_sample"] is False


def test_aggregate_by_regime_all_row_totals_every_trade():
    rows = aggregate_by_regime(_mixed_trades(), "legacy")
    all_row = next(r for r in rows if r["bucket"] == ALL_BUCKET)

    assert all_row["strategy"] == "legacy"
    assert all_row["trades"] == 4
    assert all_row["wins"] == 2  # the 100 and the 30
    assert all_row["win_rate"] == 0.5  # 2 / 4
    assert all_row["total_pnl"] == 70  # 100 - 50 + 30 - 10
    assert all_row["expectancy"] == 17.5  # 70 / 4
    # gross_profit = 100 + 30 = 130, gross_loss = 50 + 10 = 60
    assert all_row["profit_factor"] == 130 / 60
    assert all_row["sufficient_sample"] is False

    # exactly 4 rows: 3 buckets + the all-row, all-row last.
    assert len(rows) == 4
    assert rows[-1]["bucket"] == ALL_BUCKET


def test_aggregate_by_regime_rows_sorted_by_bucket_name():
    rows = aggregate_by_regime(_mixed_trades(), "legacy")
    bucket_rows = [r for r in rows if r["bucket"] != ALL_BUCKET]
    assert [r["bucket"] for r in bucket_rows] == sorted(r["bucket"] for r in bucket_rows)


# --- sufficient_sample boundary (19 vs 20) ----------------------------------


def test_sufficient_sample_false_at_19_trades():
    trades = [_trade(1, _regime("range", "normal_volatility")) for _ in range(19)]
    rows = aggregate_by_regime(trades, "legacy")
    row = next(r for r in rows if r["bucket"] == "range/normal_volatility")
    assert row["trades"] == 19
    assert row["sufficient_sample"] is False


def test_sufficient_sample_true_at_20_trades():
    assert MIN_TRADES_FOR_CONFIDENCE == 20
    trades = [_trade(1, _regime("range", "normal_volatility")) for _ in range(20)]
    rows = aggregate_by_regime(trades, "legacy")
    row = next(r for r in rows if r["bucket"] == "range/normal_volatility")
    assert row["trades"] == 20
    assert row["sufficient_sample"] is True


# --- zero-trades input -------------------------------------------------------


def test_aggregate_by_regime_zero_trades_is_graceful_single_all_row():
    rows = aggregate_by_regime([], "legacy")
    assert len(rows) == 1
    row = rows[0]
    assert row["bucket"] == ALL_BUCKET
    assert row["strategy"] == "legacy"
    assert row["trades"] == 0
    assert row["wins"] == 0
    assert row["win_rate"] == 0.0
    assert row["total_pnl"] == 0
    assert row["expectancy"] == 0.0
    assert row["profit_factor"] == 0.0
    assert row["sufficient_sample"] is False


# --- comparison_table --------------------------------------------------------


def test_comparison_table_marks_insufficient_sample_rows():
    rows_by_strategy = {
        "legacy": aggregate_by_regime(
            [_trade(1, _regime("range", "normal_volatility")) for _ in range(19)],
            "legacy",
        ),
    }
    table = comparison_table(rows_by_strategy)
    lines = [ln for ln in table.splitlines() if "range/normal_volatility" in ln]
    assert len(lines) == 1
    assert f"n<{MIN_TRADES_FOR_CONFIDENCE}" in lines[0]
    assert "(! n<" in lines[0]


def test_comparison_table_does_not_mark_sufficient_sample_rows():
    rows_by_strategy = {
        "legacy": aggregate_by_regime(
            [_trade(1, _regime("range", "normal_volatility")) for _ in range(20)],
            "legacy",
        ),
    }
    table = comparison_table(rows_by_strategy)
    lines = [ln for ln in table.splitlines() if "range/normal_volatility" in ln]
    assert len(lines) == 1
    assert "(!" not in lines[0]
    assert "n<" not in lines[0]


def test_comparison_table_sorted_by_bucket_then_strategy():
    rows_by_strategy = {
        "zzz_strategy": aggregate_by_regime(
            [_trade(5, _regime("range", "low_volatility"))], "zzz_strategy"
        ),
        "aaa_strategy": aggregate_by_regime(
            [_trade(5, _regime("range", "low_volatility"))], "aaa_strategy"
        ),
    }
    table = comparison_table(rows_by_strategy)
    lines = table.splitlines()
    # Both strategies produce a "range/low_volatility" row and an "all"
    # row; within "range/low_volatility", aaa_strategy must sort before
    # zzz_strategy.
    range_rows = [ln for ln in lines if ln.startswith("| range/low_volatility")]
    assert len(range_rows) == 2
    assert range_rows[0].split("|")[2].strip() == "aaa_strategy"
    assert range_rows[1].split("|")[2].strip() == "zzz_strategy"


def test_comparison_table_contains_header_and_expected_values():
    rows_by_strategy = {
        "legacy": aggregate_by_regime(
            [_trade(100, _regime("strong_trend", "high_volatility"))], "legacy"
        ),
    }
    table = comparison_table(rows_by_strategy)
    assert "| Bucket | Strategy | Trades | Win Rate | Total PnL | Expectancy | Profit Factor |" in table
    assert "strong_trend/high_volatility" in table
    assert "legacy" in table
    assert "100.00" in table  # total_pnl and expectancy both 100.00 here
    assert "100.00%" in table  # win_rate


def test_comparison_table_empty_input_is_header_only_never_raises():
    table = comparison_table({})
    lines = [ln for ln in table.splitlines() if ln.strip()]
    assert len(lines) == 2  # header + separator, no data rows
    assert table.startswith("| Bucket |")


def test_comparison_table_strategies_with_empty_row_lists_produce_no_data_rows():
    table = comparison_table({"legacy": [], "jade": []})
    lines = [ln for ln in table.splitlines() if ln.strip()]
    assert len(lines) == 2
