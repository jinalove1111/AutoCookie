"""run_backtest.py

BACKTEST_MODE: fetch real historical OHLCV candles from OKX's public
(keyless) market-data endpoint, replay them once through the real
Strategy/Risk/Backtest engines via `BacktestEngine.run()`, and produce a
markdown report + CSV trade export. This is a read-only historical analysis
pass -- it never places a live or paper order and never writes to the
`trades` DB table (unlike `run_paper.py`). No `LIVE_TRADING_ENABLED` guard
is needed here for the same reason: nothing in this script can ever touch a
real or paper account.

Pagination (deep history, fixed -- read before assuming this is still
capped at 300 candles): earlier versions of this script were limited to a
SINGLE fetch call capped at OKX's 300-candles-per-call limit, because
`CandleFetcher.fetch_ohlcv`'s `since` parameter was wired to OKX's `before`
query param, which returns candles NEWER than the given timestamp (empty
-- it cannot page backward). That bug is now fixed at the source
(`CandleFetcher.fetch_ohlcv`'s `since` now correctly maps to OKX's `after`
param), and `CandleFetcher.fetch_ohlcv_history()` (new) assembles real deep
history by paginating OKX's separate `/market/history-candles` endpoint
(confirmed empirically to page back reliably for months of data, unlike
`/market/candles`, which is hard-capped at ~1440 total candles regardless
of pagination -- see that method's docstring for the full empirical
findings). This script now fetches genuinely as many candles as
`--candles` requests, pagination-permitting -- it may still return fewer
if OKX's actual history for the instrument/timeframe runs out first (not
an error, printed as a note).

Exit codes:
  0 -> normal outcomes: a completed backtest, including the valid
       zero-trades outcome (no signal ever passed risk approval over the
       sample -- not an error, still produces a report).
  1 -> genuine failures: candle fetch/network error, zero candles returned,
       or an unexpected exception from the backtest engine itself.

HTF/LTF handling: `SignalEngine.generate_signal()` requires real, distinct
`ltf_candles`/`htf_candles` series (HTF bias must come from a genuine
higher-timeframe series, per docs/strategy_spec.md section 1). This script
fetches both series independently via `CandleFetcher` -- `args.timeframe`/
`settings.DEFAULT_TIMEFRAME` for LTF (unchanged), `settings.HTF_TIMEFRAME`
for HTF (new) -- mirroring `run_paper.py`'s pattern: an HTF fetch
failure/empty result is a hard failure (exit code 1), never a silent
fallback to LTF-as-HTF. `BacktestEngine.run()` walks both series in sync via
a no-lookahead HTF cursor (`app.backtesting.backtest_engine._advance_htf_cursor`)
so only genuinely closed HTF candles are ever visible to a given LTF step.
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
# Raised from the old 900 (a single-page-call artifact) now that deep
# pagination actually works -- 5000 candles at 5m is ~17 days, a much more
# statistically meaningful sample for judging whether the strategy has
# real edge than the ~1 day a single 300-candle page gave.
DEFAULT_CANDLE_COUNT = 5000

from app.backtesting.backtest_engine import MIN_CANDLES, BacktestEngine
from app.backtesting.report_generator import ReportGenerator
from app.data.candle_fetcher import CandleFetcher
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine


def fetch_candles(symbol: str, timeframe: str, requested: int) -> list:
    """Fetch historical candles for `symbol`/`timeframe` via
    `CandleFetcher.fetch_ohlcv_history()` -- real deep pagination (see
    module docstring), not a single 300-candle-capped call. May return
    fewer than `requested` if OKX's actual history for this instrument/
    timeframe runs out first; that shortfall is printed as a note by the
    caller (via the returned count), not silently swallowed here.
    """
    return CandleFetcher().fetch_ohlcv_history(symbol, timeframe, total_candles=requested)


def run_backtest(ltf_candles: list, htf_candles: list) -> Any:
    """Replay `ltf_candles`/`htf_candles` once through the real
    Strategy/Risk/Backtest engines."""
    return BacktestEngine().run(
        ltf_candles,
        htf_candles,
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
            f"How many historical candles to fetch (default {DEFAULT_CANDLE_COUNT}), "
            "paginated in real batches from OKX -- may return fewer only if "
            "OKX's actual history for the instrument/timeframe runs out first."
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

    # --- 1. Fetch historical LTF candles (real deep pagination, see docstring) ---
    try:
        candles = fetch_candles(args.symbol, args.timeframe, args.candles)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1

    if not candles:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1

    print(f"Fetched {len(candles)} candles for {args.symbol}/{args.timeframe}.")
    if len(candles) < args.candles:
        print(
            f"NOTE: requested {args.candles} candles but only {len(candles)} "
            f"are available from OKX for {args.symbol}/{args.timeframe} (e.g. "
            "a recent listing) -- not an error, this is genuinely all the "
            "history that exists."
        )
    if len(candles) < MIN_CANDLES:
        print(
            f"NOTE: {len(candles)} candles is below the engine's minimum "
            f"of {MIN_CANDLES} needed to generate even one signal; this "
            "backtest will produce a valid, empty (0-trade) result."
        )

    # --- 1b. Fetch historical HTF candles (independent fetch, mirrors
    # run_paper.py's pattern: never fall back to reusing the LTF series as
    # HTF -- an HTF fetch failure or empty result is a hard failure here
    # too, since a silent LTF-as-HTF fallback would defeat the entire point
    # of the HTF/LTF separation).
    try:
        htf_candles = fetch_candles(args.symbol, settings.HTF_TIMEFRAME, args.candles)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch HTF candles for {args.symbol}: {exc}")
        return 1

    if not htf_candles:
        print(f"No HTF candles returned for {args.symbol}/{settings.HTF_TIMEFRAME}.")
        return 1

    print(f"Fetched {len(htf_candles)} HTF candles for {args.symbol}/{settings.HTF_TIMEFRAME}.")
    if len(htf_candles) < args.candles:
        print(
            f"NOTE: requested {args.candles} HTF candles but only "
            f"{len(htf_candles)} are available from OKX for "
            f"{args.symbol}/{settings.HTF_TIMEFRAME} -- not an error, this "
            "is genuinely all the history that exists."
        )

    # --- 2. Replay through the real Strategy/Risk/Backtest engines ---
    try:
        result = run_backtest(candles, htf_candles)
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
