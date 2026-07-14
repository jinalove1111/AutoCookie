"""research_session_filter.py

Continuous research mode (operator directive, 2026-07-14), experiment 3:
does restricting the production candidate's entries to the Asian session
(00:00-08:00 UTC) improve net profit/robustness, given
`docs/ROBUSTNESS_REPORT.md` test 6 found Asian dominates both trade
volume and quality (PF 4.65 vs London's 2.41, NY/other too thin to
trust)? Uses the ALREADY-EXISTING `require_session` filter (session
windows reused unmodified from `session_liquidity.py` -- no new
indicator).

Compares CANDIDATE vs CANDIDATE+session-filter (not vs. raw Legacy
baseline -- that comparison already exists in
docs/PROFITABILITY_EXPERIMENT_REPORT.md/docs/ROBUSTNESS_REPORT.md). Both
years tested up front (not sequentially gated) since the operator
directive requires cross-year confirmation before accepting any result
regardless of how the first year looks.
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
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_session_filter.json"


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
    return {
        "total_pnl": total_pnl,
        "profit_factor": calculate_profit_factor(trades) if trades else 0.0,
        "win_rate": calculate_win_rate(trades) if trades else 0.0,
        "sharpe": calculate_sharpe_ratio([t["pnl"] for t in trades]) if trades else 0.0,
        "max_drawdown_worst": max((r.max_drawdown for r in results), default=0.0),
        "total_trades": len(trades),
        "profitable_periods": sum(1 for r in results if r.total_pnl > 0),
        "periods": len(results),
    }


def main() -> int:
    report: dict[str, Any] = {"candidate": CANDIDATE_KWARGS, "symbol": SYMBOL, "anchors": {}}

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        ltf, htf = _fetch(anchor)

        print("  candidate (no session filter)...")
        results_base, trades_base = _run(ltf, htf, **CANDIDATE_KWARGS)
        wf_base = walk_forward_report(results_base) if len(results_base) >= 2 else None

        print("  candidate + require_session=asian...")
        results_asian, trades_asian = _run(ltf, htf, require_session="asian", **CANDIDATE_KWARGS)
        wf_asian = walk_forward_report(results_asian) if len(results_asian) >= 2 else None

        entry = {
            "candidate": _metrics(results_base, trades_base),
            "candidate_asian_only": _metrics(results_asian, trades_asian),
            "walk_forward_candidate_passed": wf_base["passed"] if wf_base else None,
            "walk_forward_asian_only_passed": wf_asian["passed"] if wf_asian else None,
        }
        report["anchors"][anchor] = entry
        print(json.dumps(entry, indent=2, default=str))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
