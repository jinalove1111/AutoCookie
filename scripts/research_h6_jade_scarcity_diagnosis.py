"""research_h6_jade_scarcity_diagnosis.py

H6 (docs/HYPOTHESES_ROUND_2.md section 2, pre-registered 2026-07-19):
root-causes `ENGINEERING_DECISIONS.md` #36's disclosed, UNCONFIRMED
hypothesis for why the Jade engine (`use_jade_engine=True`) produced only
6 trades vs. Legacy's 47 on identical BTCUSDT 15m data -- is the
same-bar-retracement requirement on 3 of Jade's 5 entry models (FVG,
Order Block, Breaker Block) the dominant cause, or does scarcity trace
further upstream/downstream in the pipeline?

BACKTEST-ONLY, analysis-only, READ-ONLY research tool. Calls
`bias.detect_htf_bias`, `entry_point_engine`'s individual evaluator
functions, and `exit_point_engine.find_exit_targets` directly and
UNMODIFIED -- exactly the same functions the real Jade pipeline
(`jade_trade_plan.build_trade_plan` / `signal_engine.
_generate_signal_via_jade_engine`) already calls, in the same order. No
new `BacktestEngine` parameter, no new CLI flag, no change to
`RiskManager.evaluate()` or `scripts/run_paper.py`, no trade is ever
executed here -- this is a pure walk-forward classification scan.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.backtesting.backtest_engine import MIN_CANDLES, _advance_htf_cursor, _get  # noqa: E402
from app.strategy.bias import detect_htf_bias  # noqa: E402
from app.strategy.entry_point_engine import (  # noqa: E402
    _evaluate_breaker_block,
    _evaluate_fair_value_gap,
    _evaluate_liquidity_raid,
    _evaluate_order_block,
    _evaluate_premium_discount,
    _last_candle_overlaps_zone,
    detect_fair_value_gap,
)
from app.strategy.exit_point_engine import find_exit_targets  # noqa: E402

from run_backtest import fetch_candles, htf_candle_count_for_span  # noqa: E402
from app.config import settings  # noqa: E402

SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
ANCHORS = ["2026-07-10", "2025-07-10", "2024-07-10"]
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_h6_jade_scarcity_diagnosis.json"

SAME_BAR_MODELS = ("fair_value_gap", "order_block", "breaker_block")


def _fetch(anchor: str) -> tuple[list, list]:
    end_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    total = CANDLES_PER_PERIOD * PERIODS
    ltf = fetch_candles(SYMBOL, TIMEFRAME, total, end_ms)
    htf_req = htf_candle_count_for_span(TIMEFRAME, total, settings.HTF_TIMEFRAME)
    htf = fetch_candles(SYMBOL, settings.HTF_TIMEFRAME, htf_req, end_ms)
    return ltf, htf


def _fvg_bucket(candles: list, bias: str) -> tuple[str, dict | None]:
    """Classify Entry Model 3 (FVG) into no_matching_zone /
    zone_exists_not_retraced / candidate_found. `_evaluate_fair_value_gap`'s
    own reject reason conflates the first two ("no matching fair value gap
    currently being retested" covers both), so this re-derives the
    distinction directly from `detect_fair_value_gap` -- the same function
    `_evaluate_fair_value_gap` itself already calls, not a reimplementation
    of new logic.
    """
    result, _ = _evaluate_fair_value_gap(candles, bias)
    if result is not None:
        return "candidate_found", result
    if bias not in ("bullish", "bearish"):
        return "bias_invalid", None
    direction = "long" if bias == "bullish" else "short"
    wanted_type = "bullish" if direction == "long" else "bearish"
    matching = [z for z in detect_fair_value_gap(candles) if z["type"] == wanted_type]
    if not matching:
        return "no_matching_zone", None
    if not any(_last_candle_overlaps_zone(candles, z["top"], z["bottom"]) for z in matching):
        return "zone_exists_not_retraced", None
    return "candidate_found", None  # pragma: no cover -- would imply _evaluate_fair_value_gap disagreed


def _same_bar_reject_bucket(reject_reason: str | None) -> str:
    if reject_reason is None:
        return "candidate_found"
    if reject_reason.startswith("no matching"):
        return "no_matching_zone"
    if reject_reason.startswith("price has not retraced"):
        return "zone_exists_not_retraced"
    return "bias_invalid"  # "bias is neutral or invalid" -- should not occur, bias pre-checked


def _classify_step(ltf_slice: list, htf_slice: list) -> dict:
    bias = detect_htf_bias(htf_slice)
    if bias == "neutral":
        return {"neutral_bias": True}

    entry: dict[str, Any] = {"neutral_bias": False, "models": {}}

    fvg_result, _ = _evaluate_fair_value_gap(ltf_slice, bias)
    entry["models"]["fair_value_gap"] = {
        "bucket": _fvg_bucket(ltf_slice, bias)[0],
        "result": fvg_result,
    }

    ob_result, ob_reject = _evaluate_order_block(ltf_slice, bias)
    entry["models"]["order_block"] = {
        "bucket": _same_bar_reject_bucket(ob_reject),
        "result": ob_result,
    }

    br_result, br_reject = _evaluate_breaker_block(ltf_slice, bias)
    entry["models"]["breaker_block"] = {
        "bucket": _same_bar_reject_bucket(br_reject),
        "result": br_result,
    }

    pd_result, pd_reject = _evaluate_premium_discount(ltf_slice, bias)
    entry["models"]["premium_discount"] = {
        "bucket": "candidate_found" if pd_result is not None else "no_candidate",
        "result": pd_result,
    }

    lr_result, lr_reject = _evaluate_liquidity_raid(ltf_slice, bias)
    entry["models"]["liquidity_raid"] = {
        "bucket": "candidate_found" if lr_result is not None else "no_candidate",
        "result": lr_result,
    }

    candidates = [
        m["result"] for m in entry["models"].values() if m["result"] is not None
    ]
    if not candidates:
        entry["pipeline_outcome"] = "no_entry_candidate"
        return entry

    best = max(candidates, key=lambda r: r["confidence_score"])
    entry["pipeline_outcome"] = "entry_candidate_selected"
    entry["selected_model"] = best["entry_model"]

    entry_zone = best["entry_zone"]
    entry_price = (entry_zone["top"] + entry_zone["bottom"]) / 2
    targets = find_exit_targets(ltf_slice, best["direction"], entry_price)["targets"]
    entry["exit_targets_empty"] = not targets
    entry["pipeline_outcome"] = "exit_targets_empty" if not targets else "signal_would_generate"
    return entry


def _run_anchor(anchor: str) -> dict:
    ltf, htf = _fetch(anchor)
    if len(ltf) < MIN_CANDLES:
        return {"error": f"insufficient candles: {len(ltf)} < {MIN_CANDLES}"}

    counts: dict[str, int] = {
        "total_steps": 0,
        "neutral_bias": 0,
        "no_entry_candidate": 0,
        "entry_candidate_selected": 0,
        "exit_targets_empty": 0,
        "signal_would_generate": 0,
    }
    model_counts: dict[str, dict[str, int]] = {
        name: {"no_matching_zone": 0, "zone_exists_not_retraced": 0, "no_candidate": 0, "candidate_found": 0, "bias_invalid": 0}
        for name in ("fair_value_gap", "order_block", "breaker_block", "premium_discount", "liquidity_raid")
    }
    selected_model_counts: dict[str, int] = {}

    htf_cursor = -1
    i = MIN_CANDLES - 1
    while i < len(ltf):
        ltf_timestamp = _get(ltf[i], "timestamp")
        htf_cursor = _advance_htf_cursor(htf, htf_cursor, ltf_timestamp)
        htf_slice = htf[: htf_cursor + 1]
        ltf_slice = ltf[: i + 1]

        counts["total_steps"] += 1
        step = _classify_step(ltf_slice, htf_slice)

        if step["neutral_bias"]:
            counts["neutral_bias"] += 1
            i += 1
            continue

        for name, info in step["models"].items():
            bucket = info["bucket"]
            if bucket not in model_counts[name]:
                model_counts[name][bucket] = 0
            model_counts[name][bucket] += 1

        outcome = step["pipeline_outcome"]
        if outcome == "no_entry_candidate":
            counts["no_entry_candidate"] += 1
        else:
            counts["entry_candidate_selected"] += 1
            selected_model_counts[step["selected_model"]] = (
                selected_model_counts.get(step["selected_model"], 0) + 1
            )
            if outcome == "exit_targets_empty":
                counts["exit_targets_empty"] += 1
            else:
                counts["signal_would_generate"] += 1

        i += 1

    same_bar_totals = {"no_matching_zone": 0, "zone_exists_not_retraced": 0}
    for name in SAME_BAR_MODELS:
        same_bar_totals["no_matching_zone"] += model_counts[name]["no_matching_zone"]
        same_bar_totals["zone_exists_not_retraced"] += model_counts[name]["zone_exists_not_retraced"]

    return {
        "counts": counts,
        "model_counts": model_counts,
        "selected_model_counts": selected_model_counts,
        "same_bar_totals_across_3_models": same_bar_totals,
    }


def compute_verdict(agg_no_zone: int, agg_not_retraced: int) -> str:
    """H6's pre-registered same-bar-retracement keep-rule
    (docs/HYPOTHESES_ROUND_2.md section 2), applied to the aggregate
    no_matching_zone / zone_exists_not_retraced counts across all 3
    same-bar models and all 3 anchor years.
    """
    if agg_no_zone == 0 and agg_not_retraced == 0:
        return "INCONCLUSIVE"
    if agg_no_zone == 0:
        return "CONFIRMED"
    if agg_not_retraced == 0:
        return "REJECTED"
    if agg_not_retraced >= 2 * agg_no_zone:
        return "CONFIRMED"
    if agg_no_zone >= 2 * agg_not_retraced:
        return "REJECTED"
    return "INCONCLUSIVE"


def main() -> int:
    report: dict[str, Any] = {"symbol": SYMBOL, "timeframe": TIMEFRAME, "anchors": {}}
    agg_no_zone = 0
    agg_not_retraced = 0

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        result = _run_anchor(anchor)
        report["anchors"][anchor] = result
        print(json.dumps(result, indent=2, default=str))
        if "same_bar_totals_across_3_models" in result:
            agg_no_zone += result["same_bar_totals_across_3_models"]["no_matching_zone"]
            agg_not_retraced += result["same_bar_totals_across_3_models"]["zone_exists_not_retraced"]

    verdict = compute_verdict(agg_no_zone, agg_not_retraced)

    report["h6_verdict"] = {
        "aggregate_no_matching_zone": agg_no_zone,
        "aggregate_zone_exists_not_retraced": agg_not_retraced,
        "verdict": verdict,
        "rule": "CONFIRMED if not_retraced >= 2x no_zone; REJECTED if no_zone >= 2x not_retraced; else INCONCLUSIVE",
    }
    print("\n### H6 verdict (same-bar-retracement hypothesis) ###")
    print(json.dumps(report["h6_verdict"], indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
