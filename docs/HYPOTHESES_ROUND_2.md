# Hypothesis Round 2 — Root-Causing the Adaptive Platform's Only Structural Gap

Research + Hypothesis department deliverable (2026-07-19), operator
directive ("Begin Hypothesis Round 2... choose the highest ROI research
direction"). **Context**: Hypothesis Round 1 (`docs/HYPOTHESES_ROUND_1.md`)
is now fully resolved — H1/H2/H3/H5 REJECT, H4 MIXED, zero KEEPs
(milestones 25-29). Every tested fix for Legacy's structural
execution-delay fragility failed on its own pre-registered evidence.
Per the operator's own "prefer structural improvements over parameter
optimization" directive (`ROADMAP.md`'s "Objective change" section),
Round 2 does not propose a sixth Legacy-delay-fragility patch — that
line of inquiry is exhausted on this evidence base. Instead it targets
the adaptive platform's own stated objective directly: a working second
strategy. Strategy B (Jade) is fully built (`ENGINEERING_DECISIONS.md`
#23-#33) but has exactly one prior evaluation, and that evaluation is a
clean negative result with an explicit, disclosed, UNCONFIRMED
hypothesis and a named next step neither undertaken nor superseded since
(`ENGINEERING_DECISIONS.md` #36).

**Correcting the record**: `ROADMAP.md`'s milestone 29 close-out
(previous session) stated Jade "has never been benchmarked end-to-end."
That claim was wrong and is corrected in this same round's `ROADMAP.md`
update — Jade WAS benchmarked once (2026-07-12, BTCUSDT 15m standard
scale, decision #36), and lost badly (6 trades vs. Legacy's 47, 0/6
profitable periods, walk-forward FAILED). Round 2 does not re-run that
already-decided comparison — doing so would duplicate settled work. It
targets the specific, disclosed, un-executed next step decision #36
itself named: **"confirm or rule out the same-bar-retracement-requirement
hypothesis directly"** — step (1) of that decision's own 3-step queue,
which explicitly gates steps (2) (cross-asset check) and (3) (further
tuning) on step (1)'s outcome.

---

## 1. Ranking

| Rank | Direction | Grounding | Testability | Cost | Why |
|---|---|---|---|---|---|
| **1** | H6 — Root-cause Jade's signal scarcity (decision #36's own named, unconfirmed hypothesis) | 5 | 5 | 1 | Directly targets an explicit, disclosed, already-queued next step from this platform's own evidence base — not a new idea from nowhere. Zero new production code: reuses `entry_point_engine.py`'s already-built `reject_reason_list` machinery and existing public detector functions. Diagnostic only — its result determines whether decision #36's steps 2-3 (cross-asset Jade validation, further tuning) are worth pursuing at all, or whether Jade's scarcity is structural to its entry-model design. |
| 2 | Cross-asset Legacy delay-fragility check (ETH/SOL/XRP, `--delay-check`) | 4 | 5 | 2 | Every H1-H5 doc in Round 1 repeats the same caveat: "One asset (BTCUSDT)... not cross-asset checked." Cheap to run (reuses `--delay-check` verbatim, zero new code). Deferred behind H6 because even a positive result (fragility is BTC-specific) would not unblock anything on its own — every tested FIX for the fragility already failed on BTCUSDT regardless of whether the fragility itself is universal, so this is confirmatory/informational rather than action-unlocking right now. |
| 3 | Jade cross-asset scarcity check (decision #36 step 2) | 4 | 4 | 2 | Explicitly decision #36's own step (2) — but that same decision explicitly orders it AFTER step (1) ("only then decide whether further tuning or cross-asset validation is worth the effort"). Running it before H6 would risk validating (or invalidating) Jade's scarcity on a second asset without understanding the mechanism on the first, and would not respect this project's own pre-registration discipline of not skipping ahead of a hypothesis's own declared ordering. |

**Recommended first experiment: H6.** See section 2. Ranks 2-3 are
recorded for completeness, not pre-registered in full this round —
consistent with `docs/HYPOTHESES_ROUND_1.md`'s own template, where lower
ranks were pre-registered but deferred; here, since only one direction is
being run this round, only H6 gets a full pre-registration, matching the
discipline `CLAUDE.md` names for H5 in reverse — do not write a full
spec for a direction not being run yet, so a future session doesn't
mistake a placeholder ranking-table row for an authoritative one.

---

## 2. H6 — Root-cause Jade's entry-signal scarcity

### Mechanism

`ENGINEERING_DECISIONS.md` #36 found the Jade engine (`use_jade_engine=True`)
produces roughly 1/8th as many trades as the Legacy pipeline on
identical BTCUSDT 15m data (6 vs. 47), is profitable in zero of six
periods, and fails walk-forward outright. That decision disclosed a
PLAUSIBLE, NOT-YET-CONFIRMED explanation: 3 of Jade's 5 entry models
(FVG, Order Block, Breaker Block — `entry_point_engine.py`'s
`_evaluate_fair_value_gap`/`_evaluate_order_block`/`_evaluate_breaker_block`)
require the LAST candle to already be actively retracing INTO the zone
at that exact bar (`_last_candle_overlaps_zone`) before producing a
candidate at all, unlike Legacy's own zone selection, which has no
same-bar timing requirement. Decision #36 named confirming or ruling out
this hypothesis as the single highest-value next step, not yet
undertaken.

**This hypothesis expands decision #36's question into a complete,
mutually-exclusive pipeline attribution**, because reading
`jade_trade_plan.build_trade_plan` and `entry_point_engine.find_entry_point`
directly (both already-built, already-tested modules, read but not
modified for this hypothesis) surfaces two more candidate scarcity
drivers decision #36's text did not examine:

1. **Upstream HTF-bias gate**: `build_trade_plan` calls
   `bias.detect_htf_bias(htf_candles)` FIRST and returns `None`
   immediately if `"neutral"`, before any of the 5 entry models run at
   all. **Important disclosed distinction**: `detect_htf_bias` is the
   IDENTICAL function `SignalEngine.generate_signal` (Legacy's own
   pipeline) already calls on the SAME `htf_candles` series
   (`signal_engine.py` line 11/299) — so a high neutral-bias rate is a
   SHARED constraint on both pipelines, not a Jade-specific one, and
   cannot by itself explain a Legacy-vs-Jade GAP. It is measured here as
   disclosed context (a comparison baseline), not as a candidate
   explanation for the differential result decision #36 found.
2. **Downstream exit-target gate**: `SignalEngine._generate_signal_via_jade_engine`
   (the actual wiring point decision #36's A/B test exercised) discards
   an otherwise-valid entry-model candidate if
   `exit_point_engine.find_exit_targets(...)["targets"]` is empty
   (`signal_engine.py`: `if not exit_targets: return None`) — a second,
   Jade-specific gate `build_trade_plan` itself does not apply but the
   actual wired pipeline does. This is a genuinely different mechanism
   from decision #36's named hypothesis (entry-zone timing vs.
   exit-target availability) and has never been measured either.

**One additional structural clue worth disclosing before any run**:
Entry Model 1 (Premium/Discount)'s own docstring states it "NEVER
rejects a setup because current price sits outside the entry zone" —
unlike Models 3-5, it has no same-bar retracement requirement at all,
and its only rejection path is `calculate_premium_discount(candles) is
None` ("no coherent current swing range"), expected to be rare on real
market data. If Model 1 fires on nearly every non-neutral-bias step,
`find_entry_point` (which returns the highest-confidence candidate
across all 5 models) should rarely return `None` post-bias-gate — which
would mean the scarcity decision #36 found is NOT primarily an
entry-model-availability problem at all, and the exit-target gate (or
something else downstream) would be the more likely explanation. This is
disclosed as a reason to measure ALL pipeline stages, not only the one
decision #36 named, rather than a claim about the answer.

### Grounding

- **Internal**: `ENGINEERING_DECISIONS.md` #35 (the displacement-candidate
  performance bug found and fixed BEFORE the first A/B result, disclosed
  so Jade's performance characteristics are on record independent of its
  strategy-quality result) and #36 (the first A/B result itself: 6 vs.
  47 trades, 0/6 vs. 6/6 profitable periods, the disclosed,
  UNCONFIRMED same-bar-retracement hypothesis, and the explicit "highest
  value next steps... not undertaken" queue this hypothesis directly
  continues). `entry_point_engine.py` (`find_entry_point`'s existing
  `reject_reason_list` aggregation, already cleanly separating "no
  matching order/breaker block" from "price has not retraced... yet" for
  2 of the 3 same-bar models — FVG's own single reject string conflates
  the two, requiring one small external check reusing
  `detect_fair_value_gap` directly, not a production code change).
  `jade_trade_plan.py` (`build_trade_plan`'s neutral-bias short-circuit,
  upstream of every entry model). `signal_engine.py`
  (`_generate_signal_via_jade_engine`'s own additional `exit_targets`
  gate, the actual wiring point decision #36's A/B test exercised).
- **External**: none specific to this platform's own code-path attribution
  question — this is an internal root-cause diagnostic, not a claim
  requiring outside literature support, the same status
  `docs/HYPOTHESES_ROUND_1.md` section 6 (H5)'s Step 0 gate had.

### Pre-registered experiment

**New analysis-only harness**, `scripts/research_h6_jade_scarcity_diagnosis.py`
— reuses `bias.detect_htf_bias`, `entry_point_engine.find_entry_point`'s
individual evaluator functions (`_evaluate_fair_value_gap`/
`_evaluate_order_block`/`_evaluate_breaker_block`/`_evaluate_premium_discount`/
`_evaluate_liquidity_raid`), `entry_point_engine._last_candle_overlaps_zone`,
`entry_point_engine.detect_fair_value_gap`/`detect_order_block`/
`detect_breaker_block`, and `exit_point_engine.find_exit_targets` — all
called directly, unmodified, exactly as the real Jade pipeline already
calls them (`jade_trade_plan.build_trade_plan` /
`signal_engine._generate_signal_via_jade_engine`). No new
`BacktestEngine` parameter, no new CLI flag, no change to
`RiskManager.evaluate()` or `scripts/run_paper.py` — this is a read-only
walk-forward SCAN (same no-lookahead HTF cursor mechanism,
`_advance_htf_cursor`, and same `MIN_CANDLES - 1` starting index
`scripts/research_signal_selection.py`'s `collect_candidates` already
uses), never executes a trade.

At every walk-forward step, classify into exactly one bucket, in this
order:

1. `neutral_bias` — `detect_htf_bias(htf_slice) == "neutral"`.
2. Per-model, for non-neutral-bias steps only: each of the 5 entry-model
   evaluators is called directly. For the 3 same-bar models
   (`fair_value_gap`/`order_block`/`breaker_block`), sub-classify into
   `no_matching_zone` (no candidate zone of the matching type/direction
   exists at all) vs. `zone_exists_not_retraced` (a matching zone
   exists but `_last_candle_overlaps_zone` is false this bar) vs.
   `candidate_found`. For the 2 non-same-bar models
   (`premium_discount`/`liquidity_raid`), classify into
   `no_candidate`/`candidate_found` only (no same-bar sub-classification
   applies to either).
3. `find_entry_point`-equivalent aggregate outcome (the same
   highest-confidence-wins selection `find_entry_point` itself performs
   over the 5 evaluators' raw outputs): `no_entry_candidate` (all 5
   models rejected) vs. `entry_candidate_selected`.
4. For steps reaching `entry_candidate_selected`: call
   `find_exit_targets(ltf_slice, direction, entry_price)` with the
   selected candidate's own zone midpoint as `entry_price` (mirroring
   `build_trade_plan`'s own convention) and classify
   `exit_targets_empty` vs. `signal_would_generate` (this last bucket is
   the step-level equivalent of "the real Jade pipeline would have
   produced a `TradeSignal` here").

**Anchors**: BTCUSDT 15m, `--candles 3000 --periods 6`, `--end-date
2026-07-10 / 2025-07-10 / 2024-07-10` — this project's now-standard
3-anchor set (extending decision #36's original single-window BTCUSDT
scope for cross-year confirmation of the MECHANISM, not a re-run of the
already-decided A/B comparison itself, which stays on record unchanged).

```
python scripts/research_h6_jade_scarcity_diagnosis.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10
python scripts/research_h6_jade_scarcity_diagnosis.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10
python scripts/research_h6_jade_scarcity_diagnosis.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10
```

**Keep-rule (declared now)** — this is a diagnostic hypothesis, not a
promotion candidate, so the rule classifies decision #36's SPECIFIC named
mechanism as CONFIRMED / REJECTED / INCONCLUSIVE rather than KEEP/REJECT
a trading behavior:

Aggregate, across all 3 same-bar models (FVG/Order Block/Breaker Block)
and all 3 anchor years, the counts of `no_matching_zone` and
`zone_exists_not_retraced` among non-neutral-bias steps:

- **CONFIRMED** if `zone_exists_not_retraced >= 2x no_matching_zone`
  (aggregated) — zones are usually found; the same-bar timing gate is
  what discards them, matching decision #36's hypothesis as the
  dominant mechanism.
- **REJECTED** if `no_matching_zone >= 2x zone_exists_not_retraced`
  (aggregated) — the models rarely find a matching zone in the first
  place; the same-bar timing gate is a minor factor at most, and the
  scarcity traces to zone detection itself (structural rarity of
  qualifying FVG/OB/Breaker formations under Jade's own definitions),
  not entry timing.
- **INCONCLUSIVE** otherwise (neither ratio holds) — an honest MIXED
  result, matching this project's H4 precedent of reporting a genuinely
  unresolved ratio rather than rounding it toward either answer.

**Disclosed as important context, not part of the CONFIRMED/REJECTED/
INCONCLUSIVE verdict above** (declared now, evaluated honestly regardless
of what it shows): the `neutral_bias` share of all steps; Model 1
(Premium/Discount)'s own `candidate_found` rate among non-neutral-bias
steps; the `exit_targets_empty` share among steps that reached
`entry_candidate_selected`. If any of these turns out to dominate the
overall scarcity more than the same-bar-retracement mechanism itself,
that is reported as the more important finding regardless of the
primary verdict above — matching H3's "evidence-scarcity caveat, the
substantive finding" precedent, where a secondary observation
outweighed the nominal keep-rule's own answer.

### Cost

Small: pure read-only analysis over already-built, already-tested
detector functions (`entry_point_engine.py`, `jade_trade_plan.py`,
`exit_point_engine.py`, `bias.py` — none modified). No new production
code, no new `BacktestEngine` parameter, no new CLI flag on
`run_backtest.py`. Comparable in cost to H5's Step 0 gate (milestone
29) — an even smaller footprint than H1/H3's research harnesses, since
those needed day-batching or bucket-joining machinery this diagnostic
does not.

### Promotion path if CONFIRMED or REJECTED

**Not a promotion decision either way** — this hypothesis diagnoses a
mechanism, it does not propose a fix or a new default. Per decision
#36's own queued ordering: a CONFIRMED verdict makes a targeted
same-bar-relaxation fix (e.g., allowing retracement within the last N
candles, not only the current one) a well-grounded next hypothesis to
pre-register in a future round; a REJECTED verdict redirects decision
#36's step (2)/(3) away from entry-timing tuning and toward examining
why FVG/OB/Breaker formations are structurally rare under Jade's own
detector definitions on this data; an INCONCLUSIVE verdict means neither
direction is well-supported yet, and any further Jade investment should
wait for a larger, more disambiguating sample (cross-asset, per decision
#36's own step 2) before committing to either fix direction. Jade's
`use_jade_engine` default stays `False`, `RiskManager.evaluate()` and
`scripts/run_paper.py` are untouched by this hypothesis regardless of
its outcome — this round changes no live/paper behavior under any
verdict.

---

## 3. Deferred directions (not pre-registered in full this round)

- **Cross-asset Legacy delay-fragility check (rank 2)**: cheap and
  well-grounded, but confirmatory rather than action-unlocking given
  every proposed fix for the fragility already failed on the one asset
  tested regardless of whether the fragility itself proves universal.
  A candidate for a future round, not excluded.
- **Jade cross-asset scarcity check (rank 3, decision #36 step 2)**:
  explicitly ordered by decision #36 itself to follow, not precede, H6's
  mechanism confirmation — pre-registering it in full before H6 runs
  would violate that decision's own stated ordering.

---

## 4. Caveats

- **No result exists yet.** This document proposes H6; it reports none.
  Every number cited above is drawn from prior, already-committed
  evidence documents (`ENGINEERING_DECISIONS.md` #35/#36), not from any
  run performed for this round.
- **One asset (BTCUSDT), one timeframe (15m)** — matching decision #36's
  own original scope, extended here only to 3 years for cross-year
  mechanism confirmation, not cross-asset. Whether Jade's scarcity
  mechanism (whatever this hypothesis finds it to be) generalizes to
  ETH/SOL/XRP remains open, deferred to rank-3 above.
- **This hypothesis diagnoses a mechanism; it does not fix anything.**
  Even a CONFIRMED verdict does not itself make same-bar-relaxation a
  validated improvement — that would be a new, separately pre-registered
  hypothesis in a future round, per this project's standing discipline.
- **`find_entry_point`'s own confidence-ranking step is read but not
  independently re-verified here** — this hypothesis trusts
  `find_entry_point`'s existing, already-tested `max(..., key=confidence_score)`
  selection logic rather than re-deriving it; if that selection logic
  itself has a bug, this hypothesis would not surface it (out of scope —
  it is orthogonal to the same-bar-retracement question).
