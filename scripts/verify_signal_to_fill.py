"""verify_signal_to_fill.py

Validation-phase deliverable (2026-07-19, operator directive: "verify
that every signal reaches the execution layer correctly"). Read-only
relative to production code -- imports and calls `run_paper.run_once()`
and `run_paper._check_and_close_open_positions()` directly, UNMODIFIED.
The only thing this script injects is a deterministic synthetic
`TradeSignal` in place of `SignalEngine.generate_signal()`'s real
market-dependent output (via `unittest.mock.patch`, the same technique
`backend/tests/` already uses throughout) -- every other function in the
signal -> risk -> execute -> persist -> close chain runs completely for
real, against a REAL (but temporary, throwaway) SQLite database created
by the REAL `alembic upgrade head` migration path
(`app.main.run_migrations()`), never the production
`backend/paper_validation.db`.

Exists because Legacy's real signal rate is too low (roughly one every
1-4 days per backtest evidence) to reliably observe a full open->close
cycle by just running the real pipeline and waiting -- this script
verifies the WIRING is correct today, deterministically, without
depending on when the next real signal happens to fire.

MUST be run with `DATABASE_URL` already pointed at a throwaway temp
sqlite file BEFORE this process starts (see the invocation line in
docs/PAPER_TRADING_VALIDATION_REPORT.md) -- this script does not create
or manage that file itself, to avoid any chance of accidentally binding
to the real production database path.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

OUTPUT_PATH = SCRIPT_DIR / "reports" / "verify_signal_to_fill.json"

SLIPPAGE_PERCENT = 0.0002
FEE_PERCENT = 0.05
RISK_PER_TRADE_PERCENT = 0.25
ACCOUNT_BALANCE = 10000.0

SYNTHETIC_ENTRY = 50000.0
SYNTHETIC_STOP = 49000.0
SYNTHETIC_TARGET = 52500.0  # RR = 2.5, clears the 1:2 minimum


def _fail(check: str, expected: Any, actual: Any) -> dict:
    return {"check": check, "expected": expected, "actual": actual, "pass": expected == actual}


def _close_enough(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if "paper_validation.db" in db_url or db_url == "":
        print(
            "REFUSING TO RUN: DATABASE_URL must be a throwaway temp sqlite "
            f"file, not the production DB or empty. Got: {db_url!r}"
        )
        return 1
    print(f"Using temp DB: {db_url}")

    import app.main as app_main

    app_main.run_migrations()
    print("Real alembic migrations applied to temp DB.")

    import run_paper
    from app.strategy.signal_engine import TradeSignal

    checks: list[dict] = []

    synthetic_signal = TradeSignal(
        symbol="BTCUSDT",
        direction="long",
        timestamp=datetime.now(timezone.utc),
        htf_bias="bullish",
        sweep_type="buy_side",
        choch_detected=True,
        fvg_zone=None,
        entry_price=SYNTHETIC_ENTRY,
        stop_loss=SYNTHETIC_STOP,
        take_profit=SYNTHETIC_TARGET,
        rr=(SYNTHETIC_TARGET - SYNTHETIC_ENTRY) / (SYNTHETIC_ENTRY - SYNTHETIC_STOP),
        status="pending",
    )

    # --- Phase 1: open a trade via the REAL run_once() pipeline ---
    print("\n### Phase 1: signal -> risk -> execute -> persist (real run_once()) ###")
    with patch.object(run_paper.SignalEngine, "generate_signal", return_value=synthetic_signal):
        summary = run_paper.run_once()
    print(json.dumps({k: v for k, v in summary.items() if k != "shadow"}, indent=2, default=str))

    checks.append(_fail("signal_found", True, summary["signal_found"]))
    checks.append(_fail("approved", True, summary["approved"]))
    checks.append(_fail("executed", True, summary["executed"]))
    checks.append({"check": "trade_id_present", "expected": "not None", "actual": summary["trade_id"], "pass": summary["trade_id"] is not None})

    trade_id = summary["trade_id"]
    if trade_id is None:
        print("\nABORTING: no trade_id -- cannot verify persisted fields or close path.")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps({"checks": checks, "all_passed": False}, indent=2, default=str))
        return 1

    from app.portfolio.trades import TradeTracker

    tracker = TradeTracker()
    open_positions = tracker.get_open_positions()
    trade = next((p for p in open_positions if p["id"] == trade_id), None)
    checks.append({"check": "trade_row_found_in_db", "expected": "found", "actual": "found" if trade else "MISSING", "pass": trade is not None})

    if trade is not None:
        expected_fill_price = SYNTHETIC_ENTRY * (1 + SLIPPAGE_PERCENT)
        expected_size = (ACCOUNT_BALANCE * (RISK_PER_TRADE_PERCENT / 100)) / abs(SYNTHETIC_ENTRY - SYNTHETIC_STOP)
        expected_fee = (FEE_PERCENT / 100) * expected_size * expected_fill_price
        expected_slippage = abs(expected_fill_price - SYNTHETIC_ENTRY)

        print(f"\nExpected (hand-computed): fill_price={expected_fill_price}, size={expected_size}, fee={expected_fee}, slippage={expected_slippage}")
        print(f"Actual (from DB):         fill_price={trade['entry_price']}, size={trade['size']}, fee={trade['fee']}, slippage={trade['slippage']}")

        checks.append({"check": "fill_price_matches_slippage_formula", "expected": expected_fill_price, "actual": trade["entry_price"], "pass": _close_enough(expected_fill_price, trade["entry_price"])})
        checks.append({"check": "position_size_matches_risk_formula", "expected": expected_size, "actual": trade["size"], "pass": _close_enough(expected_size, trade["size"])})
        checks.append({"check": "fee_matches_flat_taker_formula", "expected": expected_fee, "actual": trade["fee"], "pass": _close_enough(expected_fee, trade["fee"])})
        checks.append({"check": "slippage_matches_fill_minus_planned", "expected": expected_slippage, "actual": trade["slippage"], "pass": _close_enough(expected_slippage, trade["slippage"])})
        checks.append(_fail("stop_loss_matches_signal", SYNTHETIC_STOP, trade["stop_loss"]))
        checks.append(_fail("take_profit_matches_signal", SYNTHETIC_TARGET, trade["take_profit"]))
        checks.append(_fail("status_open", "open", trade["status"]))
        checks.append(_fail("mode_paper", "paper", trade["mode"]))

    # --- Phase 2: concurrency guard -- a second pass must NOT open a second position ---
    print("\n### Phase 2: concurrency guard (one-trade-open-at-a-time) ###")
    with patch.object(run_paper.SignalEngine, "generate_signal", return_value=synthetic_signal):
        summary2 = run_paper.run_once()
    print(json.dumps({k: v for k, v in summary2.items() if k != "shadow"}, indent=2, default=str))
    checks.append(_fail("second_pass_skips_signal_generation", True, summary2["skipped_signal_generation"]))
    checks.append(_fail("second_pass_signal_found_false", False, summary2["signal_found"]))

    # --- Phase 3: close the position via the REAL exit-check function, forced to hit take_profit ---
    print("\n### Phase 3: close path (real _check_and_close_open_positions(), forced TP hit) ###")
    force_price = SYNTHETIC_TARGET + 100.0  # comfortably above TP for a long
    closed_ids = run_paper._check_and_close_open_positions(force_price)
    print(f"closed_ids={closed_ids}")
    checks.append({"check": "close_path_closed_our_trade", "expected": trade_id, "actual": closed_ids, "pass": trade_id in closed_ids})

    closed_trades = tracker.get_closed_trades()
    closed = next((t for t in closed_trades if t["id"] == trade_id), None)
    checks.append({"check": "closed_trade_row_found", "expected": "found", "actual": "found" if closed else "MISSING", "pass": closed is not None})

    if closed is not None:
        expected_exit_price = SYNTHETIC_TARGET * (1 - SLIPPAGE_PERCENT)
        print(f"Expected exit_price (TP hit, long, unfavorable slippage): {expected_exit_price}")
        print(f"Actual exit_price: {closed['exit_price']}")
        checks.append({"check": "exit_price_matches_tp_slippage_formula", "expected": expected_exit_price, "actual": closed["exit_price"], "pass": _close_enough(expected_exit_price, closed["exit_price"])})
        checks.append(_fail("closed_status", "closed", closed["status"]))
        checks.append(_fail("exit_reason_take_profit", "take_profit", closed.get("exit_reason")))
        checks.append({"check": "pnl_is_positive_on_tp_hit", "expected": "> 0", "actual": closed["pnl"], "pass": closed["pnl"] > 0})

    all_passed = all(c["pass"] for c in checks)
    print("\n### Result ###")
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  [{mark}] {c['check']}: expected={c['expected']} actual={c['actual']}")
    print(f"\nALL PASSED: {all_passed} ({sum(1 for c in checks if c['pass'])}/{len(checks)})")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"checks": checks, "all_passed": all_passed}, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
