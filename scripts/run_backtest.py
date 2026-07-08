"""run_backtest.py

BACKTEST_MODE: fetch real historical OHLCV candles from OKX's public
(keyless) market-data endpoint, replay them once through the real
Strategy/Risk/Backtest engines via `BacktestEngine.run()`, and produce a
markdown report + CSV trade export. This is a read-only historical analysis
pass -- it never places a live or paper order and never writes to the
`trades` DB table (unlike `run_paper.py`). No `LIVE_TRADING_ENABLED` guard
is needed here for the same reason: nothing in this script can ever touch a
real or paper account.

Pagination note (read before assuming this fetches deep history):
`CandleFetcher.fetch_ohlcv`'s `since` parameter is wired to OKX's `before`
query param, which per OKX's API semantics returns candles NEWER than the
given timestamp, not older. This was confirmed empirically: fetching 10
candles, then re-fetching with `since` set to the oldest of those 10
returned candles at or after that same timestamp, never anything older.
That means `since` cannot be used to page backward into deeper history with
the current `CandleFetcher` implementation -- it cannot help us assemble a
longer historical sample than one call returns. Given that, and OKX's
public candles endpoint hard cap of 300 candles per call (already clamped
inside `CandleFetcher`), this script makes a SINGLE fetch call, capped at
300 candles, and prints a clear note whenever `--candles` was requested
above that cap so the shortfall is never silent. Extending this to true
deep-history pagination would require `CandleFetcher` to expose OKX's
`after` param (older-than-ts) instead of `before`, which is out of scope
for this script (candle_fetcher.py is a frozen, already-real Milestone 2
contract this script only consumes).

Exit codes:
  0 -> normal outcomes: a completed backtest, including the valid
       zero-trades outcome (no signal ever passed risk approval over the
       sample -- not an error, still produces a report).
  1 -> genuine failures: candle fetch/network error, zero candles returned,
       or an unexpected exception from the backtest engine itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from app.config import settings

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPORTS_DIR = SCRIPT_DIR / "reports"
DEFAULT_OUTPUT_PATH = DEFAULT_REPORTS_DIR / "backtest_report.md"
DEFAULT_CANDLE_COUNT = 900

from app.backtesting.backtest_engine import MIN_CANDLES, BacktestEngine
from app.backtesting.report_generator import ReportGenerator
from app.data.candle_fetcher import OKX_MAX_LIMIT, CandleFetcher
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine


def fetch_candles(symbol: str, timeframe: str, requested: int) -> list:
    """Fetch historical candles for `symbol`/`timeframe`.

    Single-call fallback (see module docstring): `CandleFetcher`'s `since`
    param does not cleanly paginate backward in time, so this always issues
    one call capped at OKX's 300-candle limit and prints a clear note if
    `requested` exceeds that cap.
    """
    effective_limit = min(requested, OKX_MAX_LIMIT)
    if requested > OKX_MAX_LIMIT:
        print(
            f"NOTE: requested {requested} candles, but OKX's public candles "
            f"endpoint caps at {OKX_MAX_LIMIT} per call, and CandleFetcher's "
            "`since` param does not cleanly page backward into older history "
            f"(see module docstring). Fetching {effective_limit} candles "
            "instead -- this backtest sample is shallower than requested."
        )
    return CandleFetcher().fetch_ohlcv(symbol, timeframe, limit=effective_limit)


def run_backtest(candles: list) -> Any:
    """Replay `candles` once through the real Strategy/Risk/Backtest engines."""
    return BacktestEngine().run(
        candles,
        SignalEngine(),
        RiskManager(),
        account_balance=10000.0,
        fee_percent=0.05,
        slippage_percent=0.02,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest runner. Fetches real historical OKX candles (public, "
            "keyless) and replays them through the Strategy/Risk/Backtest "
            "engines, producing a markdown report and a CSV trade export. "
            "Read-only: never places orders, never writes to the trades DB."
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
            "Roughly how many historical candles to fetch, pagination-"
            f"permitting (default {DEFAULT_CANDLE_COUNT}). Currently capped "
            f"at {OKX_MAX_LIMIT} per the module docstring's pagination note."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Path to write the markdown report to (default: "
            f"{DEFAULT_OUTPUT_PATH}). A sibling CSV trade export is written "
            "next to it with the same stem and a .csv extension."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()

    # --- 1. Fetch historical candles (single call, see docstring) ---
    try:
        candles = fetch_candles(args.symbol, args.timeframe, args.candles)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1

    if not candles:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1

    print(f"Fetched {len(candles)} candles for {args.symbol}/{args.timeframe}.")
    if len(candles) < MIN_CANDLES:
        print(
            f"NOTE: {len(candles)} candles is below the engine's minimum "
            f"of {MIN_CANDLES} needed to generate even one signal; this "
            "backtest will produce a valid, empty (0-trade) result."
        )

    # --- 2. Replay through the real Strategy/Risk/Backtest engines ---
    try:
        result = run_backtest(candles)
    except Exception as exc:  # unexpected engine failure is a genuine failure
        print(f"ERROR: backtest engine raised an exception: {exc}")
        return 1

    # --- 3. Console summary (0-trade outcome is valid, not an error) ---
    print("Backtest complete:")
    print(f"  total_trades  : {result.total_trades}")
    print(f"  win_rate      : {result.win_rate * 100:.2f}%")
    print(f"  total_pnl     : {result.total_pnl:.2f}")
    print(f"  max_drawdown  : {result.max_drawdown * 100:.2f}%")

    # --- 4. Write markdown report + CSV trade export ---
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = output_path.with_suffix(".csv")

    report_generator = ReportGenerator()
    report_markdown = report_generator.generate(result)
    output_path.write_text(report_markdown, encoding="utf-8")
    report_generator.export_csv(result, str(csv_path))

    print(f"Markdown report written to: {output_path}")
    print(f"CSV trade export written to: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
