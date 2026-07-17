"""selector_dry_run.py -- what would RollingPerformanceSelector pick, per
regime bucket, against a real database TODAY?

Milestone 16 (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3).
`app.strategy.selector.RollingPerformanceSelector` (Milestone 16) is code +
tests only -- it is NOT wired into `scripts/run_paper.py`, which keeps
running `ConfigurableFallbackSelector` exclusively. This script is the
read-only evidence-audit tool for that not-yet-wired selector: it builds
real evidence via `app.portfolio.rolling_regime_performance.
collect_regime_evidence` against a real DB, then asks
`app.strategy.selector.select_for_bucket` (the module-level delegation seam
`RollingPerformanceSelector.select_with_reason` itself calls once it has
computed a bucket from a real `MarketRegime`) what it would pick for each
of the 9 trend/volatility buckets plus "untagged" -- WITHOUT ever
constructing a `MarketRegime` instance, since a dry-run audit has no live
regime to build, only bucket labels.

STRICTLY READ-ONLY, two layers deep:
  1. This script never places an order, never writes a row, never mutates
     `available` strategy state -- same guarantee `scripts/shadow_status.py`
     and `scripts/analyze_regime_performance.py` already give.
  2. The DB CONNECTION ITSELF is opened via a `mode=ro` URI
     (`sqlite:///file:<path>?mode=ro&uri=true`), same
     `scripts/shadow_status.py` READ-ONLY-AT-THE-ENGINE-LEVEL convention,
     just expressed through SQLAlchemy (`create_engine`) instead of raw
     `sqlite3.connect` -- `collect_regime_evidence` needs a real ORM
     `Session` (it queries `ShadowSignal`/`Trade` model classes via
     `sqlalchemy.select`), which `sqlite3.Row` cursors cannot provide.
     SQLite enforces `mode=ro` at the connection level: any attempted
     write raises `sqlite3.OperationalError: attempt to write a readonly
     database` rather than silently locking or mutating the file (verified
     directly against this project's live `paper_validation.db` while
     building this script). This engine is constructed LOCALLY, bound
     directly to the resolved `--db` path -- it never touches
     `app.database.session`'s module-level `engine`/`SessionLocal` (which
     binds to `settings.DATABASE_URL`, a read/write connection) and never
     imports `app.config.settings` for the DB URL, so nothing about this
     script can accidentally route through the read/write path.

Usage:
    python scripts/selector_dry_run.py                       # default DB
    python scripts/selector_dry_run.py backend/paper_validation.db
    python scripts/selector_dry_run.py path/to/other.db --window-days 30

Expected output on today's live DB (2026-07-16): every bucket reads
"legacy" -- see docs/REGIME_PERFORMANCE_ANALYSIS.md's own conclusion
("evidence-starved": Legacy itself clears the 20-trade floor in at most
one bucket over a 6-month backtest window; the live paper-trading DB is
far younger than that). This script prints its own closing note saying so
plainly rather than leaving a reader to infer it from an all-legacy table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ is a sibling of backend/ -- make the app package importable,
# same convention every other scripts/ entry point (shadow_status.py,
# migrate_paper_db.py, analyze_regime_performance.py, ...) already uses.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

DEFAULT_DB_PATH = REPO_ROOT / "backend" / "paper_validation.db"
DEFAULT_WINDOW_DAYS = 30

# The 9 trend/volatility buckets `app.regime.regime_detector.MarketRegime`
# can ever produce, plus "untagged" (the bucket a `None`/incomplete regime
# classification maps to elsewhere in this project -- see
# `app.portfolio.shadow_status.market_regime_bucket`). Same trend/volatility
# value sets that module's own docstring documents
# (`"strong_trend"|"weak_trend"|"range"` x
# `"high_volatility"|"normal_volatility"|"low_volatility"`) -- duplicated
# here as plain strings (not imported) since this script only needs the
# bucket LABELS, never a real `MarketRegime` instance (see module
# docstring: that is the entire point of the `select_for_bucket` seam).
_TRENDS = ("strong_trend", "weak_trend", "range")
_VOLATILITIES = ("high_volatility", "normal_volatility", "low_volatility")
ALL_BUCKETS = [f"{trend}/{vol}" for trend in _TRENDS for vol in _VOLATILITIES] + ["untagged"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=(
            f"Trailing window (days) passed to collect_regime_evidence "
            f"(default: {DEFAULT_WINDOW_DAYS}, same default that function "
            "itself uses)."
        ),
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help=(
            "Sample-size floor passed to BOTH collect_regime_evidence "
            "(what makes a cell 'sufficient') and RollingPerformanceSelector "
            "(recorded on the baseline-unmeasured fallback_reason). Default: "
            "rolling_regime_performance.MIN_TRADES_FOR_CONFIDENCE (20, this "
            "project's one established evidence floor) -- disclosed, not "
            "tuned."
        ),
    )
    return parser.parse_args(argv)


def _connect_readonly_session(db_path: Path) -> Session:
    """Build a SQLAlchemy `Session` bound to a `mode=ro` URI engine
    constructed LOCALLY from `db_path` -- see module docstring for the full
    read-only rationale. Deliberately does NOT touch
    `app.database.session.engine`/`SessionLocal` (bound to
    `settings.DATABASE_URL`, read/write) or `app.config.settings` at all.
    """
    uri = f"sqlite:///file:{db_path.resolve().as_posix()}?mode=ro&uri=true"
    engine = create_engine(uri, future=True)
    return Session(bind=engine, autoflush=False, autocommit=False, future=True)


def _ensure_unrelated_write_engine_importable() -> None:
    """Root-cause workaround for a real production failure (2026-07-17):
    `collect_regime_evidence` -> `_collect_shadow` LAZILY imports
    `app.portfolio.shadow_resolver` (only for its `RESOLUTION_MODEL`
    constant) -> `app.portfolio.trades` -> `app.database.session`, whose
    MODULE-LEVEL statement `create_engine(settings.DATABASE_URL, ...)`
    raises `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL
    from given URL string` whenever `settings.DATABASE_URL` is unset
    (`app/config.py`'s documented default is `""`) -- reproduced directly
    against this project's real `paper_validation.db` when this script is
    invoked from a shell with no `DATABASE_URL` configured (no
    `backend/.env`, no exported env var).

    This is UNRELATED to this script's own read-only DB connection
    (`_connect_readonly_session` above, which never imports
    `app.config.settings` / `app.database.session` at all, per this
    module's own read-only discipline) -- it is purely a side effect of
    an incidental lazy import three hops deep inside
    `collect_regime_evidence`.

    `create_engine()` itself never opens a connection (SQLAlchemy engines
    are lazy) -- setting a syntactically-valid, self-contained placeholder
    HERE, and ONLY when `DATABASE_URL` is unset, lets that one unrelated
    module-level statement succeed without ever touching a real file and
    without overriding an operator-configured value (an empty string is
    pydantic-settings' documented "not configured" default, never a real
    value an operator deliberately set).

    Copied (not imported) from `scripts/cto_report.py`'s
    `_ensure_unrelated_write_engine_importable` -- same fix, same root
    cause, same lazy-import chain, hit here independently because this
    script calls `collect_regime_evidence` too. Not imported cross-script
    because `cto_report.py` sits conceptually ABOVE this one (its own
    module docstring cites this script's read-only discipline as
    precedent, not the other way around) and pulls in a much heavier
    import surface (`app.portfolio.cto_report`, `app.portfolio.shadow_status`,
    `subprocess`, report composition) that this script's minimal,
    single-purpose, read-only-audit discipline has no other reason to
    depend on.
    """
    from app.config import settings

    if not settings.DATABASE_URL:
        settings.DATABASE_URL = "sqlite://"


def _render_table(rows: list[tuple[str, str, str]]) -> str:
    """`rows`: `(bucket, selected_name, reason)` tuples. Plain ASCII table
    (no non-ASCII glyphs anywhere) -- same Windows cp1252 console lesson
    `app.portfolio.shadow_status`'s own module docstring documents
    (ENGINEERING_DECISIONS.md #54(d)): a default Windows console cannot
    `print()` non-ASCII characters without raising `UnicodeEncodeError`,
    and this tool's whole purpose is to be safely print()-able against a
    live DB.
    """
    header = ("bucket", "selected", "reason")
    col_widths = [
        max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
        for i in range(3)
    ]

    def _fmt_row(cells: tuple[str, str, str]) -> str:
        return " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(cells))

    lines = [_fmt_row(header), "-+-".join("-" * w for w in col_widths)]
    lines.extend(_fmt_row(r) for r in rows)
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path)

    if not db_path.exists():
        print(f"ERROR: {db_path} does not exist.")
        return 1

    from app.portfolio.rolling_regime_performance import (  # noqa: E402
        MIN_TRADES_FOR_CONFIDENCE,
        collect_regime_evidence,
    )
    from app.strategy.selector import select_for_bucket  # noqa: E402
    from app.strategy.strategy_interface import AVAILABLE_STRATEGIES  # noqa: E402

    min_samples = args.min_samples if args.min_samples is not None else MIN_TRADES_FOR_CONFIDENCE

    try:
        session = _connect_readonly_session(db_path)
    except Exception as exc:  # a genuinely unreadable/missing DB is a real failure
        print(f"ERROR: could not open {db_path} read-only: {exc}")
        return 1

    try:
        _ensure_unrelated_write_engine_importable()
        evidence = collect_regime_evidence(
            session, window_days=args.window_days, min_samples=min_samples
        )
    except Exception as exc:
        # Most likely cause: db_path predates the shadow_signals/trades
        # schema this evidence layer queries -- same "graceful report, not
        # a traceback" discipline scripts/shadow_status.py already follows
        # for its own missing-table case.
        print(
            f"ERROR: could not collect regime evidence from {db_path}: {exc}\n"
            "This DB may predate the shadow-observability schema (Milestone "
            "11+) or the rolling-performance evidence layer (Milestone 15). "
            "Run scripts/migrate_paper_db.py against it first."
        )
        return 1
    finally:
        session.close()

    print(f"DB: {db_path}")
    print(f"window_days={args.window_days}  min_samples={min_samples}")
    print(f"Evidence cells observed: {len(evidence)}")
    print()

    rows: list[tuple[str, str, str]] = []
    all_legacy = True
    for bucket in ALL_BUCKETS:
        strategy, selection_reason, fallback_reason = select_for_bucket(
            bucket, evidence, AVAILABLE_STRATEGIES, min_samples
        )
        if strategy.name != "legacy":
            all_legacy = False
        reason = selection_reason if fallback_reason is None else f"{selection_reason} ({fallback_reason})"
        rows.append((bucket, strategy.name, reason))

    print(_render_table(rows))
    print()

    if all_legacy:
        print(
            "NOTE: every bucket selected 'legacy' -- expected on today's live "
            "DB. Per docs/REGIME_PERFORMANCE_ANALYSIS.md, routing is "
            "evidence-starved: even a 6-month backtest window left Legacy "
            "with a sufficient (n>=20) sample in at most one of nine regime "
            "buckets, and the live paper-trading DB has accumulated far less "
            "history than that backtest window. This is the fallback design "
            "working as intended (Hard Rule: legacy fallback is absolute "
            "under missing/insufficient/ambiguous evidence), not a bug in "
            "this script or in RollingPerformanceSelector."
        )
    else:
        print(
            "NOTE: at least one bucket selected a non-legacy strategy on "
            "REAL evidence clearing the sample floor. RollingPerformanceSelector "
            "is still NOT wired into scripts/run_paper.py -- wiring it in is "
            "an explicit, evidence-gated future operator decision, not "
            "something this script does."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
