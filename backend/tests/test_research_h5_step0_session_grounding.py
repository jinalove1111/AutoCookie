"""Tests for scripts/research_h5_step0_session_grounding.py (H5 Step 0
grounding check, docs/HYPOTHESES_ROUND_1.md section 6). scripts/ is a
sibling directory to backend/, not a package under it -- same sys.path
pattern test_research_regime_delay.py / test_research_signal_selection.py
already use.

Pure, I/O-free unit tests for `_session_of` (the UTC-hour bucketing this
script's entire result depends on) -- no real BacktestEngine/network call
anywhere in this file. `main()` itself (the fetch/run/report loop) is
exercised only manually via the real script run recorded in
docs/H5_SESSION_GROUNDING_RESULTS.md, mirroring
test_research_regime_delay.py's own scope split (pure logic under test,
CLI/fetch loop not).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from research_h5_step0_session_grounding import _bucket, _session_of  # noqa: E402


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=timezone.utc)


def test_session_of_asian_window_start_inclusive() -> None:
    assert _session_of(_ts(0, 0)) == "asian"


def test_session_of_asian_window_end_exclusive() -> None:
    # 08:00 belongs to London, not Asian -- window is [00:00, 08:00).
    assert _session_of(_ts(7, 59)) == "asian"
    assert _session_of(_ts(8, 0)) == "london"


def test_session_of_london_window() -> None:
    assert _session_of(_ts(8, 0)) == "london"
    assert _session_of(_ts(15, 59)) == "london"


def test_session_of_ny_other_is_residual_window() -> None:
    # 16:00-23:59 UTC, Test 6's own residual bucket -- not a named
    # production session constant, derived here the same way Test 6 was.
    assert _session_of(_ts(16, 0)) == "ny_other"
    assert _session_of(_ts(23, 59)) == "ny_other"


def test_session_of_midnight_boundary_wraps_to_asian() -> None:
    assert _session_of(_ts(0, 0)) == "asian"


def test_session_of_non_datetime_is_unknown() -> None:
    # Same graceful-degradation convention session_liquidity.py /
    # signal_engine.py's require_session already use for non-real
    # timestamps (hand-built test fixtures elsewhere in this project).
    assert _session_of("2026-01-05T00:00:00Z") == "unknown"
    assert _session_of(None) == "unknown"


def test_bucket_splits_trades_by_entry_session() -> None:
    trades = [
        {"opened_at": _ts(1), "pnl": 10.0},
        {"opened_at": _ts(9), "pnl": -5.0},
        {"opened_at": _ts(20), "pnl": 3.0},
        {"opened_at": "not-a-datetime", "pnl": 1.0},
    ]
    buckets = _bucket(trades)
    assert [t["pnl"] for t in buckets["asian"]] == [10.0]
    assert [t["pnl"] for t in buckets["london"]] == [-5.0]
    assert [t["pnl"] for t in buckets["ny_other"]] == [3.0]
    assert [t["pnl"] for t in buckets["unknown"]] == [1.0]


def test_bucket_empty_input_yields_empty_buckets() -> None:
    buckets = _bucket([])
    assert buckets == {"asian": [], "london": [], "ny_other": [], "unknown": []}
