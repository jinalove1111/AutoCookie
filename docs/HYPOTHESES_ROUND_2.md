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

**Addendum (2026-07-19, after H6 resolved)**: this ranking table is
historical — it reflects what was known before H6 ran, preserved as-is
rather than rewritten. H6 ran (REJECTED, section 2) and its own results
surfaced a new, higher-priority direction the original ranking above
could not have anticipated: H7 (section 3), which a full strategic
review across H1-H6 (`docs/RESEARCH_STRATEGY_REVIEW.md`) ranked #1
among six candidate directions, ahead of ranks 2-3 above. See that
review for the current, up-to-date priority ordering — do not treat
this section's original 1-2-3 ranking as still authoritative for
choosing the next hypothesis to run.

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

## 3. H7 — RiskManager/pipeline-gating attribution for Jade's real trade count

**Added 2026-07-19, after H6 resolved and a strategic review across
H1-H6 ranked this the single highest-value next direction**
(`docs/RESEARCH_STRATEGY_REVIEW.md` section 6). Follows this document's
own rule #1: pre-registered here, in full, before any run.

### Mechanism

H6 (section 2 above) found decision #36's same-bar-retracement
hypothesis REJECTED, but in doing so surfaced a much larger, explicitly
unattributed gap: 8,312 `signal_would_generate` steps across the 3
anchors versus decision #36's already-recorded 6 actual trades. H6's own
results (`docs/H6_JADE_SCARCITY_RESULTS.md` section 5) disclosed three
reasons those numbers are not directly comparable, none measured by H6
itself: (1) H6's harness does not track open-trade state, unlike
`BacktestEngine.run()`'s real single-open-trade-at-a-time invariant;
(2) Jade's own no-zone-mitigation design lets one real zone satisfy
`candidate_found` across many consecutive candles, inflating step counts
relative to distinct opportunities; (3) `RiskManager.evaluate()` gating
(`MAX_TRADES_PER_DAY`, RR>=1:2 minimum, daily/weekly loss limits) sits
downstream of every H6 number and was entirely out of its declared
scope. H7 measures (3) directly, and (1)/(2) as a byproduct, using
machinery that already exists and needs no new code at all.

**Key realization this pre-registration is built on**: `BacktestResult.risk_rejections`
(Milestone 23, `ENGINEERING_DECISIONS.md` #61(b), shipped 2026-07-17) is
GENERIC observational instrumentation on `BacktestEngine.run()` — it
counts whatever `risk_manager.evaluate()` decides on whatever signal
`SignalEngine.generate_signal()` produces, regardless of which engine
(Legacy or Jade, via the existing `use_jade_engine` flag) produced that
signal. **Decision #36's original Jade A/B backtest (2026-07-12) predates
this instrumentation by 5 days** — it was never possible to see Jade's
own risk-rejection breakdown at the time, not because anyone chose not
to look. H7 re-runs the SAME kind of comparison decision #36 already
made (`use_jade_engine=True` vs. baseline), extended to this project's
standard 3-anchor set, and reads the `risk_rejections` field that now
exists but didn't when #36 ran — this is new information, not a
duplicate of settled work, and requires writing zero new production
code: `BacktestEngine.run()`, `RiskManager.evaluate()`, and every Jade
module stay completely unmodified and uncalled-into beyond their
existing public API.

### Grounding

- **Internal**: `docs/H6_JADE_SCARCITY_RESULTS.md` section 5 (the
  disclosed, unattributed 8,312-vs-6 gap this hypothesis targets
  directly); `ENGINEERING_DECISIONS.md` #36 (Jade's original 6-trade
  result, predating risk-rejection observability); `ENGINEERING_DECISIONS.md`
  #61(b) / `ENGINEERING_DECISIONS.md` #62 (Milestone 23's
  `risk_rejections` instrumentation, and its own first real-world use:
  discovering `MAX_TRADES_PER_DAY` explains 89-92% of Legacy's own raw
  signal rejection) — the same instrumentation, never yet pointed at
  Jade; `docs/RESEARCH_STRATEGY_REVIEW.md` section 4 (this hypothesis's
  #1 ranking and rationale among six candidate directions).
- **External**: none specific — this is an internal instrumentation
  reuse question, the same status H5's Step 0 gate and H6 itself had.

### Pre-registered experiment

**No new script needed beyond a thin reporting wrapper** —
`scripts/research_h7_jade_risk_attribution.py` calls `run_backtest.py`'s
own already-existing `run_backtest(chunk, htf, use_jade_engine=True)`
per period (the exact function every other research harness in this
project already reuses) and `aggregate_risk_rejections(results)`
(already built for `run_backtest.py`'s own CLI reporting, Milestone 23)
— no new `BacktestEngine` parameter, no new production code path.

```
python scripts/research_h7_jade_risk_attribution.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2026-07-10
python scripts/research_h7_jade_risk_attribution.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2025-07-10
python scripts/research_h7_jade_risk_attribution.py --symbol BTCUSDT --timeframe 15m --candles 3000 --periods 6 --end-date 2024-07-10
```

(This project's standard 3-anchor set, extending decision #36's original
single-anchor BTCUSDT scope for cross-year confirmation — same
methodological choice H6 made for the same reason.)

For each anchor, reports: `total_signals` (how many times a Jade signal
actually reached `RiskManager.evaluate()`, i.e. survived open-trade
skipping AND entry-model/exit-target gating — the number directly
comparable, for the first time, to H6's own step-level counts),
`approved`/`rejected` and the `by_reason` breakdown, and total real
trades opened (`sum(len(r.trades) for r in results)`, expected to
reproduce decision #36's 6-trade result on the matching single anchor,
confirming this experiment reuses the identical mechanism before
trusting any new number).

**Keep-rule (declared now)** — like H6, this is a diagnostic, not a
promotion candidate, so the rule classifies which stage dominates the
gap rather than KEEP/REJECT a trading behavior:

- **RiskManager-gating-dominant** if, aggregated across the 3 anchors,
  `rejected / total_signals >= 0.5` (at least half of all signals that
  reach RiskManager are turned away by it) AND `MAX_TRADES_PER_DAY` is
  the single most frequent `by_reason` entry — mirroring decision #62's
  own finding for Legacy, extended to Jade.
- **Open-trade/zone-persistence-dominant** if `total_signals` (this
  experiment's count) is less than 25% of H6's own `signal_would_generate`
  count (8,312, aggregated) — meaning most of H6's step-level events were
  the SAME persistent zone re-counted across an open-trade window, not
  distinct opportunities that ever reached RiskManager at all.
- **Both, or neither** are honest, reportable outcomes too (matching
  H4's MIXED precedent) — this hypothesis does not force a single
  dominant-cause narrative if the evidence splits.

### Cost

Very small — smaller than H6. No new detector-level classification
logic (H6's own `_fvg_bucket`/`_same_bar_reject_bucket` machinery), no
per-step manual pipeline walk. Reuses `run_backtest()` and
`aggregate_risk_rejections()` verbatim, both already built and tested
(Milestone 23, and every research harness since). The only new code is
a thin per-anchor fetch-and-aggregate loop, matching
`scripts/research_h5_step0_session_grounding.py`'s own minimal shape.

### Promotion path if RiskManager-gating-dominant or otherwise

**Not a promotion decision either way**, same as H6. A
RiskManager-gating-dominant result would be a genuine, disclosed,
platform-level finding — TWO independently-built strategies (Legacy,
decision #62; Jade, this hypothesis) sharing the same `MAX_TRADES_PER_DAY`
bottleneck — but per `docs/RESEARCH_STRATEGY_REVIEW.md` section 5's
explicit, deliberate restraint, this does NOT authorize or recommend
testing what raising the cap would do. `MAX_TRADES_PER_DAY` stays
exactly as operator-gated as it already is (decision #62); this
hypothesis only measures how much of Jade's OWN scarcity the existing,
already-fixed cap explains, never whether to change it.
`use_jade_engine` stays `False`; `RiskManager.evaluate()` and
`scripts/run_paper.py` are completely unmodified and unaffected by this
round regardless of outcome.

---

## 4. Deferred directions (not pre-registered in full this round)

- **Cross-asset Legacy delay-fragility check (rank 2)**: cheap and
  well-grounded, but confirmatory rather than action-unlocking given
  every proposed fix for the fragility already failed on the one asset
  tested regardless of whether the fragility itself proves universal.
  A candidate for a future round, not excluded.
- **Jade cross-asset scarcity check (rank 4, decision #36 step 2)**:
  explicitly ordered by decision #36 itself to follow, not precede, H6's
  mechanism confirmation — pre-registering it in full before H6 runs
  would violate that decision's own stated ordering. Per
  `docs/RESEARCH_STRATEGY_REVIEW.md` section 4, also deferred behind H7,
  since H6 only partially explained Jade's scarcity mechanism.
- **Jade-FVG-only isolation test (rank 2)**: directly follows H6's own
  selected-model-share finding (FVG wins 76.4% of selections). Deferred
  behind H7 — if H7 finds `MAX_TRADES_PER_DAY` is the dominant
  bottleneck, entry-model composition may not matter much regardless.

---

## 5. Caveats

- **No result exists yet for H7.** H6 (section 2) has a result;
  everything in section 3 (H7) is a proposal, not a report. Every number
  cited in H7's own text is drawn from H6's own already-committed
  results (`docs/H6_JADE_SCARCITY_RESULTS.md`) or decision #36, not from
  any run performed for H7 specifically.
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
