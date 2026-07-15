"""research_combined_defense.py

Continuous research mode (operator directive, 2026-07-14), experiment 5:
combines two ALREADY-TESTED, individually-rejected levers -- moderate
`_STOP_BUFFER` widening (0.3%, experiment 2: stayed no-delay-profitable,
PF 10.45, but delay-1 was still net negative) and the entry-confirmation
gate (experiment 4: partially helped in 2026 alone, PF 0.16 -> 1.29 at
0.05%, but still failed walk-forward and provided no benefit in 2025).
No new code -- reuses `entry_model._STOP_BUFFER` monkey-patching
(research_stop_width.py's pattern) and `max_entry_drift_pct`
(research_entry_confirmation.py's pattern) together, testing whether they
compound favorably where each failed alone.
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
from app.strategy import entry_model  # noqa: E402

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
STOP_BUFFER = 0.003  # 0.3%, experiment 2's best no-delay result
DRIFT_GATE = 0.0005  # 0.05%, experiment 4's best 2026 result
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_combined_defense.json"


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
    report: dict[str, Any] = {
        "candidate": CANDIDATE_KWARGS,
        "stop_buffer": STOP_BUFFER,
        "drift_gate": DRIFT_GATE,
        "symbol": SYMBOL,
        "anchors": {},
    }

    original_buffer = entry_model._STOP_BUFFER
    try:
        entry_model._STOP_BUFFER = STOP_BUFFER
        for anchor in ANCHORS:
            print(f"\n### Anchor {anchor} (buffer={STOP_BUFFER}) ###")
            ltf, htf = _fetch(anchor)

            print("  no-delay...")
            results_nodelay, trades_nodelay = _run(ltf, htf, entry_delay_candles=0, **CANDIDATE_KWARGS)

            print("  delay=1, combined defense (buffer + gate)...")
            results_combined, trades_combined = _run(
                ltf, htf, entry_delay_candles=1, max_entry_drift_pct=DRIFT_GATE, **CANDIDATE_KWARGS
            )

            entry = {
                "no_delay": _metrics(results_nodelay, trades_nodelay),
                "delay_1_combined": _metrics(results_combined, trades_combined),
            }
            report["anchors"][anchor] = entry
            print(json.dumps(entry, indent=2, default=str))
    finally:
        entry_model._STOP_BUFFER = original_buffer

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
