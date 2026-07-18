# Research Strategy Review — Hypotheses H1-H6

Strategic review deliverable (2026-07-19), operator directive ("before
starting additional hypotheses, perform a strategic research review").
**Scope**: this document does not run or propose running any new
experiment — it synthesizes across all six hypotheses evaluated so far
(H1-H5, Hypothesis Round 1; H6, Hypothesis Round 2's first item),
extracts cross-cutting patterns, inventories what remains untested, and
produces a ranked, evidence-grounded research plan. `ROADMAP.md` carries
a distilled pointer to this document's conclusions, per this project's
"cite, don't duplicate" convention — read the relevant `docs/*_RESULTS.md`
document directly for any individual hypothesis's full numbers; this
review restates only what's needed to support its own cross-hypothesis
conclusions.

---

## 1. Hypothesis-by-hypothesis review: what was tested, verdict, and WHY

### H4 — Close the backtest/live position-sizing gap (Milestone 25, decision #63) — **MIXED**

**Tested**: whether threading `volatility_risk_scalar` (live in paper
trading since Milestone 7, never in backtests) into `BacktestEngine`
materially changes any existing finding.

**Why MIXED, not a clean answer**: the pre-registered 3-branch keep-rule
required 2-of-3 years to land on the SAME branch. Instead each year hit
a DIFFERENT branch — 2024 "confirmed improvement," 2025 "nothing moves,"
2026 alone "materially degrades" (-14.4% Net Profit for a -13.4%
drawdown improvement, not proportionate). This is not evidence the
mechanism is broken; it reflects that the disclosed-not-tuned 0.5x
scalar has a genuinely inconsistent year-to-year cost/benefit trade-off
on this asset — a real, reported, operator-relevant finding (the live
scalar has a real cost in at least one tested year) that stayed
correctly unactioned, per the same operator-gating boundary as
`MAX_TRADES_PER_DAY`.

### H1 — Quality-ranked signal selection within the fixed cap (Milestone 26, decision #64) — **REJECT**

**Tested**: holding `MAX_TRADES_PER_DAY=2` fixed, does taking the day's
2 highest-`rr`/`rr+confluence` signals (instead of FIFO) improve
expectancy?

**Why REJECT**: both ranked variants realized FEWER actual trades than
FIFO under the identical fixed cap (2026: 82/77 vs. 111; 2025: 43/46 vs.
65) — top-ranked candidates cluster in time, so the day's 2nd-ranked
candidate's window frequently overlaps the still-open 1st trade and gets
skipped, while FIFO's real-time arrival naturally spreads fills out.
`rr` won Profit Factor in both years (up to +138.3%) but LOST Net Profit
in both (down to -24.1%) — the throughput lost to clustering cost more
than the per-trade quality gain recovered. **Root mechanism**: Legacy's
edge on this platform scales more with trade FREQUENCY than with
per-trade selectivity, under the current fixed cap.

### H3 — Regime-conditional delay survival of `structure_tp` (Milestone 27, decision #65) — **REJECT**

**Tested**: does `structure_tp`'s variable stop/target geometry survive
a 15-minute entry delay better in specific regime buckets, even though
it fails catastrophically in aggregate?

**Why REJECT**: of 27 bucket-year cells (3 years × 8-10 buckets each),
**26 never even reached the n≥20 delayed-side sample floor** needed to
evaluate the keep-rule meaningfully — only one cell (2026
`weak_trend/normal_volatility`) did, and it still failed decisively on
PF retention (0.170 vs. required 0.5) with a sign flip. **Root
mechanism**: this is a data-availability failure, not necessarily a
mechanism failure — the platform's regime-bucket evidence (mirroring
`docs/REGIME_PERFORMANCE_ANALYSIS.md`'s own 8-of-9-buckets-starved
finding for a completely different exit-logic family) is too sparse at
current trade volume to test ANY regime-conditional hypothesis with
confidence, this one included.

### H2 — Passive limit-at-level entry (Milestone 28, decision #66) — **REJECT**

**Tested**: does resting a limit order at the structural zone edge
(instead of an immediate market fill) remove the delay-fragility Legacy
and `structure_tp` both share?

**Why REJECT, in two parts**: Check 2 (delay-robustness) PASSED cleanly
3/3 years (PF retention 0.883-1.003, no sign flip) — mechanistically
correct, since a resting order's fill price genuinely doesn't depend on
placement latency. But Check 1 (cost-of-passivity) FAILED catastrophically
0/3 years — Net Profit inverted sign in every year despite trade count
dropping only modestly (13-21%). **Root mechanism**: waiting for a
retest of the zone edge systematically selects for structurally WORSE
trade outcomes independent of delay — it filters OUT the
immediate-continuation setups that drove Legacy's actual edge. H2 fixed
the disease (delay-fragility) by removing the part of the edge that
caused it.

### H5 — Session-conditional position sizing (Milestone 29, decision #67) — **REJECT at Step 0**

**Tested**: pre-registered in full this project (mechanism/grounding/
keep-rule built from evidence on record, not fabricated), then ran its
own Step 0 gate: does the Asian>London session profit-factor gradient
(`docs/ROBUSTNESS_REPORT.md` Test 6) replicate on the candidate/timeframe
H5 would actually size (BTCUSDT 15m, Legacy)?

**Why REJECT**: Test 6's gradient was measured on a DIFFERENT
candidate/timeframe (BTCUSDT 5m, the `structure_tp` candidate). Re-measured
on the correct candidate, the gradient direction held in only 1 of 3
years — and in the platform's best-evidenced year (2026, 111 trades) it
INVERTED (London beat Asian). **Root mechanism**: a session-quality
characterization is not a transferable property across a strategy's
exit-logic family or timeframe. This is the one failure in this set that
is methodological rather than mechanistic — the underlying sizing idea
was never actually tested on real Legacy/15m data; its motivating
evidence simply didn't survive being checked against the right
candidate.

### H6 — Root-cause Jade's signal scarcity (Milestone 30, decision #68) — **REJECTED**

**Tested**: decision #36's own disclosed, unconfirmed hypothesis — does
the same-bar-retracement requirement on 3 of Jade's 5 entry models
(FVG/Order Block/Breaker Block) dominantly explain why Jade generated 6
trades vs. Legacy's 47 on identical data?

**Why REJECTED**: aggregate `no_matching_zone` (12,481) outweighs
`zone_exists_not_retraced` (2,710) by 4.61x — Order Block (2.42x) and
Breaker Block (17.07x) both independently clear the REJECT threshold
too. **Root mechanism**: these entry models overwhelmingly fail to find
a matching ZONE at all; same-bar timing is a minor factor at most. A
secondary, disclosed finding sharpened the picture further: FVG (the
third same-bar model) is essentially UNCONSTRAINED — Jade's deliberate
no-zone-mitigation design lets old FVGs accumulate indefinitely, so a
matching FVG exists 97.6% of the time. **Important limit on this
result**: H6 only explains part of the 6-vs-47 gap. 8,312 step-level
"would generate a signal" events were found across the 3 anchors — the
gap between that number and 6 real trades is explicitly NOT attributed
by this hypothesis (open-trade-state tracking, zone-persistence
double-counting, and `RiskManager.evaluate()` gating were all outside
H6's declared scope) — named as the top candidate for the next
hypothesis, not chased in the same round.

---

## 2. Common failure patterns across H1-H6

**Pattern A — Throughput beats selectivity/refinement on this
platform, every time it has been tested.** H1 (explicit finding),
H2 (a structurally different mechanism, same outcome: fewer, more
"deliberate" fills lost badly), and the platform's own
`MAX_TRADES_PER_DAY` disclosure (decision #62, 89-92% of Legacy's raw
signals rejected by the cap alone) all point the same direction: every
mechanism tested so far that reduces trade count or delays/filters
fills — regardless of how sound its individual rationale — has lost
Net Profit relative to the higher-throughput baseline. This is the
single most load-bearing cross-hypothesis finding in the evidence base.

**Pattern B — Evidence scarcity invalidates sub-bucketed (regime- or
session-conditional) hypotheses before their actual mechanism can be
tested.** H3 (26 of 27 regime-bucket-year cells never reached the n≥20
floor) and H5 (thin, pooled session samples whose gradient didn't even
replicate on the right candidate) both failed for reasons rooted in
DATA VOLUME, not necessarily because regime- or session-conditioning is
the wrong idea. Legacy generates 47-111 trades per year; Jade generates
~6. Neither supports fine-grained bucketing with statistical confidence
at current trade volume. This is a standing ceiling on an entire CLASS
of future hypotheses, not a fact specific to H3 or H5.

**Pattern C — Motivating evidence must be re-verified on the exact
target candidate; it does not transfer silently.** H5's specific,
root-caused failure (Test 6 measured on 5m/`structure_tp`, applied to
15m/Legacy) is the clean instance, but the lesson generalizes: any
future hypothesis that cites a number from one candidate's evaluation
as grounding for changing a DIFFERENT candidate must re-verify that
number on the actual target first (H5's own "Step 0 gate" invention).
This should be treated as a standing pre-registration requirement for
this evidence base going forward, not a one-off fix specific to H5.

**Pattern D — A hypothesis scoped to one named mechanism can miss the
actual dominant driver sitting in an adjacent, unexamined pipeline
stage.** Decision #36 named one plausible mechanism for Jade's scarcity
(same-bar retracement); H6 correctly rejected it, but doing so surfaced
a much larger, completely unexplained gap (8,312 vs. 6) sitting entirely
outside H6's declared scope. Where instrumentation is cheap (as it was
for H6 — pure read-only analysis over already-built functions), a
hypothesis should default to a WIDER pipeline-attribution net rather
than testing one named mechanism in isolation.

**Pattern E (process strength, not a finding to act on) — every
REJECT/MIXED has been mechanistically explained, not just numerically
reported.** No hypothesis in this set stopped at "the number didn't
clear the bar" — each one identifies WHY, with a disclosed root
mechanism. This is what makes Patterns A-D possible to state with
confidence; it is a property of this project's research discipline, not
a fact about the trading platform.

---

## 3. Untested assumptions

1. **Whether Legacy's structural delay-fragility is BTC-specific or
   asset-general.** Every delay-fragility finding and every rejected fix
   (ATR floor, entry-drift gate, H2, H3) is BTCUSDT-only. Cheap to check
   (`--delay-check` already exists), but not action-unlocking on its own
   — see section 5, item 3.
2. **Whether Jade's Order Block/Breaker Block zone-scarcity (H6) is
   BTC-specific or general.** Decision #36's own step (2). Technically
   unblocked by H6's verdict, but H6 itself only partially explained the
   scarcity — see item 3 below and section 5's ranking.
3. **Whether `RiskManager.evaluate()` gating (`MAX_TRADES_PER_DAY`,
   RR≥1:2, daily/weekly loss limits) is the dominant remaining
   explanation for Jade's real 6-trade count**, beyond entry-model zone
   scarcity. H6's own named, disclosed, unexecuted next step.
4. **Whether isolating Jade to its FVG model alone** (which wins
   `find_entry_point`'s selection 76.4% of the time and is nearly
   unconstrained, per H6) **would perform differently from the full
   5-model ensemble.** Never tested — could reveal whether Jade's poor
   aggregate result is being dragged down by its other 4 models, or
   whether FVG itself is a weak signal independent of the ensemble.
5. **Whether the `MAX_TRADES_PER_DAY=2` cap represents a quantifiable
   Net-Profit opportunity if relaxed.** Decision #62 already disclosed
   the rejection rate (89-92% of raw signals) but never quantified the
   counterfactual. **This review does NOT recommend testing this**, even
   in a disclosed, backtest-only, non-acted-upon form — see section 6.
6. **Whether H4's inconsistent year-to-year MIXED result would resolve
   more cleanly on a larger asset set.** Never tested cross-asset. Low
   priority: H4 isn't actionable regardless of outcome (operator-gated).
7. **Whether the 4 quarantined experimental strategies (Milestone 9/10)
   would behave differently under the regime-tagging tooling that has
   matured since their last evaluation.** Already tested twice (Milestone
   10 aggregate, Milestone 12 regime-tagged), both REJECTED cleanly.
   Lowest priority — no new reason to revisit has surfaced.

---

## 4. Ranked future research directions

| Rank | Direction | Grounding | Testability | Cost | Why |
|---|---|---|---|---|---|
| **1** | **H7 — RiskManager/pipeline-gating attribution for Jade's real trade count** (item 3) | 5 | 5 | 1-2 | Directly extends H6's own harness (add `RiskManager.evaluate()` + open-trade-state tracking + zone-persistence dedup to the same walk). Resolves the single largest disclosed-but-unexplained gap in the evidence base (8,312 vs. 6). If `MAX_TRADES_PER_DAY` turns out to gate Jade the same way decision #62 found it gates Legacy, that is a unifying, platform-level finding about both strategies sharing one bottleneck — the highest information-density experiment currently available. |
| 2 | Jade-FVG-only isolation test (item 4) | 4 | 4 | 2-3 | Directly follows H6's own selected-model-share finding. Needs a modest new opt-in flag (more cost than H6's pure analysis). Should follow H7, not precede it — if H7 finds the cap is the dominant bottleneck, entry-model composition may not matter much regardless of FVG-only vs. full-ensemble. |
| 3 | Cross-asset Legacy delay-fragility check (ETH/SOL/XRP, item 1) | 4 | 5 | 2 | Cheap (`--delay-check` already exists, zero new code). Confirmatory, not action-unlocking: every proposed FIX for the fragility already failed on BTCUSDT regardless of whether the fragility itself is universal. Worth doing eventually for evidence-base completeness, not urgent. |
| 4 | Jade cross-asset scarcity check (decision #36 step 2, item 2) | 4 | 4 | 2 | Technically unblocked by H6's verdict, but H6 itself found the mechanism only PARTIALLY explains the scarcity (section 1). Running this before H7 resolves the residual risks replicating a still-incompletely-understood phenomenon across assets — defer until after H7. |
| 5 | H4 cross-asset re-check (vol-scaled sizing on ETH/SOL/XRP, item 6) | 3 | 4 | 2 | H4's MIXED result isn't actionable regardless of outcome (operator-gated territory, same as `MAX_TRADES_PER_DAY`) — lower urgency than directions that could actually change what gets built next. |
| 6 | Re-examine quarantined experimental strategies under matured regime tooling (item 7) | 2 | 3 | 3+ | Already tested twice, twice cleanly REJECTED. No new reason to revisit has surfaced this round. |

---

## 5. Eliminated / deprioritized research paths

- **Any further Legacy delay-fragility FIX attempt** (a fifth mechanism
  after ATR floor, entry-drift gate, H2, H3 — four independently
  distinct mechanisms, all REJECTED). This line is exhausted on current
  evidence; the only remaining legitimate action here is the
  cross-asset CONFIRMATION at rank 3 above, not a new fix hypothesis.
- **Any further regime- or session-conditional hypothesis that does not
  first budget for the n≥20 sample floor across enough years/assets to
  plausibly clear it.** H3 and H5 both demonstrate this class of
  hypothesis is currently data-starved BY CONSTRUCTION at this
  platform's trade volume. Do not propose another one until either
  shadow-mode data accumulates further (Milestone 11's
  `ENABLE_SHADOW_STRATEGY_SIGNALS`, still operator-gated/off) or
  cross-asset pooling meaningfully raises available sample sizes.
- **Re-litigating `MAX_TRADES_PER_DAY` via a "what if we raised it"
  backtest sensitivity study** (untested assumption #5 above) — explicitly
  NOT recommended, even framed as disclosed-not-acted-upon research.
  This project's own established discipline (H1 explicitly tested
  selection WITHIN the fixed cap rather than the cap itself; decision
  #62 recorded the opportunity "as an insight, explicitly not acted on")
  treats even a backtest-only counterfactual of a risk-limit constant as
  close enough to the operator-gated boundary that generating "the
  evidence suggests we should raise it" momentum is itself a risk worth
  avoiding without explicit prior authorization. This review is
  consistent with that restraint, not a relaxation of it.

---

## 6. Recommendation: H7, RiskManager/pipeline-gating attribution for Jade

**Single highest expected-value hypothesis to run next**: an extension
of H6's own harness (`scripts/research_h6_jade_scarcity_diagnosis.py`)
to track open-trade state (so step counts stop overcounting repeated
retests of the same persistent zone) and route every step that would
generate a `TradeSignal` through the real, unmodified
`RiskManager.evaluate()` — measuring how much of the 8,312-vs-6 gap
(section 1's H6 review) is explained by `MAX_TRADES_PER_DAY`/RR/loss-limit
rejection versus zone-persistence overcounting.

**Why this is the top pick, not merely next in queue**: it is the
cheapest available experiment (extends existing, already-tested
analysis code — no new `BacktestEngine` parameter, no CLI flag, same
read-only discipline as H6), it is the most directly grounded (named
explicitly by H6's own results, which were in turn named by decision
#36), and it has a real chance of producing a platform-level unifying
finding — if `MAX_TRADES_PER_DAY` gates Jade the way it already gates
Legacy (decision #62), that reframes the adaptive platform's entire
Strategy Selection Engine question: TWO independently-built strategies
sharing the same bottleneck is a materially different situation than
"Legacy has a quirk" or "Jade has a quirk," and is exactly the kind of
structural finding the adaptive-platform pivot exists to surface.

**Scope discipline for H7, stated now, before any pre-registration**:
same as every hypothesis in this evidence base — diagnostic only, no
new production code path, `use_jade_engine` stays `False`, and even a
result implicating `MAX_TRADES_PER_DAY` would be reported as a finding,
not acted on, per the same operator-gated boundary decision #62 and H1
already established.
