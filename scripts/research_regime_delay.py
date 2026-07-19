"""research_regime_delay.py

H3 experiment harness (docs/HYPOTHESES_ROUND_1.md section 3, pre-registered
2026-07-17): does the already-validated `use_structure_tp=True` family
survive the 1-candle execution delay better in SOME regime buckets than in
aggregate? `docs/ROBUSTNESS_REPORT.md` Test 2 already found this family
catastrophically delay-fragile in AGGREGATE (PF 5.24 -> 0.16); this tool
asks whether that collapse is concentrated in specific regimes while others
hold up -- "no round has ever regime-tagged a `structure_tp` delay-check
run" (pre-registered spec's own wording).

BACKTEST-ONLY, analysis-only research tool. Adds NO new detection or
execution logic: `--structure-tp`, `--tag-regimes`, and `--delay-check` all
already exist independently on `scripts/run_backtest.py` and are reused
here completely unchanged (via `run_backtest.run_backtest()` ->
`BacktestEngine.run()`) -- the only new work is JOINING their outputs: a
per-regime-bucket profit-factor-retention aggregator, which nobody has ever
run before this milestone. No file in `app/risk/`, `app/execution/`, or
`scripts/run_paper.py` is touched; `RiskManager.evaluate()`'s live logic is
never called by this module.

Mechanics (mirrors `run_backtest.py`'s own `--delay-check` block, Milestone
18a, exactly -- see `delay_robustness_report`'s docstring there): candles
are fetched ONCE, then replayed through `run_backtest()` twice over the
SAME full fetched sample -- once at `entry_delay_candles=0` (baseline),
once at `entry_delay_candles=1` (delayed) -- both with `use_structure_tp=True`
(uncapped, the exact pre-registered config) and `tag_regimes=True` (NOT
threaded through `run_backtest.py`'s own `--delay-check` block today, which
is the precise gap this tool closes -- no prior run has ever combined the
two). `--periods` only sizes the total candle fetch (`--candles *
--periods`, same convention as every other script in this project); unlike
`run_backtest.py`'s own `--periods`-driven period splitting, the delay-check
comparison itself always runs over the WHOLE fetched sample (matching
`run_backtest.py`'s own `--delay-check` behavior, which is deliberately NOT
period-aware -- see that module's section 3b comment).

Per-regime join (`per_bucket_delay_retention`, the new instrumentation this
milestone adds): each of the two runs' resulting `BacktestResult.trades`
(each trade dict carrying a `"market_regime"` key because `tag_regimes=True`
was passed) is grouped by `app.backtesting.regime_analysis.regime_bucket`
(the SAME bucket-key convention `docs/REGIME_PERFORMANCE_ANALYSIS.md` /
`scripts/analyze_regime_performance.py` already use: `"{trend}/{volatility}"`,
or `"untagged"`). For each bucket present on either side, the baseline and
delayed trade SUBSETS for that bucket are wrapped in a minimal
`BacktestResult`-shaped duck type (`total_trades`/`total_pnl`/`trades`) and
handed to `run_backtest.delay_robustness_report()` UNCHANGED -- so every
bucket's profit-factor-retention number is computed by the exact same,
already-reviewed formula the platform's aggregate delay gate uses, not a
second, independently-written formula that could silently drift from it.
No new engine run per bucket: both engine runs happen exactly once each
(baseline, delayed) over the whole sample; bucketing is a pure, in-memory
join over their already-computed trade lists.

Keep-rule (`docs/HYPOTHESES_ROUND_1.md` section 3, declared now): a bucket
is a genuine delay-robust pocket only if it has n>=20 trades on the
DELAYED side of that bucket, PF retention >= 0.5, and no sign flip, in AT
LEAST 2 of the 3 tested years (2024/2025/2026 anchors). This tool computes
the SINGLE-anchor component of that rule per bucket (`"meets_keep_bar"` in
`per_bucket_delay_retention`'s output) -- the cross-year "in >= 2 of 3
years" check is a manual/later step comparing this tool's JSON output
across three separate `--end-date` runs, the same convention
`scripts/research_signal_selection.py` (H1) already established for its own
cross-year comparisons rather than baking multi-anchor orchestration into
one script invocation.

CLI example (one anchor per invocation, matching every other script in this
project's `--end-date` convention):

    python scripts/research_regime_delay.py --symbol BTCUSDT \
        --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10

Writes a JSON report (`scripts/reports/research_regime_delay.json` by
default) with one row per regime bucket (baseline/delayed trade counts,
baseline/delayed profit factor, PF retention, sign flip, delay-check gate
verdict, and whether the bucket clears the single-year keep-bar) plus an
`"all"` row (whole-population sanity cross-check, informational only --
never counted toward the keep-rule, since it is not a real regime bucket).

Does NOT run the actual pre-registered 3-anchor (2024/2025/2026) evaluation
matrix itself -- that is a separate, later step (see
`docs/HYPOTHESES_ROUND_1.md` section 3's pre-registered runs). This script
is the harness those runs will use.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _cli_path_utils import normalize_path_arg  # noqa: E402
from app.backtesting.regime_analysis import (  # noqa: E402
    ALL_BUCKET,
    MIN_TRADES_FOR_CONFIDENCE,
    UNTAGGED_BUCKET,
    regime_bucket,
)
from app.config import settings  # noqa: E402

from run_backtest import (  # noqa: E402
    _fmt_optional_float,
    delay_robustness_report,
    fetch_candles,
    htf_candle_count_for_span,
    run_backtest,
)

SYMBOL_DEFAULT = settings.SYMBOL
TIMEFRAME_DEFAULT = "15m"  # matches the pre-registered H3 CLI invocations
CANDLES_PER_PERIOD_DEFAULT = 3000
PERIODS_DEFAULT = 6
# Same disclosed-not-tuned default `delay_robustness_report` itself uses
# (run_backtest.py, Milestone 18a) -- not redeclared with a different value.
MAX_PF_DEGRADATION_DEFAULT = 0.5
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_regime_delay.json"


# --- per-regime join (the new instrumentation) ------------------------------


def group_trades_by_regime(trades: list[dict]) -> dict[str, list[dict]]:
    """Group `trades` by `app.backtesting.regime_analysis.regime_bucket` --
    the SAME bucket-key convention (`"{trend}/{volatility}"`, or
    `"untagged"` for a missing/`None` `"market_regime"` key) every other
    per-regime report in this project already uses. Pure, no I/O.
    """
    buckets: dict[str, list[dict]] = {}
    for trade in trades:
        buckets.setdefault(regime_bucket(trade), []).append(trade)
    return buckets


def _trade_subset(trades: list[dict]) -> SimpleNamespace:
    """Minimal `BacktestResult`-shaped duck type over an arbitrary trade-dict
    subset (e.g. one regime bucket's slice of a larger run) --
    `delay_robustness_report` only ever reads `.total_trades`, `.total_pnl`,
    and `.trades` (see that function's own docstring), so this is sufficient
    to reuse it completely unchanged for a filtered subset instead of a
    whole `BacktestResult`. Same duck-typing convention
    `backend/tests/test_run_backtest.py`'s own `_delay_result()` helper
    already uses for this exact function.
    """
    return SimpleNamespace(
        total_trades=len(trades),
        total_pnl=sum(t["pnl"] for t in trades),
        trades=trades,
    )


def per_bucket_delay_retention(
    baseline_trades: list[dict],
    delayed_trades: list[dict],
    *,
    max_pf_degradation: float = MAX_PF_DEGRADATION_DEFAULT,
    min_bucket_n: int = MIN_TRADES_FOR_CONFIDENCE,
) -> dict[str, dict]:
    """The H3 per-regime delay-retention aggregator: for each regime bucket
    present in EITHER `baseline_trades` or `delayed_trades`, compute the
    baseline (`entry_delay_candles=0`) vs. delayed (`entry_delay_candles=1`)
    profit-factor comparison SCOPED to only that bucket's trades, by
    delegating to `run_backtest.delay_robustness_report()` UNCHANGED (see
    module docstring) -- never a second, independently-written PF-retention
    formula.

    `baseline_trades`/`delayed_trades`: the `.trades` lists from two
    `run_backtest()` calls over the SAME candles/config, differing only in
    `entry_delay_candles` (0 vs. 1) -- both must have been run with
    `tag_regimes=True` for bucketing to produce anything beyond a single
    `"untagged"` bucket (a run without `tag_regimes=True` still works here,
    it simply has no `"market_regime"` key on any trade, so every trade
    lands in `UNTAGGED_BUCKET` -- never a crash).

    Returns a dict keyed by bucket name (every bucket found in either input,
    PLUS an `"all"` row -- whole-population sanity cross-check against the
    existing aggregate-level delay gate, informational only). Each value is
    exactly `delay_robustness_report()`'s own return shape (see that
    function's docstring for `baseline_trades`/`delayed_trades`/
    `baseline_pf`/`delayed_pf`/`pf_retention`/`sign_flip`/`passed`/
    `insufficient_data`/`reason`/`criteria` -- including its own
    never-a-crash, never-a-fabricated-ratio edge-case handling for a bucket
    with zero trades on either side), plus two additions:

      `"bucket"`: the bucket key (redundant with the dict key, included so
        a caller iterating `.values()` alone still has it).
      `"meets_keep_bar"`: `True` only if this is a REAL regime bucket (not
        `"untagged"` or `"all"`), `delayed_trades >= min_bucket_n` (default
        `MIN_TRADES_FOR_CONFIDENCE`, 20 -- this project's established
        sample-size floor, `app.backtesting.regime_analysis`), AND
        `passed is True` (real PF retention >= `max_pf_degradation` with no
        sign flip) -- the SINGLE-anchor component of `docs/
        HYPOTHESES_ROUND_1.md` section 3's full keep-rule (which
        additionally requires this in >= 2 of 3 tested years, a cross-run
        check outside this function's scope -- see module docstring).
        `False` (never `None`, never fabricated) whenever any of the above
        does not hold, including every insufficient-data case.
    """
    baseline_by_bucket = group_trades_by_regime(baseline_trades)
    delayed_by_bucket = group_trades_by_regime(delayed_trades)
    bucket_keys = sorted(set(baseline_by_bucket) | set(delayed_by_bucket))

    report: dict[str, dict] = {}
    for key in bucket_keys:
        bucket_baseline = baseline_by_bucket.get(key, [])
        bucket_delayed = delayed_by_bucket.get(key, [])
        row = delay_robustness_report(
            _trade_subset(bucket_baseline),
            _trade_subset(bucket_delayed),
            max_pf_degradation=max_pf_degradation,
        )
        row["bucket"] = key
        row["meets_keep_bar"] = (
            key != UNTAGGED_BUCKET
            and row["delayed_trades"] >= min_bucket_n
            and row["passed"] is True
        )
        report[key] = row

    # Whole-population row (informational cross-check only -- NOT a real
    # regime bucket, never counted toward the keep-rule): confirms this
    # tool's per-bucket split, summed back up, reproduces the exact number
    # run_backtest.py's own --delay-check would have printed for the same
    # two runs.
    aggregate_row = delay_robustness_report(
        _trade_subset(baseline_trades),
        _trade_subset(delayed_trades),
        max_pf_degradation=max_pf_degradation,
    )
    aggregate_row["bucket"] = ALL_BUCKET
    aggregate_row["meets_keep_bar"] = False
    report[ALL_BUCKET] = aggregate_row

    return report


def render_report(report: dict[str, dict]) -> str:
    """ASCII-only markdown table (no non-ASCII glyphs -- same Windows
    cp1252-console discipline as `app.backtesting.regime_analysis.
    comparison_table`'s own docstring explains) -- one row per bucket,
    sorted by name, with `ALL_BUCKET` always last so per-bucket rows read
    top-to-bottom before the whole-population cross-check. Never raises on
    an empty `report` (header-only table).
    """
    keys = sorted(k for k in report if k != ALL_BUCKET)
    if ALL_BUCKET in report:
        keys.append(ALL_BUCKET)

    lines = [
        "| Bucket | Baseline N | Delayed N | Baseline PF | Delayed PF | "
        "PF Retention | Sign Flip | Gate | Keep Bar (n>=20) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key in keys:
        row = report[key]
        if row["passed"] is None:
            gate = "INSUFFICIENT DATA"
        else:
            gate = "PASSED" if row["passed"] else "FAILED"
        lines.append(
            f"| {key} | {row['baseline_trades']} | {row['delayed_trades']} | "
            f"{_fmt_optional_float(row['baseline_pf'])} | "
            f"{_fmt_optional_float(row['delayed_pf'])} | "
            f"{_fmt_optional_float(row['pf_retention'])} | {row['sign_flip']} | "
            f"{gate} | {'YES' if row['meets_keep_bar'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


# --- CLI ---------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "H3 experiment harness (docs/HYPOTHESES_ROUND_1.md section 3): "
            "joins run_backtest.py's existing --structure-tp / --tag-regimes "
            "/ --delay-check machinery into a per-regime-bucket "
            "profit-factor-retention report, over ONE anchor per invocation."
        )
    )
    parser.add_argument("--symbol", default=SYMBOL_DEFAULT, help=f"Default: {SYMBOL_DEFAULT!r}")
    parser.add_argument("--timeframe", default=TIMEFRAME_DEFAULT, help=f"Default: {TIMEFRAME_DEFAULT!r}")
    parser.add_argument("--candles", type=int, default=CANDLES_PER_PERIOD_DEFAULT)
    parser.add_argument(
        "--periods",
        type=int,
        default=PERIODS_DEFAULT,
        help=(
            "Only sizes the total candle fetch (--candles * --periods), "
            "same convention as every other script in this project -- the "
            "delay-check comparison itself always runs over the WHOLE "
            "fetched sample (matching run_backtest.py's own --delay-check "
            "behavior, which is not period-aware)."
        ),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Anchor the fetch to end at this UTC date (YYYY-MM-DD), same convention as run_backtest.py.",
    )
    parser.add_argument(
        "--max-pf-degradation",
        type=float,
        default=MAX_PF_DEGRADATION_DEFAULT,
        help=(
            f"Minimum fraction of baseline profit factor a bucket's delayed "
            f"run must retain to pass (default {MAX_PF_DEGRADATION_DEFAULT}, "
            "same disclosed-not-tuned threshold run_backtest.py's own "
            "delay_robustness_report default uses)."
        ),
    )
    parser.add_argument(
        "--min-bucket-n",
        type=int,
        default=MIN_TRADES_FOR_CONFIDENCE,
        help=(
            f"H3 pre-registered keep-rule sample floor on the delayed side "
            f"of a bucket (default {MIN_TRADES_FOR_CONFIDENCE}, "
            "docs/HYPOTHESES_ROUND_1.md section 3)."
        ),
    )
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    end_time_ms: int | None = None
    if args.end_date is not None:
        try:
            end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: --end-date {args.end_date!r} is not a valid YYYY-MM-DD date.")
            return 1
        end_time_ms = int(end_dt.timestamp() * 1000)
        print(f"Anchoring fetch to end at {end_dt.isoformat()} (--end-date {args.end_date}).")

    total_requested = args.candles * args.periods
    try:
        ltf_candles = fetch_candles(args.symbol, args.timeframe, total_requested, end_time_ms)
    except Exception as exc:  # network/data errors are genuine failures
        print(f"ERROR: failed to fetch candles for {args.symbol}: {exc}")
        return 1
    if not ltf_candles:
        print(f"No candles returned for {args.symbol}/{args.timeframe}.")
        return 1
    print(f"Fetched {len(ltf_candles)} LTF candles for {args.symbol}/{args.timeframe}.")

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

    print(
        "H3 config (docs/HYPOTHESES_ROUND_1.md section 3): "
        "use_structure_tp=True (uncapped), tag_regimes=True, "
        "entry_delay_candles 0 (baseline) vs. 1 (delayed)."
    )
    try:
        baseline_result = run_backtest(
            ltf_candles,
            htf_candles,
            use_structure_tp=True,
            tag_regimes=True,
            entry_delay_candles=0,
        )
        delayed_result = run_backtest(
            ltf_candles,
            htf_candles,
            use_structure_tp=True,
            tag_regimes=True,
            entry_delay_candles=1,
        )
    except Exception as exc:  # unexpected engine failure is a genuine failure
        print(f"ERROR: backtest engine raised an exception: {exc}")
        return 1

    report = per_bucket_delay_retention(
        baseline_result.trades,
        delayed_result.trades,
        max_pf_degradation=args.max_pf_degradation,
        min_bucket_n=args.min_bucket_n,
    )

    table = render_report(report)
    print()
    print(table)

    output_path = normalize_path_arg(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "end_date": args.end_date,
        "config": {
            "use_structure_tp": True,
            "tag_regimes": True,
            "entry_delay_candles": [0, 1],
        },
        "criteria": {
            "max_pf_degradation": args.max_pf_degradation,
            "min_bucket_n": args.min_bucket_n,
        },
        "buckets": report,
    }
    output_path.write_text(json.dumps(output_payload, indent=2, default=str), encoding="utf-8")
    print(f"JSON report written to: {output_path}")

    any_keep = any(row["meets_keep_bar"] for row in report.values())
    if any_keep:
        print(
            "NOTE: at least one bucket clears the SINGLE-ANCHOR keep-bar "
            "(n>=20 delayed, PF retention>=0.5, no sign flip). The full H3 "
            "keep-rule additionally requires this in >= 2 of the 3 tested "
            "years (docs/HYPOTHESES_ROUND_1.md section 3) -- compare this "
            "run's JSON output against the other anchors' runs manually, "
            "same convention scripts/research_signal_selection.py (H1) "
            "already established for its own cross-year comparisons."
        )
    else:
        print("NOTE: no bucket clears the single-anchor keep-bar in this run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
