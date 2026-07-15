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

Walk-forward validation (`--walk-forward`, requires `--periods > 1`):
prints an explicit PASS/FAIL report checking the chronological sequence
of periods for degradation trends and losing streaks that a simple
aggregate sum would hide -- see `walk_forward_report()`'s docstring for
exact criteria. This is deliberately NOT a rolling parameter-refitting
walk-forward (see `ENGINEERING_DECISIONS.md` decision #8): the strategy
has no tunable parameters yet, so there is nothing to refit between
periods. It IS a genuine check that performance holds up moving forward
through time, which is what "walk-forward validation" means in this
project's Phase 1 checklist (see `ROADMAP.md`).

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
from app.strategy.experimental import all_strategies
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
    require_full_confluence: bool = False,
    require_ob_fvg_confluence: bool = False,
    use_structure_tp: bool = False,
    require_premium_discount_filter: bool = False,
    use_jade_engine: bool = False,
    structure_tp_max_r: float | None = None,
    entry_delay_candles: int = 0,
    fee_percent: float = 0.05,
    slippage_percent: float = 0.02,
    account_balance: float = 10000.0,
    require_session: str | None = None,
    max_entry_drift_pct: float | None = None,
    atr_stop_multiplier: float | None = None,
    strategy: Any = None,
) -> Any:
    """Replay `ltf_candles`/`htf_candles` once through the real
    Strategy/Risk/Backtest engines.

    `fee_percent`/`slippage_percent`/`account_balance` default to this
    project's standard assumptions (matching `app.execution.paper_broker`'s
    real constants -- see ENGINEERING_DECISIONS.md #41's fee/slippage
    verification) but are now caller-overridable -- added for the
    2026-07-14 robustness validation's fee/slippage stress tests, which
    need to re-run the SAME candidate under deliberately worse cost
    assumptions.

    `strategy` (default `None`, Milestone 9, 2026-07-16): when given a
    `Strategy`-conforming instance (resolved via `--strategy` /
    `app.strategy.experimental.all_strategies()`, see `main()`), threaded
    straight through to `BacktestEngine.run(..., strategy=...)` -- every
    SignalEngine-configuration flag above is then ignored, see that
    parameter's own docstring. Default `None` preserves the exact prior
    SignalEngine-driven behavior for every existing caller.
    """
    return BacktestEngine().run(
        ltf_candles,
        htf_candles,
        SignalEngine(),
        RiskManager(),
        account_balance=account_balance,
        fee_percent=fee_percent,
        slippage_percent=slippage_percent,
        use_breakeven=use_breakeven,
        use_breaker_block=use_breaker_block,
        use_partial_tp=use_partial_tp,
        require_full_confluence=require_full_confluence,
        require_ob_fvg_confluence=require_ob_fvg_confluence,
        use_structure_tp=use_structure_tp,
        require_premium_discount_filter=require_premium_discount_filter,
        use_jade_engine=use_jade_engine,
        structure_tp_max_r=structure_tp_max_r,
        entry_delay_candles=entry_delay_candles,
        require_session=require_session,
        max_entry_drift_pct=max_entry_drift_pct,
        atr_stop_multiplier=atr_stop_multiplier,
        strategy=strategy,
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


def walk_forward_report(
    results: list,
    min_profitable_ratio: float = 0.66,
    max_losing_streak: int = 2,
) -> dict:
    """Evaluate a sequence of `BacktestResult`s (one per chronological
    period from `split_into_periods`, already in oldest -> newest order)
    against explicit, deterministic walk-forward validation criteria.

    This is NOT a rolling parameter-refitting walk-forward (see decision
    #8 in ENGINEERING_DECISIONS.md -- the strategy has no tunable
    parameters yet, so there is nothing to refit). It IS a genuine
    walk-forward-style check that the strategy's behavior holds up as
    you move STRICTLY FORWARD through time, rather than just averaging
    disjoint periods together: it looks for degradation trends and
    losing streaks that an aggregate sum would hide.

    Criteria (documented so a PASS/FAIL is reproducible, not a vibe):
      - `min_profitable_ratio` (default 0.66): at least this fraction of
        periods must have `total_pnl > 0`.
      - `max_losing_streak` (default 2): no more than this many
        CONSECUTIVE unprofitable periods in the chronological sequence
        (a strategy that goes cold for 3+ periods in a row is a real
        red flag a simple profitable-period COUNT would miss).
      - Degradation check: compares the average PnL of the first half of
        the sequence against the second half. If the first half averaged
        a positive PnL, the second half must retain at least 50% of it
        (a >50% falloff is flagged as degrading). If the first half
        averaged <= 0, any further decline in the second half is flagged.
        This is a simple, honest heuristic -- not a formal statistical
        trend test -- and is documented as such rather than dressed up
        as more rigorous than it is. For odd period counts, the middle
        period is excluded from both halves (compares the oldest half
        against the newest half only).

    Raises `ValueError` if `results` has fewer than 2 periods (a
    walk-forward comparison needs at least two points to compare).
    """
    n = len(results)
    if n < 2:
        raise ValueError("walk_forward_report requires at least 2 periods to compare")

    pnls = [r.total_pnl for r in results]
    profitable_flags = [pnl > 0 for pnl in pnls]
    profitable_count = sum(profitable_flags)
    profitable_ratio = profitable_count / n

    max_streak = 0
    current_streak = 0
    for flag in profitable_flags:
        if flag:
            current_streak = 0
        else:
            current_streak += 1
            max_streak = max(max_streak, current_streak)

    half = n // 2
    first_half_avg = sum(pnls[:half]) / half
    second_half_avg = sum(pnls[n - half :]) / half
    if first_half_avg > 0:
        degrading = second_half_avg < first_half_avg * 0.5
    else:
        degrading = second_half_avg < first_half_avg

    passed = (
        profitable_ratio >= min_profitable_ratio
        and max_streak <= max_losing_streak
        and not degrading
    )

    return {
        "periods": n,
        "profitable_periods": profitable_count,
        "profitable_ratio": profitable_ratio,
        "max_losing_streak": max_streak,
        "first_half_avg_pnl": first_half_avg,
        "second_half_avg_pnl": second_half_avg,
        "degrading": degrading,
        "passed": passed,
        "criteria": {
            "min_profitable_ratio": min_profitable_ratio,
            "max_losing_streak": max_losing_streak,
        },
    }


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
        "--strict-confluence",
        action="store_true",
        default=False,
        help=(
            "Require BOTH a matching liquidity sweep AND a matching CHOCH "
            "(not just one) before a signal is produced -- resolves a real "
            "spec/code ambiguity in docs/strategy_spec.md section 6, which "
            "reads as requiring ALL of sweep+CHOCH+FVG/OB in confluence, "
            "while the actual (default) code has always required only one "
            "of sweep/CHOCH. See app.strategy.entry_model.build_entry_model's "
            "require_full_confluence docstring for the full rationale. "
            "A/B-testable, not a proven improvement; run the same "
            "--symbol/--timeframe/--candles/--periods with and without this "
            "flag and compare."
        ),
    )
    parser.add_argument(
        "--ob-fvg-confluence",
        action="store_true",
        default=False,
        help=(
            "Require BOTH a matching order block/breaker block AND a "
            "matching FVG (not just one) before a signal is produced -- "
            "changes zone selection from 'either zone' to 'both agree' "
            "(see docs/ROADMAP.md 'Core Rule MVP completion' item #3). "
            "See app.strategy.entry_model.build_entry_model's "
            "require_ob_fvg_confluence docstring for the full rationale. "
            "A/B-testable, not a proven improvement; run the same "
            "--symbol/--timeframe/--candles/--periods with and without this "
            "flag and compare."
        ),
    )
    parser.add_argument(
        "--structure-tp",
        action="store_true",
        default=False,
        help=(
            "Target real structure for take-profit instead of the fixed-RR "
            "target: long targets the previous swing high first, extending "
            "to the premium/discount 0.5 equilibrium if that reaches "
            "further (short mirrors this to the downside); falls back to "
            "the fixed-RR target when neither structure candidate is a "
            "valid forward target (see docs/ROADMAP.md 'Core Rule MVP "
            "completion' item #4). See "
            "app.strategy.entry_model.build_entry_model's use_structure_tp "
            "docstring for the full rationale. A/B-testable, not a proven "
            "improvement; run the same --symbol/--timeframe/--candles/"
            "--periods with and without this flag and compare."
        ),
    )
    parser.add_argument(
        "--premium-discount-filter",
        action="store_true",
        default=False,
        help=(
            "Reject a long entered from the premium half of the current "
            "swing range, or a short entered from the discount half "
            "(standard ICT/SMC entry-quality rule -- see "
            "docs/strategy_spec.md section 8). See "
            "app.strategy.entry_model.build_entry_model's "
            "require_premium_discount_filter docstring for the full "
            "rationale. A/B-testable, not a proven improvement; run the "
            "same --symbol/--timeframe/--candles/--periods with and "
            "without this flag and compare."
        ),
    )
    parser.add_argument(
        "--jade-engine",
        action="store_true",
        default=False,
        help=(
            "Bypass the legacy entry_model.build_entry_model pipeline "
            "entirely and use the complete Jade methodology instead "
            "(app.strategy.jade_trade_plan.build_trade_plan -- bias, all "
            "5 entry models, exit targets, HTF confluence, trendline, "
            "CRT, session bias). Every OTHER strategy flag above is "
            "ignored when this is set, since those only configure the "
            "legacy path this bypasses. See "
            "app.strategy.signal_engine.SignalEngine.generate_signal's "
            "use_jade_engine docstring and ENGINEERING_DECISIONS.md "
            "#34/#35 for the full rationale. A/B-testable, not a proven "
            "improvement; run the same --symbol/--timeframe/--candles/"
            "--periods with and without this flag and compare."
        ),
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help=(
            "Evaluate a specific Strategy-Protocol module (Milestone 9, "
            "2026-07-16 -- the adaptive platform's 'evidence pipeline': "
            "any module conforming to app.strategy.strategy_interface."
            "Strategy can be backtested through this SAME engine -- fees, "
            "slippage, walk-forward -- before ever being considered for "
            "production) instead of the default SignalEngine pipeline. "
            "Resolved by name from app.strategy.experimental.all_strategies() "
            "(production AVAILABLE_STRATEGIES + any registered experimental "
            "strategies); an unknown name exits with an error listing the "
            "available names. Default: None (today's SignalEngine-driven "
            "behavior, unchanged). Composing with other flags: when set, "
            "every SignalEngine-configuration flag above (--breaker-block, "
            "--strict-confluence, --ob-fvg-confluence, --structure-tp, "
            "--premium-discount-filter, --jade-engine) is ignored with a "
            "printed NOTE if set -- they only configure the legacy "
            "SignalEngine path this bypasses entirely. --breakeven/"
            "--partial-tp still apply normally -- those are trade-"
            "management features applied by BacktestEngine AFTER a signal "
            "fires, independent of which path produced it."
        ),
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        default=False,
        help=(
            "Print a walk-forward validation report after the per-period "
            "results (requires --periods > 1). Checks the chronological "
            "sequence of periods against explicit criteria: minimum "
            "profitable-period ratio, maximum consecutive losing "
            "periods, and a first-half-vs-second-half degradation check "
            "-- see walk_forward_report()'s docstring for exact criteria "
            "and why this is not a parameter-refitting walk-forward "
            "(the strategy has no tunable parameters yet)."
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

    # --- 0. Resolve --strategy (Milestone 9, opt-in, default None =
    # unchanged SignalEngine-driven behavior). Done before any candle fetch
    # so an unknown name fails fast rather than after a slow network call. ---
    strategy_obj: Any = None
    if args.strategy is not None:
        available = all_strategies()
        strategy_obj = available.get(args.strategy)
        if strategy_obj is None:
            print(
                f"ERROR: unknown --strategy {args.strategy!r}. Available: "
                f"{', '.join(sorted(available.keys()))}."
            )
            return 1
        # SignalEngine-configuration flags only configure the SignalEngine
        # path, which --strategy bypasses entirely -- warn (not error, same
        # spirit as --jade-engine's existing "every other flag is ignored"
        # precedent) if any were set to a non-default value alongside it.
        signal_engine_only_flags = {
            "--breaker-block": args.breaker_block,
            "--strict-confluence": args.strict_confluence,
            "--ob-fvg-confluence": args.ob_fvg_confluence,
            "--structure-tp": args.structure_tp,
            "--premium-discount-filter": args.premium_discount_filter,
            "--jade-engine": args.jade_engine,
        }
        ignored = [name for name, is_set in signal_engine_only_flags.items() if is_set]
        if ignored:
            print(
                f"NOTE: --strategy {args.strategy!r} bypasses the SignalEngine "
                f"pipeline entirely, so these flag(s) have no effect: "
                f"{', '.join(ignored)}."
            )
        print(f"Strategy module: {args.strategy!r} (bypasses SignalEngine)")
    else:
        print("Strategy module: SignalEngine (default)")

    print(f"Break-even stop management: {'ENABLED' if args.breakeven else 'disabled'}")
    print(f"Breaker Block entries: {'ENABLED' if args.breaker_block else 'disabled'}")
    print(f"Partial take-profit: {'ENABLED' if args.partial_tp else 'disabled'}")
    print(f"Strict confluence (sweep AND choch): {'ENABLED' if args.strict_confluence else 'disabled'}")
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
                require_full_confluence=args.strict_confluence,
                require_ob_fvg_confluence=args.ob_fvg_confluence,
                use_structure_tp=args.structure_tp,
                require_premium_discount_filter=args.premium_discount_filter,
                use_jade_engine=args.jade_engine,
                strategy=strategy_obj,
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

    # --- 3b. Walk-forward validation report (opt-in via --walk-forward,
    # requires --periods > 1 -- see walk_forward_report()'s docstring for
    # exact criteria and why this is not a parameter-refitting walk-forward) ---
    if args.walk_forward:
        if args.periods <= 1:
            print("ERROR: --walk-forward requires --periods > 1 (need multiple chronological periods to compare).")
            return 1
        wf = walk_forward_report(results)
        print("Walk-forward validation report (chronological, oldest -> newest):")
        print(f"  profitable periods     : {wf['profitable_periods']}/{wf['periods']} "
              f"({wf['profitable_ratio'] * 100:.1f}%, criterion >= "
              f"{wf['criteria']['min_profitable_ratio'] * 100:.0f}%)")
        print(f"  max losing streak      : {wf['max_losing_streak']} "
              f"(criterion <= {wf['criteria']['max_losing_streak']})")
        print(f"  first-half avg PnL     : {wf['first_half_avg_pnl']:.2f}")
        print(f"  second-half avg PnL    : {wf['second_half_avg_pnl']:.2f}")
        print(f"  degrading trend        : {'YES' if wf['degrading'] else 'no'}")
        print(f"  WALK-FORWARD VALIDATION: {'PASSED' if wf['passed'] else 'FAILED'}")

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
