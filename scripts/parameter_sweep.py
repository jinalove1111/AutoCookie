"""parameter_sweep.py

Phase 1 controlled parameter sweep (operator directive, 2026-07-11).
Locked constraints from that directive, enforced by this script's design,
not just its docstring:

  - Tests ONLY constants that directly affect the current JadeCap MVP's
    CORE (non-experimental, always-on) signal generation and trade
    construction path: `entry_model._RR`, `entry_model._STOP_BUFFER`,
    `order_block._LOOKBACK`, `order_block._IMPULSE_MULT`. Deliberately
    excludes BREAKEVEN_TRIGGER_R/PARTIAL_TP_TRIGGER_R/PARTIAL_TP_PORTION
    -- those only matter for the break-even/partial-TP EXPERIMENTAL
    features, which are already evidenced negative-or-inconsistent and
    off by default; tuning knobs for a feature that isn't part of the
    locked MVP baseline would be scope creep, not MVP hardening.
  - One parameter at a time (holding the other three at their existing
    defaults), never a full grid -- a 4-parameter grid at even 4 values
    each would be 256 combinations, mostly untestable noise, and
    directly invites the overfitting this sweep exists to avoid.
  - Optimizes ONLY on in-sample data (the OLDEST 8 of 12 fetched
    BTCUSDT periods). The newest 4 periods are held out, untouched,
    until AFTER a candidate is already selected on in-sample evidence
    alone.
  - Selects candidates by ROBUSTNESS (consistency across periods, no
    single-period dependency, no drawdown blowup, meaningful trade
    count), not by highest in-sample profit.
  - Any candidate that clears in-sample + out-of-sample is THEN
    cross-validated on the other 3 assets (ETH/SOL/XRP, standard
    6-month/6-period window) before being recommended at all -- a
    candidate that only works on the one asset it was tuned on is
    rejected regardless of how it looks on that one asset.

No architecture changes: this script monkey-patches the existing module
constants for the duration of each test (restored immediately after),
rather than adding new CLI flags/settings for parameters that are
expected (per the operator's own instruction #10) to likely stay at
their defaults. If a future round permanently adopts a different
default, changing the constant directly in entry_model.py/order_block.py
is the right, minimal change then -- not before.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.backtesting.backtest_engine import BacktestEngine  # noqa: E402
from app.data.candle_fetcher import CandleFetcher  # noqa: E402
from app.risk.risk_manager import RiskManager  # noqa: E402
from app.strategy import entry_model, order_block  # noqa: E402
from app.strategy.signal_engine import SignalEngine  # noqa: E402

from run_backtest import (  # noqa: E402
    htf_candle_count_for_span,
    split_into_periods,
    walk_forward_report,
)

# --- Parameter definitions (the "small, justified parameter set") ----------
#
# Each entry documents: the module/attribute to patch, current default,
# tested range, step size, and trading rationale -- required by the
# operator's methodology step 2, kept here (not scattered across a
# report) so the sweep's own source is the single source of truth for
# what was actually tested.

PARAMETERS: dict[str, dict[str, Any]] = {
    "_RR": {
        "module": entry_model,
        "attr": "_RR",
        "default": 2.0,
        "range": [1.5, 2.0, 2.5, 3.0],
        "step": 0.5,
        "rationale": (
            "Reward:risk ratio for every trade's take-profit target. "
            "Directly trades off win-rate against reward per winner -- a "
            "lower RR should win more often (nearer target) but each win "
            "pays less; a higher RR wins less often but pays more. "
            "1.5 is the practical floor (RiskManager.MIN_RR=2 currently "
            "requires >=2, so 1.5 is tested here as a research value even "
            "though it would be rejected by live risk gating today -- see "
            "report for how this is handled). 3.0 is a reasonable "
            "practical ceiling before target distance becomes so wide it "
            "rarely fills within realistic holding periods."
        ),
    },
    "_STOP_BUFFER": {
        "module": entry_model,
        "attr": "_STOP_BUFFER",
        "default": 0.001,
        "range": [0.0005, 0.001, 0.0015, 0.002],
        "step": 0.0005,
        "rationale": (
            "Fractional buffer placing the stop just beyond the zone edge "
            "(not exactly on it, which risks the same wick that respects "
            "the zone also tagging the stop). Too small re-introduces the "
            "noise risk this buffer exists to prevent; too large "
            "needlessly widens every trade's risk (and therefore lowers "
            "position size for the same risk-per-trade %, and lowers "
            "reward at a fixed RR). Range stays narrow (0.05%-0.2%) since "
            "this is a minor placement offset, not a primary strategy "
            "lever -- a buffer an order of magnitude larger would already "
            "be a different, untested idea (e.g. ATR-based stops), out of "
            "scope here."
        ),
    },
    "_LOOKBACK": {
        "module": order_block,
        "attr": "_LOOKBACK",
        "default": 10,
        "range": [5, 10, 15, 20],
        "step": 5,
        "rationale": (
            "Rolling window (candle count) used to compute the average "
            "range an order-block impulse candle must exceed. Shorter "
            "reacts faster to recent volatility but is noisier "
            "(single-candle spikes swing the average more); longer "
            "smooths but lags a genuine regime shift. Range brackets the "
            "current default (10) symmetrically: half (5) and double (20)."
        ),
    },
    "_IMPULSE_MULT": {
        "module": order_block,
        "attr": "_IMPULSE_MULT",
        "default": 1.5,
        "range": [1.2, 1.5, 1.8, 2.1],
        "step": 0.3,
        "rationale": (
            "Multiplier an impulse candle's range must exceed the rolling "
            "average by by to count as a genuine 'strong move' (order-block "
            "confirmation) rather than ordinary chop. Lower = more order "
            "blocks detected (more signals, weaker confirmation bar); "
            "higher = fewer, more strongly-confirmed order blocks. 1.2 is "
            "a meaningfully looser bar than default; 2.1 meaningfully "
            "stricter, without going so high detection would starve "
            "entirely on typical data (confirmed empirically before "
            "settling this range -- see report)."
        ),
    },
}

# Meaningful-sample floor for the REJECTION criterion "reduces trade count
# below a meaningful sample" -- 30 trades is a common rule-of-thumb
# minimum for even basic statistical inference (roughly what's needed for
# a binomial win-rate estimate's confidence interval to stop being
# dominated by sample-size noise); documented here as the explicit,
# reproducible threshold rather than an implicit judgment call made only
# in prose later.
MIN_MEANINGFUL_TRADES = 30

# Degradation thresholds for validating a candidate on held-out data --
# documented, not implicit. A candidate is rejected if out-of-sample
# expectancy per trade falls by more than this fraction relative to its
# own in-sample expectancy (comparing the candidate to ITSELF across the
# in-sample/out-of-sample split, not to the baseline -- the question is
# "does this candidate's edge survive into unseen data", not "is it still
# better than baseline on unseen data", which is a separate, additional
# check also reported).
MAX_OOS_EXPECTANCY_DEGRADATION = 0.5  # candidate rejected if OOS expectancy < 50% of in-sample expectancy
MAX_DRAWDOWN_INCREASE = 0.5  # candidate rejected if max_drawdown increases by more than +50% relative (e.g. 1.0% -> 1.5%+)


@dataclass
class ConfigMetrics:
    label: str
    overrides: dict[str, float]
    total_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float | None
    expectancy: float
    average_r: float | None
    max_drawdown_avg: float
    max_drawdown_worst: float
    profitable_periods: int
    periods: int
    walk_forward_passed: bool | None


def profit_factor(trades: list[dict]) -> float | None:
    """Gross profit / gross loss. `None` if there are no losing trades
    AND no winning trades (undefined); a very large float if there are
    wins but zero losses (not clamped -- an honest, if extreme, number)."""
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def expectancy(trades: list[dict]) -> float:
    """Mean PnL per trade (currency, not R -- see average_r for the
    risk-normalized version)."""
    if not trades:
        return 0.0
    return sum(t["pnl"] for t in trades) / len(trades)


def average_r(trades: list[dict]) -> float | None:
    """Mean PnL expressed in units of the ORIGINAL planned risk (1R =
    size * risk_per_unit at trade entry, before any breakeven/partial-TP
    move) -- comparable across trades/periods/assets regardless of
    absolute price level. `None` if no trade has a usable risk_per_unit
    (shouldn't happen for real trades; defensive only)."""
    rs = []
    for t in trades:
        risk_per_unit = t.get("risk_per_unit")
        size = t.get("size")
        if risk_per_unit and size and risk_per_unit > 0:
            risk_amount = size * risk_per_unit
            if risk_amount > 0:
                rs.append(t["pnl"] / risk_amount)
    if not rs:
        return None
    return sum(rs) / len(rs)


def run_configuration(
    ltf_periods: list[list],
    htf_candles: list,
    overrides: dict[str, float],
    progress: Callable[[str], None] | None = None,
) -> list[Any]:
    """Run BacktestEngine over each pre-split period with `overrides`
    applied to the relevant module constants for the DURATION of this
    call only -- always restored in a `finally` block, even on error, so
    a failed sweep run can never leave a stale constant behind to
    silently corrupt a later configuration's result.

    `BacktestEngine.run()`'s walk-forward scan is empirically far worse
    than linear in period length (measured: a 3000-candle period took
    ~88s, a 1500-candle period ~7s -- a 12x speedup for 2x fewer
    candles), so `progress` (optional) is called after EACH period
    finishes with a short status string -- this sweep runs many
    period-simulations back to back and would otherwise produce zero
    visible output for many minutes at a time (confirmed the hard way:
    an earlier, larger-period version of this script ran for 80+ minutes
    with no stdout output at all due to Python's block-buffering when
    piped through `tee`).
    """
    originals: dict[str, Any] = {}
    for name, value in overrides.items():
        module, attr = PARAMETERS[name]["module"], PARAMETERS[name]["attr"]
        originals[name] = getattr(module, attr)
        setattr(module, attr, value)
    try:
        results = []
        for idx, chunk in enumerate(ltf_periods, start=1):
            t0 = time.time()
            result = BacktestEngine().run(chunk, htf_candles, SignalEngine(), RiskManager())
            results.append(result)
            if progress is not None:
                progress(f"    period {idx}/{len(ltf_periods)} done in {time.time() - t0:.1f}s "
                          f"(trades={result.total_trades}, pnl=${result.total_pnl:.2f})")
        return results
    finally:
        for name, value in originals.items():
            module, attr = PARAMETERS[name]["module"], PARAMETERS[name]["attr"]
            setattr(module, attr, value)


def summarize(label: str, overrides: dict[str, float], results: list[Any]) -> ConfigMetrics:
    all_trades = [t for r in results for t in r.trades]
    total_trades = sum(r.total_trades for r in results)
    total_pnl = sum(r.total_pnl for r in results)
    wins = sum(1 for t in all_trades if t["pnl"] > 0)
    profitable_periods = sum(1 for r in results if r.total_pnl > 0)

    wf_passed: bool | None = None
    if len(results) >= 2:
        wf_passed = walk_forward_report(results)["passed"]

    return ConfigMetrics(
        label=label,
        overrides=overrides,
        total_trades=total_trades,
        total_pnl=total_pnl,
        win_rate=(wins / total_trades) if total_trades else 0.0,
        profit_factor=profit_factor(all_trades),
        expectancy=expectancy(all_trades),
        average_r=average_r(all_trades),
        max_drawdown_avg=(sum(r.max_drawdown for r in results) / len(results)) if results else 0.0,
        max_drawdown_worst=max((r.max_drawdown for r in results), default=0.0),
        profitable_periods=profitable_periods,
        periods=len(results),
        walk_forward_passed=wf_passed,
    )


def fmt_row(m: ConfigMetrics) -> str:
    pf = f"{m.profit_factor:.2f}" if m.profit_factor not in (None, float("inf")) else ("inf" if m.profit_factor == float("inf") else "n/a")
    ar = f"{m.average_r:.3f}" if m.average_r is not None else "n/a"
    wf = "PASS" if m.walk_forward_passed else ("FAIL" if m.walk_forward_passed is False else "n/a")
    return (
        f"{m.label:>10} | trades={m.total_trades:>4} | pnl=${m.total_pnl:>9.2f} | "
        f"win%={m.win_rate * 100:>6.2f} | PF={pf:>5} | exp=${m.expectancy:>7.2f} | "
        f"avgR={ar:>7} | DD_avg={m.max_drawdown_avg * 100:>5.2f}% | DD_worst={m.max_drawdown_worst * 100:>5.2f}% | "
        f"profitable={m.profitable_periods}/{m.periods} | WF={wf}"
    )


def fetch_asset(symbol: str, timeframe: str, total_candles: int) -> tuple[list, list]:
    """Fetch LTF + correctly-HTF-span-sized candles for `symbol`, ending
    at 'now' (no --end-date anchor -- this sweep deliberately stays
    within the already-validated recent window; a future round could
    cross-year-validate the winning candidate the same way break-even/
    Breaker Block/partial-TP were)."""
    from app.config import settings

    ltf = CandleFetcher().fetch_ohlcv_history(symbol, timeframe, total_candles=total_candles)
    htf_requested = htf_candle_count_for_span(timeframe, total_candles, settings.HTF_TIMEFRAME)
    htf = CandleFetcher().fetch_ohlcv_history(symbol, settings.HTF_TIMEFRAME, total_candles=htf_requested)
    return ltf, htf


def main() -> int:
    report_lines: list[str] = []
    t_start = time.time()

    def log(line: str = "") -> None:
        print(line, flush=True)
        report_lines.append(line)

    log("=" * 100)
    log("JadeCap Controlled Parameter Sweep -- Phase 1 (operator directive, 2026-07-11)")
    log("=" * 100)
    log("")
    log("Parameters tested (one at a time, others held at default):")
    for name, spec in PARAMETERS.items():
        log(f"  {name}: default={spec['default']}, range={spec['range']}, step={spec['step']}")
        log(f"    rationale: {spec['rationale']}")
    log("")
    log("Period sizing note: BacktestEngine's walk-forward scan is empirically far "
        "worse than linear in period length (measured directly before this run: a "
        "3000-candle period took ~88s, a 1500-candle period ~7s). This sweep runs "
        "many configurations back to back, so period size is set to 1500 candles "
        "(not this project's usual 3000) purely for tractable total runtime -- this "
        "does not change what's being measured (per-period consistency across a "
        "chronological sequence), only how many candles each period covers "
        "(~15.6 days at 15m instead of ~31).")
    log("")

    # --- Fetch BTCUSDT once: 12 periods of 1500 15m candles (~6 months) ---
    symbol, timeframe, candles_per_period, periods = "BTCUSDT", "15m", 1500, 12
    log(f"Fetching {symbol}: {periods} periods x {candles_per_period} candles (~6 months, ending 'now')...")
    ltf, htf = fetch_asset(symbol, timeframe, candles_per_period * periods)
    log(f"Fetched {len(ltf)} LTF / {len(htf)} HTF candles for {symbol}/{timeframe}.")
    all_periods = split_into_periods(ltf, periods)
    in_sample_periods = all_periods[:8]
    out_of_sample_periods = all_periods[8:]
    log(f"In-sample: periods 1-8 (oldest, {sum(len(p) for p in in_sample_periods)} candles).")
    log(f"Out-of-sample (held out until candidate selection is final): periods 9-12 "
        f"({sum(len(p) for p in out_of_sample_periods)} candles).")
    log("")

    # --- Baseline (all defaults) on in-sample ---
    log("-" * 100)
    log("BASELINE (all defaults) -- in-sample:")
    baseline_overrides: dict[str, float] = {}
    baseline_is = summarize("baseline", baseline_overrides, run_configuration(in_sample_periods, htf, baseline_overrides, progress=log))
    log(fmt_row(baseline_is))
    log(f"[elapsed: {time.time() - t_start:.0f}s]")
    log("")

    selected_candidates: dict[str, dict[str, Any]] = {}

    for name, spec in PARAMETERS.items():
        log("-" * 100)
        log(f"PARAMETER: {name} (default={spec['default']})")
        log("In-sample sweep:")
        configs: list[ConfigMetrics] = []
        for value in spec["range"]:
            overrides = {name: value}
            metrics = summarize(
                f"{name}={value}", overrides, run_configuration(in_sample_periods, htf, overrides, progress=log)
            )
            configs.append(metrics)
            log(fmt_row(metrics))
            log(f"[elapsed: {time.time() - t_start:.0f}s]")

        # --- Robustness-based selection (NOT highest profit) ---
        # A candidate is only even considered if it (a) is not the
        # default itself, (b) has at least MIN_MEANINGFUL_TRADES trades,
        # (c) passes its own walk-forward check, (d) has a
        # profitable-period ratio >= baseline's, and (e) has average_r
        # >= baseline's (screens for "fewer trades of WORSE quality",
        # not just "fewer trades"). Among values clearing all of that,
        # prefer the one closest to the default (smallest deviation) as
        # a tie-breaker favoring the "broad stable region" instruction
        # over chasing a lone spike.
        robust_candidates = [
            c for c in configs
            if c.total_trades >= MIN_MEANINGFUL_TRADES
            and c.walk_forward_passed is True
            and (c.profitable_periods / c.periods) >= (baseline_is.profitable_periods / baseline_is.periods)
            and (c.average_r or float("-inf")) >= (baseline_is.average_r or float("-inf"))
            and list(c.overrides.values())[0] != spec["default"]
        ]

        if not robust_candidates:
            log(f"RESULT: no candidate value cleared the robustness bar for {name}. "
                f"KEEPING DEFAULT ({spec['default']}).")
            log("")
            continue

        best = min(robust_candidates, key=lambda c: abs(list(c.overrides.values())[0] - spec["default"]))
        log(f"In-sample robust candidate found: {best.label} "
            f"(profitable_periods={best.profitable_periods}/{best.periods}, avg_r={best.average_r})")

        # --- Out-of-sample validation (NEVER used for selection above) ---
        oos_baseline = summarize("baseline_oos", {}, run_configuration(out_of_sample_periods, htf, {}, progress=log))
        oos_candidate = summarize(
            f"{best.label}_oos", best.overrides,
            run_configuration(out_of_sample_periods, htf, best.overrides, progress=log),
        )
        log("Out-of-sample validation (held-out periods 9-12, untouched until now):")
        log(fmt_row(oos_baseline))
        log(fmt_row(oos_candidate))

        rejected_reason = None
        if oos_candidate.total_trades < MIN_MEANINGFUL_TRADES:
            rejected_reason = f"out-of-sample trade count ({oos_candidate.total_trades}) below meaningful-sample floor ({MIN_MEANINGFUL_TRADES})"
        elif best.expectancy > 0 and oos_candidate.expectancy < best.expectancy * MAX_OOS_EXPECTANCY_DEGRADATION:
            rejected_reason = (
                f"out-of-sample expectancy (${oos_candidate.expectancy:.2f}) degraded more than "
                f"{(1 - MAX_OOS_EXPECTANCY_DEGRADATION) * 100:.0f}% vs in-sample (${best.expectancy:.2f})"
            )
        elif oos_candidate.max_drawdown_worst > oos_baseline.max_drawdown_worst * (1 + MAX_DRAWDOWN_INCREASE) and oos_baseline.max_drawdown_worst > 0:
            rejected_reason = (
                f"out-of-sample max drawdown ({oos_candidate.max_drawdown_worst * 100:.2f}%) increased "
                f"more than {MAX_DRAWDOWN_INCREASE * 100:.0f}% vs baseline ({oos_baseline.max_drawdown_worst * 100:.2f}%)"
            )
        elif oos_candidate.walk_forward_passed is False:
            rejected_reason = "failed its own out-of-sample walk-forward check"

        if rejected_reason:
            log(f"RESULT: candidate REJECTED on out-of-sample validation -- {rejected_reason}. "
                f"KEEPING DEFAULT ({spec['default']}).")
            log("")
            continue

        log(f"RESULT: candidate {best.label} cleared in-sample AND out-of-sample. "
            f"Proceeding to cross-asset validation before any recommendation.")
        selected_candidates[name] = {"value": list(best.overrides.values())[0], "in_sample": best, "oos": oos_candidate}
        log("")

    # --- Cross-asset validation for any candidate that survived this far ---
    if selected_candidates:
        log("=" * 100)
        log("CROSS-ASSET VALIDATION (candidates that cleared BTC in-sample + out-of-sample)")
        log("=" * 100)
        for other_symbol in ("ETHUSDT", "SOLUSDT", "XRPUSDT"):
            log(f"Fetching {other_symbol}: 8 periods x 1500 candles (~4 months, ending 'now')...")
            other_ltf, other_htf = fetch_asset(other_symbol, "15m", 1500 * 8)
            other_periods = split_into_periods(other_ltf, 8)
            baseline_other = summarize("baseline", {}, run_configuration(other_periods, other_htf, {}, progress=log))
            log(fmt_row(baseline_other))
            for name, cand in selected_candidates.items():
                overrides = {name: cand["value"]}
                m = summarize(
                    f"{name}={cand['value']}", overrides,
                    run_configuration(other_periods, other_htf, overrides, progress=log),
                )
                log(fmt_row(m))
                if (
                    m.total_trades < MIN_MEANINGFUL_TRADES
                    or (m.profitable_periods / m.periods) < (baseline_other.profitable_periods / baseline_other.periods)
                    or (m.average_r or float("-inf")) < (baseline_other.average_r or float("-inf")) * 0.5
                ):
                    log(f"  -> {name}={cand['value']} does NOT hold up on {other_symbol} -- REJECTED "
                        f"(fails the 'depends on one symbol' rejection criterion). KEEPING DEFAULT.")
                    selected_candidates[name]["failed_cross_asset"] = True
            log("")
    else:
        log("No candidates cleared in-sample + out-of-sample for ANY parameter -- skipping cross-asset validation.")
        log("")

    # --- Final verdict ---
    log("=" * 100)
    log("FINAL VERDICT")
    log("=" * 100)
    any_adopted = False
    for name, spec in PARAMETERS.items():
        if name in selected_candidates and not selected_candidates[name].get("failed_cross_asset"):
            log(f"{name}: ADOPT new value {selected_candidates[name]['value']} (was {spec['default']}) -- "
                f"robust across in-sample, out-of-sample, AND all 3 other assets.")
            any_adopted = True
        else:
            log(f"{name}: KEEP DEFAULT ({spec['default']}) -- no robust, cross-validated improvement found.")
    if not any_adopted:
        log("")
        log("No parameter changes are recommended. The existing baseline defaults remain unchanged.")
    log("=" * 100)
    log(f"Total sweep runtime: {time.time() - t_start:.0f}s")

    report_path = SCRIPT_DIR.parent / "docs" / "parameter_sweep_report.md"
    report_path.write_text(
        "# JadeCap Parameter Sweep Report\n\n```\n" + "\n".join(report_lines) + "\n```\n",
        encoding="utf-8",
    )
    print(f"\nFull report written to: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
