"""migrate_paper_db.py -- bring an existing (possibly never-alembic-stamped)
SQLite database up to the current migration head.

Adaptive platform milestone 8.1 (operator directive 2026-07-16,
ENGINEERING_DECISIONS.md #51). Thin CLI over
`app.database.migrate_existing` -- see that module's docstring for why
this exists (the live paper-trading DB predates alembic stamping, and
`run_paper.py` never runs migrations, so a paper-trader restart on
current code would crash on its first trade INSERT until the DB is
migrated).

Usage:
    # Detect only (no mutation) -- always safe:
    python scripts/migrate_paper_db.py backend/paper_validation.db

    # Apply (backs the file up first, then stamp + upgrade + verify):
    python scripts/migrate_paper_db.py backend/paper_validation.db --apply

Safe against a DB an older-code paper-trading process currently has open:
every migration between the supported baselines and head is purely
additive (ADD COLUMN / CREATE TABLE), SQLite locks are per-statement and
brief, and the paper trader's own DB reads are best-effort
(WARN-and-default). Never touches, signals, or restarts any process.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _cli_path_utils import normalize_path_arg

# scripts/ is a sibling of backend/ -- make the app package importable,
# same convention as the other scripts/ entry points.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database.migrate_existing import detect_schema_generation, migrate_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", help="Path to the SQLite database file")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually migrate (default: detect and report only, no mutation)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the pre-migration file backup (not recommended)",
    )
    args = parser.parse_args()

    db_path = normalize_path_arg(args.db_path)
    if not db_path.exists():
        print(f"ERROR: {db_path} does not exist")
        return 1

    detected = detect_schema_generation(db_path)
    if detected is None:
        print(f"ERROR: {db_path} does not match any known schema generation; refusing.")
        return 1
    if detected == "stamped":
        print(f"{db_path}: already alembic-stamped; --apply would run a plain 'upgrade head'.")
    else:
        print(f"{db_path}: un-stamped, schema matches generation {detected}.")

    if not args.apply:
        print("Detection only (pass --apply to migrate).")
        return 0

    report = migrate_database(db_path, backup=not args.no_backup)
    print(f"Backed up to: {report['backup_path']}")
    print(f"Stamped baseline: {report['detected']}")
    print(f"Now at head: {report['head']}")
    print(f"Tables: {', '.join(report['tables'])}")
    print("Verification passed (snapshot table + adaptive-platform trade columns present).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
