"""Tests for `scripts/selector_dry_run.py` (the read-only selector
dry-run CLI) -- Milestone 16, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
section 4.3.

`scripts/` is a sibling directory to `backend/`, not a package under it
-- added to `sys.path` explicitly here, same convention
`test_cto_report.py`/`test_shadow_status.py` already established (only
TEST files reach across that boundary, never production `app` code).

Regression: real 2026-07-17 production failure (the same root cause
`test_cto_report.py`'s own `test_cli_renders_rankings_and_shadow_when_
database_url_unset_regression` documents and fixes for `cto_report.py`):
`collect_regime_evidence` -> `_collect_shadow` LAZILY imports
`app.portfolio.shadow_resolver` (for its `RESOLUTION_MODEL` constant) ->
`app.portfolio.trades` -> `app.database.session`, whose MODULE-LEVEL
`create_engine(settings.DATABASE_URL, ...)` raises
`sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from given
URL string` whenever `settings.DATABASE_URL` is unset (`app/config.py`'s
documented default is `""`) -- reproduced directly against this
project's real `paper_validation.db` when `scripts/selector_dry_run.py`
is invoked from a shell with no `DATABASE_URL` configured (no
`backend/.env`, no exported env var). Entirely unrelated to this
script's own read-only `mode=ro` session (`_connect_readonly_session`),
which never imports `app.config.settings`/`app.database.session` at
all. This never surfaces in the rest of this suite because
`fresh_app_env` (via `db_session`/`migrated_db`/`app_main`) always sets
`DATABASE_URL` BEFORE the first import of `app.database.session` in the
pytest process -- the test below deliberately purges that module (and
its lazy import chain) and forces `settings.DATABASE_URL` empty first,
so the exact cold-import, no-env failure mode from the real invocation
is reproduced here rather than masked by fixture ordering.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import selector_dry_run as selector_dry_run_script  # noqa: E402

_LAZY_CHAIN_MODULES = ("app.database.session", "app.portfolio.trades", "app.portfolio.shadow_resolver")


def _db_path_from_url(sqlite_url: str) -> Path:
    assert sqlite_url.startswith("sqlite:///")
    return Path(sqlite_url[len("sqlite:///") :])


def test_ensure_unrelated_write_engine_importable_sets_placeholder_when_unset(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "", raising=False)
    selector_dry_run_script._ensure_unrelated_write_engine_importable()
    assert settings.DATABASE_URL  # non-empty now
    # Must itself be a syntactically valid SQLAlchemy URL (the whole point).
    from sqlalchemy import create_engine

    create_engine(settings.DATABASE_URL, future=True)  # never raises


def test_ensure_unrelated_write_engine_importable_preserves_operator_configured_value(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///some/real/operator/path.db", raising=False)
    selector_dry_run_script._ensure_unrelated_write_engine_importable()
    assert settings.DATABASE_URL == "sqlite:///some/real/operator/path.db"


@pytest.mark.parametrize("argv_style", ["posix", "windows_backslash"])
def test_cli_renders_all_buckets_when_database_url_unset_regression(
    argv_style, db_session, sqlite_url, monkeypatch, capsys
):
    from app.database.models import RegimeSnapshot, ShadowSignal

    now = datetime.now(timezone.utc)
    db_session.add(
        RegimeSnapshot(
            captured_at=now,
            symbol="BTCUSDT",
            timeframe="5m",
            trend="range",
            volatility="normal_volatility",
            breakout=False,
            mean_reversion=False,
            liquidity_sweep_environment=False,
            metrics={"adx": 10.0},
        )
    )
    db_session.add(
        ShadowSignal(
            captured_at=now,
            symbol="BTCUSDT",
            strategy_name="jade",
            strategy_version="1.0",
            direction="long",
            entry_price=100.0,
            stop_loss=98.0,
            take_profit=106.0,
            rr=3.0,
            market_regime={"trend": "range", "volatility": "normal_volatility"},
            signal_payload=None,
            outcome="tp",
            resolved_at=now,
            resolved_r=2.0,
            resolution_model="v2_realistic_fills",  # RESOLUTION_MODEL -- collect_regime_evidence
            # only counts rows resolved under the CURRENT model; a
            # NULL/legacy value here would silently be excluded and this
            # test would fail to observe any evidence regardless of the
            # DATABASE_URL fix under test.
        )
    )
    db_session.commit()

    db_path = _db_path_from_url(sqlite_url)
    # "windows_backslash" proves the failure is NOT about path separator
    # form (as_posix() already normalizes either way) -- it is about
    # DATABASE_URL, isolated below.
    db_path_arg = str(db_path).replace("/", "\\") if argv_style == "windows_backslash" else str(db_path)

    # Reproduce the real failure's precondition: DATABASE_URL unset AND
    # the read-write engine's import chain not yet resolved this
    # process, same as a fresh terminal invocation with no .env/exported
    # env var (`db_session`'s own `fresh_app_env` ancestor fixture would
    # otherwise mask this by having already imported+bound that chain to
    # a valid URL before this test body ever runs).
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "", raising=False)
    for name in _LAZY_CHAIN_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)

    monkeypatch.setattr(sys, "argv", ["selector_dry_run.py", db_path_arg])

    exit_code = selector_dry_run_script.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    captured.out.encode("ascii")  # never raises -- the whole table is ASCII-only

    # Before the fix: "ERROR: could not collect regime evidence ...
    # (Could not parse SQLAlchemy URL from given URL string)". After the
    # fix: real evidence renders and all 10 bucket rows print.
    assert "Could not parse SQLAlchemy URL" not in captured.out
    assert "ERROR" not in captured.out
    assert "Evidence cells observed:" in captured.out
    for bucket in selector_dry_run_script.ALL_BUCKETS:
        assert bucket in captured.out
    assert captured.out.count(" | ") >= len(selector_dry_run_script.ALL_BUCKETS)


def test_cli_missing_db_degrades_gracefully_not_traceback(tmp_path, monkeypatch, capsys):
    """A nonexistent DB path must not crash the script -- it prints a
    graceful ERROR message and returns a nonzero exit code, never an
    unhandled traceback."""
    missing_db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(sys, "argv", ["selector_dry_run.py", str(missing_db)])

    exit_code = selector_dry_run_script.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR" in captured.out
    assert str(missing_db) in captured.out
