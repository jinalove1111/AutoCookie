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

Time-anchored fetches (`--end-date YYYY-MM-DD`): by default this script
fetches candles ending at "now". `--end-date` anchors the fetch to end at
a specific past date instead, via `CandleFetcher.fetch_ohlcv_history`'s
`end_time_ms` parameter -- this is what makes it possible to validate the
strategy against a genuinely different YEAR/macro regime, not just
different assets within the same recent window (see ROADMAP.md).

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
import math
import sys
from datetime import datetime, timezone
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
# Floor for the HTF fetch (see htf_candle_count_for_span) -- one full
# OKX page, ensuring detect_htf_bias() always has enough runway even
# when the LTF request is small.
_HTF_FLOOR_CANDLES = 300

from app.backtesting.backtest_engine import MIN_CANDLES, BacktestEngine
from app.backtesting.report_generator import ReportGenerator
from app.data.candle_fetcher import CandleFetcher, timeframe_to_timedelta
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine


def fetch_candles(
    symbol: str, timeframe: str, requested: int, end_time_ms: int | None = None
) -> list:
    """Fetch historical candles for `symbol`/`timeframe` via
    `CandleFetcher.fetch_ohlcv_history()` -- real deep pagination (see
    module docstring), not a single 300-candle-capped call. May return
    fewer than `requested` if OKX's actual history for this instrument/
    timeframe runs out first; that shortfall is printed as a note by the
    caller (via the returned count), not silently swallowed here.

    `end_time_ms` (optional): anchors the fetch to end at this timestamp
    instead of "now" -- see `CandleFetcher.fetch_ohlcv_history`'s
    docstring. This is what `--end-date` uses to validate the strategy
    against a specific past YEAR, not just "however far back `--candles`
    happens to reach from today."
    """
    return CandleFetcher().fetch_ohlcv_history(
        symbol, timeframe, total_candles=requested, end_time_ms=end_time_ms
    )


def htf_candle_count_for_span(ltf_timeframe: str, ltf_candle_count: int, htf_timeframe: str) -> int:
    """How many `htf_timeframe` candles are needed to cover the SAME real
    time span as `ltf_candle_count` candles of `ltf_timeframe`.

    Bug found and fixed while running a deep multi-period backtest: this
    script previously requested the SAME candle COUNT for both the LTF
    and HTF fetch, but a fixed count means wildly different real time
    spans across timeframes -- requesting e.g. 18000 candles at `4h`
    asks for ~8 years of history (vs. the ~187 days actually needed to
    match an 18000-candle `15m` LTF request), making the HTF fetch page
    through vastly more history than needed (many minutes, and risking
    exhausting `fetch_ohlcv_history`'s `max_pages` safety cap before ever
    returning). See `app.data.candle_fetcher.timeframe_to_timedelta`'s
    docstring for the full story.

    A small floor (300, one full page) is applied so short LTF requests
    never ask for an unreasonably tiny HTF slice that would starve
    `detect_htf_bias()` of the history it needs (it requires >= 10 HTF
    candles with >= 2 swing highs/lows each, per `MIN_CANDLES`'s own
    sizing note in backtest_engine.py) -- slightly over-fetching HTF is
    harmless (`_advance_htf_cursor` simply won't use candles beyond what
    a given LTF step's timestamp allows), under-fetching risks silently
    degrading every early signal to "neutral" bias.
    """
    ltf_span = timeframe_to_timedelta(ltf_timeframe) * ltf_candle_count
    htf_bar = timeframe_to_timedelta(htf_timeframe)
    needed = math.ceil(ltf_span / htf_bar)
    return max(needed, _HTF_FLOOR_CANDLES)


def run_backtest(
    ltf_candles: list,
    htf_candles: list,
    use_breakeven: bool = False,
    use_breaker_block: bool = False,
    use_partial_tp: bool = False,
) -> Any:
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
        use_breakeven=use_breakeven,
        use_breaker_block=use_breaker_block,
        use_partial_tp=use_partial_tp,
    )


def split_into_periods(candles: list, periods: int) -> list[list]:
    """Split `candles` (already sorted oldest -> newest) into `periods`
    contiguous, NON-OVERLAPPING chronological chunks, in order (chunk 0 =
    oldest period, last chunk = most recent period, which absorbs any
    remainder from integer division so every candle is used exactly once).

    Deliberately NOT a walk-forward with a rolling parameter-fit window --
    this strategy has no tunable/fitted parameters to fit against a
    training window (see docs/strategy_spec.md / entry_model.py's
    documented "reasonable default, not tuned" constants). This is a
    simpler, honest way to check whether backtest results are consistent
    across genuinely disjoint historical windows rather than resting on a
    single continuous sample -- each period is run through
    `BacktestEngine.run()` completely independently (fresh account
    balance, no shared trades/equity state across periods), so a result
    that only "works" in one specific window and not others is a real,
    visible red flag here rather than hidden inside one long average.
    """
    if periods <= 1:
        return [candles]
    n = len(candles)
    chunk_size = n // periods
    chunks = [candles[i * chunk_size : (i + 1) * chunk_size] for i in range(periods - 1)]
    chunks.append(candles[(periods - 1) * chunk_size :])
    return chunks


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
        "--periods",
        type=int,
        default=1,
        help=(
            "Split the fetched history into this many equal, non-overlapping "
            "chronological periods and run the backtest independently on "
            "each (default 1 = single continuous run, unchanged behavior). "
            "Total candles fetched is --candles * --periods. Use this to "
            "check whether results are consistent across genuinely disjoint "
            "historical windows rather than resting on a single continuous "
            "sample -- see split_into_periods()'s docstring."
        ),
    )
    parser.add_argument(
        "--breakeven",
        action="store_true",
        default=False,
        help=(
            "Enable break-even stop management (opt-in, default off): once a "
            "trade has moved BREAKEVEN_TRIGGER_R (default 1R) in favor, its "
            "stop moves to entry. See app.backtesting.backtest_engine's "
            "BREAKEVEN_TRIGGER_R docstring and docs/strategy_coverage_audit.md "
            "-- this is an A/B-testable feature, not a proven improvement; "
            "run the same --symbol/--timeframe/--candles/--periods with and "
            "without this flag and compare."
        ),
    )
    parser.add_argument(
        "--breaker-block",
        action="store_true",
        default=False,
        help=(
            "Enable Breaker Block as an additional entry-zone candidate "
            "(opt-in, default off): app.strategy.order_block.detect_breaker_block() "
            "has existed and been unit-tested since Milestone 2 but was never "
            "wired into signal generation until this flag. See "
            "app.strategy.signal_engine.SignalEngine.generate_signal's "
            "use_breaker_block docstring and docs/strategy_coverage_audit.md "
            "-- A/B-testable, not a proven improvement; run the same "
            "--symbol/--timeframe/--candles/--periods with and without this "
            "flag and compare."
        ),
    )
    parser.add_argument(
        "--partial-tp",
        action="store_true",
        default=False,
        help=(
            "Enable partial take-profit (opt-in, default off): "
            "PARTIAL_TP_PORTION (default 50%%) of the position closes once "
            "price has moved PARTIAL_TP_TRIGGER_R (default 1R) in favor; "
            "the remaining size continues to the original stop_loss/"
            "take_profit. app.execution.order_manager.OrderManager."
            "handle_partial_tp() has existed and been unit-tested since "
            "Milestone 3 but was never wired into any trade path until "
            "this flag. See app.backtesting.backtest_engine's "
            "PARTIAL_TP_TRIGGER_R/PARTIAL_TP_PORTION docstrings and "
            "docs/strategy_coverage_audit.md -- A/B-testable, not a proven "
            "improvement; run the same --symbol/--timeframe/--candles/"
            "--periods with and without this flag and compare."
        ),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help=(
            "Anchor the fetch to end at this UTC date (format: YYYY-MM-DD) "
            "instead of 'now' -- fetches the most recent --candles*--periods "
            "candles ENDING at this date, going backward. Use this to "
            "validate the strategy against a specific past YEAR/regime "
            "rather than only whatever window --candles happens to reach "
            "back to from today (see ROADMAP.md on why asset-only "
            "out-of-sample testing has diminishing returns once several "
            "assets in the same recent window have been checked). Default: "
            "None (fetch ending at 'now', unchanged behavior)."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=(
            "Path to write the markdown report to (default: "
            f"{DEFAULT_OUTPUT_PATH}). A sibling CSV trade export is written "
            "next to it with the same stem and a .csv extension. With "
            "--periods > 1, each period gets its own "
            "<stem>_period<N><suffix> report/CSV instead."
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

    # --- 1. Fetch historical LTF candles (real deep pagination, see docstring) ---
    try:
        candles = fetch_candles(args.symbol, args.timeframe, total_requested, end_time_ms)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1

    if not candles:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1

    print(f"Break-even stop management: {'ENABLED' if args.breakeven else 'disabled'}")
    print(f"Breaker Block entries: {'ENABLED' if args.breaker_block else 'disabled'}")
    print(f"Partial take-profit: {'ENABLED' if args.partial_tp else 'disabled'}")
    print(f"Fetched {len(candles)} candles for {args.symbol}/{args.timeframe}.")
    if len(candles) < total_requested:
        print(
            f"NOTE: requested {total_requested} candles but only {len(candles)} "
            f"are available from OKX for {args.symbol}/{args.timeframe} (e.g. "
            "a recent listing) -- not an error, this is genuinely all the "
            "history that exists."
        )
    if len(candles) < MIN_CANDLES * args.periods:
        print(
            f"NOTE: {len(candles)} candles across {args.periods} period(s) may "
            f"leave some periods below the engine's minimum of {MIN_CANDLES}; "
            "those periods will produce a valid, empty (0-trade) result."
        )

    # --- 1b. Fetch historical HTF candles (independent fetch, mirrors
    # run_paper.py's pattern: never fall back to reusing the LTF series as
    # HTF -- an HTF fetch failure or empty result is a hard failure here
    # too, since a silent LTF-as-HTF fallback would defeat the entire point
    # of the HTF/LTF separation). Sized to cover the SAME REAL TIME SPAN as
    # the LTF request, not the same raw candle count (see
    # htf_candle_count_for_span's docstring for the real bug this fixes --
    # found while running a deep multi-period backtest, where requesting
    # the LTF count verbatim for HTF asked for years more history than
    # needed and took many minutes to page through).
    htf_requested = htf_candle_count_for_span(args.timeframe, total_requested, settings.HTF_TIMEFRAME)
    try:
        htf_candles = fetch_candles(
            args.symbol, settings.HTF_TIMEFRAME, htf_requested, end_time_ms
        )
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch HTF candles for {args.symbol}: {exc}")
        return 1

    if not htf_candles:
        print(f"No HTF candles returned for {args.symbol}/{settings.HTF_TIMEFRAME}.")
        return 1

    print(f"Fetched {len(htf_candles)} HTF candles for {args.symbol}/{settings.HTF_TIMEFRAME}.")
    if len(htf_candles) < htf_requested:
        print(
            f"NOTE: requested {htf_requested} HTF candles (sized to cover the "
            f"same time span as {total_requested} {args.timeframe} LTF "
            f"candles) but only {len(htf_candles)} are available from OKX "
            f"for {args.symbol}/{settings.HTF_TIMEFRAME} -- not an error, "
            "this is genuinely all the history that exists."
        )

    # --- 2. Split into non-overlapping periods (periods=1 -> single chunk,
    # identical to pre-existing behavior) and replay each independently
    # through the real Strategy/Risk/Backtest engines. The FULL htf_candles
    # list is passed to every period -- safe, not a lookahead risk: each
    # period's BacktestEngine.run() starts its own no-lookahead HTF cursor
    # fresh at -1 and advances it purely from real timestamp comparisons
    # against that period's own LTF candles, so HTF data from outside a
    # given period's time range is simply never reached by that period's
    # cursor.
    ltf_periods = split_into_periods(candles, args.periods)
    results: list[Any] = []
    for period_num, ltf_chunk in enumerate(ltf_periods, start=1):
        try:
            result = run_backtest(
                ltf_chunk,
                htf_candles,
                use_breakeven=args.breakeven,
                use_breaker_block=args.breaker_block,
                use_partial_tp=args.partial_tp,
            )
        except Exception as exc:  # unexpected engine failure is a genuine failure
            print(f"ERROR: backtest engine raised an exception on period {period_num}: {exc}")
            return 1
        results.append(result)

        label = f"period {period_num}/{args.periods}" if args.periods > 1 else "Backtest complete"
        start_ts = ltf_chunk[0]["timestamp"] if ltf_chunk else None
        end_ts = ltf_chunk[-1]["timestamp"] if ltf_chunk else None
        print(f"{label}{f' ({start_ts} -> {end_ts})' if args.periods > 1 else ''}:")
        print(f"  candles       : {len(ltf_chunk)}")
        print(f"  total_trades  : {result.total_trades}")
        print(f"  win_rate      : {result.win_rate * 100:.2f}%")
        print(f"  total_pnl     : {result.total_pnl:.2f}")
        print(f"  max_drawdown  : {result.max_drawdown * 100:.2f}%")

    # --- 3. Aggregate summary across periods (only meaningful/printed when
    # periods > 1 -- otherwise identical to the single-run output above) ---
    if args.periods > 1:
        total_trades = sum(r.total_trades for r in results)
        total_pnl = sum(r.total_pnl for r in results)
        profitable_periods = sum(1 for r in results if r.total_pnl > 0)
        print("Aggregate across periods (each period run fully independently -- fresh "
              "account balance, no shared state):")
        print(f"  periods           : {args.periods}")
        print(f"  profitable periods: {profitable_periods}/{args.periods}")
        print(f"  total_trades      : {total_trades}")
        print(f"  total_pnl (summed): {total_pnl:.2f}")
        print(
            "  NOTE: consistency across periods matters more than the sum -- "
            "a strategy profitable in only some periods is NOT validated, "
            "regardless of the aggregate total."
        )

    # --- 4. Write markdown report(s) + CSV trade export(s) ---
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_generator = ReportGenerator()

    for period_num, result in enumerate(results, start=1):
        if args.periods > 1:
            period_output = output_path.with_name(
                f"{output_path.stem}_period{period_num}{output_path.suffix}"
            )
        else:
            period_output = output_path
        csv_path = period_output.with_suffix(".csv")

        report_markdown = report_generator.generate(result)
        period_output.write_text(report_markdown, encoding="utf-8")
        report_generator.export_csv(result, str(csv_path))

        print(f"Markdown report written to: {period_output}")
        print(f"CSV trade export written to: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
