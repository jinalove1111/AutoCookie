"""paper_trader_health_check.py -- is the live paper-trading process
actually healthy right now?

Milestone 37 (Priority 3, "Monitoring and recovery"): a genuine gap this
milestone found while restarting the paper trader -- `scripts/shadow_status.py`
already answers "how close is shadow-signal evidence accumulation to the
future RollingPerformanceSelector's floor?" but nothing answers the more
basic operational question "is the process alive, current, and in a sane
state?" This script is that missing read-only check. It does NOT restart,
stop, or otherwise control the live process -- see the module-level
recommendation at the bottom of this docstring for why that's
deliberately out of scope here.

STRICTLY READ-ONLY, same `mode=ro` SQLite URI pattern as
`scripts/shadow_status.py` -- safe to run against
`backend/paper_validation.db` while the live paper trader has it open.

Checks, in order:
  1. Circuit breaker state (`bot_state.circuit_breaker_tripped`) -- a
     tripped breaker is not itself unhealthy (it may be doing exactly its
     job), but it must never go unnoticed.
  2. Freshness of the most recent `regime_snapshots` row vs. the
     configured `--expected-interval-seconds` (default 300, matching this
     project's standing `--interval-seconds 300` paper-trader launch
     convention, `[[paper-trader-launch]]` memory) -- a process that has
     silently died leaves this table stale forever.
  3. Open-position count (`trades` where `status='open'`) -- anything
     other than 0 or 1 is a genuine anomaly given the documented
     one-trade-open-at-a-time invariant (`scripts/run_paper.py`'s
     concurrency guard; verified intact in
     `scripts/verify_signal_to_fill.py`'s Phase 2 check).

Recommendation, not implemented here: an auto-restart-on-crash daemon is
explicitly NOT built by this script. Restarting the live paper-trading
process is a decision with real operational consequences (e.g., silently
resuming after a circuit-breaker trip that tripped for a good reason) --
this project's own gated-file discipline already treats any change to
`scripts/run_paper.py`'s running state as needing explicit visibility,
not silent automation. This script's job is DETECTION; RECOVERY stays a
human-in-the-loop decision informed by what this script reports.

Milestone 38 (Priority 2, "Improve monitoring, logging, and failure
detection"): added `--watch` mode. Still strictly read-only against the
trading DB; the only new write is an append-only local alert log
(`--alert-log`, default `scripts/reports/paper_trader_health_alerts.log`)
that records a line only on a HEALTHY<->UNHEALTHY *transition*, plus a
periodic heartbeat every `--heartbeat-every` checks -- not a line per
poll, which would make the real signal (something changed) impossible
to spot in the noise. This still does not restart or control the live
process; same detection-only boundary as the rest of this script.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_DB_PATH = REPO_ROOT / "backend" / "paper_validation.db"
DEFAULT_EXPECTED_INTERVAL_SECONDS = 300
DEFAULT_ALERT_LOG_PATH = SCRIPT_DIR / "reports" / "paper_trader_health_alerts.log"
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_HEARTBEAT_EVERY = 30


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--expected-interval-seconds",
        type=int,
        default=DEFAULT_EXPECTED_INTERVAL_SECONDS,
        help=(
            "Expected seconds between paper-trader passes (default: "
            f"{DEFAULT_EXPECTED_INTERVAL_SECONDS}, matching this project's "
            "standing --interval-seconds 300 launch convention). Staleness "
            "beyond 3x this value is flagged."
        ),
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Loop indefinitely (or --max-checks times), polling every "
            "--poll-interval-seconds and appending to --alert-log only on "
            "a HEALTHY<->UNHEALTHY transition or heartbeat, instead of a "
            "single one-shot check."
        ),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help=f"Seconds between polls in --watch mode (default: {DEFAULT_POLL_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--heartbeat-every",
        type=int,
        default=DEFAULT_HEARTBEAT_EVERY,
        help=(
            "Write a heartbeat line to --alert-log every N checks in "
            f"--watch mode even with no status change (default: {DEFAULT_HEARTBEAT_EVERY})."
        ),
    )
    parser.add_argument(
        "--max-checks",
        type=int,
        default=0,
        help="In --watch mode, stop after N checks (default: 0, meaning unbounded).",
    )
    parser.add_argument(
        "--alert-log",
        default=str(DEFAULT_ALERT_LOG_PATH),
        help=f"Append-only log path for --watch mode (default: {DEFAULT_ALERT_LOG_PATH}).",
    )
    return parser.parse_args(argv)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Same `mode=ro` URI safety pattern as `scripts/shadow_status.py` --
    SQLite refuses any write on the resulting connection at the engine
    level; raises `sqlite3.OperationalError` if the file does not exist."""
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a `DateTime(timezone=True)` column's raw SQLite text back into
    a naive-or-aware `datetime`. Mirrors `shadow_status._parse_captured_at`
    -- never raises, returns None for unparseable/missing values."""
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


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to UTC-aware, same fix
    Milestone 34 applied in `scripts/run_paper.py` for the identical
    SQLite round-trip tz-loss issue -- this script reads the same columns
    and would hit the same TypeError on a naive-vs-aware subtraction
    without it."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def check_circuit_breaker(conn: sqlite3.Connection) -> dict:
    cursor = conn.execute(
        "SELECT circuit_breaker_tripped, circuit_breaker_reason, "
        "circuit_breaker_tripped_at FROM bot_state LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return {"status": "NO_BOT_STATE_ROW", "tripped": None, "reason": None}
    return {
        "status": "TRIPPED" if row["circuit_breaker_tripped"] else "OK",
        "tripped": bool(row["circuit_breaker_tripped"]),
        "reason": row["circuit_breaker_reason"],
        "tripped_at": row["circuit_breaker_tripped_at"],
    }


def check_freshness(conn: sqlite3.Connection, expected_interval_seconds: int) -> dict:
    cursor = conn.execute("SELECT MAX(captured_at) AS latest FROM regime_snapshots")
    row = cursor.fetchone()
    latest = _as_utc(_parse_timestamp(row["latest"] if row else None))
    if latest is None:
        return {"status": "NO_SNAPSHOTS_YET", "latest": None, "staleness_seconds": None}

    now = datetime.now(timezone.utc)
    staleness_seconds = (now - latest).total_seconds()
    stale_threshold = expected_interval_seconds * 3
    status = "STALE" if staleness_seconds > stale_threshold else "FRESH"
    return {
        "status": status,
        "latest": latest.isoformat(),
        "staleness_seconds": round(staleness_seconds, 1),
        "stale_threshold_seconds": stale_threshold,
    }


def check_open_positions(conn: sqlite3.Connection) -> dict:
    cursor = conn.execute("SELECT id, symbol, direction, opened_at FROM trades WHERE status='open'")
    open_trades = [dict(r) for r in cursor.fetchall()]
    n = len(open_trades)
    if n <= 1:
        status = "OK"
    else:
        status = "ANOMALY_MULTIPLE_OPEN_POSITIONS"
    return {"status": status, "count": n, "open_trades": open_trades}


def run_single_check(db_path: Path, expected_interval_seconds: int) -> tuple[bool, dict]:
    """Run one full check against `db_path`. Returns (unhealthy, results).
    Raises `sqlite3.OperationalError` if the DB can't be opened read-only
    -- callers decide how to report that (a one-shot exit vs. a --watch
    loop that should keep retrying, not crash on a transient open race
    with the live writer)."""
    conn = _connect_readonly(db_path)
    try:
        breaker = check_circuit_breaker(conn)
        freshness = check_freshness(conn, expected_interval_seconds)
        positions = check_open_positions(conn)
    finally:
        conn.close()

    unhealthy = (
        breaker["status"] == "TRIPPED"
        or freshness["status"] in ("STALE", "NO_SNAPSHOTS_YET")
        or positions["status"] != "OK"
    )
    return unhealthy, {"breaker": breaker, "freshness": freshness, "positions": positions}


def _print_report(db_path: Path, results: dict, unhealthy: bool) -> None:
    breaker = results["breaker"]
    freshness = results["freshness"]
    positions = results["positions"]
    print(f"Paper trader health check -- {db_path}")
    print(f"  Circuit breaker : {breaker['status']}"
          + (f" (reason={breaker['reason']!r}, tripped_at={breaker['tripped_at']})"
             if breaker["tripped"] else ""))
    print(f"  Snapshot freshness: {freshness['status']}"
          + (f" (latest={freshness['latest']}, staleness={freshness['staleness_seconds']}s,"
             f" threshold={freshness['stale_threshold_seconds']}s)"
             if freshness["status"] != "NO_SNAPSHOTS_YET" else ""))
    print(f"  Open positions  : {positions['status']} (count={positions['count']})")
    for t in positions["open_trades"]:
        print(f"    - id={t['id']} {t['symbol']} {t['direction']} opened_at={t['opened_at']}")
    print(f"\nOverall: {'UNHEALTHY' if unhealthy else 'HEALTHY'}")


def _summarize(results: dict) -> str:
    return (
        f"breaker={results['breaker']['status']} "
        f"freshness={results['freshness']['status']} "
        f"positions={results['positions']['status']}(count={results['positions']['count']})"
    )


def _append_alert_log(alert_log_path: Path, line: str) -> None:
    alert_log_path.parent.mkdir(parents=True, exist_ok=True)
    with alert_log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_watch(
    db_path: Path,
    expected_interval_seconds: int,
    poll_interval_seconds: int,
    heartbeat_every: int,
    max_checks: int,
    alert_log_path: Path,
) -> int:
    """Poll indefinitely (or `max_checks` times), logging to
    `alert_log_path` only on a HEALTHY<->UNHEALTHY transition or every
    `heartbeat_every` checks -- one line per state CHANGE, not per poll,
    so the log stays a genuine signal instead of noise. Never restarts
    or otherwise controls the live paper-trading process (detection
    only, see module docstring)."""
    previous_unhealthy: bool | None = None
    checks_done = 0
    print(
        f"Watching {db_path} every {poll_interval_seconds}s "
        f"(alert log: {alert_log_path}). Ctrl+C to stop."
    )
    try:
        while max_checks == 0 or checks_done < max_checks:
            now = datetime.now(timezone.utc).isoformat()
            try:
                unhealthy, results = run_single_check(db_path, expected_interval_seconds)
                summary = _summarize(results)
            except sqlite3.OperationalError as exc:
                unhealthy, summary = True, f"DB_OPEN_FAILED: {exc}"

            checks_done += 1
            transitioned = previous_unhealthy is not None and unhealthy != previous_unhealthy
            is_heartbeat = heartbeat_every > 0 and checks_done % heartbeat_every == 0

            if transitioned:
                direction = "HEALTHY -> UNHEALTHY" if unhealthy else "UNHEALTHY -> HEALTHY"
                _append_alert_log(alert_log_path, f"{now} TRANSITION {direction} :: {summary}")
                print(f"{now} TRANSITION {direction} :: {summary}")
            elif is_heartbeat:
                state = "UNHEALTHY" if unhealthy else "HEALTHY"
                _append_alert_log(alert_log_path, f"{now} HEARTBEAT {state} :: {summary}")
                print(f"{now} HEARTBEAT {state} :: {summary}")

            previous_unhealthy = unhealthy
            if max_checks == 0 or checks_done < max_checks:
                time.sleep(poll_interval_seconds)
    except KeyboardInterrupt:
        print(f"\nStopped after {checks_done} check(s).")
        return 0

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db_path)

    if args.watch:
        return run_watch(
            db_path,
            args.expected_interval_seconds,
            args.poll_interval_seconds,
            args.heartbeat_every,
            args.max_checks,
            Path(args.alert_log),
        )

    try:
        unhealthy, results = run_single_check(db_path, args.expected_interval_seconds)
    except sqlite3.OperationalError as exc:
        print(f"REFUSING/FAILED TO OPEN {db_path} read-only: {exc}")
        return 1

    _print_report(db_path, results, unhealthy)
    return 1 if unhealthy else 0


if __name__ == "__main__":
    sys.exit(main())
