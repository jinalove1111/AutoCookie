# Research Platform ROI Ranking (Priority 2) — Top 10

CTO deliverable (2026-07-19), operator directive: "Evaluate the existing
research platform. Identify the top 10 highest ROI improvements. Rank
them by Expected Impact, Development Cost, Risk, Time Required, Business
Value. Separate into Immediate/Short-term/Long-term. Implement only
Immediate items that do not affect production behavior."

**Scope, deliberately narrower than `docs/CTO_PLATFORM_EVALUATION.md`
(Milestone 35)**: that document ranked the WHOLE platform (strategy
layer, exchange layer, frontend, CI). This document is scoped
specifically to the research/hypothesis-testing platform: the
`docs/HYPOTHESES_ROUND_*.md` pre-registration discipline, `run_backtest.py`/
`BacktestEngine`, the `scripts/research_h*.py` harness family, and
evidence-tracking. Nothing here re-ranks Milestone 35's items.

---

## Ranking (1-5 scale; Risk inverted, 5 = highest risk)

| Rank | Improvement | Impact | Cost | Risk | Time | Business Value | Bucket |
|---|---|---|---|---|---|---|---|
| 1 | Experiment/evidence tracking index -- a single, queryable ledger of every hypothesis (H1-H8) -> verdict -> results doc -> milestone -> decision# | 5 | 2 | 1 | 1 | 5 | Immediate |
| 2 | Hypothesis backlog table -- every currently-deferred/available candidate (cross-asset checks, H9, etc.) in one scannable table instead of scattered ROADMAP prose | 4 | 1 | 1 | 1 | 4 | Immediate |
| 3 | Shared research-harness base module (the walk-forward step loop + fetch helpers every `research_h*.py` script currently reimplements) | 4 | 3 | 1 | 3 | 4 | Short-term |
| 4 | Cross-asset validation infrastructure (parameterize `SYMBOL`, currently hardcoded `"BTCUSDT"` in every harness) | 4 | 3 | 1 | 3 | 4 | Short-term |
| 5 | Root-cause the PF-methodology discrepancy flagged as a standing follow-up since Milestone 26 (H1) and never resolved | 3 | 2 | 1 | 2 | 3 | Short-term |
| 6 | Pre-registration linter -- mechanically checks a new `HYPOTHESES_ROUND_N.md` section has all required parts (Mechanism/Grounding/Pre-registered experiment/Keep-rule/Cost/Promotion path) before a run is allowed | 3 | 2 | 1 | 1 | 4 | Immediate |
| 7 | Fresh backtest-engine profiling pass (M19/M22 fixed 2 quadratic bottlenecks; 8 more hypotheses have run since, some materially slower than the original baseline -- H8 took far longer than H6) | 3 | 3 | 1 | 2 | 3 | Short-term |
| 8 | Preserve raw JSON evidence artifacts in version control (`scripts/reports/` is entirely gitignored today -- every headline number's raw data exists only on whichever machine produced it) | 3 | 1 | 2 | 1 | 3 | Short-term (needs a size-budget policy decision first, see below) |
| 9 | CI check that every `scripts/research_h*.py` harness at least imports cleanly (catches a broken harness before the next hypothesis round tries to reuse it) | 2 | 1 | 1 | 1 | 2 | Immediate |
| 10 | Fast-iteration flags (`--candles-limit`/dry-run) for research harnesses, so a new harness's own logic bugs (like H8's test-isolation issue, or H6's tie-break bug) surface on a small slice in seconds, not after a 30-45 minute full run | 3 | 2 | 1 | 2 | 3 | Short-term |

**Not re-proposed, checked first**: shadow-mode evidence-accumulation
monitoring already exists in full (`scripts/shadow_status.py`, Milestone
13) — confirmed by reading it before drafting this list, not assumed. It
needs the paper-trading process actually running (Milestone 33's Finding
#4) to accumulate anything, not new tooling.

---

## Immediate items implemented this round (safe, zero production-behavior touch)

**Rank 1 — `docs/EXPERIMENT_INDEX.md`**: a single table of every
hypothesis run so far (H1-H8), its verdict, its full-report doc, its
milestone number, and its `ENGINEERING_DECISIONS.md` entry. Directly
serves this project's own "never duplicate completed work" rule at the
TOOLING level (a 10-second table scan) rather than only the cultural
level (grep across 300KB+ files, which is what every prior round in this
session actually had to do to confirm something hadn't already been
tested).

**Rank 2 — `docs/HYPOTHESIS_BACKLOG.md`**: every currently-known,
not-yet-run candidate direction (H9, cross-asset checks, etc.), each
with its source citation and current status (available / deferred /
blocked), so "what's the best next hypothesis" is a table lookup, not a
`ROADMAP.md` re-read.

Both are pure documentation, read-only relative to every existing
system, and do not touch `scripts/run_paper.py`, `RiskManager`, or any
research harness's own code.

**Rank 6 (pre-registration linter) and rank 9 (harness import-check
CI) were ranked cheap enough to also qualify as Immediate**, but were
not built this round to keep this deliverable's own footprint bounded,
given the number of priorities in the same request — flagged as ready,
not done, consistent with `docs/CTO_PLATFORM_EVALUATION.md`'s own
precedent of not expanding into an unprompted open-ended sprint.

---

## Short-term and Long-term

**Short-term**: ranks 3-5, 7-8, 10 above.

**Long-term**: none specific to the research platform beyond what
`docs/CTO_PLATFORM_EVALUATION.md` already lists (cross-asset validation
of the RR-geometry/delay-fragility findings themselves, as opposed to
the INFRASTRUCTURE to run them cheaply, which is rank 4 above).
