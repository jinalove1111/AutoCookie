"""research_h7_jade_risk_attribution.py

H7 (docs/HYPOTHESES_ROUND_2.md section 3, pre-registered 2026-07-19):
attributes the gap H6 disclosed but explicitly did not measure -- 8,312
`signal_would_generate` steps (docs/H6_JADE_SCARCITY_RESULTS.md) vs.
decision #36's 6 actual Jade trades. Reuses `run_backtest.py`'s own
`run_backtest(..., use_jade_engine=True)` and `aggregate_risk_rejections`
verbatim -- both already built (Milestone 23) and already engine-agnostic
(they observe whatever `RiskManager.evaluate()` decides on whatever
signal `SignalEngine.generate_signal()` produces, regardless of which
engine produced it). No new `BacktestEngine` parameter, no new production
code anywhere -- decision #36's original A/B test (2026-07-12) simply
predates this instrumentation (shipped 2026-07-17) by 5 days, so this is
new information about an already-settled comparison, not a re-litigation
of it.
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

from app.config import settings  # noqa: E402

from run_backtest import (  # noqa: E402
    aggregate_risk_rejections,
    fetch_candles,
    htf_candle_count_for_span,
    run_backtest,
    split_into_periods,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
ANCHORS = ["2026-07-10", "2025-07-10", "2024-07-10"]
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_h7_jade_risk_attribution.json"

# H6's own aggregate signal_would_generate counts per anchor
# (docs/H6_JADE_SCARCITY_RESULTS.md section 2) -- cited here, not
# recomputed, for the direct step-count-vs-total_signals comparison
# this hypothesis's keep-rule needs.
H6_SIGNAL_WOULD_GENERATE = {
    "2026-07-10": 3666,
    "2025-07-10": 2141,
    "2024-07-10": 2505,
}


def _fetch(anchor: str) -> tuple[list, list]:
    end_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    total = CANDLES_PER_PERIOD * PERIODS
    ltf = fetch_candles(SYMBOL, TIMEFRAME, total, end_ms)
    htf_req = htf_candle_count_for_span(TIMEFRAME, total, settings.HTF_TIMEFRAME)
    htf = fetch_candles(SYMBOL, settings.HTF_TIMEFRAME, htf_req, end_ms)
    return ltf, htf


def _run_anchor(anchor: str) -> dict:
    ltf, htf = _fetch(anchor)
    results = [run_backtest(chunk, htf, use_jade_engine=True) for chunk in split_into_periods(ltf, PERIODS)]
    rejections = aggregate_risk_rejections(results)
    total_trades = sum(len(r.trades) for r in results)

    total_signals = rejections.get("total_signals", 0)
    approved = rejections.get("approved", 0)
    rejected = rejections.get("rejected", 0)
    by_reason = rejections.get("by_reason") or {}
    top_reason = max(by_reason, key=by_reason.get) if by_reason else None

    h6_would_generate = H6_SIGNAL_WOULD_GENERATE[anchor]
    return {
        "total_trades": total_trades,
        "risk_rejections": rejections,
        "top_reject_reason": top_reason,
        "h6_signal_would_generate": h6_would_generate,
        "total_signals_as_pct_of_h6_would_generate": (
            round(100 * total_signals / h6_would_generate, 1) if h6_would_generate else None
        ),
        "reject_rate_of_total_signals": (
            round(rejected / total_signals, 3) if total_signals else None
        ),
    }


def compute_verdict(
    reject_rate: float, top_reject_reason: str | None, pct_of_h6_would_generate: float
) -> tuple[bool, bool, str]:
    """H7's pre-registered keep-rule (docs/HYPOTHESES_ROUND_2.md section 3):
    classifies which stage dominates the H6-disclosed 8,312-vs-6 gap.
    Returns `(risk_gating_dominant, open_trade_persistence_dominant, verdict)`.
    """
    risk_gating_dominant = reject_rate >= 0.5 and top_reject_reason is not None and "MAX_TRADES_PER_DAY" in top_reject_reason
    persistence_dominant = pct_of_h6_would_generate < 25.0

    if risk_gating_dominant and persistence_dominant:
        verdict = "BOTH"
    elif risk_gating_dominant:
        verdict = "RISK_GATING_DOMINANT"
    elif persistence_dominant:
        verdict = "OPEN_TRADE_PERSISTENCE_DOMINANT"
    else:
        verdict = "NEITHER"
    return risk_gating_dominant, persistence_dominant, verdict


def main() -> int:
    report: dict[str, Any] = {"symbol": SYMBOL, "timeframe": TIMEFRAME, "anchors": {}}
    agg_total_signals = 0
    agg_rejected = 0
    agg_by_reason: dict[str, int] = {}
    agg_h6_would_generate = 0

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        result = _run_anchor(anchor)
        report["anchors"][anchor] = result
        print(json.dumps(result, indent=2, default=str))

        rr = result["risk_rejections"]
        agg_total_signals += rr.get("total_signals", 0)
        agg_rejected += rr.get("rejected", 0)
        agg_h6_would_generate += result["h6_signal_would_generate"]
        for reason, count in (rr.get("by_reason") or {}).items():
            agg_by_reason[reason] = agg_by_reason.get(reason, 0) + count

    top_agg_reason = max(agg_by_reason, key=agg_by_reason.get) if agg_by_reason else None
    reject_rate = agg_rejected / agg_total_signals if agg_total_signals else 0.0
    pct_of_h6 = 100 * agg_total_signals / agg_h6_would_generate if agg_h6_would_generate else 0.0

    risk_gating_dominant, persistence_dominant, verdict = compute_verdict(
        reject_rate, top_agg_reason, pct_of_h6
    )

    report["h7_verdict"] = {
        "aggregate_total_signals": agg_total_signals,
        "aggregate_rejected": agg_rejected,
        "reject_rate_of_total_signals": round(reject_rate, 3),
        "top_reject_reason": top_agg_reason,
        "aggregate_by_reason": agg_by_reason,
        "aggregate_h6_signal_would_generate": agg_h6_would_generate,
        "total_signals_as_pct_of_h6_would_generate": round(pct_of_h6, 1),
        "risk_gating_dominant": risk_gating_dominant,
        "open_trade_persistence_dominant": persistence_dominant,
        "verdict": verdict,
        "rule": (
            "RISK_GATING_DOMINANT if rejected/total_signals >= 0.5 AND top "
            "reason is MAX_TRADES_PER_DAY; OPEN_TRADE_PERSISTENCE_DOMINANT if "
            "total_signals < 25% of H6's signal_would_generate; both/neither honestly reported"
        ),
    }
    print("\n### H7 verdict ###")
    print(json.dumps(report["h7_verdict"], indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
