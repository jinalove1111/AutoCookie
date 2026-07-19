# CTO Platform Evaluation — Milestone 35

Strategic deliverable (2026-07-19), operator directive: "Evaluate the
entire platform as the CTO. Identify the highest ROI improvements. Rank
them... Separate them into Immediate / Short-term / Long-term." This is
not a hypothesis and not another validation-pipeline check — it is a
full-platform survey, informed by everything already established
(H1-H8, `docs/PHASE_TRANSITION_REVIEW.md`, `docs/PAPER_TRADING_VALIDATION_REPORT.md`)
plus fresh inspection of parts of the codebase not previously covered:
the frontend, the API layer, CI/dev-infra, and the exchange/execution
abstraction layer.

---

## 1. Platform state summary (grounded, not restated from memory)

**Strategy layer**: Legacy (Strategy A) is the only live/paper-authorized
strategy. Backtested profitable but its execution-delay fragility is
confirmed STRUCTURAL across 4 independently distinct fix attempts (ATR
floor, entry-drift gate, H2 passive entry, H3 regime-conditioning), all
REJECTED. Jade (Strategy B) is fully built (5 entry models, HTF
confluence, trendline, CRT, session bias) but has zero backtest KEEPs;
H7/H8 found its bottleneck (reward:risk geometry) is STRUCTURAL with
respect to every already-built parameter choice. Four quarantined
experimental strategies were all REJECTED (milestones 10/12).

**Adaptive-platform infrastructure** (`docs/ADAPTIVE_ARCHITECTURE.md`
milestones 1-18): Market Regime Detector, Strategy interface/registry,
`RollingPerformanceSelector`, Performance DB extensions, shadow-mode
observability — all BUILT, but the selector is explicitly **built and
NOT wired** (milestone 16's own status) — only `legacy` is ever actually
selected in production today, by construction, not by omission.

**Validation phase** (milestones 33-34): Finding #1 (a critical bug that
would have permanently halted the paper trader on any real trade's
exit) is FIXED and verified. Findings #2-#5 remain open:
- #2: cannot confirm whether the real deployment's `.env` has
  `DEFAULT_TIMEFRAME=5m` (the code default) or `15m` (the standard
  every delay-fragility safety finding was computed on) — now given a
  prominent, permanent warning comment in `app/config.py` (this round),
  but not resolved.
- #3: Gate #4's "measured signal-to-fill latency" requirement cannot be
  produced by the current architecture — no real exchange order-placement
  round-trip exists anywhere in this codebase.
- #4: the paper-trading process was not observably running during the
  last validation pass.
- #5: `strategy_logs`/`risk_events` are real, migration-created DB
  tables that no code writes to.

**Newly surfaced this round** (not previously documented anywhere in
this evidence base):
- **No CI pipeline existed until this round.** 791 tests, entirely
  manually run. Nothing automatically caught a regression on push/PR.
- **A dormant, parallel, fully-unimplemented exchange-abstraction layer**:
  `app.exchange.base_exchange.BaseExchange` (an abstract contract:
  `fetch_ohlcv`/`place_order`/`cancel_order`/`get_balance`/
  `get_open_positions`) and its two concrete stubs,
  `app.exchange.okx_client.OkxClient` and
  `app.exchange.orangex_client.OrangexClient`, are **100% `NotImplementedError`
  stubs** — confirmed by direct source inspection. `app.execution.live_broker.LiveBroker`
  (the real-money broker counterpart to the working `PaperBroker`) is
  the same: every method raises `NotImplementedError`. None of these
  four classes is referenced anywhere in the active codebase beyond
  their own definitions (confirmed via exhaustive grep) — completely
  dormant, zero test coverage. **This is directly relevant to Finding
  #3**: this stub hierarchy already defines the exact interface Gate #4's
  missing order-placement infrastructure would need. Building it means
  filling in an existing, already-designed contract — not designing a
  new one. It also means the REAL, working candle-fetch path
  (`app.data.candle_fetcher.CandleFetcher`, confirmed live this
  validation phase with real measured latency) duplicates
  `BaseExchange.fetch_ohlcv`'s job through a completely separate,
  unrelated class hierarchy — a real architectural incoherence worth
  resolving deliberately, not accidentally, whenever item 1 below is
  designed.
- **The `/dashboard/logs` API route and the frontend `LogsPanel`
  component are both fully built and already correctly handle the empty
  state** ("No recent log entries.") — but structurally can never show
  anything else, because Finding #5's `strategy_logs` table is never
  written to. Not a frontend bug; the gap is entirely backend-side.
- Frontend (Next.js): 7 components (`BiasCard`, `BotStatusCard`,
  `LogsPanel`, `ModeToggle` — has its own test, `PositionsPanel`,
  `RiskStatusPanel`, `SignalsPanel`) against a working 4-route API layer
  (`routes_dashboard.py`/`routes_health.py`/`routes_settings.py`/
  `routes_trades.py`). Reasonably complete for what it covers; not
  independently audited beyond this survey.

---

## 2. Ranked improvements

Scored 1 (low) – 5 (high) per column; **Risk** is inverted (5 = highest
risk, matching the other columns' "5 = most consequential" convention
so the table reads consistently).

| Rank | Improvement | Impact | Cost | Risk | Long-term Value | Bucket | Autonomy |
|---|---|---|---|---|---|---|---|
| 1 | Resolve Finding #2 (confirm real `.env`'s `DEFAULT_TIMEFRAME`; re-run delay-fragility check at whichever value is confirmed real if it differs from 15m) | 5 | 1 | 2 | 5 | Immediate | Operator action (I cannot access the real deployment `.env`) |
| 2 | Build real signal-to-fill latency measurement infrastructure (fill in `OkxClient`/`LiveBroker` against OKX's demo-trading API, wired into a NEW standalone measurement harness only, never into `run_paper.py`'s live path) | 5 | 4 | 3 | 5 | Immediate | **Approval required** — new external integration, real credentials, architecture decision (see section 3) |
| 3 | Confirm current real-world paper-trading process status (Finding #4) | 4 | 1 | 1 | 3 | Immediate | Operator action |
| 4 | Stand up CI (GitHub Actions running `pytest` on push/PR) | 4 | 2 | 1 | 5 | Immediate | **Done this round** (safe, zero production-behavior touch) |
| 5 | Wire `strategy_logs`/`risk_events` observability writes into `run_paper.py` (Finding #5) | 3 | 2 | 2 | 4 | Short-term | **Approval required** — touches the gated file, even though it's pure bookkeeping (same precedent as Finding #1) |
| 6 | Pre-approval security/secrets review ahead of item 2 (`docs/api_keys_security.md` against real credential handling for a live exchange demo integration) | 3 | 1 | 1 | 4 | Short-term | Safe to do autonomously as a review; flagged as a prerequisite for item 2's approval, not done in full this round (see section 4) |
| 7 | A genuinely constructive Jade hypothesis (H9): does a farther-target selection convention improve real Net Profit/win-rate, not just nominal RR (H8's own disclosed, unvalidated candidate) | 3 | 3 | 1 | 3 | Short-term | Backtest-only, same safety class as H1-H8 — available on request, **not auto-started** (prior explicit instruction: "do not create new hypotheses unless validation reveals a clear evidence gap") |
| 8 | Broaden test coverage for thin/uncovered modules (`app.exchange.*`, `app.execution.live_broker`, notification senders) | 2 | 2 | 1 | 3 | Short-term | Safe, available; not exhaustively done this round (see section 4) |
| 9 | Resolve the `app.exchange.*` vs. `CandleFetcher` duplication (consolidate or deliberately delete the dead stub hierarchy) | 2 | 2 | 2 | 3 | Short-term | Coupled to item 2's design — a design INPUT for item 2's approval conversation, not independently actionable |
| 10 | Cross-asset validation of the RR-geometry / delay-fragility findings (deferred multiple times already) | 3 | 2 | 1 | 3 | Long-term | Backtest-only, available; confirmatory rather than action-unlocking per `docs/PHASE_TRANSITION_REVIEW.md`'s own prior reasoning |
| 11 | Wire `RollingPerformanceSelector` into `run_paper.py` (enable real regime-conditional multi-strategy selection) | 4 (in principle) / 1 (in practice today) | 3 | 5 | 5 | Long-term | **Approval required**, and low-value until a second strategy actually clears a KEEP — Jade has zero today, so wiring the selector now would just always select Legacy anyway (per its own milestone-16 dry-run finding) |

---

## 3. Item 2 (Gate #4 latency infrastructure), expanded — the single highest-leverage remaining blocker

This is the most consequential item on the list and deserves its own
scoping note before any approval conversation, so the decision isn't
made blind:

- **What exists already**: `BaseExchange`'s abstract contract and
  `OkxClient`'s stub already define `place_order`/`cancel_order`/
  `get_balance`/`get_open_positions` with the right shapes. `LiveBroker`
  mirrors `PaperBroker`'s interface. Nothing needs to be designed from
  scratch — implementing means filling in these four already-scoped
  methods against OKX's real API.
- **What this explicitly would NOT do**: touch `scripts/run_paper.py`'s
  live path, touch `RiskManager.evaluate()`, or place any order with
  real capital. The proposed scope is a NEW, separate, additive
  measurement harness (same pattern as `scripts/measure_pipeline_latency.py`
  from the validation phase) that calls the newly-implemented
  `OkxClient` against OKX's **demo/paper-trading API endpoint**
  specifically (not the real-money endpoint), purely to produce the
  measured signal-to-fill number Gate #4 requires.
- **What it would need, that this evaluation cannot supply**: real OKX
  API credentials (even demo-mode credentials are still real secrets
  requiring careful handling per `docs/api_keys_security.md`), and an
  operator decision on which OKX API tier/endpoint is appropriate for
  this purpose.
- **Why this belongs in "Immediate" despite requiring approval**: every
  other item on this list is either already resolvable without it
  (CI, config clarity) or blocked BY it (any live-trading progress at
  all). This is the one item where the ranking's own "Immediate" bucket
  and "requires approval" status coexist rather than compete — it should
  be raised for approval now, not deferred to "short-term," even though
  actual implementation cannot start without that approval.

---

## 4. What was done autonomously this round (safe, zero production-behavior touch)

1. **CI pipeline**: `.github/workflows/backend-tests.yml` — runs the
   full `backend/tests/` suite via `pytest` on every push/PR to
   `master`. Does not touch `scripts/run_paper.py`, `RiskManager`, or
   any trading-decision code; only runs the existing, already-passing
   suite. This repository has never had automated regression coverage
   before this file.
2. **Finding #2 recurrence-prevention**: added a prominent, permanent
   warning comment directly on `Settings.DEFAULT_TIMEFRAME`
   (`backend/app/config.py`) cross-referencing the 5m/15m discrepancy,
   citing the exact validation-report finding and engineering decision.
   **Does not change the setting's VALUE** — the actual ambiguity
   (Finding #2 itself) remains unresolved and still requires operator
   access to the real deployment `.env`; this only ensures the next
   session (or the next person reading `config.py` directly) cannot miss
   the warning the way this project's own evidence base apparently did
   for its entire history until the validation phase surfaced it.

Both changes verified against the full test suite (791 passed, 0
failures, 0 xfailed, unchanged from before these edits) before
committing.

**Explicitly NOT done this round, and why**: item 7 (H9) was not
auto-started, honoring the standing "do not create new hypotheses
unless validation reveals a clear evidence gap" instruction from the
prior validation-phase turn — this evaluation did not surface a NEW
evidence gap of that kind, only re-confirmed H8's own already-disclosed
candidate. Item 8 (broader test coverage) and item 6 (security review)
are flagged as available and safe but not executed in full this round,
to keep this deliverable's own scope bounded to what was explicitly
asked (evaluate and rank, implement what's safe) rather than expanding
into an open-ended engineering sprint unprompted.

---

## 5. Summary table: Immediate / Short-term / Long-term

**Immediate** (next milestone):
- Resolve Finding #2 (operator action)
- Raise item 2 (Gate #4 latency infrastructure) for approval
- Confirm paper-trading process status (operator action)
- ~~Stand up CI~~ — done this round

**Short-term**:
- Wire `strategy_logs`/`risk_events` (pending approval)
- Security/secrets review ahead of item 2's approval
- H9 (farther-target Jade hypothesis) — available on request
- Broaden test coverage for thin modules
- Resolve `app.exchange.*` vs. `CandleFetcher` duplication (as part of item 2's design)

**Long-term**:
- Cross-asset validation of RR-geometry/delay-fragility findings
- Wire `RollingPerformanceSelector` into production selection (blocked on a second strategy actually clearing a KEEP)

No hypothesis was run to produce this evaluation. `RiskManager.evaluate()`
and `scripts/run_paper.py` were not modified. `app/config.py` received a
comment-only change (no value changed). A new CI workflow file was added
(pure repo tooling, cannot affect trading behavior).
