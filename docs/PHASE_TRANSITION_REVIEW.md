# Phase Transition Review — Research (H1-H8) vs. Validation

Strategic review deliverable (2026-07-19), operator directive: "Stop
before starting H9. Review the entire project from H1 through H8...
Recommend the next phase based on evidence, not momentum." This document
does not open, run, or propose running any new hypothesis. It answers
six specific questions about the accumulated evidence base and makes an
explicit recommendation the operator did not pre-authorize a default
answer to — unlike `docs/RESEARCH_STRATEGY_REVIEW.md` (which ranked
future hypotheses within an assumed continuing-research frame), this
document's job is to question that frame itself.

---

## 1. What has actually been learned?

**About Legacy (Strategy A), from H1-H5 (Milestones 25-29)**:

- Legacy's execution-delay fragility is **structural**, not fixable by
  any of four independently distinct mechanisms tried across this and
  prior rounds: a wider ATR-multiple stop floor (REJECTED,
  `docs/ATR_FLOOR_EVALUATION.md`), an entry-confirmation drift gate
  (REJECTED, `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4), passive
  limit-at-level entry (H2, Milestone 28, REJECTED — solved delay
  cleanly, PF retention 0.883-1.003, but destroyed the underlying edge:
  Net Profit inverted sign in 3/3 years), and regime-conditional
  `structure_tp` survival (H3, Milestone 27, REJECTED — 26 of 27
  bucket-year cells never even reached the sample floor to test the
  claim). This is a real, converged, multi-mechanism finding, not one
  failed attempt.
- Legacy's edge depends more on trade **frequency/throughput** than
  per-signal selectivity (H1, Milestone 26, REJECTED — quality-ranking
  the day's top-2 signals lost Net Profit in both tested years because
  it reduced fill count more than it improved per-trade quality).
- `MAX_TRADES_PER_DAY=2` rejects 89-92% of Legacy's own raw signal
  stream (decision #62) — a large, quantified, and deliberately
  untouched lever.
- Backtest-only numbers are silently missing the volatility-scaled
  sizing that has been live in paper trading since Milestone 7 (H4,
  Milestone 25, MIXED) — closed as a correctness gap, not a profitable
  finding, but a real integrity issue in how prior evidence should be
  read.

**About Jade (Strategy B), from H6-H8 (Milestones 30-32)**:

- Jade generates far fewer trades than Legacy on identical data (6 vs.
  47, decision #36) — and the mechanism is now well-characterized across
  three rounds: NOT same-bar entry timing (H6 REJECTED — zones for Order
  Block/Breaker Block simply don't form often; only 2 of the 3 same-bar
  models are meaningfully zone-scarce), and NOT the shared
  `MAX_TRADES_PER_DAY` cap that gates Legacy (H7 — RR-below-minimum is
  92.3% of rejection-reason instances, the cap only 7.3%). Jade's real
  bottleneck is a **reward:risk geometry** problem, confirmed
  **structural** with respect to every already-built `stop_model`
  parameter choice (H8 — 0.92%-0.95% RR≥2.0 qualification regardless of
  which existing stop convention is used).
- **Two independently-built strategies on this platform are bottlenecked
  by two completely different gates** — Legacy by throughput under a
  fixed cap, Jade by trade-quality geometry under a fixed minimum RR.
  This is a genuine, platform-level finding for the Strategy Selection
  Engine question the adaptive-platform pivot exists to answer.
- A real bug was found and corrected in Milestone 30's own harness
  during H8 (tie-breaking order diverged from production's real
  `find_entry_point` selection) — Milestone 30's verdict was unaffected,
  but its narrative explanation was wrong until this round caught it.

**Process-level findings, true of the research program itself**:

- Every REJECT/MIXED across all eight hypotheses has been mechanistically
  explained, not just numerically reported — a real, demonstrated
  discipline, cited here because question 4 depends on whether that
  discipline is still producing NEW mechanism-level information or just
  re-confirming what's already known (see section 4).

---

## 2. Which assumptions have been disproven?

| # | Assumption | Status | Evidence |
|---|---|---|---|
| 1 | Legacy's delay-fragility is patchable with tighter risk/entry mechanics | **DISPROVEN** | 4 independent mechanisms REJECTED (ATR floor, entry-drift gate, H2, H3) |
| 2 | Selecting only the day's highest-quality signals improves Legacy's returns under the fixed cap | **DISPROVEN** | H1: Net Profit worse both years despite PF improving |
| 3 | The Asian-session PF gradient (Test 6) is a real, transferable edge-quality signal | **DISPROVEN on the actual target candidate** | H5 Step 0: gradient held 1 of 3 years, inverted in the best-evidenced year |
| 4 | Same-bar retracement timing explains Jade's signal scarcity (decision #36's own working hypothesis) | **DISPROVEN** | H6: `no_matching_zone` outweighs `zone_exists_not_retraced` 4.6x, and per-model independently |
| 5 | Jade shares Legacy's `MAX_TRADES_PER_DAY`-driven bottleneck | **DISPROVEN** | H7: RR-below-minimum is 92.3% of rejections vs. the cap's 7.3% |
| 6 | Jade's RR shortfall is fixable by an existing, already-built `stop_model` choice | **DISPROVEN** | H8: 0.92%-0.95% regardless of stop_model, holding target fixed |
| 7 | A research harness that reimplements a shared selection function is safe if it "looks equivalent" | **DISPROVEN** | H6's own harness silently diverged from `find_entry_point`'s real tie-break order; caught only because H8 called the real function directly |

Seven concrete, load-bearing assumptions disproven across eight
hypotheses is a genuinely productive rate — this is not a research
program spinning without traction. The question this review actually
needs to answer is not "was this worthwhile" (yes) but "is the SAME KIND
of next hypothesis still the best use of effort" (section 4).

---

## 3. What remains genuinely unknown?

- Whether Legacy's delay-fragility is BTC-specific or general — never
  tested cross-asset, deferred at least twice (Round 1's own caveats,
  Round 2's ranking table rank 2/3).
- Whether Jade's RR-geometry problem is BTC-specific or general — same
  status, never tested.
- Whether a farther-target selection convention for Jade would improve
  REAL Net Profit/win-rate, not just nominal RR — H8 deliberately did
  not measure this (its own disclosed win-rate-blind caveat); this is
  the one clearly constructive, well-grounded hypothesis this review
  identifies as still open (see section 4).
- WHY Order Block/Breaker Block zones are structurally rare on this
  data at the detector level — H6 found the fact, never the
  detector-level cause.
- **Whether verified sub-15-minute (ideally seconds-scale) signal-to-fill
  execution latency is achievable at all on this operator's actual
  infrastructure** — `docs/live_trading_checklist.md`'s Gate #4 hardening
  requires this as a measured, not assumed, hard prerequisite for ANY
  real-capital escalation, and **nothing in H1-H8, or in any prior
  milestone, has ever measured it.** This is not a backtest question at
  all — no amount of further hypothesis research answers it.
- Whether raising `MAX_TRADES_PER_DAY` would help Legacy's Net Profit —
  unknown **by policy**, not incapacity: this project has consistently
  and correctly declined to test it even in disclosed, backtest-only,
  non-acted-upon form (`docs/RESEARCH_STRATEGY_REVIEW.md` section 5),
  and this review does not recommend revisiting that restraint.
- **Whether Legacy's live paper-trading process is currently running at
  all.** `PROJECT_STATUS.md` (as of Milestone 28's writeup) recorded
  PID 24616 as confirmed running. Checked directly for this review
  (`tasklist`, this environment): **no matching process, no Python
  process of any kind is currently running.** This may reflect a
  restarted or different environment rather than an actual production
  outage — this review does not have enough information to distinguish
  those cases — but it is a concrete, disclosed fact this review found
  while gathering evidence, not one carried over from memory, and it
  bears directly on question 5 below.

---

## 4. Are we still exploring the highest-ROI research direction?

**Round 1 (Legacy, H1-H5): No longer — confirmed exhausted, twice now.**
`docs/RESEARCH_STRATEGY_REVIEW.md` (preceding H7) already reached this
conclusion once; nothing since has changed it. Five hypotheses, four
independently distinct mechanisms, zero KEEPs. Further Legacy-delay-fragility
research is explicitly eliminated in that document and this review
agrees.

**Round 2 (Jade, H6-H8): Was highest-ROI through H7; H8 is the inflection
point.** H6 and H7 each answered an explicit, previously-disclosed,
cheap, well-grounded question and produced genuine new mechanism-level
findings. H8 was still worth running — it validated H7's finding cheaply
AND caught a real bug in Milestone 30's own harness, a finding that
would not otherwise have surfaced. But H8 also completed something: it
closed the loop on "is Jade's RR problem fixable by an existing
parameter" with a clean STRUCTURAL answer. **The next hypothesis in the
same diagnostic mode would not be answering a new question — it would
be re-diagnosing a finding already confirmed structural.** Three
consecutive diagnostic-only rounds on the same strategy (H6→H7→H8), each
narrowing the explanation further without yet producing a single
constructive, pre-registerable fix candidate, is this review's own
concrete trigger criterion for a pause (formalized in section 6).

**The one clearly still-highest-ROI-shaped item in the Jade line** is
not diagnostic: does a farther-target selection convention improve real
Net Profit/win-rate, not just nominal RR (H8's own disclosed, explicitly
unvalidated caveat)? This is qualitatively different from H6/H7/H8 — it
is a genuine fix candidate with a real backtest to run, not another
counterfactual sweep. If Jade research continues at all, this review's
answer to question 4 is: **only this**, not a fourth round of
root-causing.

**Compared across BOTH research lines to the non-research alternative**
(section 5): the honest answer is that neither remaining research
direction (a farther-target Jade backtest, or a deferred cross-asset
check) currently outranks the one piece of work this evidence base has
never touched at all — Gate #4's latency-measurement prerequisite —
because that prerequisite blocks progress regardless of which strategy
eventually clears backtest gates, and three consecutive research rounds
have now gone by without anyone addressing it.

---

## 5. Is continued hypothesis research more valuable than moving toward paper trading/implementation?

This question needs a factual correction before it can be answered:
**Legacy is not "moving toward" paper trading — per `CLAUDE.md` and
`README.md`, it has been running in paper trading continuously since
early in this project** (`scripts/run_paper.py` against real OKX data,
no real capital). The real open transition is not backtest-research →
paper-trading; it is paper-trading → **Gate #4, small live validation
with real capital** — and that gate has a hardened, explicit,
**never-yet-measured** prerequisite (section 3).

Given that framing, the comparison this review actually needs to make
is: further backtest-only hypothesis research (on either strategy) vs.
addressing Gate #4's latency-measurement prerequisite, or auditing
Legacy's own accumulated real paper-trading track record.

- **Further Legacy research**: no. Exhausted (section 4).
- **Further Jade diagnostic research**: no, not in the same mode
  (section 4) — only a genuinely constructive hypothesis (farther-target
  Net Profit/win-rate check) remains well-grounded, and even that would
  not change Jade's live/paper eligibility status, since Jade has never
  cleared a single backtest profitability gate regardless of mechanism
  understanding.
- **Gate #4 latency measurement**: this is **not a hypothesis this
  review can pre-register or run** — it requires real infrastructure
  measurement (actual signal-to-fill timing against the operator's own
  exchange connectivity), which is qualitatively different work from
  every one of the eight hypotheses completed so far, and plausibly
  requires operator-level infrastructure decisions (deployment location,
  connection type, whether to invest in low-latency infrastructure at
  all) that are outside this review's authority to decide, only to
  recommend.
- **Auditing Legacy's own paper-trading track record**: this review
  found the paper-trading process is not currently observably running
  (section 3) — before any further conclusion about "how much real
  validation exists already," that fact itself needs the operator's
  attention, since this review cannot distinguish "the live process
  stopped" from "this review ran in a different environment than
  production."

**Answer: no, continued open-ended hypothesis research is not more
valuable right now than addressing either of the two items above** —
but this review does not have the standing or the tooling to execute
either of them itself. Both are recommended to the operator, not
autonomously started.

---

## 6. What objective criteria should trigger the transition from research to validation?

Proposed, mechanically-checkable triggers — stated so a future round can
check them the same way a keep-rule gets checked, not re-litigated from
feeling:

1. **Diagnostic saturation**: N=3 consecutive diagnostic-only hypotheses
   on the same strategy, each narrowing an explanation without producing
   a constructive, pre-registerable fix candidate, should pause that
   line's default continuation. **Already triggered for Jade as of H8**
   (H6→H7→H8).
2. **Constructive-hypothesis-availability gate**: a research line may
   only continue past trigger 1 if a genuinely constructive (not
   re-diagnostic) hypothesis is currently pre-registerable — i.e., a
   real proposed change with a real backtest to run, not another
   counterfactual sweep of an already-structural finding. Jade currently
   has exactly one such candidate (farther-target Net Profit/win-rate),
   not zero — this is why section 4 does not recommend fully retiring
   Jade research, only demoting it below the item in trigger 3.
3. **Prerequisite orthogonality**: if the next live-trading gate has a
   hard prerequisite that NO further backtest research can satisfy
   (Gate #4's measured-latency requirement fits exactly), and that
   prerequisite has gone unaddressed across multiple research rounds,
   it should outrank further backtest hypotheses regardless of their own
   individual ROI. **Already triggered** — three consecutive rounds
   (H6, H7, H8) have passed without this being addressed, and it was
   never addressed in Round 1 either.
4. **Evidence-scarcity ceiling** (already established in
   `docs/RESEARCH_STRATEGY_REVIEW.md`): do not pre-register a new
   regime-/session-conditional hypothesis until either shadow-mode data
   accumulates further or cross-asset pooling raises available sample
   sizes past the n≥20 floor. Standing, not newly triggered.
5. **Sunk-cost check for a strategy with zero backtest KEEPs**:
   continued diagnostic investment in a strategy that has never cleared
   a single profitability gate (Jade: zero KEEPs across 3 hypotheses,
   and decision #36's own original backtest was a clean loss) should be
   weighed against whether ANY plausible fix exists, not just whether
   the next diagnostic question is cheap to ask. This is the qualitative
   judgment behind trigger 1-2 above, stated explicitly so it does not
   get re-derived from momentum next time.

---

## Recommendation

**Based on evidence, not momentum**: pause the default "run the next
hypothesis" cadence. Specifically:

- **Retire Legacy-delay-fragility hypothesis research** as a line —
  confirmed exhausted twice, nothing new to test without a genuinely
  novel mechanism, none currently identified.
- **Demote Jade diagnostic research** below constructive status — do
  not pre-register another root-causing hypothesis; the one remaining
  well-grounded Jade question (farther-target Net Profit/win-rate) is
  constructive, not diagnostic, and could be pre-registered later, but
  is not urgent, since Jade is not currently eligible for any promotion
  regardless of its outcome.
- **Recommend, do not autonomously start, two operator-level decisions**:
  (a) commissioning real signal-to-fill latency measurement against the
  operator's actual execution infrastructure — the single most
  consequential, never-yet-touched, decision-relevant gap this entire
  evidence base has accumulated, and the literal, hardened prerequisite
  for Gate #4; (b) confirming whether Legacy's live paper-trading
  process is still actually running, given this review could not
  observe it running in this environment.
- This review does **not** recommend declaring the research phase
  "complete" outright, nor recommend unilaterally pivoting into
  infrastructure/latency work without operator direction — both are
  judgment calls about resource allocation and physical infrastructure
  that this evidence base can inform but not decide.

No hypothesis was run to produce this document. No production code was
touched. `RiskManager.evaluate()` and `scripts/run_paper.py` were not
modified.
