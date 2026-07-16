"""Tests for `app.portfolio.shadow_status` (pure helpers) and
`scripts/shadow_status.py` (the read-only CLI) -- Milestone 13,
2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3.

Mirrors `test_shadow_recorder.py`'s discipline: real synthetic
`RegimeSnapshot`/`ShadowSignal` rows are inserted via the ORM against the
same real-migration-driven temp-DB fixtures (`migrated_db`/`db_session`)
`test_shadow_observability_schema.py` uses, so this module proves the
FULL read path (real sqlite file -> `scripts/shadow_status.py`'s
read-only fetch functions -> JSON/datetime decoding -> the pure helpers
in `app.portfolio.shadow_status`), not just the arithmetic in isolation.

`scripts/` is a sibling directory to `backend/`, not a package under it --
added to `sys.path` explicitly here, same convention `test_run_backtest.py`
/ `test_parameter_sweep.py` already established (only TEST files reach
across that boundary, never production `app` code).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shadow_status as shadow_status_script  # noqa: E402

from app.portfolio.shadow_status import (  # noqa: E402
    HONESTY_NOTE,
    MIN_TRADES_FOR_CONFIDENCE,
    compute_shadow_signal_stats,
    compute_snapshot_stats,
    market_regime_bucket,
    regime_bucket,
    render_report,
    routability_report,
)


def _db_path_from_url(sqlite_url: str) -> Path:
    assert sqlite_url.startswith("sqlite:///")
    return Path(sqlite_url[len("sqlite:///") :])


# --------------------------------------------------------------------
# Pure helpers, hand-built fixtures (no DB) -- straight arithmetic.
# --------------------------------------------------------------------


def test_regime_bucket_composes_trend_and_volatility():
    assert regime_bucket("strong_trend", "high_volatility") == "strong_trend/high_volatility"


def test_regime_bucket_untagged_when_either_half_missing():
    assert regime_bucket(None, "high_volatility") == "untagged"
    assert regime_bucket("strong_trend", None) == "untagged"
    assert regime_bucket(None, None) == "untagged"
    assert regime_bucket("", "high_volatility") == "untagged"


def test_market_regime_bucket_untagged_when_none_or_incomplete():
    assert market_regime_bucket(None) == "untagged"
    assert market_regime_bucket({}) == "untagged"
    assert market_regime_bucket({"trend": "range"}) == "untagged"


def test_market_regime_bucket_composes_from_dict():
    assert (
        market_regime_bucket({"trend": "range", "volatility": "normal_volatility"})
        == "range/normal_volatility"
    )


def test_compute_snapshot_stats_empty_rows():
    stats = compute_snapshot_stats([])
    assert stats == {
        "total": 0,
        "first_captured_at": None,
        "last_captured_at": None,
        "span_days": 0.0,
        "per_bucket": {},
    }


def test_compute_snapshot_stats_single_row_zero_span():
    ts = datetime(2026, 7, 16, tzinfo=timezone.utc)
    stats = compute_snapshot_stats([{"captured_at": ts, "trend": "range", "volatility": "normal_volatility"}])
    assert stats["total"] == 1
    assert stats["first_captured_at"] == ts
    assert stats["last_captured_at"] == ts
    assert stats["span_days"] == 0.0
    assert stats["per_bucket"] == {"range/normal_volatility": 1}


def test_compute_snapshot_stats_span_and_bucket_counts():
    rows = [
        {
            "captured_at": datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc),
            "trend": "range",
            "volatility": "normal_volatility",
        },
        {
            "captured_at": datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc),
            "trend": "range",
            "volatility": "normal_volatility",
        },
        {
            "captured_at": datetime(2026, 7, 12, 0, 0, 0, tzinfo=timezone.utc),
            "trend": "strong_trend",
            "volatility": "high_volatility",
        },
    ]
    stats = compute_snapshot_stats(rows)
    assert stats["total"] == 3
    assert stats["first_captured_at"] == rows[0]["captured_at"]
    assert stats["last_captured_at"] == rows[2]["captured_at"]
    assert stats["span_days"] == pytest.approx(2.0)
    assert stats["per_bucket"] == {"range/normal_volatility": 2, "strong_trend/high_volatility": 1}


def test_compute_shadow_signal_stats_groups_by_strategy_and_bucket():
    rows = [
        {"strategy_name": "jade_v1", "market_regime": {"trend": "range", "volatility": "normal_volatility"}},
        {"strategy_name": "jade_v1", "market_regime": {"trend": "range", "volatility": "normal_volatility"}},
        {"strategy_name": "jade_v1", "market_regime": None},
        {"strategy_name": "legacy", "market_regime": {"trend": "strong_trend", "volatility": "high_volatility"}},
    ]
    stats = compute_shadow_signal_stats(rows)
    assert stats["total"] == 4
    assert stats["counts"] == {
        ("jade_v1", "range/normal_volatility"): 2,
        ("jade_v1", "untagged"): 1,
        ("legacy", "strong_trend/high_volatility"): 1,
    }


def test_compute_shadow_signal_stats_empty():
    stats = compute_shadow_signal_stats([])
    assert stats == {"total": 0, "counts": {}}


def test_routability_report_distance_to_floor_and_at_floor():
    counts = {
        ("jade_v1", "range/normal_volatility"): MIN_TRADES_FOR_CONFIDENCE,
        ("jade_v1", "strong_trend/high_volatility"): 5,
        ("legacy", "untagged"): 0 + 1,  # 1
    }
    report = routability_report(counts)
    rows_by_key = {(r["strategy"], r["bucket"]): r for r in report["rows"]}

    at_floor_row = rows_by_key[("jade_v1", "range/normal_volatility")]
    assert at_floor_row["count"] == MIN_TRADES_FOR_CONFIDENCE
    assert at_floor_row["distance_to_floor"] == 0
    assert at_floor_row["at_floor"] is True

    below_floor_row = rows_by_key[("jade_v1", "strong_trend/high_volatility")]
    assert below_floor_row["count"] == 5
    assert below_floor_row["distance_to_floor"] == MIN_TRADES_FOR_CONFIDENCE - 5
    assert below_floor_row["at_floor"] is False

    far_row = rows_by_key[("legacy", "untagged")]
    assert far_row["count"] == 1
    assert far_row["distance_to_floor"] == MIN_TRADES_FOR_CONFIDENCE - 1
    assert far_row["at_floor"] is False

    assert report["total_pairs"] == 3
    assert report["routable_pairs"] == 1
    assert report["summary"] == (
        f"1 of 3 observed (strategy,bucket) pairs have reached the "
        f"{MIN_TRADES_FOR_CONFIDENCE}-signal floor."
    )


def test_routability_report_custom_floor():
    counts = {("jade_v1", "range/normal_volatility"): 3}
    report = routability_report(counts, floor=3)
    assert report["rows"][0]["at_floor"] is True
    assert report["rows"][0]["distance_to_floor"] == 0
    assert report["routable_pairs"] == 1


def test_routability_report_empty_counts():
    report = routability_report({})
    assert report["rows"] == []
    assert report["routable_pairs"] == 0
    assert report["total_pairs"] == 0
    assert report["summary"] == (
        f"0 of 0 observed (strategy,bucket) pairs have reached the "
        f"{MIN_TRADES_FOR_CONFIDENCE}-signal floor."
    )


def test_render_report_is_ascii_only_and_includes_honesty_note():
    snap_stats = compute_snapshot_stats([])
    signal_stats = compute_shadow_signal_stats([])
    routability = routability_report({})
    report = render_report("some.db", snap_stats, signal_stats, routability)

    # Never raises -- the whole point of ASCII-only output (this project's
    # own cp1252-console lesson, ENGINEERING_DECISIONS.md #54).
    report.encode("ascii")
    assert HONESTY_NOTE in report
    assert "shadow SIGNAL counts are NOT TRADE counts" in report


# --------------------------------------------------------------------
# Full read path: real synthetic rows inserted via the ORM into a real
# migrated temp DB, then read back through scripts/shadow_status.py's
# own read-only sqlite3 fetch functions.
# --------------------------------------------------------------------


def test_fetch_functions_round_trip_real_orm_rows(db_session, sqlite_url):
    from app.database.models import RegimeSnapshot, ShadowSignal

    db_session.add(
        RegimeSnapshot(
            captured_at=datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            timeframe="5m",
            trend="range",
            volatility="normal_volatility",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
            metrics={"adx": 12.3},
        )
    )
    db_session.add(
        ShadowSignal(
            captured_at=datetime(2026, 7, 16, 0, 5, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            strategy_name="jade_v1",
            strategy_version="1.0",
            direction="long",
            entry_price=100.0,
            stop_loss=98.0,
            take_profit=106.0,
            rr=3.0,
            market_regime={"trend": "range", "volatility": "normal_volatility"},
            signal_payload={"htf_bias": "bullish"},
        )
    )
    db_session.add(
        ShadowSignal(
            captured_at=datetime(2026, 7, 16, 0, 6, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            strategy_name="legacy",
            strategy_version=None,
            direction="short",
            entry_price=200.0,
            stop_loss=204.0,
            take_profit=188.0,
            rr=3.0,
            market_regime=None,
            signal_payload=None,
        )
    )
    db_session.commit()

    db_path = _db_path_from_url(sqlite_url)
    conn = shadow_status_script._connect_readonly(db_path)
    try:
        snapshot_rows = shadow_status_script._fetch_snapshot_rows(conn)
        signal_rows = shadow_status_script._fetch_shadow_signal_rows(conn)
    finally:
        conn.close()

    assert len(snapshot_rows) == 1
    assert snapshot_rows[0]["trend"] == "range"
    assert snapshot_rows[0]["volatility"] == "normal_volatility"
    assert isinstance(snapshot_rows[0]["captured_at"], datetime)

    assert len(signal_rows) == 2
    by_strategy = {r["strategy_name"]: r for r in signal_rows}
    assert by_strategy["jade_v1"]["market_regime"] == {
        "trend": "range",
        "volatility": "normal_volatility",
    }
    assert by_strategy["legacy"]["market_regime"] is None

    snap_stats = compute_snapshot_stats(snapshot_rows)
    assert snap_stats["total"] == 1
    assert snap_stats["per_bucket"] == {"range/normal_volatility": 1}

    signal_stats = compute_shadow_signal_stats(signal_rows)
    assert signal_stats["total"] == 2
    assert signal_stats["counts"] == {
        ("jade_v1", "range/normal_volatility"): 1,
        ("legacy", "untagged"): 1,
    }


def test_connect_readonly_never_writes(db_session, sqlite_url):
    """The `mode=ro` URI connection genuinely refuses writes at the SQLite
    engine level -- attempting an INSERT through it raises
    `sqlite3.OperationalError` rather than succeeding or silently locking
    the file."""
    db_path = _db_path_from_url(sqlite_url)
    conn = shadow_status_script._connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO regime_snapshots "
                "(captured_at, symbol, timeframe, trend, volatility, breakout, "
                "mean_reversion, liquidity_sweep_environment) VALUES "
                "('2026-07-16 00:00:00', 'BTCUSDT', '5m', 'range', "
                "'normal_volatility', 0, 0, 0)"
            )
    finally:
        conn.close()


def test_main_end_to_end_against_real_migrated_db(db_session, sqlite_url, monkeypatch, capsys):
    """Full CLI path: real migrated DB (currently empty of shadow rows) ->
    `main()` -> ASCII report printed, exit code 0. Proves the "0 rows,
    tables exist" path renders cleanly (the honest common case for a
    freshly-migrated DB before any paper pass has run)."""
    db_path = _db_path_from_url(sqlite_url)
    monkeypatch.setattr(sys, "argv", ["shadow_status.py", str(db_path)])

    exit_code = shadow_status_script.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    captured.out.encode("ascii")  # never raises
    assert "Shadow Data Accumulation Status" in captured.out
    assert "Total rows: 0" in captured.out
    assert HONESTY_NOTE in captured.out


def test_main_graceful_message_on_missing_tables(tmp_path, monkeypatch, capsys):
    """A fresh, empty sqlite file (pre-Milestone-11, or migrations never
    applied) -- `main()` prints a graceful explanatory message and exits
    0, never a traceback."""
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE unrelated_table (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(sys, "argv", ["shadow_status.py", str(db_path)])

    exit_code = shadow_status_script.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "does not have shadow-observability table" in captured.out
    assert "regime_snapshots" in captured.out
    assert "shadow_signals" in captured.out
    captured.out.encode("ascii")


def test_main_missing_file_reports_error_not_traceback(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(sys, "argv", ["shadow_status.py", str(db_path)])

    exit_code = shadow_status_script.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not exist" in captured.out
