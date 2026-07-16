"""Rolling per-(strategy, regime-bucket) performance evidence layer
(Milestone 15, 2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md section 4.3,
ENGINEERING_DECISIONS.md #55).

This module answers exactly one question, honestly: "over the last
`window_days`, what has each (strategy, regime bucket, source) cell
actually done?" It is a pure, queryable evidence layer -- it reports
arithmetic over rows that already exist in the database, and nothing
more. It makes NO routing/selection decisions and takes NO sufficiency
shortcuts (an under-sampled cell is still returned, just flagged
`sufficient=False`, never silently hidden or dropped) -- same "results
below the sample floor must be labeled, never hidden" discipline
`app.backtesting.regime_analysis.comparison_table` and
`app.portfolio.shadow_status.routability_report` already established.
Choosing WHICH cell to trust, and what to do when a cell is
insufficient, is `RollingPerformanceSelector`'s job (Milestone 16,
ADAPTIVE_ARCHITECTURE.md section 4.3, not yet built) -- this module
exists so that selector has a single, well-defined interface to be
coded against, matching this project's established "computation/evidence
first, decision path wired in later, separately" pattern (decisions
#19, #23, #24, #45, #46, #53, #54).

Bucket convention: `"{trend}/{volatility}"`, `"untagged"` when no usable
trend/volatility pair is available -- the SAME convention
`app.backtesting.regime_analysis.regime_bucket` and
`app.portfolio.shadow_status.market_regime_bucket` already established.
Reused directly (`market_regime_bucket`, imported from
`app.portfolio.shadow_status`), not re-implemented: both `ShadowSignal.
market_regime` and `Trade.market_regime` store the same full
`MarketRegime` `dataclasses.asdict()` shape, so one bucketing function
already covers both row types.

Two data sources, kept in SEPARATE cells (`shadow` vs `live`), never
averaged together: `ShadowSignal` outcomes are SIMULATED fills, while
`Trade` rows are real, fee-paying executions. Averaging a simulated-fill
win rate together with a real-fill win rate into one number would
silently blend two different measurement instruments and produce a
figure that is neither an honest shadow estimate nor an honest live
one. The dict key returned by `collect_regime_evidence` therefore
includes `source` (`(strategy_name, bucket, source)`, not just
`(strategy_name, bucket)`) so a caller (the future selector) can see
both cells for the same (strategy, bucket) pair and decide EXPLICITLY
which to trust/prefer -- that precedence decision belongs to the
selector, not to this evidence layer.

Milestone 18c (2026-07-16, docs/RESEARCH_ROUND_1.md recommendation #3):
shadow fills are now simulated but fee/slippage/delay-adjusted (v2) --
`app.portfolio.shadow_resolver`'s realistic-fill model (1-candle entry
delay, adverse slippage, both-leg fees folded into `resolved_r`), not
the original Milestone 14b instant fee-free fill this module's docstring
used to describe as an "optimistic upper bound". That resolver stamps
every row it settles with `resolution_model =
app.portfolio.shadow_resolver.RESOLUTION_MODEL` (imported here, not
copied); rows resolved under the OLD, more optimistic model (or never
re-resolved at all) still carry `resolution_model IS NULL` and are a
DIFFERENT, less trustworthy measurement instrument -- mixing them into
the same evidence pool as current-model rows would repeat exactly the
shadow-vs-live blending mistake this module's own two-source design
already avoids. `_collect_shadow` therefore only counts a resolved
(`"tp"`/`"sl"`) row toward `n`/`win_rate`/`expectancy_r` when its
`resolution_model == RESOLUTION_MODEL`; a resolved row under any other
model (including legacy NULL) is excluded from `n` and counted in
`n_excluded` instead, same as an `"expired"`/still-open row.

Sample-inclusion contract (see `RegimeCellEvidence` below for field
shapes):

  - Shadow (`source="shadow"`): a `ShadowSignal` row contributes to a
    cell's `n`/`win_rate`/`expectancy_r` only when `outcome` is `"tp"`
    or `"sl"` (a definitively resolved, win-or-loss sample) AND
    `resolution_model == RESOLUTION_MODEL` (current-model evidence only
    -- see the Milestone 18c paragraph above) AND its resolution
    timestamp falls inside `[now - window_days, now]`. `"expired"` rows
    (aged out without either level touching, or gapped past the target
    before the delayed entry could fill -- neither a win nor a loss
    either way), still-`open` rows (`outcome IS NULL`, no verdict yet),
    and resolved rows under a DIFFERENT/legacy `resolution_model` are
    all EXCLUDED from `n` but counted in `n_excluded` for that same cell
    -- they are real observed signals, just not (or not currently
    trusted as) evidence of a win or a loss.

    Window timestamp used per row: `resolved_at` when set (true for
    `"tp"`/`"sl"`/`"expired"` rows once the Milestone 14b resolver has
    settled them -- see `ShadowSignal.resolved_at`'s own docstring:
    it is written "when [the resolver] wrote a non-NULL outcome", which
    includes `"expired"`), falling back to `captured_at` for still-`open`
    rows (which have no `resolved_at` yet by definition). This keeps a
    single, always-available "when does this row belong to the window"
    timestamp across all four `outcome` states, without inventing a
    resolution time for a signal that hasn't resolved.

  - Live (`source="live"`): a `Trade` row is considered at all only when
    `status == "closed"` (mirrors `TradeTracker.get_closed_trades()`'s
    own filter -- a `"cancelled"` trade never entered a real market
    outcome and is not evidence of anything), `closed_at` falls inside
    the window, AND `market_regime` is non-NULL (per this milestone's
    spec: a trade with no regime classification at all cannot be
    attributed to any bucket -- deliberately NOT folded into
    `"untagged"` the way a present-but-incomplete regime dict would be,
    since the historical population of trades recorded before regime
    tagging existed would otherwise dump an enormous, meaningless pile
    into one bucket). Among rows that pass that gate, a row with a
    non-NULL `r_multiple` contributes to `n`/`win_rate` (win := `r_multiple
    > 0`) /`expectancy_r`; a row with `r_multiple IS NULL` is excluded
    from `n` but counted in `n_excluded` for that cell -- a real closed
    trade whose R could not be computed at close time (see
    `compute_rolling_metrics`'s own docstring for when that happens),
    not evidence of a win or a loss either way.

No invented statistics: `win_rate`/`expectancy_r` are `0.0` for a cell
with `n == 0` (`n_excluded` may still be nonzero) rather than raising or
fabricating a value -- `sufficient=False` already communicates "don't
trust this" to a caller without needing a sentinel/NaN in the numeric
fields themselves. An empty database returns an empty dict, not an
error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ShadowSignal, Trade
from app.portfolio.shadow_status import market_regime_bucket
from app.utils.time_utils import utc_now

# `RESOLUTION_MODEL` is imported LAZILY, inside `_collect_shadow` below,
# rather than at module level here: `app.portfolio.shadow_resolver`
# itself imports `app.portfolio.trades.session_scope`, which imports
# `app.database.session`, which binds a real SQLAlchemy engine to
# `settings.DATABASE_URL` at IMPORT time (see conftest.py's module
# docstring for the full rationale). Several callers of this module
# (e.g. `app.strategy.selector`, and tests that import
# `RegimeCellEvidence` at module/collection time) import THIS module
# before any DB-URL-setting fixture has run; a module-level import here
# would transitively force that premature engine bind for every one of
# them, exactly the failure mode conftest.py warns about.

# Same established floor duplicated (not imported) a fourth time -- same
# cross-module reasoning `app.backtesting.regime_analysis`,
# `app.portfolio.shadow_status`, and `app.portfolio.performance_snapshots`
# each already documented: this is the project's one real sample-size
# floor, just re-declared locally rather than importing a sibling module
# for a single constant.
MIN_TRADES_FOR_CONFIDENCE = 20

SHADOW_SOURCE = "shadow"
LIVE_SOURCE = "live"


@dataclass
class RegimeCellEvidence:
    """One evidence row for a single (strategy_name, bucket, source)
    cell over the trailing `window_days` -- see this module's own
    docstring for the exact per-source inclusion/exclusion rules.

    `n`: resolved samples only (tp+sl resolved under the CURRENT
    `resolution_model` for shadow -- see this module's docstring,
    Milestone 18c paragraph; closed trades with a non-NULL `r_multiple`
    for live) -- the denominator behind `win_rate` and `expectancy_r`.
    `n_excluded`: samples observed in this cell/window that could not be
    scored as current-model evidence (shadow: `"expired"` + still-`open`
    + tp/sl rows resolved under a different/legacy `resolution_model`;
    live: NULL `r_multiple`) -- reported, never hidden, never folded
    into `n`.
    `sufficient`: `n >= MIN_TRADES_FOR_CONFIDENCE` (the `min_samples`
    argument `collect_regime_evidence` was called with) -- `>=`, not
    `>`, matching this project's existing floor convention (`regime_
    analysis._aggregate_row`, `shadow_status.routability_report`):
    exactly the floor is sufficient.
    """

    strategy_name: str
    bucket: str
    source: str
    n: int
    win_rate: float
    expectancy_r: float
    n_excluded: int
    sufficient: bool
    window_days: int


@dataclass
class _CellAccumulator:
    """Mutable running totals for one (strategy_name, bucket, source)
    cell while scanning rows -- collapsed into a `RegimeCellEvidence`
    only once scanning is complete. Not part of this module's public
    contract."""

    n: int = 0
    wins: int = 0
    r_sum: float = 0.0
    n_excluded: int = 0


def _bucket_key(
    strategy_name: str | None, market_regime: dict | None, source: str
) -> tuple[str, str, str] | None:
    if not strategy_name:
        return None
    return (strategy_name, market_regime_bucket(market_regime), source)


def _naive_utc(dt):
    """Strip tzinfo for comparison purposes. SQLite has no native
    timezone-aware storage -- `DateTime(timezone=True)` columns still
    round-trip as naive `datetime` objects once read back through
    SQLAlchemy on a sqlite engine, even though every value this codebase
    writes is UTC. Normalizing BOTH sides of a comparison to naive
    (rather than assuming one specific side's awareness) avoids
    `TypeError: can't compare offset-naive and offset-aware datetimes`
    regardless of which side happens to still carry `tzinfo` in a given
    call path, without silently shifting any actual instant in time
    (every value here is already UTC, aware or not)."""
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _collect_shadow(
    session: Session, window_start, cells: dict[tuple[str, str, str], _CellAccumulator]
) -> None:
    from app.portfolio.shadow_resolver import RESOLUTION_MODEL

    rows = session.execute(select(ShadowSignal)).scalars().all()
    for row in rows:
        # `resolved_at` is set for "tp"/"sl"/"expired" (the resolver
        # writes it whenever it writes a non-NULL outcome); still-`open`
        # rows have no `resolved_at` yet, so `captured_at` (when the
        # signal was generated) is the only available "when does this
        # row belong to the window" timestamp for them. See this
        # module's docstring for the full rationale.
        effective_ts = _naive_utc(row.resolved_at if row.resolved_at is not None else row.captured_at)
        if effective_ts is None or effective_ts < window_start:
            continue

        key = _bucket_key(row.strategy_name, row.market_regime, SHADOW_SOURCE)
        if key is None:
            continue
        acc = cells.setdefault(key, _CellAccumulator())

        if row.outcome not in ("tp", "sl"):
            # "expired" (including a Milestone 18c gap-past-TP
            # resolution) or still-open (outcome IS NULL): observed, but
            # neither a win nor a loss -- excluded from n, counted here.
            acc.n_excluded += 1
            continue

        if row.resolution_model != RESOLUTION_MODEL:
            # Resolved under a DIFFERENT (or legacy/NULL) resolution
            # model -- a different measurement instrument than current
            # evidence. Excluded from n rather than silently pooled with
            # v2-resolved rows; see this module's docstring, Milestone
            # 18c paragraph.
            acc.n_excluded += 1
            continue

        if row.resolved_r is None:
            # Should not happen per the ShadowSignal contract (tp/sl
            # always carry a resolved_r) -- defensively excluded rather
            # than fabricating a win/loss verdict with no R to back it.
            acc.n_excluded += 1
            continue

        acc.n += 1
        acc.r_sum += row.resolved_r
        if row.outcome == "tp":
            acc.wins += 1


def _collect_live(
    session: Session, window_start, cells: dict[tuple[str, str, str], _CellAccumulator]
) -> None:
    rows = session.execute(
        select(Trade).where(Trade.status == "closed")
    ).scalars().all()
    for row in rows:
        if row.market_regime is None:
            # Per this milestone's spec: a trade with no regime
            # classification at all is not attributable to any bucket
            # (deliberately not folded into "untagged" -- see this
            # module's docstring).
            continue
        closed_at = _naive_utc(row.closed_at)
        if closed_at is None or closed_at < window_start:
            continue

        key = _bucket_key(row.strategy_name, row.market_regime, LIVE_SOURCE)
        if key is None:
            continue
        acc = cells.setdefault(key, _CellAccumulator())

        if row.r_multiple is None:
            acc.n_excluded += 1
            continue

        acc.n += 1
        acc.r_sum += row.r_multiple
        if row.r_multiple > 0:
            acc.wins += 1


def collect_regime_evidence(
    session: Session,
    window_days: int = 30,
    min_samples: int = MIN_TRADES_FOR_CONFIDENCE,
) -> dict[tuple[str, str, str], RegimeCellEvidence]:
    """Scan `shadow_signals` and `trades` and return one
    `RegimeCellEvidence` per observed `(strategy_name, bucket, source)`
    cell over the trailing `window_days`.

    `session`: an already-open SQLAlchemy `Session` (this function does
    not open, commit, or close one -- caller-managed, same as
    `StrategyPerformanceEvaluator`'s DB access pattern but without
    owning the session itself, since this is a pure read/aggregate).

    `min_samples`: the floor `RegimeCellEvidence.sufficient` is computed
    against (default `MIN_TRADES_FOR_CONFIDENCE` = 20, this project's
    established evidence floor -- see module docstring).

    Returns an empty dict for an empty (or all-out-of-window) database --
    never raises on absence of data. Every returned cell has `n >= 0`
    and/or `n_excluded >= 0` (a cell only exists in the dict if at least
    one row -- scored or excluded -- was actually observed for it; there
    are no synthetic zero-count rows for unobserved (strategy, bucket,
    source) combinations, matching `shadow_status.compute_shadow_signal_
    stats`'s own "only observed pairs appear" convention).
    """
    window_start = _naive_utc(utc_now() - timedelta(days=window_days))
    cells: dict[tuple[str, str, str], _CellAccumulator] = {}

    _collect_shadow(session, window_start, cells)
    _collect_live(session, window_start, cells)

    result: dict[tuple[str, str, str], RegimeCellEvidence] = {}
    for (strategy_name, bucket, source), acc in cells.items():
        n = acc.n
        win_rate = (acc.wins / n) if n else 0.0
        expectancy_r = (acc.r_sum / n) if n else 0.0
        result[(strategy_name, bucket, source)] = RegimeCellEvidence(
            strategy_name=strategy_name,
            bucket=bucket,
            source=source,
            n=n,
            win_rate=win_rate,
            expectancy_r=expectancy_r,
            n_excluded=acc.n_excluded,
            sufficient=n >= min_samples,
            window_days=window_days,
        )
    return result
