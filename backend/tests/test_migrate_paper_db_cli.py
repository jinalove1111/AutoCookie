"""Tests for `scripts/migrate_paper_db.py`'s CLI (`main()`) -- Milestone
39 gap fill (`ENGINEERING_DECISIONS.md` #77's cross-script path-argument
fix touched this script but it had no dedicated test file at all before
this one). The underlying migration logic
(`app.database.migrate_existing.detect_schema_generation`/
`migrate_database`) already has its own thorough coverage in
`test_migrate_existing.py` -- this file only covers the thin CLI layer
on top: argument parsing, the missing/unrecognized-file error paths,
detect-only vs `--apply`, and the `normalize_db_path_arg` integration
(same `windows_backslash` regression pattern
`test_cto_report.py`/`test_selector_dry_run.py` already established).

`scripts/` is a sibling directory to `backend/`, not a package under it
-- added to `sys.path` explicitly, same convention every other
`scripts/`-reaching test file in this suite already uses.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import migrate_paper_db as migrate_paper_db_script  # noqa: E402

from app.database.migrate_existing import build_alembic_config  # noqa: E402


def _make_unstamped_db_at(tmp_path, revision: str) -> Path:
    """Same real-migration-chain fixture pattern `test_migrate_existing.py`
    uses -- a real schema at `revision`, alembic_version hidden via RENAME
    to simulate the live paper DB's actual pre-alembic-stamped condition."""
    db_path = tmp_path / "legacy.db"
    cfg = build_alembic_config(db_path)
    command.upgrade(cfg, revision)
    conn = sqlite3.connect(str(db_path))
    conn.execute("ALTER TABLE alembic_version RENAME TO not_a_stamp_fixture")
    conn.commit()
    conn.close()
    return db_path


def test_missing_db_file_errors_without_traceback(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(sys, "argv", ["migrate_paper_db.py", str(missing)])
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not exist" in captured.out


def test_unrecognized_db_refuses_without_mutating(tmp_path, monkeypatch, capsys):
    not_ours = tmp_path / "not_ours.db"
    conn = sqlite3.connect(str(not_ours))
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(sys, "argv", ["migrate_paper_db.py", str(not_ours)])
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "does not match any known schema generation" in captured.out


def test_detect_only_mode_reports_and_does_not_mutate(tmp_path, monkeypatch, capsys):
    db_path = _make_unstamped_db_at(tmp_path, "a0f5ebc23690")
    mtime_before = db_path.stat().st_mtime

    monkeypatch.setattr(sys, "argv", ["migrate_paper_db.py", str(db_path)])
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Detection only (pass --apply to migrate)." in captured.out
    assert db_path.stat().st_mtime == mtime_before  # untouched


def test_apply_mode_migrates_to_head_and_backs_up(tmp_path, monkeypatch, capsys):
    db_path = _make_unstamped_db_at(tmp_path, "a0f5ebc23690")

    monkeypatch.setattr(sys, "argv", ["migrate_paper_db.py", str(db_path), "--apply"])
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Now at head:" in captured.out
    assert "Backed up to:" in captured.out
    backups = list(tmp_path.glob("legacy.db.backup-*"))
    assert len(backups) == 1


def test_apply_mode_with_no_backup_flag_skips_backup(tmp_path, monkeypatch, capsys):
    db_path = _make_unstamped_db_at(tmp_path, "a0f5ebc23690")

    monkeypatch.setattr(
        sys, "argv", ["migrate_paper_db.py", str(db_path), "--apply", "--no-backup"]
    )
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    backups = list(tmp_path.glob("legacy.db.backup-*"))
    assert len(backups) == 0


def test_windows_backslash_path_regression(tmp_path, monkeypatch, capsys):
    """Same class of bug `ENGINEERING_DECISIONS.md` #77 root-caused in
    `cto_report.py`/`selector_dry_run.py` -- confirms this script's own
    `normalize_db_path_arg` integration works end-to-end, not just the
    shared helper in isolation."""
    db_path = _make_unstamped_db_at(tmp_path, "a0f5ebc23690")
    backslash_arg = str(db_path).replace("/", "\\")

    monkeypatch.setattr(sys, "argv", ["migrate_paper_db.py", backslash_arg])
    exit_code = migrate_paper_db_script.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "does not exist" not in captured.out
    assert "Detection only (pass --apply to migrate)." in captured.out
