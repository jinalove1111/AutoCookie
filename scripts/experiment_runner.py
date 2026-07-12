"""experiment_runner.py

Controlled, reproducible A/B experiment harness for Legacy-pipeline
candidate features (operator directive, 2026-07-12 "AUTONOMOUS 2-HOUR
PROFITABILITY SPRINT", Phase B). Legacy (`entry_model.build_entry_model`,
all experimental flags False) is the LOCKED baseline and the only
production-approved configuration -- this script never changes that; it
only measures whether a candidate flag combination is a robust enough
improvement to be worth a future, separate, deliberate decision to flip a
default. Nothing here writes to the paper-trading DB or touches
`scripts/run_paper.py`'s running process.

Design, matching this project's established discipline
(ENGINEERING_DECISIONS.md #8/#14/#15/#18):

  - ONE candle fetch (LTF + HTF), anchored to a FIXED `--end-date`, reused
    across every named config -- guarantees every candidate is compared
    against the LITERAL SAME price data as the baseline, not a
    close-but-not-identical fetch from a slightly different "now" (the
    gap that made the 2026-07-12 same-session Legacy/Jade comparison
    require a re-fetched baseline earlier this session).
  - Periods split via `run_backtest.split_into_periods` (already-existing,
    tested chronological splitter). The newest `--holdout-periods` periods
    are held out as genuinely untouched out-of-sample data: every keep/
    reject decision is made on in-sample periods first, out-of-sample is
    only ever CONFIRMED against afterward, never used to pick a candidate.
  - No look-ahead: reuses `BacktestEngine.run()`'s own no-lookahead HTF
    cursor unmodified -- this script never touches candle ordering or
    HTF/LTF separation logic itself.
  - Every result (full metrics + exact config + exact command) is
    appended to `scripts/reports/experiment_results.json` -- a
    machine-readable, append-only ledger, one record per run, so every
    number in docs/PROFITABILITY_EXPERIMENT_REPORT.md traces back to a
    reproducible, timestamped record.

Usage:
    python experiment_runner.py --configs baseline structure_tp
    python experiment_runner.py --configs all
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.backtesting.performance import calculate_profit_factor, calculate_win_rate  # noqa: E402
from app.config import settings  # noqa: E402

from run_backtest import (  # noqa: E402
    fetch_candles,
    htf_candle_count_for_span,
    run_backtest,
    split_into_periods,
    walk_forward_report,
)

RESULTS_LEDGER = SCRIPT_DIR / "reports" / "experiment_results.json"

# --- Named candidate configs ------------------------------------------------
# Every value here is an EXISTING, already-implemented, already-individually-
# switchable kwarg of `run_backtest()`/`BacktestEngine.run()`. No new trading
# concepts are introduced by this dict -- see module docstring.
CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "structure_tp": {"use_structure_tp": True},
    "ob_fvg_confluence": {"require_ob_fvg_confluence": True},
    "premium_discount_filter": {"require_premium_discount_filter": True},
    "structure_tp_and_premium_discount_filter": {
        "use_structure_tp": True,
        "require_premium_discount_filter": True,
    },
    # Phase D #5: conservative-exit variant -- SAME entries/stops as
    # structure_tp (structure_tp_max_r never touches zone/entry/stop
    # selection, see entry_model.py), caps the structure target's implied
    # reward:risk at 3.0R so it can only ever pull take_profit NEARER than
    # uncapped structure_tp would, never farther. Not a new trading
    # concept -- a bounded version of the same, already-implemented target.
    "structure_tp_capped_3r": {"use_structure_tp": True, "structure_tp_max_r": 3.0},
}
# Deliberately NOT re-included: use_breaker_block/use_breakeven/use_partial_tp/
# require_full_confluence/use_jade_engine -- already conclusively A/B tested
# across 4 assets x 2 years in prior sessions (all negative or inconsistent,
# see ENGINEERING_DECISIONS.md #10-#17/#34-#36). Re-running them here would
# violate this sprint's own "do not revive previously conclusive negative
# features unless there is a documented implementation defect" instruction --
# no such defect has been found.


@dataclass
class SegmentMetrics:
    periods: int
    total_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    expectancy: float
    avg_r: float | None
    max_drawdown_worst: float
    max_drawdown_avg: float
    return_over_drawdown: float
    profitable_periods: int
    period_pnls: list[float] = field(default_factory=list)


def _segment_metrics(results: list, account_balance: float) -> SegmentMetrics:
    all_trades = [t for r in results for t in r.trades]
    total_trades = len(all_trades)
    total_pnl = sum(r.total_pnl for r in results)
    r_multiples = [
        t["pnl"] / (t["risk_per_unit"] * t["size"])
        for t in all_trades
        if t.get("risk_per_unit") and t.get("size")
    ]
    dds = [r.max_drawdown for r in results] if results else [0.0]
    worst_dd = max(dds)
    avg_dd = statistics.mean(dds)
    if worst_dd > 0:
        return_over_dd = total_pnl / (worst_dd * account_balance)
    else:
        return_over_dd = float("inf") if total_pnl > 0 else 0.0

    return SegmentMetrics(
        periods=len(results),
        total_trades=total_trades,
        total_pnl=total_pnl,
        win_rate=calculate_win_rate(all_trades) if all_trades else 0.0,
        profit_factor=calculate_profit_factor(all_trades) if all_trades else 0.0,
        expectancy=(total_pnl / total_trades) if total_trades else 0.0,
        avg_r=(statistics.mean(r_multiples) if r_multiples else None),
        max_drawdown_worst=worst_dd,
        max_drawdown_avg=avg_dd,
        return_over_drawdown=return_over_dd,
        profitable_periods=sum(1 for r in results if r.total_pnl > 0),
        period_pnls=[r.total_pnl for r in results],
    )


MIN_TRADES_FOR_CONFIDENCE = 20  # below this, "adequate trade count" fails (Phase C)


def evaluate_candidate(
    name: str,
    in_sample: SegmentMetrics,
    out_of_sample: SegmentMetrics,
    wf: dict,
    baseline_in_sample: SegmentMetrics,
) -> dict:
    """Phase C reject rules + Phase C ranking score. Legacy baseline is
    never itself "rejected" by this function (it has nothing to be
    compared against) -- callers should skip calling this for the
    baseline config itself.
    """
    reasons: list[str] = []

    if not wf["passed"]:
        reasons.append(
            f"walk-forward FAILED (profitable_ratio={wf['profitable_ratio']:.2f}, "
            f"max_losing_streak={wf['max_losing_streak']}, degrading={wf['degrading']})"
        )
    if out_of_sample.total_trades == 0:
        reasons.append("zero trades in the held-out out-of-sample segment -- cannot confirm")
    elif out_of_sample.total_pnl <= 0:
        reasons.append(
            f"out-of-sample segment NOT profitable (total_pnl={out_of_sample.total_pnl:.2f})"
        )
    if in_sample.total_trades < MIN_TRADES_FOR_CONFIDENCE:
        reasons.append(
            f"too few in-sample trades ({in_sample.total_trades} < {MIN_TRADES_FOR_CONFIDENCE}) "
            "to trust the result"
        )
    if in_sample.periods >= 3 and in_sample.profitable_periods <= 1:
        reasons.append(
            f"profit concentrated in <=1 of {in_sample.periods} in-sample periods "
            "-- single-period dependence"
        )
    # The project's own stated bar (operator directive, prior turn this
    # session): keep only if Net Profit AND Profit Factor AND Drawdown all
    # improve over baseline (worst-period drawdown, the more conservative
    # of the two DD figures tracked).
    improves_net_profit = in_sample.total_pnl > baseline_in_sample.total_pnl
    improves_profit_factor = in_sample.profit_factor > baseline_in_sample.profit_factor
    improves_drawdown = in_sample.max_drawdown_worst < baseline_in_sample.max_drawdown_worst
    if not (improves_net_profit and improves_profit_factor and improves_drawdown):
        reasons.append(
            "fails the three-metric keep rule (Net Profit improve="
            f"{improves_net_profit}, Profit Factor improve={improves_profit_factor}, "
            f"Drawdown improve={improves_drawdown})"
        )

    verdict = "KEEP" if not reasons else "REJECT"

    # Phase C ranking score: a sortable tuple in the EXACT stated priority
    # order (walk-forward pass > out-of-sample profitability > profit
    # factor > drawdown control > expectancy > adequate trade count > net
    # profit). Higher is better in every position.
    rank_key = (
        1 if wf["passed"] else 0,
        1 if out_of_sample.total_pnl > 0 else 0,
        in_sample.profit_factor if in_sample.profit_factor != float("inf") else 1e9,
        -in_sample.max_drawdown_worst,
        in_sample.expectancy,
        1 if in_sample.total_trades >= MIN_TRADES_FOR_CONFIDENCE else 0,
        in_sample.total_pnl,
    )

    return {
        "verdict": verdict,
        "reject_reasons": reasons,
        "rank_key": rank_key,
        "improves_net_profit": improves_net_profit,
        "improves_profit_factor": improves_profit_factor,
        "improves_drawdown": improves_drawdown,
    }


def run_one_config(
    name: str,
    kwargs: dict,
    ltf_periods: list[list],
    htf_candles: list,
    holdout_periods: int,
    account_balance: float,
) -> dict:
    period_results = []
    for ltf_chunk in ltf_periods:
        result = run_backtest(ltf_chunk, htf_candles, **kwargs)
        period_results.append(result)

    n = len(period_results)
    in_sample_results = period_results[: n - holdout_periods]
    out_of_sample_results = period_results[n - holdout_periods :]

    in_sample = _segment_metrics(in_sample_results, account_balance)
    out_of_sample = _segment_metrics(out_of_sample_results, account_balance)
    combined = _segment_metrics(period_results, account_balance)

    wf = None
    if len(in_sample_results) >= 2:
        wf = walk_forward_report(in_sample_results)

    return {
        "name": name,
        "config": kwargs,
        "in_sample": asdict(in_sample),
        "out_of_sample": asdict(out_of_sample),
        "combined": asdict(combined),
        "walk_forward_in_sample": wf,
    }


def _append_ledger(records: list[dict], run_meta: dict) -> None:
    RESULTS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if RESULTS_LEDGER.exists():
        try:
            existing = json.loads(RESULTS_LEDGER.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    for record in records:
        existing.append({**run_meta, **record})
    RESULTS_LEDGER.write_text(json.dumps(existing, indent=2, default=str))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=settings.SYMBOL)
    parser.add_argument("--timeframe", default=settings.DEFAULT_TIMEFRAME)
    parser.add_argument("--candles", type=int, default=3000)
    parser.add_argument("--periods", type=int, default=6)
    parser.add_argument("--holdout-periods", type=int, default=1)
    parser.add_argument(
        "--end-date",
        default="2026-07-12",
        help=(
            "Fixed anchor date (default 2026-07-12, this sprint's session "
            "date) -- ALL configs in one invocation share ONE fetch anchored "
            "here, guaranteeing identical underlying candle data across "
            "every candidate compared in this run. Override only to run a "
            "genuinely different, still-reproducible window."
        ),
    )
    parser.add_argument("--account-balance", type=float, default=10000.0)
    parser.add_argument(
        "--configs",
        nargs="+",
        default=["baseline"],
        help=f"Config names to run, or 'all'. Available: {list(CONFIGS)}",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    names = list(CONFIGS) if args.configs == ["all"] else args.configs
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        print(f"ERROR: unknown config(s) {unknown}. Available: {list(CONFIGS)}")
        return 1

    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_time_ms = int(end_dt.timestamp() * 1000)
    total_requested = args.candles * args.periods

    print(f"Fetching {total_requested} {args.symbol}/{args.timeframe} candles anchored to {args.end_date} (ONE fetch, reused for all {len(names)} config(s))...")
    ltf_candles = fetch_candles(args.symbol, args.timeframe, total_requested, end_time_ms)
    if not ltf_candles:
        print("ERROR: no LTF candles returned.")
        return 1

    htf_requested = htf_candle_count_for_span(args.timeframe, total_requested, settings.HTF_TIMEFRAME)
    htf_candles = fetch_candles(args.symbol, settings.HTF_TIMEFRAME, htf_requested, end_time_ms)
    if not htf_candles:
        print("ERROR: no HTF candles returned.")
        return 1

    print(f"Fetched {len(ltf_candles)} LTF / {len(htf_candles)} HTF candles.")
    ltf_periods = split_into_periods(ltf_candles, args.periods)

    run_meta = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "candles_per_period": args.candles,
        "periods": args.periods,
        "holdout_periods": args.holdout_periods,
        "end_date": args.end_date,
        "account_balance": args.account_balance,
        "command": "python experiment_runner.py --symbol {} --timeframe {} --candles {} --periods {} --holdout-periods {} --end-date {} --configs {}".format(
            args.symbol, args.timeframe, args.candles, args.periods, args.holdout_periods, args.end_date, " ".join(names)
        ),
    }

    records = []
    baseline_record = None
    for name in names:
        print(f"\n=== Running config: {name} ({CONFIGS[name]}) ===")
        record = run_one_config(
            name, CONFIGS[name], ltf_periods, htf_candles, args.holdout_periods, args.account_balance
        )
        if name == "baseline":
            baseline_record = record
        records.append(record)

    # Evaluate every non-baseline config against the baseline IN-SAMPLE metrics
    # (fetch baseline fresh if it wasn't in this invocation's config list).
    if baseline_record is None:
        print("\n(no 'baseline' in --configs this run; fetching it now for comparison)")
        baseline_record = run_one_config(
            "baseline", CONFIGS["baseline"], ltf_periods, htf_candles, args.holdout_periods, args.account_balance
        )
        records.append(baseline_record)

    baseline_in_sample = SegmentMetrics(**baseline_record["in_sample"])

    for record in records:
        if record["name"] == "baseline":
            record["evaluation"] = {"verdict": "BASELINE", "reject_reasons": [], "rank_key": None}
            continue
        in_sample = SegmentMetrics(**record["in_sample"])
        out_of_sample = SegmentMetrics(**record["out_of_sample"])
        wf = record["walk_forward_in_sample"]
        record["evaluation"] = evaluate_candidate(
            record["name"], in_sample, out_of_sample, wf, baseline_in_sample
        )

    print("\n" + "=" * 100)
    print(f"{'config':<45} {'net_profit':>12} {'PF':>7} {'WR':>7} {'DD_worst':>9} {'trades':>7} {'verdict':>10}")
    print("=" * 100)
    for record in records:
        m = record["combined"]
        v = record["evaluation"]["verdict"]
        print(
            f"{record['name']:<45} {m['total_pnl']:>12.2f} {m['profit_factor']:>7.2f} "
            f"{m['win_rate']*100:>6.1f}% {m['max_drawdown_worst']*100:>8.2f}% "
            f"{m['total_trades']:>7} {v:>10}"
        )
    print("=" * 100)

    _append_ledger(records, run_meta)
    print(f"\nResults appended to {RESULTS_LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
