"""research_entry_confirmation.py

Continuous research mode (operator directive, 2026-07-14), experiment 4:
does an entry-confirmation gate (`max_entry_drift_pct`, skip the fill if
the delayed price has moved too far from plan) fix the execution-delay
material failure (`docs/ROBUSTNESS_REPORT.md` test 2) without the
profitability cost seen in experiments 1-3 (stop-buffer widening, session
filtering)?

Compares, at `entry_delay_candles=1`: no confirmation gate (the existing
robustness-report baseline) vs. gate at a few drift thresholds, against
the plain no-delay candidate as the reference point. Both confirmed years
tested up front.
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

from app.backtesting.performance import calculate_profit_factor, calculate_sharpe_ratio, calculate_win_rate  # noqa: E402
from app.config import settings  # noqa: E402

from run_backtest import fetch_candles, htf_candle_count_for_span, run_backtest, split_into_periods, walk_forward_report  # noqa: E402

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
ANCHORS = ["2026-07-12", "2025-07-12"]
CANDIDATE_KWARGS: dict[str, Any] = {
    "use_structure_tp": True,
    "structure_tp_max_r": 3.0,
    "require_premium_discount_filter": True,
}
# Average stop distance is ~0.23% of price (docs/ROBUSTNESS_REPORT.md
# test 7) -- thresholds chosen as fractions of that, not arbitrary.
DRIFT_THRESHOLDS = [0.0005, 0.001, 0.0015]  # 0.05%, 0.10%, 0.15%
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_entry_confirmation.json"


def _fetch(anchor: str) -> tuple[list, list]:
    end_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    total = CANDLES_PER_PERIOD * PERIODS
    ltf = fetch_candles(SYMBOL, TIMEFRAME, total, end_ms)
    htf_req = htf_candle_count_for_span(TIMEFRAME, total, settings.HTF_TIMEFRAME)
    htf = fetch_candles(SYMBOL, settings.HTF_TIMEFRAME, htf_req, end_ms)
    return ltf, htf


def _run(ltf: list, htf: list, **kwargs) -> tuple[list, list[dict]]:
    periods = split_into_periods(ltf, PERIODS)
    results = []
    trades: list[dict] = []
    for chunk in periods:
        r = run_backtest(chunk, htf, **kwargs)
        results.append(r)
        trades.extend(r.trades)
    return results, trades


def _metrics(results: list, trades: list[dict]) -> dict:
    total_pnl = sum(r.total_pnl for r in results)
    wf = walk_forward_report(results) if len(results) >= 2 else None
    return {
        "total_pnl": total_pnl,
        "profit_factor": calculate_profit_factor(trades) if trades else 0.0,
        "win_rate": calculate_win_rate(trades) if trades else 0.0,
        "sharpe": calculate_sharpe_ratio([t["pnl"] for t in trades]) if trades else 0.0,
        "max_drawdown_worst": max((r.max_drawdown for r in results), default=0.0),
        "total_trades": len(trades),
        "profitable_periods": sum(1 for r in results if r.total_pnl > 0),
        "periods": len(results),
        "walk_forward_passed": wf["passed"] if wf else None,
    }


def main() -> int:
    report: dict[str, Any] = {"candidate": CANDIDATE_KWARGS, "symbol": SYMBOL, "anchors": {}}

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        ltf, htf = _fetch(anchor)

        print("  no-delay (reference)...")
        results_nodelay, trades_nodelay = _run(ltf, htf, entry_delay_candles=0, **CANDIDATE_KWARGS)

        print("  delay=1, no confirmation gate...")
        results_delay, trades_delay = _run(ltf, htf, entry_delay_candles=1, **CANDIDATE_KWARGS)

        entry: dict[str, Any] = {
            "no_delay": _metrics(results_nodelay, trades_nodelay),
            "delay_1_no_gate": _metrics(results_delay, trades_delay),
            "delay_1_with_gate": {},
        }

        for threshold in DRIFT_THRESHOLDS:
            print(f"  delay=1, drift gate={threshold*100:.2f}%...")
            results_gate, trades_gate = _run(
                ltf, htf, entry_delay_candles=1, max_entry_drift_pct=threshold, **CANDIDATE_KWARGS
            )
            entry["delay_1_with_gate"][str(threshold)] = _metrics(results_gate, trades_gate)

        report["anchors"][anchor] = entry
        print(json.dumps(entry, indent=2, default=str))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
