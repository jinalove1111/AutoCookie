"""Tests for `app.portfolio.cto_report` (pure helpers) and
`scripts/cto_report.py` (the read-only daily CTO report CLI) --
Milestone 17b, 2026-07-16, standing operator directive (daily report:
completed work, bottleneck, risks, evidence, strategy rankings, shadow
performance, suggested next milestone, completion %).

Mirrors `test_shadow_status.py`'s discipline: pure-helper tests against
hand-built fixtures (no DB), plus one integration test running the real
CLI against a real migrated temp DB with a couple of synthetic ORM rows.
`scripts/` is a sibling directory to `backend/`, not a package under it
-- added to `sys.path` explicitly here, same convention
`test_shadow_status.py`/`test_run_backtest.py` already established (only
TEST files reach across that boundary, never production `app` code).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import cto_report as cto_report_script  # noqa: E402

from app.portfolio.cto_report import (  # noqa: E402
    SECTION_KEYS,
    SECTION_ORDER,
    ascii_safe,
    completion_estimate,
    compose_report,
    render_strategy_rankings,
    summarize_strategy_rankings,
)
from app.portfolio.rolling_regime_performance import RegimeCellEvidence  # noqa: E402


def _db_path_from_url(sqlite_url: str) -> Path:
    assert sqlite_url.startswith("sqlite:///")
    return Path(sqlite_url[len("sqlite:///") :])


# --------------------------------------------------------------------
# ascii_safe
# --------------------------------------------------------------------


def test_ascii_safe_maps_known_glyphs_and_never_raises():
    text = "profitable strategy — not by “popularity” ✅ done ❌ fail"
    safe = ascii_safe(text)
    safe.encode("ascii")  # never raises
    assert "--" in safe
    assert "[DONE]" in safe
    assert "[NOT DONE]" in safe


def test_ascii_safe_idempotent():
    text = "em dash — and check ✅"
    once = ascii_safe(text)
    twice = ascii_safe(once)
    assert once == twice


def test_ascii_safe_unmapped_glyph_falls_back_to_replace_char():
    # A glyph with no entry in _ASCII_REPLACEMENTS still never raises.
    text = "unmapped glyph: ☃"  # snowman
    safe = ascii_safe(text)
    safe.encode("ascii")
    assert "☃" not in safe


# --------------------------------------------------------------------
# compose_report
# --------------------------------------------------------------------


def test_compose_report_fixed_section_order_and_ascii():
    sections = {key: f"content for {key}" for key, _ in SECTION_ORDER}
    report = compose_report(sections)

    report.encode("ascii")  # never raises

    # Headings must appear in the exact fixed order (1..8), never
    # reordered regardless of dict insertion order.
    positions = [report.index(heading) for _, heading in SECTION_ORDER]
    assert positions == sorted(positions)

    for key, heading in SECTION_ORDER:
        assert heading in report
        assert f"content for {key}" in report


def test_compose_report_missing_key_renders_unavailable_not_crash():
    # Only supply half the required keys.
    partial = {"completed": "did stuff", "risks": "- some risk"}
    report = compose_report(partial)

    report.encode("ascii")
    assert "did stuff" in report
    assert "- some risk" in report
    # Every one of the 8 headings still appears even though most keys
    # were never provided.
    for _, heading in SECTION_ORDER:
        assert heading in report
    assert report.count("unavailable: section not provided") == len(SECTION_ORDER) - 2


def test_compose_report_blank_string_also_treated_as_unavailable():
    sections = {key: "" for key, _ in SECTION_ORDER}
    report = compose_report(sections)
    assert report.count("unavailable: section not provided") == len(SECTION_ORDER)


def test_compose_report_sanitizes_non_ascii_section_content():
    sections = {key: "" for key, _ in SECTION_ORDER}
    sections["completed"] = "commit — fixed a bug ✅"
    report = compose_report(sections)
    report.encode("ascii")  # never raises
    assert "--" in report
    assert "[DONE]" in report


def test_section_keys_matches_section_order():
    assert SECTION_KEYS == tuple(key for key, _ in SECTION_ORDER)
    assert len(SECTION_KEYS) == 8


# --------------------------------------------------------------------
# strategy rankings
# --------------------------------------------------------------------


def _cell(strategy_name, bucket, source, n, win_rate, expectancy_r, sufficient, n_excluded=0):
    return RegimeCellEvidence(
        strategy_name=strategy_name,
        bucket=bucket,
        source=source,
        n=n,
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        n_excluded=n_excluded,
        sufficient=sufficient,
        window_days=30,
    )


def test_summarize_strategy_rankings_empty_evidence():
    assert summarize_strategy_rankings({}) == []


def test_summarize_strategy_rankings_hand_computed_totals_and_best_cell():
    evidence = {
        ("jade", "range/normal_volatility", "shadow"): _cell(
            "jade", "range/normal_volatility", "shadow", n=25, win_rate=0.6, expectancy_r=0.5, sufficient=True
        ),
        ("jade", "strong_trend/high_volatility", "live"): _cell(
            "jade", "strong_trend/high_volatility", "live", n=30, win_rate=0.7, expectancy_r=1.2, sufficient=True
        ),
        ("jade", "weak_trend/low_volatility", "shadow"): _cell(
            "jade", "weak_trend/low_volatility", "shadow", n=5, win_rate=0.4, expectancy_r=-0.2, sufficient=False
        ),
        ("legacy", "range/normal_volatility", "live"): _cell(
            "legacy", "range/normal_volatility", "live", n=28, win_rate=0.55, expectancy_r=0.8, sufficient=True
        ),
    }

    rankings = summarize_strategy_rankings(evidence)
    by_name = {r["strategy_name"]: r for r in rankings}

    jade = by_name["jade"]
    assert jade["shadow_n"] == 25 + 5  # both shadow cells, sufficient or not
    assert jade["live_n"] == 30
    assert jade["sufficient_cells"] == 2  # the two sufficient cells only
    assert jade["best_bucket"] == "strong_trend/high_volatility"
    assert jade["best_expectancy_r"] == 1.2
    assert jade["best_source"] == "live"

    legacy = by_name["legacy"]
    assert legacy["shadow_n"] == 0
    assert legacy["live_n"] == 28
    assert legacy["sufficient_cells"] == 1
    assert legacy["best_expectancy_r"] == 0.8

    # jade's best (1.2) beats legacy's best (0.8) -> jade ranked first.
    assert [r["strategy_name"] for r in rankings] == ["jade", "legacy"]


def test_summarize_strategy_rankings_no_sufficient_cell_reports_none_not_fabricated():
    evidence = {
        ("jade", "range/normal_volatility", "shadow"): _cell(
            "jade", "range/normal_volatility", "shadow", n=3, win_rate=1.0, expectancy_r=5.0, sufficient=False
        ),
    }
    rankings = summarize_strategy_rankings(evidence)
    assert len(rankings) == 1
    row = rankings[0]
    assert row["best_expectancy_r"] is None
    assert row["best_bucket"] is None
    assert row["best_source"] is None
    assert row["shadow_n"] == 3
    assert row["sufficient_cells"] == 0


def test_summarize_strategy_rankings_sorts_with_evidence_before_none_alphabetical_tiebreak():
    evidence = {
        ("zeta", "range/normal_volatility", "live"): _cell(
            "zeta", "range/normal_volatility", "live", n=1, win_rate=0.0, expectancy_r=0.0, sufficient=False
        ),
        ("alpha", "range/normal_volatility", "live"): _cell(
            "alpha", "range/normal_volatility", "live", n=1, win_rate=0.0, expectancy_r=0.0, sufficient=False
        ),
        ("beta", "range/normal_volatility", "live"): _cell(
            "beta", "range/normal_volatility", "live", n=20, win_rate=0.9, expectancy_r=2.0, sufficient=True
        ),
    }
    rankings = summarize_strategy_rankings(evidence)
    names = [r["strategy_name"] for r in rankings]
    # beta has real evidence -> first; alpha/zeta have none -> alphabetical after.
    assert names == ["beta", "alpha", "zeta"]


def test_render_strategy_rankings_empty():
    assert render_strategy_rankings([]) == "(no evidence cells observed yet)"


def test_render_strategy_rankings_is_ascii_and_shows_none_placeholders():
    rankings = summarize_strategy_rankings(
        {
            ("jade", "range/normal_volatility", "shadow"): _cell(
                "jade", "range/normal_volatility", "shadow", n=3, win_rate=1.0, expectancy_r=5.0, sufficient=False
            ),
        }
    )
    text = render_strategy_rankings(rankings)
    text.encode("ascii")
    assert "(none)" in text
    assert "jade" in text


# --------------------------------------------------------------------
# completion_estimate
# --------------------------------------------------------------------


def test_completion_estimate_empty_rows_is_zero():
    assert completion_estimate([]) == 0.0


def test_completion_estimate_all_done():
    rows = [("m1", True), ("m2", True), ("m3", True)]
    assert completion_estimate(rows) == 100.0


def test_completion_estimate_none_done():
    rows = [("m1", False), ("m2", False)]
    assert completion_estimate(rows) == 0.0


def test_completion_estimate_partial_rounds_to_one_decimal():
    rows = [("m1", True), ("m2", True), ("m3", False)]
    # 2 of 3 = 66.666...% -> rounds to 66.7
    assert completion_estimate(rows) == 66.7


# --------------------------------------------------------------------
# scripts/cto_report.py pure-ish parsing helpers
# --------------------------------------------------------------------


def test_parse_milestone_table_extracts_done_and_not_done_rows():
    text = """
## 7. Implementation roadmap with milestones

| # | Milestone | Depends on | Status |
|---|---|---|---|
| 1 | **Thing One** (details) | none | ✅ DONE (2026-07-01) |
| 2 | **Thing Two** | #1 | NOT STARTED |

**This session's scope**: prose after the table, not part of it.
"""
    rows = cto_report_script._parse_milestone_table(text)
    assert rows == [
        ("1: Thing One (details)", True),
        ("2: Thing Two", False),
    ]


def test_parse_milestone_table_returns_empty_list_when_not_found():
    assert cto_report_script._parse_milestone_table("no table here at all") == []


# --------------------------------------------------------------------
# Full CLI integration: real migrated temp DB + a couple synthetic rows.
# Per task instructions: git/roadmap-derived sections may legitimately
# read "unavailable" (or real content) depending on the sandboxed test
# environment -- this test asserts graceful, non-crashing behavior and
# structural correctness (all 8 headings present, ASCII-only, file
# written), not the specific content of every section.
# --------------------------------------------------------------------


def test_cli_end_to_end_against_tmp_migrated_db(db_session, sqlite_url, tmp_path, monkeypatch, capsys):
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
        )
    )
    db_session.commit()

    db_path = _db_path_from_url(sqlite_url)
    output_path = tmp_path / "cto_report_test_output.md"

    monkeypatch.setattr(
        sys, "argv", ["cto_report.py", str(db_path), "--output", str(output_path), "--since", "24 hours ago"]
    )

    exit_code = cto_report_script.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    captured.out.encode("ascii")  # never raises -- the whole report is ASCII-only

    # All 8 required headings present, in the fixed order, regardless of
    # which individual sections degraded to "unavailable" in this
    # environment.
    positions = [captured.out.index(heading) for _, heading in SECTION_ORDER]
    assert positions == sorted(positions)
    for _, heading in SECTION_ORDER:
        assert heading in captured.out

    # File written BEFORE stdout print (decision #54) -- by the time
    # main() has returned, the file must already exist with matching
    # (ASCII) content.
    assert output_path.exists()
    file_text = output_path.read_text(encoding="ascii")  # never raises if truly ASCII-only
    file_text.encode("ascii")
    for _, heading in SECTION_ORDER:
        assert heading in file_text

    # The evidence/shadow sections should reflect the real synthetic
    # rows just inserted (this part of the pipeline runs against the
    # real temp DB regardless of git/roadmap availability).
    assert "Regime snapshots: 1 rows" in captured.out
    assert "Shadow signals: 1 rows" in captured.out


def test_cli_missing_db_degrades_gracefully_not_traceback(tmp_path, monkeypatch, capsys):
    """A nonexistent DB path must not crash the report -- every
    DB-dependent section degrades to 'unavailable', the rest of the
    report (git/roadmap/architecture-doc sections) still renders."""
    missing_db = tmp_path / "does_not_exist.db"
    output_path = tmp_path / "out.md"
    monkeypatch.setattr(sys, "argv", ["cto_report.py", str(missing_db), "--output", str(output_path)])

    exit_code = cto_report_script.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    captured.out.encode("ascii")
    assert "unavailable" in captured.out
    assert output_path.exists()
    for _, heading in SECTION_ORDER:
        assert heading in captured.out
