"""research_stop_width.py

Continuous research mode (operator directive, 2026-07-14): systematic
testing of an EXISTING, already-implemented parameter --
`entry_model._STOP_BUFFER` -- directly motivated by
`docs/ROBUSTNESS_REPORT.md`'s material execution-delay failure (Profit
Factor 5.24 -> 0.16 at a single 5-minute delay, traced to the candidate's
very tight 0.23%-of-price average stop distance).

Question: does widening `_STOP_BUFFER` (monkey-patched for the duration
of each test, same pattern as `scripts/parameter_sweep.py`) preserve
profitability while fixing the delay-fragility that made the candidate
NOT PROMOTED? This is NOT a new strategy -- `_STOP_BUFFER` already exists
and is already a tunable, disclosed-not-tuned constant (see
`entry_model.py`'s own docstring history, ENGINEERING_DECISIONS.md #18).

Not restarting completed work: reuses the BTC candidate config
(`use_structure_tp=True, structure_tp_max_r=3.0,
require_premium_discount_filter=True`) and the 2026-07-12 anchor already
established as this session's standard comparison window.
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

from app.backtesting.performance import calculate_profit_factor, calculate_win_rate  # noqa: E402
from app.config import settings  # noqa: E402
from app.strategy import entry_model  # noqa: E402

from run_backtest import fetch_candles, htf_candle_count_for_span, run_backtest, split_into_periods  # noqa: E402

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
ANCHOR = "2026-07-12"
CANDIDATE_KWARGS: dict[str, Any] = {
    "use_structure_tp": True,
    "structure_tp_max_r": 3.0,
    "require_premium_discount_filter": True,
}
# Experiment 2: 1% (~7x baseline) was REJECTED after cross-year testing
# (see docs/CONTINUOUS_RESEARCH_LOG.md experiment 1) -- unprofitable in
# 2025 even with no delay. Testing more modest widths (2x/3x baseline)
# to see if a smaller step avoids the trade-count collapse / profitability
# reversal seen at 1%, while still meaningfully improving delay-robustness.
STOP_BUFFER_VALUES = [0.0015, 0.003, 0.005]  # baseline, 0.3%, 0.5%
OUTPUT_PATH = SCRIPT_DIR / "reports" / f"research_stop_width_exp2_{ANCHOR}.json"


def _fetch() -> tuple[list, list]:
    end_dt = datetime.strptime(ANCHOR, "%Y-%m-%d").replace(tzinfo=timezone.utc)
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


def main() -> int:
    print(f"Fetching {SYMBOL}/{TIMEFRAME} anchored to {ANCHOR}...")
    ltf, htf = _fetch()

    report: dict[str, Any] = {
        "candidate": CANDIDATE_KWARGS,
        "symbol": SYMBOL,
        "anchor": ANCHOR,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "buffers_tested": {},
    }

    original_buffer = entry_model._STOP_BUFFER
    try:
        for buffer_value in STOP_BUFFER_VALUES:
            entry_model._STOP_BUFFER = buffer_value
            print(f"\n=== _STOP_BUFFER = {buffer_value} ({buffer_value*100:.2f}%) ===")

            print("  no-delay run...")
            results_nodelay, trades_nodelay = _run(ltf, htf, entry_delay_candles=0, **CANDIDATE_KWARGS)
            avg_stop_pct = None
            stop_pcts = [
                abs(t["entry_price"] - t["stop_loss"]) / t["entry_price"]
                for t in trades_nodelay
                if t.get("stop_loss")
            ]
            if stop_pcts:
                avg_stop_pct = sum(stop_pcts) / len(stop_pcts)

            print("  1-candle-delay run...")
            results_delay1, trades_delay1 = _run(ltf, htf, entry_delay_candles=1, **CANDIDATE_KWARGS)

            report["buffers_tested"][str(buffer_value)] = {
                "avg_stop_distance_pct": avg_stop_pct,
                "no_delay": {
                    "total_pnl": sum(r.total_pnl for r in results_nodelay),
                    "profit_factor": calculate_profit_factor(trades_nodelay) if trades_nodelay else 0.0,
                    "win_rate": calculate_win_rate(trades_nodelay) if trades_nodelay else 0.0,
                    "total_trades": len(trades_nodelay),
                },
                "delay_1_candle": {
                    "total_pnl": sum(r.total_pnl for r in results_delay1),
                    "profit_factor": calculate_profit_factor(trades_delay1) if trades_delay1 else 0.0,
                    "win_rate": calculate_win_rate(trades_delay1) if trades_delay1 else 0.0,
                    "total_trades": len(trades_delay1),
                },
            }
            print(json.dumps(report["buffers_tested"][str(buffer_value)], indent=2, default=str))
    finally:
        entry_model._STOP_BUFFER = original_buffer

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
