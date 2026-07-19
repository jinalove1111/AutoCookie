"""measure_exchange_readonly_latency.py

Milestone 37 (Priority 1, Phase 0 of `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`)
deliverable: a new, standalone measurement harness for `OkxClient`'s
authenticated read-only calls (`get_balance`/`get_open_positions`)
against OKX's real **demo-trading** environment (`x-simulated-trading: 1`,
`OkxClient(demo=True)` -- never real capital). Same pattern as
`scripts/measure_pipeline_latency.py`: standalone, additive, never
touches `scripts/run_paper.py` or any live-trading path.

**Refuses to run without real OKX demo credentials configured**
(`OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE`), matching
`scripts/verify_signal_to_fill.py`'s own fail-closed safety-check
pattern -- this script is written and unit-testable end-to-end today,
but actually producing Gate #4's next real measurement still requires an
operator to supply those three values; this milestone does not have and
does not fabricate them.

This does NOT place this platform on OKX in any way: `OkxClient` is not
imported by `scripts/run_paper.py` or any other live-trading path.
`place_order`/`cancel_order` are Phase 1 scope and remain unimplemented
in `OkxClient` itself -- this script only exercises the two read-only
methods Phase 0 implements.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.exchange.okx_client import OkxClient  # noqa: E402

OUTPUT_PATH = SCRIPT_DIR / "reports" / "exchange_readonly_latency.json"
N_SAMPLES = 10


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


def _measure(label: str, fn) -> list[float]:
    timings: list[float] = []
    for i in range(N_SAMPLES):
        started = time.monotonic()
        try:
            fn()
        except Exception as exc:
            print(f"  {label} sample {i + 1} FAILED: {exc}")
            continue
        elapsed_ms = (time.monotonic() - started) * 1000
        timings.append(elapsed_ms)
        print(f"  {label} sample {i + 1}: {elapsed_ms:.1f}ms")
    return timings


def main() -> int:
    if not (settings.OKX_API_KEY and settings.OKX_API_SECRET and settings.OKX_API_PASSPHRASE):
        print(
            "REFUSING TO RUN: OKX_API_KEY/OKX_API_SECRET/OKX_API_PASSPHRASE must "
            "all be set (OKX demo-trading credentials -- see "
            "docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md section 2). "
            "This is Phase 0 of that roadmap and requires explicit operator "
            "sign-off + real (demo) credentials before it can produce a number."
        )
        return 1

    client = OkxClient(demo=True)
    print(f"Using OKX demo-trading endpoint (x-simulated-trading: 1), {N_SAMPLES} samples each.")

    print("\n### get_balance() latency ###")
    balance_timings = _measure("get_balance", client.get_balance)

    print("\n### get_open_positions() latency ###")
    positions_timings = _measure("get_open_positions", client.get_open_positions)

    report = {
        "disclosed_scope": (
            "Read-only Phase 0 measurement only (get_balance/get_open_positions "
            "against OKX's demo-trading environment). Not order-placement "
            "latency -- place_order/cancel_order are Phase 1 scope and remain "
            "unimplemented in OkxClient. Not wired into scripts/run_paper.py "
            "or any live-trading path."
        ),
        "demo_mode": True,
        "get_balance_latency": _stats(balance_timings),
        "get_open_positions_latency": _stats(positions_timings),
    }
    print("\n### Summary ###")
    print(json.dumps(report, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
