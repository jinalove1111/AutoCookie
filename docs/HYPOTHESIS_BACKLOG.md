# Hypothesis Backlog

Research-platform tooling (Priority 2, rank 2,
`docs/RESEARCH_PLATFORM_ROI_RANKING.md`). Every currently-known,
not-yet-run candidate hypothesis/direction in one scannable table —
check `docs/EXPERIMENT_INDEX.md` first to confirm none of these has
already been tested, then check here before re-deriving "what's next"
from a full `ROADMAP.md` read.

| Candidate | Grounding / source | Status | Why not run yet |
|---|---|---|---|
| **H9 — Farther-target Jade selection: does it improve real Net Profit/win-rate, not just nominal RR?** | H8's own disclosed, explicitly unvalidated caveat (`docs/H8_JADE_RR_SENSITIVITY_RESULTS.md` section 3) | Available, backtest-only-safe | Standing "no new hypotheses without a clear evidence gap" instruction — not auto-started; ready to pre-register on request |
| **Cross-asset Legacy delay-fragility check (ETH/SOL/XRP)** | Deferred since Hypothesis Round 1's own caveats; every H1-H5 doc repeats "not cross-asset checked" | Available, cheap (`--delay-check` already exists) | Confirmatory, not action-unlocking — every proposed fix already failed on BTCUSDT regardless of universality (`docs/PHASE_TRANSITION_REVIEW.md`) |
| **Jade cross-asset scarcity check** | Decision #36's own step (2); `docs/HYPOTHESES_ROUND_2.md` section 5 | Available | Explicitly ordered by decision #36 to follow, not precede, mechanism understanding — H6-H8 only partially explained the mechanism (RR-geometry confirmed structural on stop_model, but the larger 8,312-vs-6 gap driver is still undetermined per H7's own disclosed limits) |
| **`RollingPerformanceSelector` wiring into `run_paper.py`** | Built, milestone 16 — "built but NOT wired," dry-run only | Blocked, not just deferred | Would just always select Legacy anyway — Jade has zero backtest KEEPs, no second viable strategy exists to select between yet (`docs/CTO_PLATFORM_EVALUATION.md` item 11) |
| **Root-cause the PF-methodology discrepancy (research_signal_selection.py's own PF vs. published baseline PF)** | Standing follow-up since Milestone 26 (H1), never resolved | Available | Not prioritized above the validation-phase/CTO-evaluation work this session; a bounded, cheap analysis task, not a full hypothesis |
| **Resolve `DEFAULT_TIMEFRAME` ambiguity (5m vs 15m) and re-run delay-fragility at whichever value is confirmed real** | `docs/PAPER_TRADING_VALIDATION_REPORT.md` Finding #2 | **Blocked on operator** | Requires access to the real deployment `.env`, which is gitignored and not in this repository |

## What this table is not

Not a re-statement of `docs/CTO_PLATFORM_EVALUATION.md`'s whole-platform
improvement ranking (CI, exchange layer, etc.) — those are engineering/
infrastructure items, not hypotheses. Not a re-statement of
`docs/RESEARCH_PLATFORM_ROI_RANKING.md`'s research-TOOLING improvements
(shared harness module, cross-asset infra as CODE, etc.) — this table is
specifically the research QUESTIONS themselves.

## Maintenance note

Same discipline as `docs/EXPERIMENT_INDEX.md`: update in the same
commit that resolves or newly identifies a candidate, not retroactively.
