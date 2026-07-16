"""shadow_status.py -- how close is the shadow-mode data accumulation to
the future RollingPerformanceSelector's evidence floor?

Milestone 13 (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3).
`ENABLE_SHADOW_STRATEGY_SIGNALS` (milestone 11/11b) is now live in the
paper trader: `regime_snapshots` gains roughly one row per pass and
`shadow_signals` gains a row whenever a non-active registered strategy
would have signaled. The future `RollingPerformanceSelector` needs
`>= 20` shadow signals per (strategy, regime bucket) before any bucket is
routable (`app.portfolio.shadow_status.MIN_TRADES_FOR_CONFIDENCE`) -- this
script answers "how close are we?" in one command, straight from real
rows in the target DB.

STRICTLY READ-ONLY: connects via `sqlite3.connect(..., uri=True)` with a
`mode=ro` URI, which SQLite itself enforces at the connection level (any
attempted write on a `mode=ro` connection raises `sqlite3.OperationalError:
attempt to write a readonly database` rather than silently locking or
mutating the file) -- safe to run against `backend/paper_validation.db`
while the live paper trader has it open, same "purely additive migrations,
brief per-statement locks" safety reasoning `migrate_paper_db.py`'s
docstring already established for read/write access to that file, made
airtight here by never issuing a write statement at all.

Usage:
    python scripts/shadow_status.py                       # default DB
    python scripts/shadow_status.py backend/paper_validation.db
    python scripts/shadow_status.py path/to/other.db

All arithmetic is computed by `app.portfolio.shadow_status`'s pure helper
functions from rows fetched here -- this script's own job is strictly
I/O: connect read-only, fetch, decode JSON columns, call the pure
helpers, print. ASCII-only output throughout (this project's own
established Windows-console lesson, ENGINEERING_DECISIONS.md #54(d) --
see `app.portfolio.shadow_status`'s module docstring).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# scripts/ is a sibling of backend/ -- make the app package importable,
# same convention every other scripts/ entry point (migrate_paper_db.py,
# analyze_regime_performance.py, ...) already uses.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.portfolio.shadow_status import (  # noqa: E402
    compute_shadow_signal_stats,
    compute_snapshot_stats,
    render_report,
    routability_report,
)

DEFAULT_DB_PATH = REPO_ROOT / "backend" / "paper_validation.db"

_REQUIRED_TABLES = ("regime_snapshots", "shadow_signals")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    return parser.parse_args(argv)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open `db_path` via a `mode=ro` URI -- SQLite refuses any write on
    the resulting connection at the engine level (see module docstring).
    Raises `sqlite3.OperationalError` if the file does not exist (a
    `mode=ro` connection, unlike a normal one, never creates a missing
    file) or cannot be opened -- callers handle that as a graceful error,
    not a traceback.
    """
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cursor.fetchone() is not None


def _parse_captured_at(value: str | None) -> datetime | None:
    """Parse a `DateTime(timezone=True)` column's raw SQLite text back
    into a `datetime` for span/min/max arithmetic. `datetime.fromisoformat`
    handles this project's actual stored format (`"YYYY-MM-DD HH:MM:SS"`,
    optionally with a fractional-seconds suffix) directly on the Python
    version this repo runs; the two explicit `strptime` fallbacks below
    are defensive only, for an older-Python or slightly different-format
    reader of this same file. Returns `None` (never raises) for a `None`
    or genuinely unparseable value -- a single bad timestamp must not
    crash the whole report.
    """
    if value is None:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fetch_snapshot_rows(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("SELECT captured_at, trend, volatility FROM regime_snapshots")
    return [
        {
            "captured_at": _parse_captured_at(row["captured_at"]),
            "trend": row["trend"],
            "volatility": row["volatility"],
        }
        for row in cursor.fetchall()
    ]


def _fetch_shadow_signal_rows(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute("SELECT strategy_name, market_regime FROM shadow_signals")
    rows = []
    for row in cursor.fetchall():
        raw_regime = row["market_regime"]
        regime = json.loads(raw_regime) if raw_regime else None
        rows.append({"strategy_name": row["strategy_name"], "market_regime": regime})
    return rows


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path)

    if not db_path.exists():
        print(f"ERROR: {db_path} does not exist.")
        return 1

    try:
        conn = _connect_readonly(db_path)
    except sqlite3.OperationalError as exc:
        print(f"ERROR: could not open {db_path} read-only: {exc}")
        return 1

    try:
        missing = [t for t in _REQUIRED_TABLES if not _table_exists(conn, t)]
        if missing:
            print(
                f"{db_path} does not have shadow-observability table(s) "
                f"{', '.join(missing)} yet -- this DB predates Milestone 11 "
                "(or migrations haven't been applied). Run "
                "scripts/migrate_paper_db.py against it first. Nothing to "
                "report."
            )
            return 0

        snapshot_rows = _fetch_snapshot_rows(conn)
        signal_rows = _fetch_shadow_signal_rows(conn)
    finally:
        conn.close()

    snap_stats = compute_snapshot_stats(snapshot_rows)
    signal_stats = compute_shadow_signal_stats(signal_rows)
    routability = routability_report(signal_stats["counts"])

    report = render_report(str(db_path), snap_stats, signal_stats, routability)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
