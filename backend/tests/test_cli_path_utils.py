"""Tests for scripts/_cli_path_utils.py (Milestone 39,
`ENGINEERING_DECISIONS.md` #77, extended Milestone 40).

Real CI failure, not speculation: `scripts/cto_report.py` and
`scripts/selector_dry_run.py` each had their own `windows_backslash`
regression test pass on every LOCAL Windows reproduction (three
separate ones, across three prior milestones) but fail on the actual
Linux CI runner, because `pathlib.Path(raw)` only treats a backslash as
a path separator when the process itself runs on Windows. A grep across
`scripts/` for the same pattern found it applied to both DB-read paths
(`db_path = Path(args.db_path)`) and write-target paths
(`Path(args.output)`/`Path(args.alert_log)`) across more than ten call
sites total -- fixed once in `scripts/_cli_path_utils.normalize_path_arg`
and imported everywhere instead of duplicating the same logic. These
tests check the string transformation directly so the behavior is
verified without depending on which OS actually runs pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _cli_path_utils import normalize_path_arg  # noqa: E402


def test_converts_windows_backslash_path_with_drive_letter_to_posix_form():
    result = normalize_path_arg("C:\\Users\\test\\paper_validation.db")
    assert result == Path("C:/Users/test/paper_validation.db")


def test_converts_relative_backslash_path():
    result = normalize_path_arg("backend\\paper_validation.db")
    assert result == Path("backend/paper_validation.db")


def test_leaves_forward_slash_path_untouched():
    result = normalize_path_arg("backend/paper_validation.db")
    assert result == Path("backend/paper_validation.db")


def test_leaves_plain_filename_untouched():
    result = normalize_path_arg("paper_validation.db")
    assert result == Path("paper_validation.db")


def test_mixed_separators_left_untouched_not_misinterpreted():
    """A path already containing `/` is never touched, even if it also
    contains a `\\` -- avoids misinterpreting a genuine (if unusual)
    POSIX path that happens to contain a literal backslash character."""
    result = normalize_path_arg("some/dir\\odd_name.db")
    assert result == Path("some/dir\\odd_name.db")
