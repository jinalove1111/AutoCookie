"""cto_report.py -- daily CTO report generator (Milestone 17b, 2026-07-16,
standing operator directive: every morning produce a report covering (1)
what was completed, (2) current bottleneck, (3) remaining risks, (4)
evidence accumulated, (5) strategy rankings, (6) shadow performance, (7)
suggested next milestone, (8) estimated platform completion %.

Thin I/O layer only -- every number/table is either computed by a pure
helper this project already has (`app.portfolio.shadow_status`,
`app.portfolio.rolling_regime_performance.collect_regime_evidence`,
`app.strategy.selector.select_for_bucket`) or by this module's own
sibling, `app.portfolio.cto_report` (report composition + strategy
rankings + completion-percent arithmetic). This script's own job is
strictly: connect read-only, run read-only subprocess checks, read
docs, call the pure helpers, compose, write, print.

STRICTLY READ-ONLY, same discipline as `scripts/shadow_status.py` and
`scripts/selector_dry_run.py`: every DB connection this module opens
uses a `mode=ro` SQLite URI (SQLite enforces this at the ENGINE level --
any attempted write raises `sqlite3.OperationalError` rather than
silently locking or mutating the file), and no `app.config.settings` /
`app.database.session` read-write engine is ever imported or touched.
The one subprocess check that inspects running processes
(`_check_paper_trader_running`) only ever reads process state (`Get-
CimInstance`/`tasklist`), never signals, kills, or restarts anything.

Honesty discipline (every gathering step below): each of the 8 report
inputs is collected in its OWN `try`/`except`, independent of every
other -- a git failure, a missing DB table, an unreadable doc, or a
process-inspection failure on this machine degrades ONLY that section
to an explicit `"unavailable: <reason>"` string, never crashes the
whole report and never silently fabricates a number in its place. This
mirrors `scripts/selector_dry_run.py`'s own "graceful report, not a
traceback" discipline, applied to every gathering step instead of just
one DB-open call.

Usage:
    python scripts/cto_report.py                              # default DB, default output path
    python scripts/cto_report.py backend/paper_validation.db
    python scripts/cto_report.py path/to/other.db --output out.md --since "48 hours ago"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _cli_path_utils import normalize_db_path_arg

# scripts/ is a sibling of backend/ -- make the app package importable,
# same convention every other scripts/ entry point (shadow_status.py,
# selector_dry_run.py, migrate_paper_db.py, ...) already uses. Also add
# scripts/ itself to sys.path so `import shadow_status` (this module's
# own sibling, reused for its read-only fetch helpers rather than
# reimplementing them) resolves regardless of how this script was
# invoked/imported.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import shadow_status  # noqa: E402 -- sibling script, reused read-only fetch helpers

from app.portfolio.cto_report import (  # noqa: E402
    compose_report,
    completion_estimate,
    render_strategy_rankings,
    summarize_strategy_rankings,
)
from app.portfolio.shadow_status import (  # noqa: E402
    MIN_TRADES_FOR_CONFIDENCE,
    compute_shadow_signal_stats,
    compute_snapshot_stats,
    routability_report,
)

DEFAULT_DB_PATH = REPO_ROOT / "backend" / "paper_validation.db"
DEFAULT_SINCE = "24 hours ago"
DEFAULT_WINDOW_DAYS = 30
REPORTS_DIR = SCRIPT_DIR / "reports"

# The 9 trend/volatility buckets `app.regime.regime_detector.MarketRegime`
# can ever produce, plus "untagged" -- same set `scripts/selector_dry_run.py`
# already establishes (duplicated here as plain strings for the same
# reason that module documents: a dry-run/report audit has no live
# regime to build, only bucket labels).
_TRENDS = ("strong_trend", "weak_trend", "range")
_VOLATILITIES = ("high_volatility", "normal_volatility", "low_volatility")
ALL_BUCKETS = [f"{trend}/{vol}" for trend in _TRENDS for vol in _VOLATILITIES] + ["untagged"]

# Disclosed, mechanical bottleneck rule (see `_gather_bottleneck` below):
# fewer than this many sufficient (strategy, bucket, source) evidence
# cells anywhere in the DB means NO challenger can yet be judged against
# legacy in ANY bucket -- the bottleneck is data volume, not a decision.
# `1`, not a larger guessed number: even ONE sufficient cell existing
# somewhere would mean the evidence chain has produced its first
# judgeable comparison, at which point the next real constraint is the
# evidence REVIEW + WIRING decision, not more raw data volume.
BOTTLENECK_SUFFICIENT_CELL_FLOOR = 1

ROADMAP_NEXT_MILESTONE_MARKER = "**What remains is data and a decision, not more building.**"
ARCHITECTURE_MILESTONE_TABLE_HEADER_HINTS = ("Milestone", "Status")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output .md path (default: "
            "scripts/reports/cto_report_<YYYYMMDD>.md, UTC date)"
        ),
    )
    parser.add_argument(
        "--since",
        default=DEFAULT_SINCE,
        help=f"git log --since window for the 'completed work' section (default: {DEFAULT_SINCE!r})",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"Trailing window (days) passed to collect_regime_evidence (default: {DEFAULT_WINDOW_DAYS})",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------
# (a) completed work
# --------------------------------------------------------------------


def _gather_completed_work(since: str) -> str:
    try:
        # Explicit UTF-8 decode (not `text=True`, which decodes with the
        # platform locale encoding -- cp1252 on this project's Windows
        # environment): commit messages in this repo use non-ASCII
        # punctuation (em dashes), and cp1252-decoding UTF-8 bytes
        # produces mojibake BEFORE `ascii_safe` ever sees the real
        # character, so its glyph-to-ASCII table (e.g. em dash -> "--")
        # never matches and the output degrades to raw "?" replacement
        # chars instead of a clean substitution. `errors="replace"`
        # still guarantees this never raises even on a genuinely
        # undecodable byte sequence.
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "--oneline", f"--since={since}"],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except Exception as exc:  # git missing, not a repo, timeout, etc.
        return f"unavailable: git log failed ({exc})"

    out = result.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return f"(no commits in the last window: --since={since!r})"
    return out


# --------------------------------------------------------------------
# (b) evidence accumulated -- shadow_status pure helpers over the
# read-only DB (regime_snapshots + shadow_signals)
# --------------------------------------------------------------------


def _gather_evidence(db_path: Path) -> str:
    try:
        conn = shadow_status._connect_readonly(db_path)
    except Exception as exc:
        return f"unavailable: could not open {db_path} read-only ({exc})"

    try:
        missing = [t for t in shadow_status._REQUIRED_TABLES if not shadow_status._table_exists(conn, t)]
        if missing:
            return (
                f"unavailable: {db_path} is missing shadow-observability table(s) "
                f"{', '.join(missing)} (predates Milestone 11, or migrations not "
                "applied -- run scripts/migrate_paper_db.py against it first)"
            )
        snapshot_rows = shadow_status._fetch_snapshot_rows(conn)
        signal_rows = shadow_status._fetch_shadow_signal_rows(conn)
    except Exception as exc:
        return f"unavailable: {exc}"
    finally:
        conn.close()

    snap_stats = compute_snapshot_stats(snapshot_rows)
    signal_stats = compute_shadow_signal_stats(signal_rows)
    routability = routability_report(signal_stats["counts"])

    lines = [
        f"Regime snapshots: {snap_stats['total']} rows, span "
        f"{snap_stats['span_days']:.2f} days, {len(snap_stats['per_bucket'])} "
        "bucket(s) observed.",
        f"Shadow signals: {signal_stats['total']} rows.",
        routability["summary"],
        f"(floor = {MIN_TRADES_FOR_CONFIDENCE} shadow signals per strategy/bucket "
        "pair; signal counts are necessary, not sufficient, for routability -- "
        "see app.portfolio.shadow_status.HONESTY_NOTE)",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------
# (c) shadow performance + strategy rankings -- collect_regime_evidence
# over a read-only ORM session
# --------------------------------------------------------------------


def _connect_readonly_session(db_path: Path):
    """Same `mode=ro`-URI-via-SQLAlchemy pattern
    `scripts/selector_dry_run.py._connect_readonly_session` already
    establishes: `collect_regime_evidence` needs a real ORM `Session`
    (it queries `ShadowSignal`/`Trade` model classes), which
    `sqlite3.Row` cursors cannot provide. Constructed LOCALLY, bound
    directly to `db_path` -- never touches
    `app.database.session`'s read-write module-level engine.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

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
    (`app/config.py`'s documented default is `""`) -- reproduced
    directly against this project's real `paper_validation.db` when this
    script is invoked from a shell with no `DATABASE_URL` configured (no
    `backend/.env`, no exported env var). `tests/conftest.py::fresh_app_env`
    always sets `DATABASE_URL` before importing any `app.*` module, which
    is why this never surfaces in the test suite even though it can (and
    did) surface for a real invocation.

    This is UNRELATED to this report's own read-only DB connection
    (`_connect_readonly_session` above, which never imports
    `app.config.settings` / `app.database.session` at all, per this
    module's own read-only discipline) -- it is purely a side effect of
    an incidental lazy import three hops deep inside
    `collect_regime_evidence`, which this report has no control over and
    is not in scope to change.

    `create_engine()` itself never opens a connection (SQLAlchemy
    engines are lazy, per `app.database.session`'s own module docstring)
    -- setting a syntactically-valid, self-contained placeholder HERE,
    and ONLY when `DATABASE_URL` is unset, lets that one unrelated
    module-level statement succeed without ever touching a real file and
    without overriding an operator-configured value (an empty string is
    pydantic-settings' documented "not configured" default, never a real
    value an operator deliberately set).
    """
    from app.config import settings

    if not settings.DATABASE_URL:
        settings.DATABASE_URL = "sqlite://"


def _gather_shadow_and_rankings(db_path: Path, window_days: int) -> tuple[str, str, dict | None]:
    """Returns `(rankings_text, shadow_text, evidence_dict_or_None)` --
    `evidence_dict_or_None` is threaded through to `_gather_selector_state`
    and `_gather_bottleneck` below so `collect_regime_evidence` is only
    ever called once per report."""
    try:
        session = _connect_readonly_session(db_path)
    except Exception as exc:
        msg = f"unavailable: could not open {db_path} read-only ({exc})"
        return msg, msg, None

    try:
        _ensure_unrelated_write_engine_importable()

        from app.portfolio.rolling_regime_performance import collect_regime_evidence

        evidence = collect_regime_evidence(session, window_days=window_days)
    except Exception as exc:
        msg = (
            f"unavailable: could not collect regime evidence from {db_path} ({exc}) "
            "-- DB may predate the shadow-observability schema (Milestone 11+) or "
            "the rolling-performance evidence layer (Milestone 15)"
        )
        return msg, msg, None
    finally:
        session.close()

    rankings = summarize_strategy_rankings(evidence)
    rankings_text = render_strategy_rankings(rankings)

    total_shadow_n = sum(cell.n for (_, _, source), cell in evidence.items() if source == "shadow")
    total_live_n = sum(cell.n for (_, _, source), cell in evidence.items() if source == "live")
    shadow_lines = [
        f"window_days={window_days}",
        f"Total resolved shadow samples (tp/sl outcomes): {total_shadow_n}",
        f"Total resolved live samples (closed trades with r_multiple): {total_live_n}",
        f"Evidence cells observed: {len(evidence)}",
        "",
        "CAVEAT: shadow outcomes are SIMULATED fills (no fees, no slippage) -- an "
        "optimistic upper bound, not a real-fill result. See "
        "app.portfolio.rolling_regime_performance's own module docstring.",
    ]
    return rankings_text, "\n".join(shadow_lines), evidence


# --------------------------------------------------------------------
# (d) selector state -- select_for_bucket over the 9 buckets + untagged
# --------------------------------------------------------------------


def _gather_selector_state(evidence: dict | None) -> tuple[str, int | None]:
    if evidence is None:
        return "unavailable: no evidence collected (see Shadow Performance section)", None

    try:
        from app.strategy.selector import select_for_bucket
        from app.strategy.strategy_interface import AVAILABLE_STRATEGIES
    except Exception as exc:
        return f"unavailable: {exc}", None

    non_legacy_count = 0
    for bucket in ALL_BUCKETS:
        strategy, _reason, _fallback = select_for_bucket(
            bucket, evidence, AVAILABLE_STRATEGIES, MIN_TRADES_FOR_CONFIDENCE
        )
        if strategy.name != "legacy":
            non_legacy_count += 1

    text = (
        f"Selector dry-run (RollingPerformanceSelector, NOT wired into "
        f"scripts/run_paper.py): {non_legacy_count} of {len(ALL_BUCKETS)} buckets "
        "would route to a non-legacy strategy today (expected 0 while evidence "
        "remains insufficient -- see docs/REGIME_PERFORMANCE_ANALYSIS.md)."
    )
    return text, non_legacy_count


# --------------------------------------------------------------------
# (e) bottleneck -- derived mechanically from (c)/(d), not guessed
# --------------------------------------------------------------------


def _gather_bottleneck(evidence: dict | None, non_legacy_count: int | None) -> str:
    if evidence is None:
        return (
            "Evidence accumulation (unverifiable this run: shadow/live evidence "
            "collection failed -- see Shadow Performance section for the reason)."
        )

    sufficient_cells = sum(1 for cell in evidence.values() if cell.sufficient)
    non_legacy_display = non_legacy_count if non_legacy_count is not None else "unknown"

    # Rule (disclosed, mechanical, not a judgment call): fewer than
    # BOTTLENECK_SUFFICIENT_CELL_FLOOR sufficient (strategy, bucket,
    # source) cells anywhere in the DB -> bottleneck is "evidence
    # accumulation." Otherwise, the next constraint is the evidence
    # review + wiring decision ROADMAP.md's "what remains" section names
    # explicitly (an operator step, not more code) -- see
    # `_gather_next_milestone` below for that same section quoted.
    if sufficient_cells < BOTTLENECK_SUFFICIENT_CELL_FLOOR:
        return (
            "Evidence accumulation. "
            f"{sufficient_cells} of {len(evidence)} observed (strategy, bucket, "
            f"source) cells have reached the {MIN_TRADES_FOR_CONFIDENCE}-sample "
            f"floor (rule: bottleneck = 'evidence accumulation' whenever "
            f"sufficient_cells < {BOTTLENECK_SUFFICIENT_CELL_FLOOR}). "
            f"{non_legacy_display} of {len(ALL_BUCKETS)} regime buckets currently "
            "route to a non-legacy strategy."
        )
    return (
        "Evidence review and wiring decision. "
        f"{sufficient_cells} of {len(evidence)} observed cells now clear the "
        f"{MIN_TRADES_FOR_CONFIDENCE}-sample floor -- the remaining blocker is an "
        "operator evidence review plus the explicit decision to wire "
        "RollingPerformanceSelector into scripts/run_paper.py (see ROADMAP.md, "
        "'What remains is data and a decision, not more building,' items (b)/(c)), "
        "not further architecture work."
    )


# --------------------------------------------------------------------
# (f) risks -- live checks: paper trader process, DB migration head
# --------------------------------------------------------------------


def _check_paper_trader_running() -> str:
    """Best-effort, read-only process check via subprocess (no psutil
    dependency, per this project's usual "stdlib/already-available tools
    only" discipline). Tries PowerShell's `Get-CimInstance` first (shows
    full command lines, so it can confirm `run_paper.py` specifically);
    falls back to `tasklist` (Windows-always-available, but cannot show
    command lines -- a disclosed, degraded check that can only say
    "some python.exe is/isn't running," not confirm which script).
    """
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                "-ErrorAction Stop).CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            hits = [line for line in lines if "run_paper.py" in line]
            if hits:
                return (
                    f"OK: {len(hits)} python.exe process(es) with run_paper.py in "
                    "their command line."
                )
            return (
                f"RISK: no python.exe process command line contains 'run_paper.py' "
                f"({len(lines)} other python.exe process(es) found) -- paper trader "
                "may not be running."
            )
    except Exception:
        pass  # fall through to the degraded tasklist check below

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        count = result.stdout.lower().count("python.exe")
        if count:
            return (
                f"UNKNOWN (degraded check): {count} python.exe process(es) running, "
                "but this fallback check (tasklist) cannot show command lines to "
                "confirm run_paper.py specifically (PowerShell/Get-CimInstance check "
                "failed or unavailable)."
            )
        return "RISK: no python.exe process found at all -- paper trader is very likely NOT running."
    except Exception as exc:
        return f"unavailable: process check failed ({exc})"


def _check_migration_head(db_path: Path) -> str:
    try:
        from alembic.script import ScriptDirectory

        from app.database.migrate_existing import build_alembic_config

        cfg = build_alembic_config(db_path)
        head = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception as exc:
        return f"unavailable: could not determine migration head ({exc})"

    try:
        conn = shadow_status._connect_readonly(db_path)
        try:
            if not shadow_status._table_exists(conn, "alembic_version"):
                return f"RISK: {db_path} has no alembic_version table (never stamped) -- head is {head}."
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        return f"unavailable: could not read alembic_version from {db_path} ({exc})"

    if row is None:
        return f"RISK: alembic_version table exists but is empty in {db_path} -- head is {head}."
    current = row[0]
    if current == head:
        return f"OK: {db_path} is at migration head ({head})."
    return f"RISK: {db_path} is at revision {current}, head is {head} -- migration pending (scripts/migrate_paper_db.py)."


def _gather_risks(db_path: Path) -> str:
    checks = [
        "Paper trader process: " + _check_paper_trader_running(),
        "DB migration head: " + _check_migration_head(db_path),
        "Shadow fills are simulated (no fees/slippage) -- an optimistic upper "
        "bound on any shadow-backed selector decision (ROADMAP.md, milestone "
        "13-16 section, item (d)).",
        "No statistical significance test exists yet in the selector's "
        "sample-floor rule -- a disclosed floor-plus-strict-inequality "
        "comparison, not a t-test/confidence interval (ENGINEERING_DECISIONS.md "
        "#56).",
        "RollingPerformanceSelector is built and tested but NOT wired into "
        "scripts/run_paper.py -- wiring it in remains an explicit, "
        "evidence-gated, not-yet-made operator decision.",
    ]
    return "\n".join(f"- {c}" for c in checks)


# --------------------------------------------------------------------
# (g) suggested next milestone -- ROADMAP.md, quoted verbatim
# --------------------------------------------------------------------


def _gather_next_milestone() -> str:
    roadmap_path = REPO_ROOT / "ROADMAP.md"
    try:
        text = roadmap_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"unavailable: could not read ROADMAP.md ({exc})"

    idx = text.find(ROADMAP_NEXT_MILESTONE_MARKER)
    if idx == -1:
        return (
            "unavailable: ROADMAP.md's 'what remains' section marker "
            f"({ROADMAP_NEXT_MILESTONE_MARKER!r}) was not found -- the file's "
            "structure may have changed; see ROADMAP.md directly."
        )

    # This section is prose bullets (a)/(b)/(c)/(d), not markdown
    # checkboxes -- no robust "first unchecked item" parse is available,
    # so this quotes the section VERBATIM rather than attempting a
    # brittle heuristic parse that could misrepresent it. Extracted up to
    # the next "## " heading (or end of file).
    rest = text[idx:]
    end_idx = rest.find("\n## ")
    section = rest if end_idx == -1 else rest[:end_idx]
    return "QUOTED VERBATIM from ROADMAP.md (not parsed):\n\n" + section.strip()


# --------------------------------------------------------------------
# (h) completion % -- docs/ADAPTIVE_ARCHITECTURE.md section 7 table
# --------------------------------------------------------------------


def _parse_milestone_table(text: str) -> list[tuple[str, bool]]:
    """Parse section 7's `| # | Milestone | Depends on | Status |` table
    into `(label, is_done)` pairs. `is_done` is `True` iff the Status
    cell contains the checkmark glyph this doc uses for DONE (`✅`)
    -- the raw glyph is matched here (not re-emitted); anything this
    function returns is plain ASCII, and any later render still runs
    through `app.portfolio.cto_report.ascii_safe` as a second safety
    net. Stops at the first non-`|`-prefixed line after the table
    starts (the table is immediately followed by prose, not another
    table). Returns `[]` if no matching table is found -- callers must
    treat that as "unavailable," not "0% done."
    """
    lines = text.splitlines()
    rows: list[tuple[str, bool]] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not in_table:
            if (
                stripped.startswith("|")
                and all(hint in stripped for hint in ARCHITECTURE_MILESTONE_TABLE_HEADER_HINTS)
                and "#" in stripped
            ):
                in_table = True
            continue
        if stripped.startswith("|---") or stripped.startswith("|-"):
            continue
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        milestone_id, name, _depends, status = cells[0], cells[1], cells[2], cells[3]
        clean_name = name.replace("**", "").strip()
        done = "✅" in status
        rows.append((f"{milestone_id}: {clean_name}", done))
    return rows


def _gather_completion() -> str:
    arch_path = REPO_ROOT / "docs" / "ADAPTIVE_ARCHITECTURE.md"
    try:
        text = arch_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"unavailable: could not read docs/ADAPTIVE_ARCHITECTURE.md ({exc})"

    milestone_rows = _parse_milestone_table(text)
    if not milestone_rows:
        return (
            "unavailable: could not locate/parse section 7's milestone table in "
            "docs/ADAPTIVE_ARCHITECTURE.md (file structure may have changed)"
        )

    pct = completion_estimate(milestone_rows)
    done = sum(1 for _, is_done in milestone_rows if is_done)
    lines = [
        f"{pct}% of currently-scoped milestones "
        f"(docs/ADAPTIVE_ARCHITECTURE.md section 7): {done} of {len(milestone_rows)} "
        "rows marked done.",
        "NOTE: this is completion of the CURRENTLY-SCOPED adaptive-platform "
        "milestone table only, NOT of the operator's full long-term vision -- "
        "further steps (e.g. ML-based selection, section 4.3 item 2; a real "
        "statistical significance test, ROADMAP.md item (d)) are explicitly "
        "deferred/out of scope, not counted as remaining work here.",
        "",
    ]
    for name, is_done in milestone_rows:
        lines.append(f"  [{'DONE' if is_done else 'NOT DONE'}] {name}")
    return "\n".join(lines)


# --------------------------------------------------------------------
# main
# --------------------------------------------------------------------


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return REPORTS_DIR / f"cto_report_{stamp}.md"


def main() -> int:
    args = _parse_args()
    db_path = normalize_db_path_arg(args.db_path)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    completed = _gather_completed_work(args.since)
    evidence_text = _gather_evidence(db_path)
    rankings_text, shadow_text, regime_evidence = _gather_shadow_and_rankings(db_path, args.window_days)
    selector_text, non_legacy_count = _gather_selector_state(regime_evidence)
    bottleneck_text = _gather_bottleneck(regime_evidence, non_legacy_count)
    risks_text = _gather_risks(db_path)
    next_milestone_text = _gather_next_milestone()
    completion_text = _gather_completion()

    # Selector dry-run state folds into "Shadow Performance" (closest
    # conceptual fit -- both describe what RollingPerformanceSelector
    # would do with today's evidence) rather than inventing a 9th
    # section outside this tool's fixed 8-section contract.
    shadow_full = shadow_text + "\n\n" + selector_text

    sections = {
        "completed": completed,
        "bottleneck": bottleneck_text,
        "risks": risks_text,
        "evidence": evidence_text,
        "rankings": rankings_text,
        "shadow": shadow_full,
        "next_milestone": next_milestone_text,
        "completion": completion_text,
    }

    report = compose_report(sections, title="Daily CTO Report", generated_at=generated_at)

    output_path = Path(args.output) if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # File write BEFORE print (decision #54).
    output_path.write_text(report, encoding="ascii")
    print(report)
    print(f"\n(report written to {output_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
