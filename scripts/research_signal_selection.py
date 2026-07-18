"""research_signal_selection.py

H1 experiment harness (docs/HYPOTHESES_ROUND_1.md section 2, pre-registered
2026-07-17): holding `settings.MAX_TRADES_PER_DAY` (2) fixed, does selecting
the two highest-QUALITY signals of the day (instead of the first two
chronologically) improve expectancy over Legacy's existing FIFO rule?

BACKTEST-ONLY research tool. Purely additive: no file in `app/risk/`,
`app/execution/`, or `scripts/run_paper.py` is touched by this module, and
`RiskManager.evaluate()`'s live sequential-approval logic is called
UNCHANGED (same signature, same decision rules) -- only which signals get
OFFERED to it, and in what order, differs by variant. Every downstream
mechanic (fees, slippage, fills, PnL) reuses `BacktestEngine` unchanged:
the chronological variant calls `BacktestEngine.run()` directly, and the
two ranked variants reuse `BacktestEngine._simulate_trade()` for every
fill.

Three variants, all replayable over the SAME already-fetched candle set:

  - "chronological": today's existing FIFO baseline. A direct pass-through
    to `run_backtest.run_backtest()` (-> `BacktestEngine.run()`) with NO
    day-batching at all -- guaranteed byte-identical to calling that
    function directly, not a second, independent reimplementation of FIFO
    behavior (see `run_variant()`).
  - "rr": Variant A, `score = signal.rr` (`TradeSignal.rr`, the real
    reward:risk implied by that specific entry/stop/target).
  - "rr_confluence": Variant B, `score = signal.rr + confluence_count`,
    where `confluence_count` (0-4) counts how many of the legacy pipeline's
    four structural confluence factors are present and direction-matching
    at that step: liquidity sweep, CHOCH/MSS, order block, FVG (see
    `docs/strategy_spec.md` section 6 and `_confluence_count()` below).

Both scoring formulas are declared here, disclosed-not-tuned, exactly as
pre-registered in `docs/HYPOTHESES_ROUND_1.md` section 2 -- no third
variant, no tuning of either formula.

Day-batched selection mechanism (rr / rr_confluence only):

  Phase 1 (`collect_candidates`): scans EVERY walk-forward step from
  `MIN_CANDLES - 1` onward and collects every non-`None` signal
  `SignalEngine.generate_signal()` would produce, tagged with its own UTC
  calendar day (`str(timestamp)[:10]`, the SAME day-rollover convention
  `BacktestEngine.run()` uses) and score inputs (`rr`, `confluence_count`).
  Unlike `BacktestEngine.run()`'s own single-pass walk-forward loop, this
  phase NEVER skips ahead for a hypothetically open trade -- there is no
  real trade open during a pure candidate scan, which is exactly what "EVERY
  candidate signal SignalEngine would have generated at each step" (the H1
  pre-registered spec's own wording) requires.

  Phase 2 (`select_daily_top`): ranks each day's candidates by
  `score_signal(...)` descending (ties broken by earliest arrival index --
  deterministic, relies on Python's stable sort), keeps the top
  `settings.MAX_TRADES_PER_DAY`, then re-sorts the kept candidates back into
  chronological (index) order for replay.

  Phase 3 (`replay_selected`): replays ONLY the selected signals, in
  chronological order, through the real `RiskManager.evaluate()` (with real
  `trades_today`/`daily_pnl_percent`/`weekly_pnl_percent` bookkeeping,
  mirroring `BacktestEngine.run()`'s own bookkeeping exactly) and
  `BacktestEngine._simulate_trade()` for fill/fee/slippage/PnL.

  Disclosed structural difference from the chronological baseline: because
  Phase 1's candidate scan is independent of execution state (no trade is
  ever actually open during that scan), two selected signals for the same
  day can straddle a still-open trade's window in a way that never arises
  in `BacktestEngine.run()`'s own single-pass loop (there, an open trade
  structurally prevents any candle inside its window from ever reaching
  signal generation at all). `replay_selected` preserves the
  single-open-trade-at-a-time invariant every other mode in this project
  respects: a selected candidate whose index falls before the currently
  open trade's own exit index is SKIPPED (never risk-evaluated, never
  simulated) -- exactly like "no signal this step," never force-opened as a
  second concurrent position. This can make a day execute fewer than
  `MAX_TRADES_PER_DAY` selected candidates; it never opens more than that
  cap allows.

CLI example (mirrors `scripts/run_backtest.py`'s own flags where
applicable):

    python scripts/research_signal_selection.py --symbol BTCUSDT \
        --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10 \
        --walk-forward

Writes a JSON report (`scripts/reports/research_signal_selection.json` by
default) with per-anchor, per-variant Net Profit / Profit Factor / trade
count / walk-forward pass-fail, directly comparable to the existing
chronological-FIFO baseline numbers already recorded in
`docs/ATR_FLOOR_EVALUATION.md` / `docs/LEGACY_DELAY_ROBUSTNESS.md`.

Does NOT run the full multi-year evaluation matrix itself -- that is a
separate, later step (see docs/HYPOTHESES_ROUND_1.md section 2's
pre-registered runs). This script is the harness those runs will use.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.backtesting.backtest_engine import (  # noqa: E402
    MIN_CANDLES,
    BacktestEngine,
    BacktestResult,
    _advance_htf_cursor,
    _day_bounds,
    _empty_risk_rejections,
    _get,
    _realized_pnl_in_window,
    _week_bounds,
)
from app.backtesting.performance import (  # noqa: E402
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_win_rate,
)
from app.config import settings  # noqa: E402
from app.risk.position_sizing import calculate_position_size  # noqa: E402
from app.risk.risk_manager import RiskManager  # noqa: E402
from app.strategy.fvg import find_latest_unmitigated_fvg_zone  # noqa: E402
from app.strategy.liquidity import detect_liquidity_sweep  # noqa: E402
from app.strategy.market_structure import detect_choch_mss  # noqa: E402
from app.strategy.order_block import detect_order_block  # noqa: E402
from app.strategy.signal_engine import SignalEngine  # noqa: E402
from app.strategy.utils import is_zone_mitigated  # noqa: E402

from run_backtest import (  # noqa: E402
    fetch_candles,
    htf_candle_count_for_span,
    run_backtest,
    split_into_periods,
    walk_forward_report,
)

VARIANTS = ("chronological", "rr", "rr_confluence")

SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
CANDLES_PER_PERIOD_DEFAULT = 3000
PERIODS_DEFAULT = 6
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_signal_selection.json"


# --- confluence scoring -----------------------------------------------------


def _confluence_count(ltf_slice: list, direction: str) -> int:
    """Independently recompute the legacy pipeline's own confluence
    factors (liquidity-sweep match, CHOCH match, order-block match, FVG
    match) for a signal `SignalEngine.generate_signal()` already produced
    at this exact walk-forward step, from the SAME no-lookahead candle
    slice the signal itself was generated from.

    Reuses the SAME pure detectors `SignalEngine.generate_signal()` calls
    internally (`app.strategy.liquidity.detect_liquidity_sweep`,
    `app.strategy.market_structure.detect_choch_mss`,
    `app.strategy.order_block.detect_order_block`,
    `app.strategy.fvg.find_latest_unmitigated_fvg_zone`) and mirrors
    `entry_model.build_entry_model`'s own matching-sweep/matching-choch/
    ob_zone/fvg_zone logic (`docs/strategy_spec.md` section 6) read-only,
    rather than re-deriving it from scratch -- this is a STANDALONE,
    research-only recomputation, not threaded through `TradeSignal` itself
    (that dataclass is shared with live/paper trading and is deliberately
    left untouched by this research tool).

    Returns an int 0-4: 1 point each for a direction-matching liquidity
    sweep, a direction-matching CHOCH, a direction-matching (and
    unmitigated) order block, and a direction-matching (and unmitigated)
    FVG. `direction` must be `"long"` or `"short"` (any other value
    returns 0 -- should never happen for a signal `generate_signal()`
    actually returned, since `build_entry_model` never produces one
    without a resolved direction).
    """
    if direction not in ("long", "short"):
        return 0

    bias = "bullish" if direction == "long" else "bearish"
    wanted_sweep_type = "sell_side" if direction == "long" else "buy_side"
    wanted_choch_type = "bullish_choch" if direction == "long" else "bearish_choch"

    sweep = detect_liquidity_sweep(ltf_slice)
    choch = detect_choch_mss(ltf_slice, swept_index=sweep["swept_index"] if sweep else None)
    matching_sweep = sweep is not None and sweep["type"] == wanted_sweep_type
    matching_choch = choch is not None and choch["type"] == wanted_choch_type

    order_block = detect_order_block(ltf_slice)
    if order_block is not None and is_zone_mitigated(
        ltf_slice,
        order_block["impulse_index"] + 1,
        order_block["top"],
        order_block["bottom"],
    ):
        order_block = None
    ob_present = order_block is not None and order_block["type"] == bias

    fvg_zone = find_latest_unmitigated_fvg_zone(ltf_slice, bias)
    fvg_present = fvg_zone is not None

    return int(matching_sweep) + int(matching_choch) + int(ob_present) + int(fvg_present)


def score_signal(rr: float, confluence_count: int, variant: str) -> float:
    """Disclosed-not-tuned scoring formula (H1, `docs/HYPOTHESES_ROUND_1.md`
    section 2) -- both variants declared now, not chosen post-hoc, no third
    variant.

    `variant="rr"` (Variant A): `score = rr`.
    `variant="rr_confluence"` (Variant B): `score = rr + confluence_count`.

    Raises `ValueError` for `variant="chronological"` or any other unknown
    value -- chronological selection does not use a score at all (see
    `select_daily_top`'s docstring), so calling this for it would be a
    caller bug, not a silently-handled case.
    """
    if variant == "rr":
        return rr
    if variant == "rr_confluence":
        return rr + confluence_count
    raise ValueError(
        f"score_signal: unknown variant {variant!r} (expected 'rr' or 'rr_confluence')"
    )


# --- candidate collection (Phase 1) -----------------------------------------


@dataclass
class Candidate:
    """One signal-generation step's non-`None` result, tagged for
    day-batched selection.

    `index`: the walk-forward LTF index the signal was generated at (same
    convention as `BacktestEngine.run()`'s own `i`).
    `day`: the UTC calendar day key (`str(timestamp)[:10]`), matching
    `BacktestEngine.run()`'s own day-rollover convention.
    `signal`: the real `TradeSignal` (or duck-typed equivalent) produced.
    `rr` / `confluence_count`: score inputs, precomputed once at collection
    time so `select_daily_top` can score the SAME candidate population
    identically for every ranked variant, without re-scanning candles.
    """

    index: int
    day: str
    signal: Any
    rr: float
    confluence_count: int


def collect_candidates(ltf_candles: list, htf_candles: list, signal_engine: Any) -> list["Candidate"]:
    """Phase 1: scan EVERY walk-forward step from `MIN_CANDLES - 1` onward
    and collect every non-`None` signal `signal_engine.generate_signal()`
    would produce.

    Unlike `BacktestEngine.run()`'s own single-pass loop, this NEVER skips
    ahead for a hypothetically open trade -- no real trade is ever open
    during this scan, so every step's signal (if any) is observed. Uses the
    SAME no-lookahead HTF cursor mechanism (`_advance_htf_cursor`) and the
    SAME default `SignalEngine` flags (all off) the chronological baseline
    uses -- this tool varies signal SELECTION only, never any other
    strategy flag.
    """
    candidates: list[Candidate] = []
    if len(ltf_candles) < MIN_CANDLES:
        return candidates

    htf_cursor = -1
    i = MIN_CANDLES - 1
    while i < len(ltf_candles):
        ltf_timestamp = _get(ltf_candles[i], "timestamp")
        day = str(ltf_timestamp)[:10]
        symbol = _get(ltf_candles[i], "symbol") or "UNKNOWN"

        htf_cursor = _advance_htf_cursor(htf_candles, htf_cursor, ltf_timestamp)
        htf_slice = htf_candles[: htf_cursor + 1]

        signal = signal_engine.generate_signal(
            symbol=symbol,
            ltf_candles=ltf_candles[: i + 1],
            htf_candles=htf_slice,
        )
        if signal is not None:
            confluence_count = _confluence_count(ltf_candles[: i + 1], signal.direction)
            candidates.append(
                Candidate(
                    index=i,
                    day=day,
                    signal=signal,
                    rr=signal.rr,
                    confluence_count=confluence_count,
                )
            )
        i += 1

    return candidates


# --- daily selection (Phase 2) ----------------------------------------------


def select_daily_top(
    candidates: list["Candidate"], variant: str, cap: int | None = None
) -> list["Candidate"]:
    """Phase 2: group `candidates` by `.day` (preserving each day's
    ORIGINAL arrival order) and keep only the top `cap` (default
    `settings.MAX_TRADES_PER_DAY`) per day.

    `variant="chronological"`: no scoring at all -- plain first-`cap`-in-
    arrival-order per day (today's FIFO rule). Included here for
    completeness/testability; `run_variant()` never calls this for
    `"chronological"` in practice -- it delegates straight to
    `BacktestEngine.run()` instead, for a guaranteed byte-identical
    baseline rather than reproducing FIFO behavior a second, independent
    way.

    `variant in ("rr", "rr_confluence")`: each day's candidates are sorted
    by `score_signal(c.rr, c.confluence_count, variant)` descending. Ties
    are broken by earliest arrival index -- deterministic, since
    `candidates` (and therefore each day's group) is already in arrival
    order when passed in, and Python's `sorted()` is stable: equal-score
    candidates retain their original (arrival) relative order.

    Returns the selected candidates re-sorted by `.index` ascending
    (chronological replay order) -- within-day ranking only decides WHICH
    candidates are kept, never the order they are replayed in.
    """
    if cap is None:
        cap = settings.MAX_TRADES_PER_DAY

    by_day: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_day.setdefault(c.day, []).append(c)

    selected: list[Candidate] = []
    for day_candidates in by_day.values():
        if variant == "chronological":
            selected.extend(day_candidates[:cap])
        else:
            ranked = sorted(
                day_candidates,
                key=lambda c: score_signal(c.rr, c.confluence_count, variant),
                reverse=True,
            )
            selected.extend(ranked[:cap])

    selected.sort(key=lambda c: c.index)
    return selected


# --- replay (Phase 3) -------------------------------------------------------


def replay_selected(
    selected: list["Candidate"],
    ltf_candles: list,
    risk_manager: Any,
    account_balance: float = 10000.0,
    fee_percent: float = 0.05,
    slippage_percent: float = 0.02,
) -> "BacktestResult":
    """Phase 3: replay ONLY `selected` (already sorted by `.index`
    ascending -- see `select_daily_top`) through the real
    `RiskManager.evaluate()` and `BacktestEngine._simulate_trade()` --
    every downstream mechanic (fees, slippage, fills, PnL) is the SAME
    engine code the chronological baseline uses, completely unchanged.

    Single-open-trade-at-a-time invariant (same as `BacktestEngine.run()`):
    a selected candidate whose `.index` falls before the currently open
    trade's own exit index is SKIPPED entirely (never risk-evaluated,
    never simulated) -- exactly like "no signal this step," never
    force-opened as a second concurrent position. See module docstring for
    why this can arise here but never in `BacktestEngine.run()`'s own
    single-pass loop.
    """
    starting_balance = account_balance
    trades: list = []
    equity_curve = [account_balance]
    trades_today = 0
    current_day: str | None = None
    risk_rejections = _empty_risk_rejections()
    engine = BacktestEngine()

    open_until_index = -1  # no trade open initially

    for c in selected:
        if c.index <= open_until_index:
            continue

        ltf_timestamp = _get(ltf_candles[c.index], "timestamp")
        day = str(ltf_timestamp)[:10]
        if day != current_day:
            current_day = day
            trades_today = 0

        risk_rejections["total_signals"] += 1

        day_start, day_end = _day_bounds(ltf_timestamp)
        week_start, week_end = _week_bounds(ltf_timestamp)
        daily_pnl_percent = (
            _realized_pnl_in_window(trades, day_start, day_end) / starting_balance
        ) * 100
        weekly_pnl_percent = (
            _realized_pnl_in_window(trades, week_start, week_end) / starting_balance
        ) * 100

        risk_decision = risk_manager.evaluate(
            c.signal,
            trades_today=trades_today,
            daily_pnl_percent=daily_pnl_percent,
            weekly_pnl_percent=weekly_pnl_percent,
        )
        if getattr(risk_decision, "approved", False):
            risk_rejections["approved"] += 1
        else:
            risk_rejections["rejected"] += 1
            for reason in getattr(risk_decision, "reasons", None) or []:
                risk_rejections["by_reason"][reason] = (
                    risk_rejections["by_reason"].get(reason, 0) + 1
                )
            continue

        size = calculate_position_size(
            account_balance,
            settings.RISK_PER_TRADE_PERCENT,
            c.signal.entry_price,
            c.signal.stop_loss,
        )
        if size == 0.0:
            continue

        trades_today += 1
        trade, exit_index, account_balance = engine._simulate_trade(
            c.signal,
            ltf_candles,
            c.index,
            account_balance,
            fee_percent,
            slippage_percent,
            size,
        )
        trades.append(trade)
        equity_curve.append(account_balance)
        open_until_index = exit_index

    total_pnl = sum(t["pnl"] for t in trades)
    return BacktestResult(
        total_trades=len(trades),
        win_rate=calculate_win_rate(trades),
        total_pnl=total_pnl,
        max_drawdown=calculate_max_drawdown(equity_curve),
        trades=trades,
        risk_rejections=risk_rejections,
    )


# --- top-level variant runner ------------------------------------------------


def run_variant(
    ltf_candles: list,
    htf_candles: list,
    variant: str,
    account_balance: float = 10000.0,
    fee_percent: float = 0.05,
    slippage_percent: float = 0.02,
) -> "BacktestResult":
    """Run one full H1 variant over `ltf_candles`/`htf_candles`.

    `variant="chronological"`: delegates straight to
    `run_backtest.run_backtest()` (-> `BacktestEngine.run()`) with NO
    day-batching at all -- guaranteed byte-identical to today's existing
    FIFO baseline.

    `variant in ("rr", "rr_confluence")`: Phase 1 (`collect_candidates`) +
    Phase 2 (`select_daily_top`) + Phase 3 (`replay_selected`), using a
    fresh `SignalEngine`/`RiskManager` pair.
    """
    if variant not in VARIANTS:
        raise ValueError(f"run_variant: unknown variant {variant!r} (expected one of {VARIANTS})")

    if variant == "chronological":
        return run_backtest(
            ltf_candles,
            htf_candles,
            account_balance=account_balance,
            fee_percent=fee_percent,
            slippage_percent=slippage_percent,
        )

    signal_engine = SignalEngine()
    risk_manager = RiskManager()
    candidates = collect_candidates(ltf_candles, htf_candles, signal_engine)
    selected = select_daily_top(candidates, variant)
    return replay_selected(
        selected,
        ltf_candles,
        risk_manager,
        account_balance=account_balance,
        fee_percent=fee_percent,
        slippage_percent=slippage_percent,
    )


# --- CLI ---------------------------------------------------------------------


def _fetch(symbol: str, timeframe: str, total_candles: int, end_time_ms: int | None) -> tuple[list, list]:
    ltf = fetch_candles(symbol, timeframe, total_candles, end_time_ms)
    htf_req = htf_candle_count_for_span(timeframe, total_candles, settings.HTF_TIMEFRAME)
    htf = fetch_candles(symbol, settings.HTF_TIMEFRAME, htf_req, end_time_ms)
    return ltf, htf


def _metrics(results: list) -> dict:
    trades: list[dict] = []
    for r in results:
        trades.extend(r.trades)
    return {
        "total_pnl": sum(r.total_pnl for r in results),
        "profit_factor": calculate_profit_factor(trades) if trades else 0.0,
        "total_trades": len(trades),
        "profitable_periods": sum(1 for r in results if r.total_pnl > 0),
        "periods": len(results),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "H1 experiment harness (docs/HYPOTHESES_ROUND_1.md section 2): "
            "compares the chronological-FIFO baseline against rr-ranked and "
            "rr+confluence-ranked signal selection, holding "
            "settings.MAX_TRADES_PER_DAY fixed. Reuses BacktestEngine "
            "unchanged for every downstream mechanic."
        )
    )
    parser.add_argument("--symbol", default=SYMBOL, help=f"Default: {SYMBOL!r}")
    parser.add_argument("--timeframe", default=TIMEFRAME, help=f"Default: {TIMEFRAME!r}")
    parser.add_argument("--candles", type=int, default=CANDLES_PER_PERIOD_DEFAULT)
    parser.add_argument("--periods", type=int, default=PERIODS_DEFAULT)
    parser.add_argument(
        "--end-date",
        default=None,
        help="Anchor the fetch to end at this UTC date (YYYY-MM-DD), same convention as run_backtest.py.",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        default=False,
        help="Print/record a walk_forward_report() for each variant (requires --periods > 1).",
    )
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    end_time_ms: int | None = None
    if args.end_date is not None:
        end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_time_ms = int(end_dt.timestamp() * 1000)
        print(f"Anchoring fetch to end at {end_dt.isoformat()} (--end-date {args.end_date}).")

    total_requested = args.candles * args.periods
    try:
        ltf, htf = _fetch(args.symbol, args.timeframe, total_requested, end_time_ms)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1

    if not ltf or not htf:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1

    print(f"Fetched {len(ltf)} LTF / {len(htf)} HTF candles for {args.symbol}/{args.timeframe}.")

    ltf_periods = split_into_periods(ltf, args.periods)
    report: dict[str, Any] = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
        "variants": {},
    }

    for variant in VARIANTS:
        print(f"\n### Variant: {variant} ###")
        results = [run_variant(chunk, htf, variant) for chunk in ltf_periods]
        entry: dict[str, Any] = {"metrics": _metrics(results)}
        if args.walk_forward and len(results) >= 2:
            entry["walk_forward"] = walk_forward_report(results)
        report["variants"][variant] = entry
        print(json.dumps(entry, indent=2, default=str))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
