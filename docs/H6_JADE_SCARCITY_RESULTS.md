# H6 — Root-Causing Jade's Signal Scarcity — Milestone 30

Evaluation deliverable (2026-07-19). This closes out `docs/HYPOTHESES_ROUND_2.md`
section 2 (H6): the pre-registered diagnostic testing `ENGINEERING_DECISIONS.md`
#36's disclosed, UNCONFIRMED hypothesis for why the Jade engine produced
only 6 trades vs. Legacy's 47 on identical BTCUSDT 15m data. New
analysis-only harness `scripts/research_h6_jade_scarcity_diagnosis.py`
(+ `backend/tests/test_research_h6_jade_scarcity_diagnosis.py`, 17 tests)
was implemented and verified this round. `RiskManager.evaluate()`,
`scripts/run_paper.py`, and every Jade module (`entry_point_engine.py`,
`jade_trade_plan.py`, `exit_point_engine.py`, `bias.py`) are read but
UNMODIFIED — no trade is ever executed by this harness. Full suite:
773/773 passed (756 prior + 17 new), 0 failures. Every number below is transcribed from
`scripts/reports/research_h6_jade_scarcity_diagnosis.json`.

## 1. Purpose and methodology

**The gap this closes**: `ENGINEERING_DECISIONS.md` #36 (the Jade
engine's first and only A/B result: 6 trades vs. Legacy's 47, 0/6 vs.
6/6 profitable periods, walk-forward FAILED) disclosed an unconfirmed
hypothesis — 3 of Jade's 5 entry models (FVG, Order Block, Breaker
Block) require the CURRENT candle to already be retracing into a zone
(`_last_candle_overlaps_zone`) before producing a candidate, unlike
Legacy's zone selection, which has no same-bar timing requirement — and
named "confirm or rule out the same-bar-retracement-requirement
hypothesis directly" as the single highest-value next step, not yet
undertaken until this round.

**New instrumentation** (read-only, walks every candle exactly like
`scripts/research_signal_selection.py`'s `collect_candidates` phase —
same `MIN_CANDLES - 1` starting index, same no-lookahead
`_advance_htf_cursor` mechanism): at every step, calls
`bias.detect_htf_bias`, then each of `entry_point_engine.py`'s 5
individual entry-model evaluators directly, classifying each of the 3
same-bar models into `no_matching_zone` / `zone_exists_not_retraced` /
`candidate_found` (FVG's own reject reason conflates the first two, so
this re-derives the distinction from `detect_fair_value_gap` directly —
the same function `_evaluate_fair_value_gap` itself already calls, not
new production logic). Also tracks `find_entry_point`'s own
highest-confidence-wins aggregate outcome and, for selected candidates,
whether `exit_point_engine.find_exit_targets` would return empty (the
second gate the real wired pipeline, `SignalEngine._generate_signal_via_jade_engine`,
applies beyond `build_trade_plan` itself).

**Anchors**: BTCUSDT 15m, `--candles 3000 --periods 6`, `--end-date
2026-07-10 / 2025-07-10 / 2024-07-10` — this project's standard 3-anchor
set, extending decision #36's original single-window BTCUSDT scope for
cross-year confirmation of the MECHANISM (not a re-run of the
already-decided A/B trade-count comparison itself, which is unchanged
and not disputed by this round).

## 2. Results, all three anchors

| Anchor | Total steps | Neutral bias | Entry candidate selected | Exit targets empty | Signal would generate |
|---|---|---|---|---|---|
| 2026-07-10 | 17,970 | 14,242 (79.3%) | 3,728 | 62 (1.7%) | 3,666 |
| 2025-07-10 | 17,970 | 15,810 (88.0%) | 2,160 | 19 (0.9%) | 2,141 |
| 2024-07-10 | 17,970 | 15,458 (86.0%) | 2,512 | 7 (0.3%) | 2,505 |
| **3-year total** | **53,910** | **45,510 (84.4%)** | **8,400** | **88 (1.0%)** | **8,312** |

Per-model breakdown, `no_matching_zone` / `zone_exists_not_retraced` /
`candidate_found`, summed across all 3 anchor years:

| Model | Same-bar model? | no_matching_zone | zone_exists_not_retraced | candidate_found | Individual ratio |
|---|---|---|---|---|---|
| fair_value_gap | yes | **0** | 202 | 8,198 | not_retraced/no_zone: undefined (no_zone=0) |
| order_block | yes | 5,004 | 2,070 | 1,326 | 2.42x (no_zone dominates) |
| breaker_block | yes | 7,477 | 438 | 485 | 17.07x (no_zone dominates) |
| premium_discount | no | 0 | 0 | 8,374 | n/a (never rejects on zone-location grounds, per its own docstring) |
| liquidity_raid | no | 0 | 0 | 3,731 | n/a (4,669 `no_candidate` — a different, un-instrumented rejection path) |

`selected_model_counts` (which model `find_entry_point`'s
highest-confidence-wins step actually picked), summed across all 3
years: `fair_value_gap` 6,421, `order_block` 1,316, `breaker_block` 485,
`premium_discount` 178, **`liquidity_raid` 0** — Liquidity Raid never
won the highest-confidence selection in any of the 8,400
entry-candidate-selected steps across all 3 years, despite 3,731
`candidate_found` occurrences of its own.

## 3. Primary keep-rule verdict — decision #36's same-bar-retracement hypothesis

Quoting `docs/HYPOTHESES_ROUND_2.md` section 2's keep-rule verbatim:

> **CONFIRMED** if `zone_exists_not_retraced >= 2x no_matching_zone`
> (aggregated) ... **REJECTED** if `no_matching_zone >= 2x
> zone_exists_not_retraced` (aggregated) ... **INCONCLUSIVE** otherwise.

**Aggregate across all 3 same-bar models and all 3 anchor years**:
`no_matching_zone = 12,481`, `zone_exists_not_retraced = 2,710` — a
4.61x ratio, clearing the REJECTED threshold cleanly.

**VERDICT: REJECTED.** Decision #36's same-bar-retracement hypothesis is
NOT the dominant driver of Jade's entry-model scarcity. The models
overwhelmingly fail to find a MATCHING ZONE AT ALL — not "find one but
miss the exact retracement bar."

**Robustness check (not fragile to the aggregation choice)**: evaluated
per-model rather than pooled, Order Block (5,004 vs. 2,070 = 2.42x) and
Breaker Block (7,477 vs. 438 = 17.07x) BOTH independently clear the
REJECTED bar on their own. The REJECTED verdict is not an artifact of
FVG's near-zero `no_matching_zone` count numerically outweighing the
other two models in the aggregate sum — it holds up model-by-model.

## 4. The substantive finding: the aggregate REJECTED verdict masks real per-model heterogeneity

Evaluated alone, FVG's own numbers (`no_matching_zone=0`,
`zone_exists_not_retraced=202`, `candidate_found=8,198`) would satisfy
the CONFIRMED branch trivially — FVG essentially never lacks a matching
zone. This is a real, disclosed structural consequence of a design
choice: Jade's FVG/OB/Breaker detectors deliberately do NOT apply
`is_zone_mitigated` ("repeated FVG tests do not invalidate the setup"
per spec, `entry_point_engine.py`'s module docstring) and search the
FULL candle history at every step, not a bounded recent window. Over an
~18,000-candle series, the pool of "still-valid, never-invalidated"
matching-direction FVGs only grows — so FVG's `candidate_found` rate
(8,198 of 8,400 non-neutral-bias-and-zone-checked steps, ~97.6%) is
enormous, and it wins `find_entry_point`'s highest-confidence selection
76.4% of the time (6,421 of 8,400) specifically BECAUSE it is almost
always available to compete.

Order Block and Breaker Block are the genuinely zone-scarce models — his
is a real, model-specific finding, not decision #36's originally-framed
"3 same-bar models behave alike" hypothesis. Breaker Block in particular
(17.07x no-zone-to-not-retraced ratio) is overwhelmingly bottlenecked by
zone existence, not timing.

## 5. The larger finding this round surfaces, disclosed honestly and explicitly out of scope

**8,312 `signal_would_generate` steps were found across the 3 anchors —
versus decision #36's already-recorded 6 actual trades in its one-anchor
A/B backtest.** This is NOT a contradiction and NOT a claim that
thousands of trading opportunities are being missed — it is disclosed
here specifically to prevent that misreading:

1. **This harness does not track open-trade state.** `BacktestEngine.run()`'s
   real walk-forward loop stops evaluating new signals while a trade is
   open (the single-open-trade-at-a-time invariant every mode in this
   project respects — `scripts/research_signal_selection.py`'s own
   docstring names this explicitly). This harness evaluates every step
   unconditionally, so its step-level counts cannot be read as a trade
   count.
2. **Jade's own no-zone-mitigation design (section 4) means the SAME
   zone can satisfy `candidate_found` on many consecutive candles** —
   Jade explicitly treats a repeated retest of the same zone as still
   valid, so a single real zone plausibly accounts for many consecutive
   `signal_would_generate` steps, not many independent opportunities.
3. **`RiskManager.evaluate()` gating was NOT measured by this harness at
   all** — `MAX_TRADES_PER_DAY` (already found to reject 89-92% of
   Legacy's own raw signals, `ENGINEERING_DECISIONS.md` #62), the 1:2
   minimum RR rule, and daily/weekly loss limits (`docs/risk_rules.md`)
   all sit downstream of every number in this document and were
   deliberately out of H6's declared scope (`docs/HYPOTHESES_ROUND_2.md`
   section 2 pre-registers entry-model and exit-target attribution only).

**This is disclosed as the most likely remaining explanation for
decision #36's 6-trades result, and as a well-grounded candidate for a
future hypothesis (a natural H7) — explicitly NOT chased further in this
round**, matching decision #36's own precedent of naming a next step
without executing it prematurely in the same round it was found.

## 6. Secondary, disclosed context (not part of the primary verdict)

- **Neutral-bias rate**: 84.4% of all steps across the 3 anchors
  (79.3%/88.0%/86.0% per year). `detect_htf_bias` is the IDENTICAL
  function Legacy's `SignalEngine.generate_signal` already calls on the
  same `htf_candles` series — this is a SHARED constraint on both
  pipelines, not a Jade-specific one, and cannot explain the
  Legacy-vs-Jade differential decision #36 found. Reported here as
  context, per the pre-registration's own framing, not as a competing
  explanation.
- **Exit-target availability is a negligible gate**: only 88 of 8,400
  (1.0%) `entry_candidate_selected` steps had `find_exit_targets` return
  empty. This candidate explanation (named in `docs/HYPOTHESES_ROUND_2.md`
  section 2 as a possible second driver) is effectively ruled out —
  whatever explains the 8,312-vs-6 gap (section 5), it is not this.
- **Liquidity Raid never wins selection** (0 of 8,400 selected steps,
  despite 3,731 `candidate_found` occurrences) — its confidence score is
  evidently always dominated by a competing model when both are present.
  Not investigated further; noted as a minor footnote for any future
  round examining Jade's confidence-ranking logic specifically.

## 7. Promotion path

**NONE — this is a diagnostic, not a promotion candidate.** Per H6's own
pre-registered text: a REJECTED verdict (this round's result) redirects
any future Jade investment away from same-bar-timing tuning and toward
examining why Order Block/Breaker Block formations are structurally rare
under Jade's own detector definitions on this data — NOT toward
decision #36's originally-recommended fix direction (relaxing the
retracement window). `use_jade_engine` stays `False`;
`RiskManager.evaluate()` and `scripts/run_paper.py` are completely
unchanged by this round.

**Legacy's live/paper trading behavior is completely unchanged.** 100%
backtest-only, read-only research round: no `BacktestEngine` parameter
or CLI flag was added, no trade was ever executed by this harness, no
orders placed, no writes to `backend/paper_validation.db`.

## 8. Caveats

- **One asset (BTCUSDT), one timeframe (15m)** — matching decision #36's
  own original scope, extended only to 3 years for cross-year mechanism
  confirmation. Whether this mechanism generalizes to ETH/SOL/XRP is
  open, deferred to `docs/HYPOTHESES_ROUND_2.md` section 1's rank-3 item
  (Jade cross-asset scarcity check, decision #36's own step 2) — which
  that same document explicitly deferred until step (1)'s outcome was
  known. That precondition is now satisfied (REJECTED); whether to run
  the cross-asset check next is an open prioritization question, not
  decided by this document.
- **This hypothesis diagnoses a mechanism; it fixes nothing.** The
  REJECTED verdict does not itself validate or invalidate any specific
  fix direction for Jade's scarcity — it only rules out one candidate
  mechanism and redirects attention toward zone-detection rarity
  (Order Block/Breaker Block specifically) and the un-instrumented
  RiskManager-gating/zone-persistence explanation (section 5).
- **Section 5's 8,312-vs-6 gap is the most consequential open question
  this round surfaces, not a solved one.** Read it as a disclosed,
  well-grounded next-step candidate, not as evidence of a missed trading
  opportunity — the methodological caveats in that section (open-trade
  tracking, zone-persistence, RiskManager gating) are all real reasons
  the two numbers are not directly comparable.
- **No code changed production behavior.** `scripts/research_h6_jade_scarcity_diagnosis.py`
  is a new research-only script, never imported by any production or
  paper-trading path; every Jade module it calls is read, not modified.
