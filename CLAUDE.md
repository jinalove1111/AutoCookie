# CLAUDE.md — JadeCap Automated Trading Bot

Orientation for a fresh Claude Code session working in this repo. This
file points at the authoritative docs rather than restating them — this
project's own convention is "cite, don't duplicate," and this file
follows it too. Read the linked doc before acting on anything summarized
here.

## 1. What this project is

JadeCap is a Smart-Money-Concepts (SMC/ICT-style) crypto trading bot,
originally built to progress one strategy ("Legacy") through a staged
validation pipeline — **Backtest → Paper → Small Live → Full Live**
(`README.md`) — before any real capital is at risk.

**Objective pivot (2026-07-15, operator directive, see `ROADMAP.md`
"Objective change")**: the goal changed from "find one profitable
strategy" to **"build an adaptive trading system that survives changing
market conditions."** This was not a stylistic reframing — it reversed an
explicit prior scope lock. The trigger: six consecutive research
experiments (`docs/CONTINUOUS_RESEARCH_LOG.md`) exhausted the reasonable
parameter space for fixing Legacy's execution-delay fragility (its
backtested edge collapses under a single candle of entry delay) without
finding a fix. Rather than keep tuning, the operator concluded the
single-strategy framing itself was wrong. Legacy was reframed as
**"Strategy A"** — one module in a multi-strategy platform being built
around a Market Regime Detector, a common Strategy interface, and a
Strategy Selection Engine — see `docs/ADAPTIVE_ARCHITECTURE.md`. A second
existing-but-unwired strategy (Jade) became "Strategy B." Legacy itself
was, and remains, untouched by this pivot.

As of this writing the platform has run a full research-company loop
(Research → Hypothesis → Experiment → Evaluation, see section 4 below)
against Legacy's own delay fragility and against several proposed fixes
— all four tested delay-robustness ideas so far have been REJECTED on
evidence, and Legacy's delay fragility is now confirmed **STRUCTURAL**
(3-for-3 years tested). See milestones 24/27/28 in `PROJECT_STATUS.md`
and `ROADMAP.md` for the current state of that line of inquiry.

## 2. Current production state — hard constraint, not a suggestion

**Legacy is the ONLY strategy currently authorized for live/paper
trading.** Every other strategy (Jade, the four quarantined experimental
strategies in `app.strategy.experimental`, any research-only harness
output) is backtest-only or shadow-only until an explicit, evidence-gated
operator decision promotes it.

Two files are the live-trading path and require **explicit operator
gating before modification**, not just normal code review — this
boundary has been consistently respected across Milestones 25-28's
backtest-only research work, none of which touched either file:

- `RiskManager.evaluate()` (`app.risk.risk_manager`) — the gate every
  trade signal must pass before execution.
- `scripts/run_paper.py` — the live paper-trading loop, currently running
  continuously against real OKX market data (no real capital).

`LIVE_TRADING_ENABLED` defaults to `false` (`README.md` "Safety Note").
Real order placement requires deliberately setting it plus
`TRADING_MODE=live`, and only after every item in
`docs/live_trading_checklist.md` is satisfied — see section 5 below.

If a task requires changing either file's behavior, treat that as
requiring explicit operator sign-off before implementation, not just
before merge.

## 3. Architecture

Full system design: `docs/architecture.md` (the original 6-layer design:
Data / Strategy / Risk / Execution / Portfolio-Journal / Dashboard, plus
the folder structure and module responsibility table) and
`docs/ADAPTIVE_ARCHITECTURE.md` (the adaptive-platform layer built on top
of it: Market Regime Detector, Strategy interface/registry, Strategy
Selection Engine, Performance Database extensions, continuous
evaluation/auto-disable — see section 7's milestone table for what's
built vs. planned).

Do not duplicate either document's content here — read them directly.
The one-line mental model: `Market Data → Regime Detector → Strategy
Selector → {Legacy | Jade | ...} → Risk Engine → Execution → Performance
Evaluation → (loops back into Strategy Selection)`. Every stage that
already existed pre-pivot (Data, Risk, Execution) is reused unmodified;
every new stage is additive.

## 4. The research workflow

This is the most important cultural fact about this repository. Read
`docs/HYPOTHESES_ROUND_1.md` as the working template before running or
proposing any experiment.

**Pre-registration discipline**: every hypothesis is declared, in full,
*before* any run —

- **Mechanism**: the falsifiable claim, grounded in this platform's own
  accumulated evidence (not a fresh idea from nowhere).
- **Citation**: internal evidence (prior results docs) and, where
  relevant, external literature.
- **Exact experiment invocation**: the literal `run_backtest.py` (or
  research-harness) command line(s) that will be run, on named anchors.
- **Keep-rule**: the exact, mechanically-checkable pass/fail criterion,
  written down before the run — not adjusted after seeing results.

A result only earns **KEEP** if the pre-declared criterion is met **as
written**. A future round that revisits a hypothesis must quote its
existing keep-rule, not restate it from memory or re-derive a "similar"
one.

**Negative and mixed results are first-class, documented outcomes**, not
failures to hide or bury. Precedent: H4 (`docs/H4_SIZING_PARITY_RESULTS.md`)
resolved **MIXED** — its 3-branch keep-rule genuinely did not resolve to
one answer across years, and that was reported honestly rather than
rounded toward a cleaner story. H1 (`docs/H1_SIGNAL_SELECTION_RESULTS.md`),
H3 (`docs/H3_REGIME_DELAY_RESULTS.md`), and H2
(`docs/H2_LIMIT_ENTRY_RESULTS.md`) all resolved **REJECT**, each recorded
with its full mechanism and evidence, not deleted or minimized.

**H5 is a cautionary example of the discipline's boundary**: it exists
only as a ranking-table row in `docs/HYPOTHESES_ROUND_1.md` (section 1),
not a full pre-registered section like H1-H4. The operator/CTO explicitly
declined to fabricate a full spec for it after the fact — if you are
asked to implement H5, read section 1's ranking-table entry and the
"Rejected ideas" cross-reference (section 6) directly, confirm which
section actually carries its full mechanism/keep-rule text before
treating anything as authoritative, and do not invent the missing
pre-registration yourself.

**New backtest features are opt-in, default off, byte-identical when
unset.** Examples: `--vol-scaled-sizing`, `--structure-tp`,
`--limit-at-level`. This is verified, not assumed — recent milestones
include dedicated regression tests proving the flag's disabled path is
byte-for-byte identical to pre-flag behavior. Follow this pattern for any
new backtest-affecting flag.

**Every completed research round updates the same 6-7 files** — for
consistency, treat this as a checklist for any research-round writeup:

1. `PROJECT_STATUS.md` — a new numbered milestone entry.
2. `ROADMAP.md` — close out the milestone, queue the next item.
3. `CHANGELOG.md` — chronological entry.
4. `ENGINEERING_DECISIONS.md` — a new numbered decision entry (rationale).
5. `docs/ADAPTIVE_ARCHITECTURE.md` — section 7's milestone table gets a
   new row.
6. `HANDOFF.md` — a new Korean-language session-log entry (see below).
7. A canonical results doc under `docs/` (e.g. `docs/H2_LIMIT_ENTRY_RESULTS.md`)
   with the full numbers, cited (not duplicated) from the other six.

`HANDOFF.md`'s working language is Korean, established convention — its
entries follow a `## 상태: (...)` narrative summary plus a `## 전체 회차
(...)` checklist-of-bullets pattern per round. Match that pattern if
asked to write a HANDOFF entry.

## 5. Production rules / safety gates

Full rule sets: `docs/risk_rules.md` (Risk Engine rules — RR minimum
1:2, `MAX_DAILY_LOSS_PERCENT`, `MAX_WEEKLY_LOSS_PERCENT`,
`RISK_PER_TRADE_PERCENT`, `MAX_TRADES_PER_DAY`, daily/weekly UTC-calendar
boundary convention, circuit-breaker behavior) and
`docs/live_trading_checklist.md` (the 10-item pre-real-order checklist,
plus the Gate #4 hardening below). Do not duplicate either document's
rule text — read it directly before touching risk logic.

**Risk-limit constants are operator-gated, worked example:
`MAX_TRADES_PER_DAY`.** Milestone 24 (`ENGINEERING_DECISIONS.md` #62)
found that this cap — not signal scarcity — explains most of Legacy's
regime-bucket evidence starvation (92.5% of raw signals rejected in the
2025 anchor, 100% of fired rejections were the daily-cap reason). This
finding was recorded **as an insight, explicitly not acted on**: changing
a risk-limit constant changes real trading behavior (position frequency,
aggregate risk exposure) and requires the same A/B-evidence-before-
enabling discipline as any other risk-affecting change, gated by the
operator, never inferred as "the evidence suggests we should raise it."
Treat any request to change a `Settings` risk constant the same way,
regardless of how compelling the evidence looks.

**Gate #4 (small live validation) is hardened, not just gated by
approval.** `docs/live_trading_checklist.md`'s Gate #4 now requires
*verified, measured* low-latency execution infrastructure as an explicit
hard prerequisite — not backtest/paper numbers alone — because Legacy's
edge has been shown not to survive a 15-minute (1-candle) entry delay,
confirmed structural across two independent years
(`docs/LEGACY_DELAY_ROBUSTNESS.md`).

## 6. Where to look for X

| Question | File |
|---|---|
| Current state, right now | `PROJECT_STATUS.md` |
| What's next, and why | `ROADMAP.md` |
| Chronological history | `CHANGELOG.md` |
| Why a specific engineering choice was made | `ENGINEERING_DECISIONS.md` (numbered entries) |
| Session-by-session log (Korean) | `HANDOFF.md` |
| A specific past research result | the relevant `docs/*_RESULTS.md`, or the originating `docs/HYPOTHESES_ROUND_1.md` / `docs/HYPOTHESES_ROUND_2.md` / `docs/RESEARCH_ROUND_1.md` section |
| Has hypothesis X already been tested? (check before proposing anything new) | `docs/EXPERIMENT_INDEX.md` |
| What's the next best hypothesis/improvement to pursue? | `docs/HYPOTHESIS_BACKLOG.md` (research), `docs/CTO_PLATFORM_EVALUATION.md` (whole platform), `docs/RESEARCH_PLATFORM_ROI_RANKING.md` (research tooling specifically) |
| Plan for real exchange order-placement infrastructure (Gate #4) | `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` (planning only, not implemented, needs approval) |
| System architecture (pre-pivot layers) | `docs/architecture.md` |
| Adaptive-platform design (regime detector, selector, milestones) | `docs/ADAPTIVE_ARCHITECTURE.md` |
| Legacy strategy logic (the only strategy live) | `docs/strategy_spec.md` |
| Risk Engine rules | `docs/risk_rules.md` |
| Live-trading gates | `docs/live_trading_checklist.md` |
| DB schema (draft; `backend/app/database/models.py` is authoritative) | `docs/database_schema.md` |
| API key handling practices | `docs/api_keys_security.md` |
| How to run tests | `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q` (project venv is `backend/.venv`; system Python has no pytest installed) |
| How to run a script (`run_paper.py`, `run_backtest.py`, etc.) | needs `PYTHONPATH` set to the `backend/` directory and `DATABASE_URL` set explicitly (`scripts/*.py` have no `sys.path` bootstrap and `settings.DATABASE_URL` defaults to empty). See `.claude/settings.local.json`'s allowed commands for working invocation examples. |

## 7. Milestone count

The current milestone count is **35** as of this writing (2026-07-19,
commit `91c1f29`). This number increments once per completed
research/engineering round and both `PROJECT_STATUS.md` and
`ROADMAP.md`/`docs/ADAPTIVE_ARCHITECTURE.md` section 7 are updated
together whenever it does. Do not predict or hardcode what the next
milestone number will contain — `ROADMAP.md`'s "Next experiment"/"Next
research action" note is the live source for that, and it will already
be stale by the time this file is read again.

**Phase note (2026-07-19, do not let this go stale without checking
`ROADMAP.md` first)**: Hypothesis Round 1 (Legacy, milestones 25-29) and
Round 2 (Jade, milestones 30-32) are both closed — see
`docs/EXPERIMENT_INDEX.md` for the full per-hypothesis ledger before
proposing anything new. The project then moved through a phase
transition review (pausing the default hypothesis cadence,
`docs/PHASE_TRANSITION_REVIEW.md`), a Validation Phase (milestones
33-34, direct pipeline verification rather than backtest research —
found and fixed a critical bug, `docs/PAPER_TRADING_VALIDATION_REPORT.md`),
and a CTO platform evaluation (milestone 35,
`docs/CTO_PLATFORM_EVALUATION.md`). Section 4's research-workflow
discipline below is unchanged and still applies to any FUTURE
hypothesis — it just isn't the only mode this project operates in
anymore.

## A note on the agent/department operating model

This repo also runs under a separate `.claude/` multi-agent harness (CTO
→ department Heads → sub-agents; Sonnet implements, Opus plans/verifies;
commit/push require explicit operator approval). That harness's
configuration lives under `.claude/` (see `.claude/settings.local.json`
for currently-allowed commands) — it is process infrastructure for how
work on this repo gets delegated and reviewed, not part of the JadeCap
project's own architecture, and is out of scope for this file beyond this
pointer.
