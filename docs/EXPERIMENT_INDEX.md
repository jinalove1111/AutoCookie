# Experiment Index

Research-platform tooling (Priority 2, rank 1,
`docs/RESEARCH_PLATFORM_ROI_RANKING.md`). A single, queryable ledger of
every pre-registered hypothesis run so far — check here FIRST before
proposing or pre-registering anything new, to satisfy this project's own
"never duplicate completed work" rule at the tooling level rather than
only the cultural one (every prior round in this session had to confirm
"has this been tested" by grepping across `ENGINEERING_DECISIONS.md`/
`PROJECT_STATUS.md`, both 300KB+ files). Cite, don't duplicate: this
table points at full reports, it does not restate their content.

## Hypothesis Round 1 (Legacy, Strategy A)

| ID | Question | Verdict | Milestone | Decision # | Full report |
|---|---|---|---|---|---|
| H4 | Does closing the backtest/live position-sizing gap (vol-scaled sizing) change any existing finding? | **MIXED** (3-branch keep-rule didn't resolve to one answer across years) | 25 | #63 | `docs/H4_SIZING_PARITY_RESULTS.md` |
| H1 | Does quality-ranked signal selection (within the fixed daily cap) beat FIFO? | **REJECT** (wins PF, loses Net Profit, both years) | 26 | #64 | `docs/H1_SIGNAL_SELECTION_RESULTS.md` |
| H3 | Does `structure_tp`'s variable stop/target survive delay better in specific regimes? | **REJECT** (evidence-scarcity-compounded; 26/27 bucket-year cells below sample floor) | 27 | #65 | `docs/H3_REGIME_DELAY_RESULTS.md` |
| H2 | Does a passive limit-at-level entry fix Legacy's delay-fragility? | **REJECT** (delay-robust cleanly, but destroys the underlying edge) | 28 | #66 | `docs/H2_LIMIT_ENTRY_RESULTS.md` |
| H5 | Does session-conditional (Asian/London) position sizing improve Legacy? | **REJECT at Step 0** (motivating gradient doesn't transfer across candidate/timeframe) | 29 | #67 | `docs/H5_SESSION_GROUNDING_RESULTS.md` |

**Round 1 status: fully resolved, zero KEEPs.** Legacy's execution-delay
fragility is confirmed STRUCTURAL across 4 independently distinct fix
mechanisms (H2, H3, plus the pre-Round-1 ATR floor and entry-drift gate
below) — do not propose a 5th fix attempt without a genuinely new
mechanism; see `docs/PHASE_TRANSITION_REVIEW.md`'s own "diagnostic
saturation" / eliminated-paths reasoning before proposing one.

## Hypothesis Round 2 (Jade, Strategy B)

| ID | Question | Verdict | Milestone | Decision # | Full report |
|---|---|---|---|---|---|
| H6 | Does the same-bar-retracement requirement (3 of 5 entry models) explain Jade's signal scarcity? | **REJECTED** (zone absence dominates 4.6x over mistiming) | 30 | #68 | `docs/H6_JADE_SCARCITY_RESULTS.md` (correction banner added after H8, section 4 narrative superseded, verdict unaffected) |
| H7 | Does `RiskManager` gating (`MAX_TRADES_PER_DAY`) explain the H6-disclosed 8,312-vs-6 gap? | **RISK_GATING_DOMINANT (literal)** / **RR-below-minimum actually dominant (92.3%) once pooled by category, not exact string** | 31 | #69 | `docs/H7_JADE_RISK_ATTRIBUTION_RESULTS.md` |
| H8 | Does an existing `stop_model`/target-selection choice fix Jade's RR-geometry bottleneck? | **STRUCTURAL** on stop_model (no meaningful difference) / **PARAMETER_SENSITIVE (literal, not endorsed)** on target-index (win-rate-blind) | 32 | #70 | `docs/H8_JADE_RR_SENSITIVITY_RESULTS.md` |

**Round 2 status: open.** H6-H8 diagnosed Jade's scarcity mechanism in
increasing precision; no constructive fix has been tested yet. See
`docs/HYPOTHESIS_BACKLOG.md` for what's next.

## Pre-Round-1 foundational findings (cited throughout Round 1/2, not re-litigated)

| Finding | Verdict | Source |
|---|---|---|
| ATR stop-distance floor as a delay-robustness fix | **REJECTED** (thins population, doesn't confer robustness) | Milestone 20, decision #60, `docs/ATR_FLOOR_EVALUATION.md` |
| Entry-confirmation drift gate (`max_entry_drift_pct`) | **REJECTED** (inconsistent/partial across years) | `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 4 |
| Asian-session-only entry filter | **REJECTED** (uniformly worse Net Profit/PF/Sharpe both years) | `docs/CONTINUOUS_RESEARCH_LOG.md` Experiment 3 |
| Legacy delay-fragility, cross-year confirmation | **STRUCTURAL**, confirmed 3-for-3 years | Milestone 24, decision #62, `docs/LEGACY_DELAY_ROBUSTNESS.md` |
| Jade engine, first A/B result (predates decision #63's sizing gap fix) | **Clean negative** (6 trades vs. Legacy's 47, 0/6 profitable periods) | Decision #36 |

## Cross-cutting synthesis (do not re-derive, cite directly)

- `docs/RESEARCH_STRATEGY_REVIEW.md` — full H1-H6 review: 5 cross-cutting
  patterns, untested-assumption inventory, 6 directions ranked by ROI,
  3 paths explicitly eliminated.
- `docs/PHASE_TRANSITION_REVIEW.md` — 6-question review of all 8
  hypotheses; recommended pausing the default hypothesis cadence in
  favor of validation-phase work.
- `docs/PAPER_TRADING_VALIDATION_REPORT.md` — 6 findings from direct
  pipeline verification (not backtest research): a critical bug (fixed,
  decision #72), a config ambiguity (open), an infrastructure gap
  (open), and 3 more.
- `docs/CTO_PLATFORM_EVALUATION.md` — whole-platform ROI ranking
  (11 items), CI pipeline added, dormant exchange-abstraction layer
  surfaced.
- `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` — planning-only
  roadmap for the exchange layer (not yet implemented).

## Maintenance note

Add a new row here whenever a hypothesis resolves (H9 onward) — this
table's own value depends on staying current. Do not let it drift stale
the way `CLAUDE.md`'s own milestone count is explicitly tolerated to
(`CLAUDE.md` section 7 says as much about itself) — this index should be
updated in the SAME commit that closes out a hypothesis, not
retroactively.
