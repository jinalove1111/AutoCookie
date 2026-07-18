"""research_h5_step0_session_grounding.py

H5 Step 0 grounding check (docs/HYPOTHESES_ROUND_1.md section 6,
pre-registered 2026-07-19): before any `session_risk_scalar` sizing code
is written, does the session profit-factor gradient
`docs/ROBUSTNESS_REPORT.md` Test 6 found (Asian PF 4.65 > London PF 2.41,
on BTCUSDT 5m against the `structure_tp` candidate) actually replicate on
the candidate/timeframe H5 would size -- Legacy's own default exit,
BTCUSDT 15m, this document's standard 3-anchor set?

BACKTEST-ONLY, analysis-only research tool. No new `BacktestEngine`
parameter, no new CLI flag, no change to `RiskManager.evaluate()` or
`scripts/run_paper.py` -- this script buckets ALREADY-PRODUCED trade
output (`BacktestEngine`'s existing `opened_at` timestamp on every trade
dict) by UTC entry hour into the same three Test-6 windows (Asian
00:00-08:00, London 08:00-16:00, NY/other 16:00-24:00) and computes PF
per bucket per year. Nothing here decides whether to size trades
differently; it only decides whether that idea is worth building at all.

Step-0 gate, quoted verbatim from `docs/HYPOTHESES_ROUND_1.md` section 6:
"H5's mechanism proceeds to Step 1 only if Legacy/15m shows the SAME
qualitative gradient direction Test 6 found (Asian PF > London PF) in at
least 2 of the 3 tested years, AND at least the Asian and London buckets
individually reach n>=10 trades in the year(s) counted toward that
check... If this gate fails, H5 is REJECTED at step 0."
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.backtesting.performance import calculate_profit_factor  # noqa: E402
from app.config import settings  # noqa: E402

from run_backtest import fetch_candles, htf_candle_count_for_span, run_backtest, split_into_periods  # noqa: E402

SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
CANDLES_PER_PERIOD = 3000
PERIODS = 6
# Same three standard anchors every H1-H4 experiment in
# docs/HYPOTHESES_ROUND_1.md used.
ANCHORS = ["2026-07-10", "2025-07-10", "2024-07-10"]
OUTPUT_PATH = SCRIPT_DIR / "reports" / "research_h5_step0_session_grounding.json"

# Same three windows as docs/ROBUSTNESS_REPORT.md Test 6 / the
# already-disclosed Asian/London constants in
# backend/app/strategy/session_liquidity.py -- NY/other is Test 6's own
# residual bucket (16:00-24:00 UTC), not a new detector.
_ASIAN = (time(0, 0), time(8, 0))
_LONDON = (time(8, 0), time(16, 0))


def _session_of(ts: Any) -> str:
    if not isinstance(ts, datetime):
        return "unknown"
    t = ts.time()
    if _ASIAN[0] <= t < _ASIAN[1]:
        return "asian"
    if _LONDON[0] <= t < _LONDON[1]:
        return "london"
    return "ny_other"


def _fetch(anchor: str) -> tuple[list, list]:
    end_dt = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    total = CANDLES_PER_PERIOD * PERIODS
    ltf = fetch_candles(SYMBOL, TIMEFRAME, total, end_ms)
    htf_req = htf_candle_count_for_span(TIMEFRAME, total, settings.HTF_TIMEFRAME)
    htf = fetch_candles(SYMBOL, settings.HTF_TIMEFRAME, htf_req, end_ms)
    return ltf, htf


def _run_all_periods(ltf: list, htf: list) -> list[dict]:
    """Plain Legacy default backtest (no kwargs -- byte-identical to the
    already-published Legacy baseline in docs/LEGACY_DELAY_ROBUSTNESS.md),
    all periods pooled into one trade list for this anchor year.
    """
    trades: list[dict] = []
    for chunk in split_into_periods(ltf, PERIODS):
        result = run_backtest(chunk, htf)
        trades.extend(result.trades)
    return trades


def _bucket(trades: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {"asian": [], "london": [], "ny_other": [], "unknown": []}
    for t in trades:
        buckets[_session_of(t.get("opened_at"))].append(t)
    return buckets


def main() -> int:
    report: dict[str, Any] = {"symbol": SYMBOL, "timeframe": TIMEFRAME, "anchors": {}}
    gradient_holds_years: list[str] = []
    sample_ok_years: list[str] = []

    for anchor in ANCHORS:
        print(f"\n### Anchor {anchor} ###")
        ltf, htf = _fetch(anchor)
        trades = _run_all_periods(ltf, htf)
        buckets = _bucket(trades)

        entry: dict[str, Any] = {"total_trades": len(trades)}
        for label in ("asian", "london", "ny_other", "unknown"):
            bt = buckets[label]
            entry[label] = {
                "trades": len(bt),
                "profit_factor": calculate_profit_factor(bt) if bt else 0.0,
                "net_profit": sum(t["pnl"] for t in bt),
            }
        asian_pf = entry["asian"]["profit_factor"]
        london_pf = entry["london"]["profit_factor"]
        asian_n = entry["asian"]["trades"]
        london_n = entry["london"]["trades"]

        gradient_this_year = asian_pf > london_pf
        sample_ok_this_year = asian_n >= 10 and london_n >= 10
        entry["gradient_holds"] = gradient_this_year
        entry["sample_floor_met"] = sample_ok_this_year

        if gradient_this_year:
            gradient_holds_years.append(anchor)
        if sample_ok_this_year:
            sample_ok_years.append(anchor)

        report["anchors"][anchor] = entry
        print(json.dumps(entry, indent=2, default=str))

    # Step-0 gate: gradient direction (Asian PF > London PF) must hold in
    # >=2 of 3 years, AND those counted years must independently clear the
    # n>=10 floor on both buckets -- a year satisfying the direction only
    # because of a thin bucket does not count toward the gate.
    qualifying_years = [y for y in gradient_holds_years if y in sample_ok_years]
    gate_passed = len(qualifying_years) >= 2

    report["step0_gate"] = {
        "years_gradient_holds": gradient_holds_years,
        "years_sample_floor_met": sample_ok_years,
        "years_qualifying_both": qualifying_years,
        "gate_passed": gate_passed,
        "rule": "Asian PF > London PF in >=2/3 years, both buckets n>=10 in the counted years",
    }
    print("\n### Step-0 gate ###")
    print(json.dumps(report["step0_gate"], indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
