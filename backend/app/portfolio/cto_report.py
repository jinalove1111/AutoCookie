"""Daily CTO report -- pure composition helpers (Milestone 17b, 2026-07-16,
standing operator directive: every morning produce a report covering (1)
what was completed, (2) current bottleneck, (3) remaining risks, (4)
evidence accumulated, (5) strategy rankings, (6) shadow performance, (7)
suggested next milestone, (8) estimated platform completion %.

Deliberately pure (no DB/file/network/subprocess I/O) -- same
"computation-only, separate from I/O" split this project already
established for `app.backtesting.regime_analysis` (decision #54c),
`app.portfolio.performance_snapshots.compute_rolling_metrics`, and
`app.portfolio.shadow_status` (decision #55(a)): every function here
takes plain dicts/lists/strings in and returns plain strings/floats out,
so it is independently unit-testable against hand-built fixtures without
a database, and reusable from any future caller (this module's own CLI,
`scripts/cto_report.py`; a future dashboard; tests) without dragging in
I/O concerns. `scripts/cto_report.py` is the thin read-only-DB +
subprocess + file-reading CLI that gathers real data and calls into this
module.

Reuses `app.portfolio.rolling_regime_performance.RegimeCellEvidence`
directly (imported for typing only) rather than reinventing a parallel
evidence-cell shape -- `summarize_strategy_rankings` below consumes
exactly what `collect_regime_evidence()` already returns.

ASCII-only output (decision #54(d), same Windows cp1252-console lesson
`app.portfolio.shadow_status`'s own module docstring documents): a
default Windows console raises `UnicodeEncodeError` on non-ASCII
`print()` output, and every source document this report quotes from
(ROADMAP.md, docs/ADAPTIVE_ARCHITECTURE.md) contains non-ASCII glyphs
(checkmarks, em dashes, curly quotes). `compose_report` therefore runs
every byte of its own output through `ascii_safe` as a final safety net,
regardless of what the caller passed in -- callers do not need to
individually sanitize every string they hand to this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.portfolio.rolling_regime_performance import RegimeCellEvidence

# --------------------------------------------------------------------
# ASCII sanitization
# --------------------------------------------------------------------

# Common typographic characters this project's own source documents use,
# mapped to a reasonable ASCII equivalent rather than just dropped --
# preserves meaning ("done"/"not done"/"partial") instead of silently
# erasing it. Anything not in this table falls through to the
# `encode("ascii", "replace")` fallback below (becomes "?"), which is
# safe (never raises) but uninformative -- this table exists to keep the
# common, EXPECTED non-ASCII glyphs from degrading to "?" in the first
# place.
_ASCII_REPLACEMENTS: dict[str, str] = {
    "—": "--",  # em dash
    "–": "-",  # en dash
    "‘": "'",  # left single quote
    "’": "'",  # right single quote
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "…": "...",  # ellipsis
    "✅": "[DONE]",  # white heavy check mark
    "❌": "[NOT DONE]",  # cross mark
    "⚠": "[WARN]",  # warning sign
    "️": "",  # variation selector-16 (often trails an emoji glyph)
    "\U0001f7e1": "[PARTIAL]",  # large yellow circle (this project's "partial" marker)
    "→": "->",  # rightwards arrow
    "––": "--",
}


def ascii_safe(text: str) -> str:
    """Return `text` with every non-ASCII character either mapped to a
    disclosed ASCII equivalent (`_ASCII_REPLACEMENTS`) or replaced with
    `"?"` (the `encode(..., "replace")` fallback) -- never raises, and
    the result always satisfies `text.encode("ascii")` without error.
    Idempotent: running this twice produces the same output as running
    it once.
    """
    for bad, good in _ASCII_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("ascii", "replace").decode("ascii")


# --------------------------------------------------------------------
# compose_report
# --------------------------------------------------------------------

# Fixed section order matching the 8 items the standing operator
# directive names, in that exact order -- `compose_report` never
# reorders these regardless of the order keys are inserted into
# `sections`.
SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("completed", "1. What Was Completed"),
    ("bottleneck", "2. Current Bottleneck"),
    ("risks", "3. Remaining Risks"),
    ("evidence", "4. Evidence Accumulated"),
    ("rankings", "5. Strategy Rankings"),
    ("shadow", "6. Shadow Performance"),
    ("next_milestone", "7. Suggested Next Milestone"),
    ("completion", "8. Estimated Platform Completion %"),
)

SECTION_KEYS: tuple[str, ...] = tuple(key for key, _ in SECTION_ORDER)


def compose_report(
    sections: dict[str, str],
    title: str = "Daily CTO Report",
    generated_at: str | None = None,
) -> str:
    """Render the full ASCII markdown report from a `sections` dict keyed
    by `SECTION_KEYS` (`"completed"`, `"bottleneck"`, `"risks"`,
    `"evidence"`, `"rankings"`, `"shadow"`, `"next_milestone"`,
    `"completion"`). A missing key renders as
    `"unavailable: section not provided"` rather than raising or
    silently omitting the section -- every one of the 8 required
    headings always appears in the output, matching the standing
    directive's fixed 8-item contract regardless of what the caller
    managed to gather.

    Pure string-in/string-out: this function performs no I/O and never
    raises on a malformed/partial `sections` dict. The entire returned
    string is guaranteed ASCII (`ascii_safe`, see module docstring) --
    `report.encode("ascii")` never raises.
    """
    lines: list[str] = [f"# {title}"]
    if generated_at:
        lines.append(f"Generated: {generated_at}")
    lines.append("")

    for key, heading in SECTION_ORDER:
        content = sections.get(key)
        if not content or not str(content).strip():
            content = "unavailable: section not provided"
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(str(content).strip())
        lines.append("")

    return ascii_safe("\n".join(lines))


# --------------------------------------------------------------------
# Strategy rankings
# --------------------------------------------------------------------


def summarize_strategy_rankings(
    evidence: "dict[tuple[str, str, str], RegimeCellEvidence]",
) -> list[dict]:
    """Collapse a `collect_regime_evidence()` result (keyed
    `(strategy_name, bucket, source)`) into one summary row per
    `strategy_name` -- reuses `RegimeCellEvidence`'s own fields
    directly, does not recompute anything `collect_regime_evidence`
    already computed.

    Each returned row:
      {
        "strategy_name": str,
        "shadow_n": int,           # sum of .n across all source="shadow" cells
        "live_n": int,              # sum of .n across all source="live" cells
        "sufficient_cells": int,     # count of cells (either source) with .sufficient True
        "best_bucket": str | None,    # bucket of the highest-expectancy SUFFICIENT cell
        "best_expectancy_r": float | None,  # that cell's expectancy_r; None if no sufficient cell
        "best_source": str | None,     # "live" or "shadow" of the best cell
      }

    `best_*` fields are `None` for a strategy with zero sufficient cells
    -- never fabricated from an insufficient (untrustworthy) cell, same
    "don't invent a number a caller could mistake for evidence"
    discipline every sibling module in this evidence chain follows.

    Sort order: strategies with at least one sufficient cell first
    (descending `best_expectancy_r`), then strategies with none at all,
    alphabetically -- a strategy with zero trustworthy evidence is not
    ranked ABOVE or interleaved with one that has real evidence, but it
    is still listed (never silently dropped).

    Returns `[]` for an empty `evidence` dict.
    """
    per_strategy: dict[str, dict] = {}
    for (strategy_name, bucket, source), cell in evidence.items():
        row = per_strategy.setdefault(
            strategy_name,
            {
                "strategy_name": strategy_name,
                "shadow_n": 0,
                "live_n": 0,
                "sufficient_cells": 0,
                "best_bucket": None,
                "best_expectancy_r": None,
                "best_source": None,
            },
        )
        if source == "shadow":
            row["shadow_n"] += cell.n
        elif source == "live":
            row["live_n"] += cell.n

        if cell.sufficient:
            row["sufficient_cells"] += 1
            if row["best_expectancy_r"] is None or cell.expectancy_r > row["best_expectancy_r"]:
                row["best_expectancy_r"] = cell.expectancy_r
                row["best_bucket"] = bucket
                row["best_source"] = source

    def _sort_key(row: dict):
        has_evidence = row["best_expectancy_r"] is not None
        return (not has_evidence, -(row["best_expectancy_r"] or 0.0), row["strategy_name"])

    return sorted(per_strategy.values(), key=_sort_key)


def render_strategy_rankings(rankings: list[dict]) -> str:
    """Plain ASCII table rendering of `summarize_strategy_rankings`'s
    output -- same "no non-ASCII glyphs anywhere" discipline
    `shadow_status.render_report`/`selector_dry_run._render_table`
    already follow. `"(none)"` for any `None` field (never a raw
    `"None"` string or a fabricated number).
    """
    if not rankings:
        return "(no evidence cells observed yet)"

    lines = [
        "strategy | shadow_n | live_n | sufficient_cells | best_bucket | best_expectancy_r | best_source"
    ]
    for row in rankings:
        best_bucket = row["best_bucket"] if row["best_bucket"] is not None else "(none)"
        best_expectancy = (
            f"{row['best_expectancy_r']:.4f}" if row["best_expectancy_r"] is not None else "(none)"
        )
        best_source = row["best_source"] if row["best_source"] is not None else "(none)"
        lines.append(
            f"{row['strategy_name']} | {row['shadow_n']} | {row['live_n']} | "
            f"{row['sufficient_cells']} | {best_bucket} | {best_expectancy} | {best_source}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------
# Completion estimate
# --------------------------------------------------------------------


def completion_estimate(milestone_rows: list[tuple[str, bool]]) -> float:
    """Percent of `milestone_rows` marked done (`True`), rounded to one
    decimal place. `milestone_rows`: `(milestone_label, is_done)` pairs
    -- the CALLER is responsible for parsing whatever document defines
    the milestone list (this stays pure, no file I/O); see
    `scripts/cto_report.py`'s own table parser for
    `docs/ADAPTIVE_ARCHITECTURE.md` section 7.

    Returns `0.0` for an empty list rather than raising a
    `ZeroDivisionError` -- an empty milestone list is "nothing scoped
    yet," not "0% of something."
    """
    if not milestone_rows:
        return 0.0
    done = sum(1 for _, is_done in milestone_rows if is_done)
    return round(100.0 * done / len(milestone_rows), 1)
