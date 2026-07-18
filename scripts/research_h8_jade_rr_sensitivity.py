"""research_h8_jade_rr_sensitivity.py

H8 (docs/HYPOTHESES_ROUND_2.md section 4, pre-registered 2026-07-19):
validates H7's disclosed reward:risk-geometry finding -- is Jade's
RR-below-minimum rejection pattern structural (inherent to its
entry/stop/target geometry), or does some ALREADY-EXISTING, already-built
stop_model/target-selection choice, never used by production, already
clear the 1:2 minimum meaningfully more often than production's actual
default combination?

BACKTEST-ONLY, analysis-only, READ-ONLY research tool. Calls
`bias.detect_htf_bias`, `entry_point_engine.find_entry_point`, and its
own `_evaluate_fair_value_gap`/`_evaluate_breaker_block` evaluators
(with different, already-supported `stop_model` values) and
`exit_point_engine.find_exit_targets` directly and UNMODIFIED -- no
trade is ever executed, no new production code, no new
`BacktestEngine` parameter, no new CLI flag. `find_entry_point`'s own
selection is run ONCE per step with production's default stop_models
(selection does not depend on stop_model choice -- confidence scores are
fixed per model type); stop-loss counterfactuals only re-evaluate the
ONE selected model's own evaluator for its other supported stop_model
values, not a full 6x re-walk of the whole pipeline.
"""

from __future__ import annotations

import json
import statistics
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
    find_entry_point,
)
from app.strategy.exit_point_engine import find_exit_targets  # noqa: E402

from run_backtest import fetch_candles, htf_candle_count_for_span  # noqa: E402
from app.config import settings  # noqa: E402

SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
ANCHORS = ["2026-07-10", "2025-07-10", "2024-07-10"]
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_h8_jade_rr_sensitivity.json"

MIN_RR = 2.0
STOP_CHOICES = ("aggressive", "moderate", "conservative")
MAX_TARGET_INDEX = 6  # generous upper bound; most steps have far fewer targets

# Production's actual default combination -- the baseline every
# alternative is compared against.
PRODUCTION_STOP_FOR_MODEL = {
    "fair_value_gap": "moderate",
    "breaker_block": "aggressive",
    "order_block": "default",
    "premium_discount": "default",
    "liquidity_raid": "default",
}
PRODUCTION_TARGET_INDEX = 1


def _fetch(anchor: str) -> tuple[list, list]:
    end_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    total = CANDLES_PER_PERIOD * PERIODS
    ltf = fetch_candles(SYMBOL, TIMEFRAME, total, end_ms)
    htf_req = htf_candle_count_for_span(TIMEFRAME, total, settings.HTF_TIMEFRAME)
    htf = fetch_candles(SYMBOL, settings.HTF_TIMEFRAME, htf_req, end_ms)
    return ltf, htf


def stop_loss_for_choice(
    selected_model: str, ltf_slice: list, bias: str, default_stop_loss: float, stop_choice: str
) -> float:
    """Resolve the stop_loss `stop_choice` ("aggressive"/"moderate"/
    "conservative") would have produced for `selected_model`, re-calling
    only that model's own evaluator (not a full find_entry_point re-run).
    Order Block/Premium-Discount/Liquidity Raid have no stop_model
    parameter at all -- they always fall back to `default_stop_loss`
    (disclosed limitation, docs/HYPOTHESES_ROUND_2.md section 6).
    Breaker Block has no "moderate" value -- falls back to production's
    own default ("aggressive") for that slot, also disclosed.
    """
    if selected_model == "fair_value_gap":
        result, _ = _evaluate_fair_value_gap(ltf_slice, bias, stop_model=stop_choice)
        return result["stop_loss"] if result is not None else default_stop_loss
    if selected_model == "breaker_block":
        if stop_choice == "moderate":
            stop_choice = "aggressive"
        result, _ = _evaluate_breaker_block(ltf_slice, bias, stop_model=stop_choice)
        return result["stop_loss"] if result is not None else default_stop_loss
    return default_stop_loss


def _run_anchor(anchor: str) -> tuple[dict, dict[tuple[str, int], list[float]], list[float]]:
    ltf, htf = _fetch(anchor)
    if len(ltf) < MIN_CANDLES:
        empty_cells: dict[tuple[str, int], list[float]] = {
            (sc, ti): [] for sc in STOP_CHOICES for ti in range(1, MAX_TARGET_INDEX + 1)
        }
        return {"error": f"insufficient candles: {len(ltf)} < {MIN_CANDLES}"}, empty_cells, []

    # cells[(stop_choice, target_index)] -> list of RR values
    cells: dict[tuple[str, int], list[float]] = {
        (sc, ti): [] for sc in STOP_CHOICES for ti in range(1, MAX_TARGET_INDEX + 1)
    }
    baseline_rrs: list[float] = []
    total_selected_steps = 0
    selected_model_counts: dict[str, int] = {}

    htf_cursor = -1
    i = MIN_CANDLES - 1
    while i < len(ltf):
        ltf_timestamp = _get(ltf[i], "timestamp")
        htf_cursor = _advance_htf_cursor(htf, htf_cursor, ltf_timestamp)
        htf_slice = htf[: htf_cursor + 1]
        ltf_slice = ltf[: i + 1]

        b = detect_htf_bias(htf_slice)
        if b == "neutral":
            i += 1
            continue

        entry = find_entry_point(ltf_slice, b)
        if entry is None:
            i += 1
            continue

        selected_model = entry["entry_model"]
        direction = entry["direction"]
        entry_zone = entry["entry_zone"]
        entry_price = entry_zone["top"] if direction == "long" else entry_zone["bottom"]
        default_stop_loss = entry["stop_loss"]

        total_selected_steps += 1
        selected_model_counts[selected_model] = selected_model_counts.get(selected_model, 0) + 1

        targets = find_exit_targets(ltf_slice, direction, entry_price)["targets"]
        if not targets:
            i += 1
            continue

        for stop_choice in STOP_CHOICES:
            stop_loss = stop_loss_for_choice(selected_model, ltf_slice, b, default_stop_loss, stop_choice)
            risk = abs(entry_price - stop_loss)
            if risk == 0:
                continue
            for idx, t in enumerate(targets[:MAX_TARGET_INDEX], start=1):
                reward = abs(t["level"] - entry_price)
                rr = reward / risk
                cells[(stop_choice, idx)].append(rr)

        # Production's own actual baseline combination for this step.
        prod_stop_choice = PRODUCTION_STOP_FOR_MODEL[selected_model]
        prod_stop_loss = (
            default_stop_loss
            if prod_stop_choice == "default"
            else stop_loss_for_choice(selected_model, ltf_slice, b, default_stop_loss, prod_stop_choice)
        )
        prod_risk = abs(entry_price - prod_stop_loss)
        if prod_risk > 0 and len(targets) >= PRODUCTION_TARGET_INDEX:
            prod_reward = abs(targets[PRODUCTION_TARGET_INDEX - 1]["level"] - entry_price)
            baseline_rrs.append(prod_reward / prod_risk)

        i += 1

    def _cell_stats(rrs: list[float]) -> dict:
        if not rrs:
            return {"n": 0, "qualify_rate": None, "median": None, "p25": None, "p75": None}
        qualifying = sum(1 for r in rrs if r >= MIN_RR)
        sorted_rrs = sorted(rrs)
        return {
            "n": len(rrs),
            "qualify_rate": round(qualifying / len(rrs), 4),
            "median": round(statistics.median(sorted_rrs), 4),
            "p25": round(sorted_rrs[len(sorted_rrs) // 4], 4),
            "p75": round(sorted_rrs[(3 * len(sorted_rrs)) // 4], 4),
        }

    cell_results = {f"{sc}|TP{ti}": _cell_stats(rrs) for (sc, ti), rrs in cells.items()}
    stats = {
        "total_selected_steps": total_selected_steps,
        "selected_model_counts": selected_model_counts,
        "baseline": _cell_stats(baseline_rrs),
        "cells": cell_results,
    }
    return stats, cells, baseline_rrs


def compute_verdict(baseline_qualify_rate: float, best_alt_qualify_rate: float) -> str:
    """H8's pre-registered keep-rule (docs/HYPOTHESES_ROUND_2.md section 4)."""
    if best_alt_qualify_rate < 0.25:
        return "STRUCTURAL"
    if best_alt_qualify_rate >= 2 * baseline_qualify_rate:
        return "PARAMETER_SENSITIVE"
    return "INCONCLUSIVE"


def main() -> int:
    report: dict[str, Any] = {"symbol": SYMBOL, "timeframe": TIMEFRAME, "anchors": {}}
    agg_cells: dict[tuple[str, int], list[float]] = {
        (sc, ti): [] for sc in STOP_CHOICES for ti in range(1, MAX_TARGET_INDEX + 1)
    }
    agg_baseline: list[float] = []

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        stats, cells, baseline_rrs = _run_anchor(anchor)
        report["anchors"][anchor] = stats
        print(json.dumps(stats, indent=2, default=str))
        for key, rrs in cells.items():
            agg_cells[key].extend(rrs)
        agg_baseline.extend(baseline_rrs)

    def _qualify_rate(rrs: list[float]) -> float:
        return (sum(1 for r in rrs if r >= MIN_RR) / len(rrs)) if rrs else 0.0

    baseline_qualify_rate = _qualify_rate(agg_baseline)
    agg_cell_rates = {
        f"{sc}|TP{ti}": {"n": len(rrs), "qualify_rate": round(_qualify_rate(rrs), 4)}
        for (sc, ti), rrs in agg_cells.items()
    }
    best_key, best_stats = max(agg_cell_rates.items(), key=lambda kv: kv[1]["qualify_rate"])
    best_alt_qualify_rate = best_stats["qualify_rate"]

    verdict = compute_verdict(baseline_qualify_rate, best_alt_qualify_rate)

    report["h8_verdict"] = {
        "baseline_n": len(agg_baseline),
        "baseline_qualify_rate": round(baseline_qualify_rate, 4),
        "best_alt_combination": best_key,
        "best_alt_n": best_stats["n"],
        "best_alt_qualify_rate": best_alt_qualify_rate,
        "verdict": verdict,
        "rule": (
            "STRUCTURAL if best_alt < 0.25; PARAMETER_SENSITIVE if "
            "best_alt >= 0.25 AND best_alt >= 2x baseline; else INCONCLUSIVE"
        ),
        "all_pooled_cells": agg_cell_rates,
    }
    print("\n### H8 verdict ###")
    print(json.dumps({k: v for k, v in report["h8_verdict"].items() if k != "all_pooled_cells"}, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
