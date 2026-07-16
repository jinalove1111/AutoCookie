"""Per-regime performance analytics (Milestone 12b, 2026-07-16,
docs/ADAPTIVE_ARCHITECTURE.md section 4.3): aggregates regime-tagged
backtest trades into the per-(strategy, regime) evidence a future
`RollingPerformanceSelector` will consume -- "once ... enough
regime-tagged trades per strategy (a real sample size threshold ...
this project's own established floor for trusting a result is 20+
trades) a `RollingPerformanceSelector` can pick argmax strategy by
(e.g.) rolling expectancy within each regime, falling back to `legacy`
whenever a regime has insufficient data" (ADAPTIVE_ARCHITECTURE.md
section 4.3). This module only produces the evidence table -- it does
not select or gate anything, same "computation-only, not yet wired into
a decision path" discipline as `app.portfolio.performance_snapshots`
(decisions #19, #23, #24, #45, #46).

Pure functions, no I/O: consumes `BacktestResult.trades` lists already
held in memory, never touches the DB or network. `scripts/
analyze_regime_performance.py` is the thin CLI that fetches candles,
runs `BacktestEngine.run(..., tag_regimes=True)` per strategy, and calls
into this module to aggregate/render the results.

Trade-dict contract (Milestone 12a, `BacktestEngine.run(...,
tag_regimes=True)`, landed in parallel -- see that parameter's own
docstring in `app.backtesting.backtest_engine.BacktestEngine.run`):
every trade dict this module reads either has NO `"market_regime"` key
at all (an untagged run, `tag_regimes=False`, the default) or has a
`"market_regime"` key whose value is either `None` (regime detection
had insufficient history, or failed) or a dict shaped like
`app.regime.regime_detector.MarketRegime` (`dataclasses.asdict()`
output: `trend`/`volatility`/`breakout`/`mean_reversion`/
`liquidity_sweep_environment`/`metrics`). `regime_bucket` below treats
"key missing" and "key present but None" identically as `"untagged"` --
a consumer of THIS module never needs to know which of the two produced
a given untagged trade.
"""

from __future__ import annotations

from app.backtesting.performance import calculate_profit_factor, calculate_win_rate

# Same established floor as scripts/experiment_runner.py's
# MIN_TRADES_FOR_CONFIDENCE (20, decision #41) -- duplicated here rather
# than imported, the same decision app.portfolio.performance_snapshots
# already made and documented: scripts/ and backend/app are separate
# top-level packages with no existing cross-import path, and importing
# app.portfolio.performance_snapshots just to reuse this one constant
# would drag its DB-backed dependencies (app.database.models,
# app.portfolio.trades/TradeTracker/session_scope) into this pure,
# I/O-free module for no reason. Same value, same meaning: below this
# many trades in a bucket, "adequate sample size" fails.
MIN_TRADES_FOR_CONFIDENCE = 20

UNTAGGED_BUCKET = "untagged"
ALL_BUCKET = "all"


def regime_bucket(trade: dict) -> str:
    """Bucket key for a single trade dict: `"{trend}/{volatility}"` for a
    tagged trade with a real classification, or `"untagged"` when the
    `"market_regime"` key is either missing entirely (untagged run) or
    present but `None` (tagged run, but `detect_market_regime` had
    insufficient history or failed for that trade) -- both cases are
    "no usable regime classification" from this module's point of view,
    deliberately not distinguished any further here.

    Only `trend`/`volatility` compose the bucket (not the three boolean
    flags `breakout`/`mean_reversion`/`liquidity_sweep_environment`,
    which can co-occur with any trend/volatility pair) -- this matches
    `RollingPerformanceSelector`'s own eventual per-regime lookup unit
    per docs/ADAPTIVE_ARCHITECTURE.md section 4.3, keeping the number of
    buckets small enough to realistically reach `MIN_TRADES_FOR_CONFIDENCE`
    per bucket rather than exploding into dozens of near-empty
    combinations.
    """
    regime = trade.get("market_regime")
    if regime is None:
        return UNTAGGED_BUCKET
    return f"{regime['trend']}/{regime['volatility']}"


def _expectancy(trades: list[dict]) -> float:
    """Mean PnL per trade (currency, not R). Deliberately duplicated
    (not imported) from `scripts/parameter_sweep.py`'s `expectancy()` --
    same cross-package import constraint as `MIN_TRADES_FOR_CONFIDENCE`
    above (scripts/ is a sibling top-level directory to backend/app, not
    importable from app code without a sys.path hack -- by this
    project's existing convention, e.g. `backend/tests/test_run_backtest.py`,
    only TEST files reach across that boundary, never production app
    code). Identical formula, byte-for-byte: `sum(pnl) / len(trades)`,
    `0.0` for an empty list.
    """
    if not trades:
        return 0.0
    return sum(t["pnl"] for t in trades) / len(trades)


def _aggregate_row(strategy: str, bucket: str, trades: list[dict]) -> dict:
    """One evidence row for `strategy` over exactly `trades` (already
    filtered to a single bucket, or the full list for the `"all"` row).

    `win_rate`/`profit_factor` reuse `app.backtesting.performance`'s
    existing implementations (same package, direct import -- genuine
    reuse, not duplication): `calculate_win_rate` returns `0.0` for an
    empty list; `calculate_profit_factor` returns `0.0` for an empty
    list or when gross profit and gross loss are both zero, and
    `float("inf")` when there is profit but zero loss -- see that
    module's docstrings for the exact edge-case behavior reused here
    unchanged.
    """
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "strategy": strategy,
        "bucket": bucket,
        "trades": n,
        "wins": wins,
        "win_rate": calculate_win_rate(trades),
        "total_pnl": sum(t["pnl"] for t in trades),
        "expectancy": _expectancy(trades),
        "profit_factor": calculate_profit_factor(trades),
        # >= (not >), matching MIN_TRADES_FOR_CONFIDENCE's own "below
        # this many trades, adequate sample size FAILS" phrasing --
        # exactly `MIN_TRADES_FOR_CONFIDENCE` trades is sufficient.
        "sufficient_sample": n >= MIN_TRADES_FOR_CONFIDENCE,
    }


def aggregate_by_regime(trades: list[dict], strategy_name: str) -> list[dict]:
    """Group `trades` (a single strategy's pooled trade list, e.g. one
    strategy's `BacktestResult.trades` across however many periods a
    caller ran) by `regime_bucket`, and return one evidence row per
    bucket PLUS one final `"all"` row totaling every trade regardless of
    bucket -- rows are sorted by bucket name (deterministic, diffable
    output), with the `"all"` row always last so per-bucket rows read
    top-to-bottom before the total.

    No invented statistics: every number is plain, verifiable arithmetic
    over the trades actually in that bucket (see `_aggregate_row`) --
    `sufficient_sample` labels rows below `MIN_TRADES_FOR_CONFIDENCE`
    rather than hiding or excluding them, so a caller/renderer can never
    accidentally present a low-confidence bucket as equally trustworthy.

    Graceful on zero trades (never raises): returns a list containing
    only the `"all"` row, itself all-zero (`trades=0`, `win_rate=0.0`,
    `profit_factor=0.0`, `sufficient_sample=False`) -- there are no
    buckets to report when there is nothing to bucket, but the caller
    still gets a well-formed row rather than an empty list to special-case.
    """
    buckets: dict[str, list[dict]] = {}
    for trade in trades:
        buckets.setdefault(regime_bucket(trade), []).append(trade)

    rows = [
        _aggregate_row(strategy_name, bucket, bucket_trades)
        for bucket, bucket_trades in sorted(buckets.items())
    ]
    rows.append(_aggregate_row(strategy_name, ALL_BUCKET, trades))
    return rows


def comparison_table(rows_by_strategy: dict[str, list[dict]]) -> str:
    """Markdown comparison table across every strategy in
    `rows_by_strategy` (as produced by `aggregate_by_regime`, keyed by
    strategy name), one row per (bucket, strategy) pair, sorted by
    bucket then strategy name -- a deterministic, diffable report rather
    than insertion-order-dependent.

    Rows below `MIN_TRADES_FOR_CONFIDENCE` (`row["sufficient_sample"] is
    False`) get an explicit trailing `"(! n<20)"` marker appended to the
    Trades cell -- per this repo's "results below the sample floor must
    be labeled, never hidden" discipline: an insufficient-sample row
    still appears with its real (if noisy) numbers, just visibly flagged
    rather than silently indistinguishable from a confidence-worthy row.
    Pure ASCII marker (no U+26A0 warning-sign glyph): this string is both
    `print()`-ed to a console and written to a report file, and a default
    Windows console (cp1252) raises `UnicodeEncodeError` on non-ASCII
    output, which previously crashed the whole script AFTER a completed
    multi-minute run had already produced results but BEFORE they were
    saved to disk.

    Never raises: an empty `rows_by_strategy` (or one where every
    strategy's row list is itself empty) renders a header-only table
    with zero data rows.
    """
    all_rows = [row for rows in rows_by_strategy.values() for row in rows]
    all_rows.sort(key=lambda r: (r["bucket"], r["strategy"]))

    lines = [
        "| Bucket | Strategy | Trades | Win Rate | Total PnL | Expectancy | Profit Factor |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in all_rows:
        trades_cell = str(row["trades"])
        if not row.get("sufficient_sample", True):
            # ASCII-only marker ("!" not the U+26A0 warning-sign glyph) --
            # see comparison_table's docstring: this string is printed to
            # a default Windows (cp1252) console as well as written to a
            # file.
            trades_cell += f" (! n<{MIN_TRADES_FOR_CONFIDENCE})"
        profit_factor = row["profit_factor"]
        pf_cell = "inf" if profit_factor == float("inf") else f"{profit_factor:.2f}"
        lines.append(
            f"| {row['bucket']} | {row['strategy']} | {trades_cell} | "
            f"{row['win_rate'] * 100:.2f}% | {row['total_pnl']:.2f} | "
            f"{row['expectancy']:.2f} | {pf_cell} |"
        )
    return "\n".join(lines) + "\n"
