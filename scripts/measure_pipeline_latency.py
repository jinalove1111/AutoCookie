"""measure_pipeline_latency.py

Validation-phase deliverable (2026-07-19, operator directive: "measure
end-to-end latency from signal generation to simulated order
execution"). Read-only, additive observability tool -- imports and
calls `run_paper.run_once()` and `CandleFetcher.fetch_ohlcv` directly,
UNMODIFIED. Does not touch `scripts/run_paper.py` or any production
trading logic; this is a new, separate script, run against the REAL
`backend/paper_validation.db` and REAL OKX market data (paper mode only
-- `LIVE_TRADING_ENABLED` is not touched, no real order is ever placed).

Measures two genuinely different things, kept clearly separate rather
than combined into one misleading number:

1. **Real network latency**: `CandleFetcher.fetch_ohlcv`'s actual
   round-trip to OKX's public REST API (`https://www.okx.com/api/v5/market/candles`)
   -- the one place in this pipeline with a real external network call.
2. **Full in-process pipeline latency**: one complete `run_once()` pass
   (candle fetch -> signal generation -> [risk evaluation -> execution
   -> persistence, only on the passes where a signal actually fires]),
   run repeatedly within a SINGLE warm Python process (matching
   production's real `--iterations N` loop-mode behavior, not N
   separate process launches, which would inflate the number with
   interpreter/import startup cost that never recurs in the real loop).

**Disclosed scope limit, load-bearing**: `app.execution.paper_broker.PaperBroker.execute()`
never makes a real exchange API round-trip (confirmed by reading its
source -- no `requests`/`httpx`/network call of any kind). Neither of
the two numbers this script produces is real exchange order-placement
latency, because no such call exists anywhere in this codebase's
paper-trading path. This script cannot manufacture that measurement;
it can only measure what's actually there and disclose what isn't.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.config import settings  # noqa: E402
from app.data.candle_fetcher import CandleFetcher  # noqa: E402

from run_paper import run_once  # noqa: E402

OUTPUT_PATH = SCRIPT_DIR / "reports" / "paper_pipeline_latency.json"
N_RUN_ONCE_PASSES = 10
N_FETCH_ONLY_SAMPLES = 10


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    sorted_v = sorted(values)
    n = len(sorted_v)
    return {
        "n": n,
        "min_ms": round(min(sorted_v), 1),
        "median_ms": round(statistics.median(sorted_v), 1),
        "mean_ms": round(statistics.mean(sorted_v), 1),
        "p95_ms": round(sorted_v[min(n - 1, int(n * 0.95))], 1),
        "max_ms": round(max(sorted_v), 1),
    }


def measure_fetch_only() -> list[float]:
    """Isolated OKX candle-fetch network round-trip, LTF series only,
    same symbol/timeframe/limit `run_once()`'s own first fetch call
    uses (`app.config.settings.SYMBOL`/`DEFAULT_TIMEFRAME`, limit=300).
    """
    fetcher = CandleFetcher()
    timings: list[float] = []
    for i in range(N_FETCH_ONLY_SAMPLES):
        started = time.monotonic()
        try:
            fetcher.fetch_ohlcv(settings.SYMBOL, settings.DEFAULT_TIMEFRAME, limit=300)
        except Exception as exc:
            print(f"  fetch sample {i + 1} FAILED: {exc}")
            continue
        elapsed_ms = (time.monotonic() - started) * 1000
        timings.append(elapsed_ms)
        print(f"  fetch sample {i + 1}: {elapsed_ms:.1f}ms")
    return timings


def measure_run_once_passes() -> tuple[list[float], list[dict]]:
    """N real, live `run_once()` passes within ONE warm process --
    matches production's real loop-mode per-iteration cost, not N
    separate process launches. Writes to the REAL
    backend/paper_validation.db exactly as production would; paper mode
    only, LIVE_TRADING_ENABLED untouched, no real order ever placed.
    """
    timings: list[float] = []
    outcomes: list[dict] = []
    for i in range(N_RUN_ONCE_PASSES):
        started = time.monotonic()
        try:
            summary = run_once()
        except Exception as exc:
            print(f"  pass {i + 1} FAILED: {exc}")
            outcomes.append({"error": str(exc)})
            continue
        elapsed_ms = (time.monotonic() - started) * 1000
        timings.append(elapsed_ms)
        outcome = {
            "signal_found": summary.get("signal_found"),
            "approved": summary.get("approved"),
            "executed": summary.get("executed"),
            "fetch_failed": summary.get("fetch_failed"),
            "exit_code": summary.get("exit_code"),
            "elapsed_ms": round(elapsed_ms, 1),
        }
        outcomes.append(outcome)
        print(f"  pass {i + 1}: {elapsed_ms:.1f}ms outcome={outcome}")
    return timings, outcomes


def main() -> int:
    print(f"### Isolated OKX candle-fetch latency ({N_FETCH_ONLY_SAMPLES} samples) ###")
    fetch_timings = measure_fetch_only()

    print(f"\n### Full run_once() pipeline, {N_RUN_ONCE_PASSES} live passes, one warm process ###")
    run_once_timings, outcomes = measure_run_once_passes()

    report = {
        "disclosed_scope_limit": (
            "PaperBroker.execute() makes no real exchange API round-trip "
            "(verified by source inspection) -- neither measurement below "
            "is real exchange order-placement latency. No such call exists "
            "anywhere in this codebase's paper-trading path."
        ),
        "settings": {"symbol": settings.SYMBOL, "default_timeframe": settings.DEFAULT_TIMEFRAME, "htf_timeframe": settings.HTF_TIMEFRAME},
        "fetch_only_latency": _stats(fetch_timings),
        "run_once_pipeline_latency": _stats(run_once_timings),
        "run_once_outcomes": outcomes,
    }
    print("\n### Summary ###")
    print(json.dumps({k: v for k, v in report.items() if k != "run_once_outcomes"}, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
