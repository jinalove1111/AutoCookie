"""Shadow-data accumulation status: pure computation over already-fetched
`regime_snapshots` / `shadow_signals` rows (Milestone 13, 2026-07-16,
docs/ADAPTIVE_ARCHITECTURE.md section 4.3, ENGINEERING_DECISIONS.md #53/#54).

Motivation: `ENABLE_SHADOW_STRATEGY_SIGNALS` (milestone 11/11b) is now live
in the paper trader, so `regime_snapshots` gains roughly one row per pass
and `shadow_signals` gains a row whenever a non-active registered strategy
would have signaled. The future `RollingPerformanceSelector`
(ADAPTIVE_ARCHITECTURE.md section 4.3) needs `>= 20` trades per
(strategy, regime bucket) before any bucket is routable -- this module
answers "how close are we?" from plain arithmetic over the accumulated
rows.

Deliberately pure (no DB/file/network I/O), same "computation-only,
separate from I/O" split this project already established for
`app.backtesting.regime_analysis` (decision #54c) and
`app.portfolio.performance_snapshots`'s `compute_rolling_metrics`: every
function here takes plain dicts/values in and returns plain dicts/strings
out, so it is independently unit-testable against hand-built fixtures
without a database, and reusable from any future caller (this module's
own CLI, `scripts/shadow_status.py`; a future dashboard; tests) without
dragging in I/O concerns. `scripts/shadow_status.py` is the thin
read-only-sqlite3 CLI that fetches rows and calls into this module.

Bucket convention: `"{trend}/{volatility}"`, `"untagged"` when no usable
trend/volatility pair is available -- the SAME convention
`app.backtesting.regime_analysis.regime_bucket` already established for
regime-tagged BACKTEST trades. `MIN_TRADES_FOR_CONFIDENCE = 20` is the
same evidence floor `app.backtesting.regime_analysis` and
`app.portfolio.performance_snapshots` each already duplicate (not
import) for the same reason: `experiment_runner.MIN_TRADES_FOR_CONFIDENCE`
lives in `scripts/`, which is not importable from `backend/app` code (a
one-way dependency boundary this project has kept consistently). Same
value, same meaning, duplicated a third time here rather than importing
either sibling module and dragging in dependencies (regime_analysis
reuses `app.backtesting.performance`; performance_snapshots reuses
`app.portfolio.trades`) this read-only status tool has no reason to need.
"""

from __future__ import annotations

from typing import Any

MIN_TRADES_FOR_CONFIDENCE = 20
UNTAGGED_BUCKET = "untagged"

# ASCII-only marker/note strings throughout this module (no U+26A0 or other
# non-ASCII glyphs) -- the same real bug this project already hit and
# documented (ENGINEERING_DECISIONS.md #54(d), `regime_analysis.
# comparison_table`'s docstring): a default Windows console is cp1252,
# which raises `UnicodeEncodeError` on non-ASCII `print()` output, and this
# tool's whole purpose is to be safely `print()`-able against a live DB.
HONESTY_NOTE = (
    "NOTE: shadow SIGNAL counts are NOT TRADE counts. A routable selector "
    "ultimately needs performance-evaluated samples (wins/losses/PnL over "
    "real or simulated outcomes), not just observed signal occurrences -- "
    f"reaching the {MIN_TRADES_FOR_CONFIDENCE}-signal floor below is a "
    "NECESSARY, not SUFFICIENT, precondition for a (strategy, regime) "
    "bucket to become routable."
)


def regime_bucket(trend: str | None, volatility: str | None) -> str:
    """`"{trend}/{volatility}"`, or `UNTAGGED_BUCKET` when either half is
    missing -- mirrors `app.backtesting.regime_analysis.regime_bucket`'s
    "no usable classification" fallback, just taking the two already-
    extracted strings directly rather than a whole trade dict (this
    module's callers extract trend/volatility from two different row
    shapes -- `RegimeSnapshot`'s own promoted columns, and
    `ShadowSignal.market_regime`'s embedded JSON dict -- see
    `market_regime_bucket` below for the latter)."""
    if not trend or not volatility:
        return UNTAGGED_BUCKET
    return f"{trend}/{volatility}"


def market_regime_bucket(market_regime: dict[str, Any] | None) -> str:
    """Bucket key for a `ShadowSignal.market_regime` value: the JSON
    column is `None` when a shadow signal was generated with no regime
    classification available for that pass (see
    `app.portfolio.shadow_recorder.record_shadow_pass`'s `regime=None`
    path) -- `UNTAGGED_BUCKET` for that case, and for a present-but-
    incomplete dict, same as `regime_bucket`."""
    if not market_regime:
        return UNTAGGED_BUCKET
    return regime_bucket(market_regime.get("trend"), market_regime.get("volatility"))


def compute_snapshot_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`rows`: one dict per `regime_snapshots` row, each with
    `"captured_at"` (a `datetime`, or `None`), `"trend"` (`str`),
    `"volatility"` (`str`) -- already extracted/parsed by the caller (the
    CLI reads these straight from real columns, no JSON involved, unlike
    `shadow_signals.market_regime`).

    Returns:
      {
        "total": int,
        "first_captured_at": datetime | None,
        "last_captured_at": datetime | None,
        "span_days": float,        # 0.0 when 0 or 1 rows have a timestamp
        "per_bucket": {bucket: count, ...},
      }

    Never raises on an empty `rows` (a pre-shadow-mode or brand-new DB):
    `total=0`, both timestamps `None`, `span_days=0.0`, `per_bucket={}`.
    """
    per_bucket: dict[str, int] = {}
    for row in rows:
        bucket = regime_bucket(row.get("trend"), row.get("volatility"))
        per_bucket[bucket] = per_bucket.get(bucket, 0) + 1

    timestamps = [row["captured_at"] for row in rows if row.get("captured_at") is not None]
    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    span_days = (last - first).total_seconds() / 86400.0 if first and last else 0.0

    return {
        "total": len(rows),
        "first_captured_at": first,
        "last_captured_at": last,
        "span_days": span_days,
        "per_bucket": per_bucket,
    }


def compute_shadow_signal_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`rows`: one dict per `shadow_signals` row, each with
    `"strategy_name"` (`str`) and `"market_regime"` (already
    `json.loads`-decoded `dict`, or `None` -- the caller's job, this
    module never touches raw JSON text).

    Returns:
      {
        "total": int,
        "counts": {(strategy_name, bucket): count, ...},
      }

    Never raises on an empty `rows`: `total=0`, `counts={}`.
    """
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        bucket = market_regime_bucket(row.get("market_regime"))
        key = (row["strategy_name"], bucket)
        counts[key] = counts.get(key, 0) + 1
    return {"total": len(rows), "counts": counts}


def routability_report(
    counts: dict[tuple[str, str], int], floor: int = MIN_TRADES_FOR_CONFIDENCE
) -> dict[str, Any]:
    """Per-(strategy, bucket) distance-to-floor table plus one overall
    summary line, from the `"counts"` dict `compute_shadow_signal_stats`
    produces.

    Each row: `{"strategy", "bucket", "count", "distance_to_floor"
    (`max(0, floor - count)`), "at_floor" (`count >= floor`, same `>=`-not-`>`
    convention `regime_analysis._aggregate_row`'s `sufficient_sample`
    already established -- exactly `floor` signals is sufficient)}`. Rows
    are sorted by `(strategy, bucket)` for deterministic, diffable output.

    `summary` is the exact honesty-adjacent accounting line this
    milestone's spec calls for: `"N of M observed (strategy,bucket) pairs
    have reached the {floor}-signal floor."` -- N/M count only pairs that
    have ever produced at least one shadow signal (an unobserved pair
    simply never appears as a key in `counts`, it is not reported as a
    zero-count row here).

    Never raises on empty `counts`: `rows=[]`, `routable_pairs=0`,
    `total_pairs=0`, and `summary` reads `"0 of 0 observed ..."`.
    """
    rows = []
    routable = 0
    for (strategy, bucket), count in sorted(counts.items()):
        at_floor = count >= floor
        if at_floor:
            routable += 1
        rows.append(
            {
                "strategy": strategy,
                "bucket": bucket,
                "count": count,
                "distance_to_floor": max(0, floor - count),
                "at_floor": at_floor,
            }
        )

    total_pairs = len(rows)
    summary = (
        f"{routable} of {total_pairs} observed (strategy,bucket) pairs "
        f"have reached the {floor}-signal floor."
    )
    return {
        "rows": rows,
        "routable_pairs": routable,
        "total_pairs": total_pairs,
        "summary": summary,
    }


def render_report(
    db_label: str,
    snapshot_stats: dict[str, Any],
    signal_stats: dict[str, Any],
    routability: dict[str, Any],
) -> str:
    """Render the full ASCII status report as a single string -- pure
    string-in/string-out (well, dicts-in), same "renderer lives next to
    the pure computation, not in the I/O-bound CLI" placement
    `regime_analysis.comparison_table` already established. ASCII-only
    throughout (see `HONESTY_NOTE`'s docstring note above): no glyph
    outside the 7-bit range appears anywhere in this function's output,
    verified by `str.encode("ascii")` in this module's own tests.
    """
    lines: list[str] = []
    lines.append("=== Shadow Data Accumulation Status ===")
    lines.append(f"DB: {db_label}")
    lines.append("")

    lines.append("--- Regime Snapshots ---")
    lines.append(f"Total rows: {snapshot_stats['total']}")
    first = snapshot_stats["first_captured_at"]
    last = snapshot_stats["last_captured_at"]
    lines.append(f"First captured_at: {first if first is not None else '(none)'}")
    lines.append(f"Last captured_at: {last if last is not None else '(none)'}")
    lines.append(f"Span: {snapshot_stats['span_days']:.2f} days")
    lines.append("Per-bucket distribution:")
    per_bucket = snapshot_stats["per_bucket"]
    if not per_bucket:
        lines.append("  (no rows)")
    else:
        for bucket in sorted(per_bucket):
            lines.append(f"  {bucket}: {per_bucket[bucket]}")
    lines.append("")

    lines.append("--- Shadow Signals ---")
    lines.append(f"Total rows: {signal_stats['total']}")
    lines.append("")

    lines.append(
        f"--- Routability (floor = {MIN_TRADES_FOR_CONFIDENCE} shadow signals "
        "per strategy/bucket pair) ---"
    )
    rows = routability["rows"]
    if not rows:
        lines.append("  (no (strategy,bucket) pairs observed yet)")
    else:
        lines.append("  strategy | bucket | count | distance_to_floor | at_floor")
        for row in rows:
            lines.append(
                f"  {row['strategy']} | {row['bucket']} | {row['count']} | "
                f"{row['distance_to_floor']} | {row['at_floor']}"
            )
    lines.append("")
    lines.append(routability["summary"])
    lines.append("")
    lines.append(HONESTY_NOTE)

    return "\n".join(lines) + "\n"
