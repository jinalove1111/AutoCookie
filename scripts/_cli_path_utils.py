"""_cli_path_utils.py -- shared CLI path-argument normalization.

Milestone 39 (`ENGINEERING_DECISIONS.md` #77): found via a real CI
failure, not speculation -- `scripts/cto_report.py` and
`scripts/selector_dry_run.py` both had their own `windows_backslash`
regression test pass on every LOCAL Windows reproduction (three
separate ones, across three milestones) but fail on the actual Linux CI
runner. Root cause: `pathlib.Path(raw)` only treats `\\` as a path
separator when the process itself is running on Windows (`WindowsPath`
vs `PosixPath`) -- a Windows-style backslash-separated path string
handed to a script running on Linux/macOS silently resolves to the
WRONG, nonexistent path instead of raising, which then degrades
whatever DB-dependent section reads it to an "unavailable" placeholder
rather than a loud error.

A grep across `scripts/` for the same `db_path = Path(args.db_path)`
pattern found FIVE call sites sharing this exact bug (`cto_report.py`,
`selector_dry_run.py`, `shadow_status.py`, `migrate_paper_db.py`,
`paper_trader_health_check.py`) -- fixed once here and imported by all
five, instead of five separate copies of the same normalization logic.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


def normalize_db_path_arg(raw: str) -> Path:
    """Convert a CLI-supplied DB path string into a `Path` that resolves
    correctly regardless of which OS actually runs this process.

    Only triggers when `raw` contains `\\` and no `/` at all (a path
    already using `/` is never touched, so a genuine POSIX path is
    never misinterpreted) -- uses `PureWindowsPath` to correctly parse
    backslash-separated segments (including a drive letter like `C:\\`)
    regardless of the runtime OS, then converts to a `/`-form string
    every platform's `Path()` parses identically.
    """
    if "\\" in raw and "/" not in raw:
        return Path(PureWindowsPath(raw).as_posix())
    return Path(raw)
