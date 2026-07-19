"""analyze_regime_performance.py

Milestone 12b (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3):
thin CLI over `app.backtesting.regime_analysis` -- fetches real
historical OKX candles ONCE (same fetch pattern as `run_backtest.py`),
runs EVERY requested strategy over the SAME candles/periods through
`BacktestEngine.run(..., tag_regimes=True)` (Milestone 12a, landed in
parallel), and aggregates the resulting regime-tagged trades into the
per-(strategy, regime) evidence table a future `RollingPerformanceSelector`
(not yet built) will eventually consume. Read-only: never places orders,
never writes to the `trades` DB table -- same guarantee as
`run_backtest.py`.

`--strategies` (comma-separated, default `"legacy"` plus every
currently-registered experimental strategy -- see `_default_strategies()`):
`"legacy"` is special-cased to mean "the default SignalEngine path" --
`run_backtest()`/`BacktestEngine.run()` called WITHOUT a `strategy=`
kwarg at all (passing `strategy=None`, its own default), the exact
"unchanged default behavior" path every other script in this project
preserves (see `run_backtest.py`'s own `Strategy module: SignalEngine
(default)` NOTE) -- NOT `AVAILABLE_STRATEGIES["legacy"]` (the
`LegacyStrategy` Protocol adapter), even though that adapter wraps the
identical `SignalEngine(use_jade_engine=False)` call and should behave
equivalently. Any other name is resolved via
`app.strategy.experimental.all_strategies()` (production + experimental
registries merged); an unknown name exits with an error listing every
available name, checked BEFORE any network fetch -- same
fail-fast-before-slow-I/O convention `run_backtest.py --strategy`
already established.

Candles (both LTF and HTF) are fetched exactly ONCE and reused across
every requested strategy's run -- each strategy is evaluated against a
genuinely identical historical sample, and this avoids N redundant
network fetches for N strategies. `--periods` splits that fetch into
`--periods` non-overlapping chronological chunks (same
`split_into_periods` this project already uses in `run_backtest.py`);
each strategy's trades are POOLED across all periods (a strategy that
only got 8 trades in period 1 and 15 in period 2 pools to 23 before
`MIN_TRADES_FOR_CONFIDENCE` is checked) before one
`regime_analysis.aggregate_by_regime()` call per strategy -- more trades
per (strategy, regime) bucket is exactly what the sample-floor
discipline wants; regime aggregation itself is not period-aware.

NOT run end-to-end as part of this milestone: `BacktestEngine.run(...,
tag_regimes=True)` (Milestone 12a) landed in parallel with this CLI --
only `--help` argument parsing is verified here, a later evidence round
exercises this against real OKX data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# scripts/ is a sibling of backend/ -- make the app package importable,
# same convention every other scripts/ entry point (run_backtest.py,
# parameter_sweep.py, experiment_runner.py, ...) already uses.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _cli_path_utils import normalize_path_arg  # noqa: E402
from app.backtesting.regime_analysis import aggregate_by_regime, comparison_table  # noqa: E402
from app.config import settings  # noqa: E402
from app.strategy.experimental import EXPERIMENTAL_STRATEGIES, all_strategies  # noqa: E402

# run_backtest.py lives in this same scripts/ directory (now on
# sys.path, see above) -- reusing its fetch_candles/htf_candle_count_for_span/
# split_into_periods/run_backtest exactly, same reuse pattern
# parameter_sweep.py already established for split_into_periods/
# walk_forward_report/htf_candle_count_for_span, instead of
# reimplementing the fetch/split logic here.
from run_backtest import (  # noqa: E402
    fetch_candles,
    htf_candle_count_for_span,
    run_backtest,
    split_into_periods,
)

DEFAULT_REPORTS_DIR = SCRIPT_DIR / "reports"
DEFAULT_OUTPUT_PATH = DEFAULT_REPORTS_DIR / "regime_performance.md"
# Same default as run_backtest.py's DEFAULT_CANDLE_COUNT -- kept as an
# independent constant (not imported) so this script's default can't
# silently drift if run_backtest.py's own default ever changes for
# reasons specific to that script.
DEFAULT_CANDLE_COUNT = 5000
LEGACY_LABEL = "legacy"


def _default_strategies() -> str:
    """`"legacy"` plus every key currently registered in
    `EXPERIMENTAL_STRATEGIES`, sorted for a deterministic default
    (insertion order of a dict literal shouldn't leak into a CLI
    default's printed help text). Does NOT include `"jade"` -- `jade`
    is a production (`AVAILABLE_STRATEGIES`) adapter, not an
    experimental strategy, and a caller who wants it included can always
    pass `--strategies legacy,jade,...` explicitly.
    """
    return ",".join([LEGACY_LABEL] + sorted(EXPERIMENTAL_STRATEGIES.keys()))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Per-regime performance analytics (Milestone 12b). Fetches real "
            "historical OKX candles once and runs every --strategies entry "
            "over the same candles/periods with tag_regimes=True, printing "
            "and writing a markdown comparison table of per-(strategy, "
            "regime) evidence. Read-only: never places orders, never "
            "writes to the trades DB."
        )
    )
    parser.add_argument(
        "--symbol", default=settings.SYMBOL, help=f"Default: {settings.SYMBOL!r}"
    )
    parser.add_argument(
        "--timeframe",
        default=settings.DEFAULT_TIMEFRAME,
        help=f"Default: {settings.DEFAULT_TIMEFRAME!r}",
    )
    parser.add_argument(
        "--candles",
        type=int,
        default=DEFAULT_CANDLE_COUNT,
        help=(
            f"How many historical candles to fetch per period (default "
            f"{DEFAULT_CANDLE_COUNT}), paginated in real batches from OKX -- "
            "same convention as run_backtest.py --candles."
        ),
    )
    parser.add_argument(
        "--periods",
        type=int,
        default=1,
        help=(
            "Split the fetched history into this many equal, non-"
            "overlapping chronological periods (default 1 = single "
            "continuous run) -- same split_into_periods() convention as "
            "run_backtest.py --periods. Each strategy's trades are pooled "
            "across all periods before per-regime aggregation; total "
            "candles fetched is --candles * --periods."
        ),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help=(
            "Anchor the fetch to end at this UTC date (format: YYYY-MM-DD) "
            "instead of 'now' -- same convention as run_backtest.py "
            "--end-date. Default: None (fetch ending at 'now')."
        ),
    )
    parser.add_argument(
        "--strategies",
        default=_default_strategies(),
        help=(
            "Comma-separated strategy names to evaluate (default: "
            f"{_default_strategies()!r} -- 'legacy' plus every currently-"
            "registered experimental strategy). 'legacy' means the "
            "default SignalEngine path (BacktestEngine.run() called "
            "WITHOUT strategy=); any other name is resolved via "
            "app.strategy.experimental.all_strategies() (production + "
            "experimental) -- an unknown name exits with an error listing "
            "every available name, checked before any network fetch."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Path to write the markdown comparison table to (default: "
            f"{DEFAULT_OUTPUT_PATH})."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    total_requested = args.candles * args.periods

    end_time_ms: int | None = None
    if args.end_date is not None:
        try:
            end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: --end-date {args.end_date!r} is not a valid YYYY-MM-DD date.")
            return 1
        end_time_ms = int(end_dt.timestamp() * 1000)
        print(f"Anchoring fetch to end at {end_dt.isoformat()} (--end-date {args.end_date}).")

    # --- 0. Resolve --strategies BEFORE any network fetch (fail fast,
    # same convention run_backtest.py --strategy already established). ---
    requested_names = [n.strip() for n in args.strategies.split(",") if n.strip()]
    if not requested_names:
        print("ERROR: --strategies resolved to an empty list.")
        return 1

    available = all_strategies()
    resolved: list[tuple[str, Any]] = []  # (label, strategy_obj_or_None)
    unknown: list[str] = []
    for name in requested_names:
        if name == LEGACY_LABEL:
            # Literal "no strategy=" path -- see module docstring for why
            # this is NOT AVAILABLE_STRATEGIES["legacy"].
            resolved.append((LEGACY_LABEL, None))
            continue
        strategy_obj = available.get(name)
        if strategy_obj is None:
            unknown.append(name)
            continue
        resolved.append((name, strategy_obj))
    if unknown:
        all_names = sorted({LEGACY_LABEL, *available.keys()})
        print(
            f"ERROR: unknown --strategies name(s) {unknown!r}. Available: "
            f"{', '.join(all_names)}."
        )
        return 1

    # --- 1. Fetch candles ONCE (LTF + HTF), reused across every strategy. ---
    try:
        candles = fetch_candles(args.symbol, args.timeframe, total_requested, end_time_ms)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1
    if not candles:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1
    print(f"Fetched {len(candles)} candles for {args.symbol}/{args.timeframe}.")

    htf_requested = htf_candle_count_for_span(args.timeframe, total_requested, settings.HTF_TIMEFRAME)
    try:
        htf_candles = fetch_candles(args.symbol, settings.HTF_TIMEFRAME, htf_requested, end_time_ms)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch HTF candles for {args.symbol}: {exc}")
        return 1
    if not htf_candles:
        print(f"No HTF candles returned for {args.symbol}/{settings.HTF_TIMEFRAME}.")
        return 1
    print(f"Fetched {len(htf_candles)} HTF candles for {args.symbol}/{settings.HTF_TIMEFRAME}.")

    ltf_periods = split_into_periods(candles, args.periods)

    # --- 2. Run every strategy over the SAME periods with
    # tag_regimes=True, pooling trades across periods before a single
    # per-strategy aggregation call (see module docstring). ---
    rows_by_strategy: dict[str, list[dict]] = {}
    for label, strategy_obj in resolved:
        pooled_trades: list[dict] = []
        for period_num, ltf_chunk in enumerate(ltf_periods, start=1):
            try:
                result = run_backtest(
                    ltf_chunk,
                    htf_candles,
                    strategy=strategy_obj,
                    tag_regimes=True,
                )
            except Exception as exc:  # unexpected engine failure is a genuine failure
                print(
                    f"ERROR: backtest engine raised an exception for "
                    f"strategy {label!r}, period {period_num}: {exc}"
                )
                return 1
            pooled_trades.extend(result.trades)
        print(f"{label}: {len(pooled_trades)} trades pooled across {args.periods} period(s).")
        rows_by_strategy[label] = aggregate_by_regime(pooled_trades, label)

    # --- 3. Render + write + print the comparison table. Write to disk
    # BEFORE printing: `table` is plain ASCII (see regime_analysis's
    # comparison_table docstring) so this print is not expected to raise,
    # but a completed multi-minute run's results must survive regardless
    # -- writing the file first means a console encoding failure (or any
    # other printing surprise) can never lose already-computed results. ---
    table = comparison_table(rows_by_strategy)

    output_path = normalize_path_arg(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(table, encoding="utf-8")

    print()
    print(table)
    print(f"Markdown report written to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
