"""research_atr_stop.py

Continuous research mode (operator directive, 2026-07-14), experiment 6:
does a volatility-scaled (ATR-based) stop-distance FLOOR fix the
execution-delay material failure without the profitability collapse a
flat percentage buffer caused (experiments 1/2/5)? Uses the new
`atr_stop_multiplier` parameter (`entry_model.build_entry_model`) --
widens the stop only when the zone-derived stop is tighter than
`atr * multiplier`, never tightens an already-wider stop.
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
ATR_MULTIPLIERS = [1.0, 2.0]
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_atr_stop.json"


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
    avg_stop_pct = None
    stop_pcts = [
        abs(t["entry_price"] - t["stop_loss"]) / t["entry_price"]
        for t in trades
        if t.get("stop_loss")
    ]
    if stop_pcts:
        avg_stop_pct = sum(stop_pcts) / len(stop_pcts)
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
        "avg_stop_distance_pct": avg_stop_pct,
    }


def main() -> int:
    report: dict[str, Any] = {"candidate": CANDIDATE_KWARGS, "symbol": SYMBOL, "anchors": {}}

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        ltf, htf = _fetch(anchor)
        entry: dict[str, Any] = {}

        for multiplier in ATR_MULTIPLIERS:
            print(f"  multiplier={multiplier}, no-delay...")
            results_nodelay, trades_nodelay = _run(
                ltf, htf, entry_delay_candles=0, atr_stop_multiplier=multiplier, **CANDIDATE_KWARGS
            )
            print(f"  multiplier={multiplier}, delay=1...")
            results_delay, trades_delay = _run(
                ltf, htf, entry_delay_candles=1, atr_stop_multiplier=multiplier, **CANDIDATE_KWARGS
            )
            entry[str(multiplier)] = {
                "no_delay": _metrics(results_nodelay, trades_nodelay),
                "delay_1": _metrics(results_delay, trades_delay),
            }

        report["anchors"][anchor] = entry
        print(json.dumps(entry, indent=2, default=str))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
