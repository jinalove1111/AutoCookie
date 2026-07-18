# H8 — Validating Jade's Reward:Risk-Geometry Bottleneck — Milestone 32

Evaluation deliverable (2026-07-19). This closes out `docs/HYPOTHESES_ROUND_2.md`
section 4 (H8): validating H7's disclosed reward:risk-geometry finding
by sweeping every already-existing `stop_model` value and every
already-computed exit-target rank against production's actual default
combination. New analysis-only harness
`scripts/research_h8_jade_rr_sensitivity.py` (+
`backend/tests/test_research_h8_jade_rr_sensitivity.py`, 9 tests) was
implemented and verified this round. `RiskManager.evaluate()`,
`scripts/run_paper.py`, and every Jade module are read but UNMODIFIED —
no trade is ever executed by this harness, no new `BacktestEngine`
parameter, no new CLI flag. Full suite: 789/789 passed (780 prior + 9
new), 0 failures. Every number below is transcribed from
`scripts/reports/research_h8_jade_rr_sensitivity.json`.

**This round also found and disclosed a real bug in Milestone 30's own
harness (section 4 below) — read that section before citing H6's
`selected_model_counts` or its "FVG dominates selection" claim from any
other document.**

## 1. Purpose and methodology

**The question**: H7 found Jade's dominant rejection reason is
RR-below-minimum (92.3% of rejection-reason instances), not the shared
`MAX_TRADES_PER_DAY` cap. H8 asks whether that shortfall is structural
(inherent to Jade's entry/stop/target geometry) or fixable by simply
choosing a DIFFERENT, already-built, already-tested parameter value
production never uses: `_evaluate_fair_value_gap`/`_evaluate_breaker_block`'s
own `stop_model` argument (`aggressive`/`moderate`/`conservative` for
FVG, `aggressive`/`conservative` for Breaker Block), and
`exit_point_engine.find_exit_targets`'s own full ranked target list
(production always uses `targets[0]`, the nearest/smallest-reward
candidate, never a farther one).

**Method**: same walk-forward step loop H6 used (`MIN_CANDLES - 1`
start, no-lookahead `_advance_htf_cursor`). At each non-neutral-bias
step, `find_entry_point` is called ONCE with production's default
stop_models to identify the real selected candidate (selection itself
does not depend on `stop_model` — confidence scores are fixed per model
type, verified by code inspection before this design was finalized).
For the selected model, stop-loss counterfactuals re-evaluate ONLY that
model's own evaluator for its other supported `stop_model` values (FVG:
3 values; Breaker Block: 2 values; Order Block/Premium-Discount/
Liquidity Raid: no `stop_model` parameter exists, so these always use
the single already-computed default, unswept, disclosed as a real
coverage limit). Target counterfactuals compute RR against every
available ranked target (`TP1` through `TP6`, an arbitrary but generous
cap) from the already-computed target list.

**Anchors**: BTCUSDT 15m, `--candles 3000 --periods 6`, `--end-date
2026-07-10 / 2025-07-10 / 2024-07-10` — matching H6/H7.

## 2. Results

**Pooled selection distribution across all 3 anchors** (8,400 selected
steps): `premium_discount` 3,742 (44.5%), `liquidity_raid` 2,840
(33.8%), `order_block` 1,316 (15.7%), `breaker_block` 485 (5.8%),
`fair_value_gap` 17 (0.2%). **See section 4 — this directly contradicts
Milestone 30's own reported selection distribution, and section 4
explains why.**

**Baseline (production's actual default combination — FVG moderate /
Breaker aggressive / OB,PD,LR default stop, target index 1, pooled
across 3 anchors)**: n=8,340, **qualify rate (RR≥2.0) = 0.95%** — 99.05%
of Jade's own generated candidates fail the 1:2 minimum under the exact
combination production actually uses. Consistent with, and a direct
confirmation at the candidate level of, H7's own RiskManager-level
finding (99.3% of signals reaching `RiskManager.evaluate()` were
rejected, overwhelmingly for RR).

**Isolating the stop_model dimension** (target held at production's
default, `TP1`, pooled across 3 anchors):

| stop_model | n | Qualify rate (RR≥2.0) |
|---|---|---|
| aggressive | 8,340 | 0.95% |
| moderate | 8,340 | 0.95% |
| conservative | 8,340 | 0.92% |

**Stop-model choice alone changes essentially nothing.** This is
expected given the corrected selection distribution (section 4): 94.0%
of all selected steps (Order Block + Premium-Discount + Liquidity Raid)
have NO `stop_model` parameter to vary at all, and always use the same
single default stop regardless of which value is nominally "chosen" —
only Breaker Block (5.8% of steps) and FVG (0.2%) can move at all under
this dimension, too small a share to shift the pooled rate.

**Isolating the target-index dimension** (stop held at `aggressive`,
pooled across 3 anchors):

| Target rank | n | Qualify rate (RR≥2.0) |
|---|---|---|
| TP1 (production default) | 8,340 | 0.95% |
| TP2 | 8,284 | 2.61% |
| TP3 | 7,731 | 7.19% |
| TP4 | 7,488 | 12.69% |
| TP5 | 7,227 | 20.53% |
| TP6 | 6,949 | 26.35% |

**Nearly all of the movement comes from choosing a farther exit target,
not from stop_model choice.** The best pooled cell overall is
`aggressive|TP6` at 26.35% (n=6,949).

## 3. Primary keep-rule verdict, applied literally — then a necessary qualification

Quoting `docs/HYPOTHESES_ROUND_2.md` section 4's keep-rule verbatim:

> **STRUCTURAL** if `best_alt`'s qualification rate is `< 25%` ...
> **PARAMETER-SENSITIVE** if `best_alt`'s qualification rate is `>= 25%`
> AND at least double `baseline`'s own rate ... **INCONCLUSIVE**
> otherwise.

Mechanically: `best_alt` (`aggressive|TP6`, 26.35%) clears 25% and is
~27.7x `baseline`'s 0.95% — **PARAMETER_SENSITIVE per the rule as
literally written.**

**This mechanical result needs the same kind of qualification H7's own
literal result needed, and this document does not let it stand alone as
"Jade's problem is fixable."** The entire effect is driven by choosing
an increasingly FARTHER exit target (section 2's target-index table);
the stop_model dimension — the parameter H8's own motivating question
(H7 section 4) was actually about — moves the qualify rate by less than
0.1 percentage points in either direction. **A structurally important,
disclosed limitation of this hypothesis's own keep-rule**: RR is a
ratio of DISTANCES, not a measure of probability. A farther target
mechanically produces a larger nominal RR without regard to how likely
price is to ever reach it before the stop is hit — plausibly making the
trade both higher-RR AND lower-win-rate at the same time, in a way this
hypothesis's design cannot distinguish. `find_exit_targets` itself
disclosed no ranking beyond nearest-to-farthest by construction; nothing
in this measurement establishes that TP6 is actually reached more often
than it looks, or that trading against it would improve real Net Profit.

**The more honest reading of this round's own data**: on the specific
question H7's finding actually raised (does an existing `stop_model`
choice change Jade's RR profile), the answer is **STRUCTURAL — NO,
essentially not at all** (section 2's stop-model-only table). On the
much larger, industry-standard-cautionary target-selection question, the
mechanical PARAMETER_SENSITIVE label is real but should not be trusted
as an improvement without a dedicated future hypothesis that measures
actual win rate / Net Profit under a farther-target convention, not RR
alone — a natural, well-grounded candidate for a future H9, explicitly
not validated or endorsed by this round.

## 4. A bug found in Milestone 30's own harness, disclosed and corrected

H8's pooled selection distribution (section 2: `premium_discount` 44.5%,
`liquidity_raid` 33.8%, `fair_value_gap` 0.2%) is the OPPOSITE of what
`docs/H6_JADE_SCARCITY_RESULTS.md` section 4 reported (`fair_value_gap`
76.4%, `liquidity_raid` 0%). Both cannot be right on the same real
`find_entry_point` function. Root cause, found by reading both
harnesses side by side: `scripts/research_h6_jade_scarcity_diagnosis.py`
reimplemented `find_entry_point`'s own highest-confidence-wins selection
rather than calling `find_entry_point` itself, iterating candidates in
its own dict's insertion order (`fair_value_gap, order_block,
breaker_block, premium_discount, liquidity_raid`). The REAL
`find_entry_point` iterates its own `evaluators` tuple in a DIFFERENT
order: `(order_block, breaker_block, liquidity_raid, premium_discount,
fair_value_gap)`. `fair_value_gap`, `premium_discount`, and
`liquidity_raid` all share a fixed `confidence_score` of 4
(`entry_point_engine.py` lines 307/414/500) — a common tie whenever more
than one fires on the same step — and Python's `max()` keeps the FIRST
maximal element it encounters on a tie, never a later one. H6's own
harness therefore silently favored `fair_value_gap` in every such tie
(it iterated first in H6's own list); production actually favors
`liquidity_raid` first, then `premium_discount`, with `fair_value_gap`
evaluated and inserted LAST and only winning when neither of the other
two also fired.

**Scope of the correction**: `docs/H6_JADE_SCARCITY_RESULTS.md`
section 3's PRIMARY VERDICT (same-bar-retracement hypothesis REJECTED)
is **UNAFFECTED** — that verdict was computed from each model's own
independent `no_matching_zone`/`zone_exists_not_retraced` classification
at every step, which never called `max()` or depended on selection order
at all. Only section 4's "substantive finding" narrative (FVG dominates
selection because it is nearly unconstrained) and the
`selected_model_counts` figures it cites are wrong, now superseded by
this document's section 2. A correction notice has been added to the
top of `docs/H6_JADE_SCARCITY_RESULTS.md` itself, pointing here, rather
than silently editing that document's original, already-committed
analysis — matching this project's standing discipline of disclosing
corrections as new, dated entries rather than rewriting history.

**Why this was caught**: H8 calls the real, unmodified `find_entry_point`
directly (a design choice made specifically so H8's own selection logic
could not diverge from production, per this hypothesis's own
pre-registered text) rather than reimplementing it a second time. This
is itself a disclosed argument for a general research-harness
convention: prefer calling the real aggregation function over
re-deriving its selection/tie-breaking logic, even when re-deriving
looks equivalent on inspection.

## 5. Promotion path

**NONE — this is a diagnostic, not a promotion candidate.** The
STRUCTURAL finding on the stop_model dimension does not itself validate
or invalidate anything (there was nothing to promote). The
PARAMETER_SENSITIVE finding on the target-index dimension is explicitly
NOT endorsed as a fix (section 3) and does not authorize any change to
Jade's default target selection. `use_jade_engine` stays `False`;
`RiskManager.evaluate()` and `scripts/run_paper.py` are completely
unmodified by this round.

**Legacy's live/paper trading behavior is completely unchanged.** 100%
backtest-only, read-only research round: no `BacktestEngine` parameter
or CLI flag was added. No orders placed, no writes to
`backend/paper_validation.db`.

## 6. Caveats

- **The target-index "improvement" is win-rate-blind by design** (section
  3) — the single most important caveat in this document. Do not cite
  the 26.35% figure as evidence a farther-target convention would help
  Jade's real profitability without a dedicated, separately
  pre-registered end-to-end backtest.
- **The stop_model sweep only covers FVG and Breaker Block** — 94.0% of
  selected steps (Order Block, Premium-Discount, Liquidity Raid) have no
  `stop_model` parameter to sweep at all, per this hypothesis's own
  pre-registered coverage limit. The STRUCTURAL finding on stop_model
  applies most confidently to FVG/Breaker specifically, not to the three
  models that actually dominate selection.
- **Target sweep capped at `TP6`** — an arbitrary, disclosed limit; this
  round does not know whether `TP7`+ would show an even larger (and
  presumably even less win-rate-plausible) apparent improvement.
- **One asset (BTCUSDT), one timeframe (15m)** — matching every
  hypothesis in this evidence base so far.
- **No code changed production behavior.**
  `scripts/research_h8_jade_rr_sensitivity.py` is a new research-only
  script that calls only already-existing, already-tested functions; no
  Jade module or `RiskManager` code was modified.
