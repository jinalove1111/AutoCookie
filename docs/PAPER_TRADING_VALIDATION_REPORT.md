# Paper Trading Pipeline Validation Report — Milestone 33

> **UPDATE (2026-07-19, operator-approved fix, Milestone 34,
> `ENGINEERING_DECISIONS.md` #72): Finding #1 is FIXED.**
> `_check_and_close_open_positions()` now normalizes `opened_at` to
> UTC-aware before the subtraction. Both the stop-loss and take-profit
> close paths are verified via two passing regression tests (replacing
> the original `xfail`) — `backend/tests/test_run_paper_exit_check.py`.
> Findings #2-#6 below remain open/unresolved as originally reported;
> only Finding #1 is updated by this note.

Validation-phase deliverable (2026-07-19), operator directive: "You are
entering Validation Phase... verify the paper trading pipeline
end-to-end... measure end-to-end execution latency... identify any
reliability, synchronization, logging, or execution issues." This is
the first validation-phase milestone following
`docs/PHASE_TRANSITION_REVIEW.md`'s recommendation. No hypothesis was
run to produce this report — this is direct system verification, not
backtest research. `RiskManager.evaluate()` and `scripts/run_paper.py`
were READ and RUN, never modified. Three new, additive, read-only tools
were built to make this verification possible without waiting on
Legacy's naturally low real signal rate:
`scripts/measure_pipeline_latency.py`,
`scripts/verify_signal_to_fill.py`, and one permanent regression test,
`backend/tests/test_run_paper_exit_check.py`. Full suite: 790 collected
(789 passed, 1 xfailed — the new regression test documenting finding #1
below), 0 unexpected failures.

---

## Finding #1 (CRITICAL): the exit-check step crashes and silently blocks the pipeline the first time a real trade's stop-loss or take-profit is actually reached

**Severity: highest of anything found in this validation round.** This
is a real, reproducible bug in `scripts/run_paper.py`'s
`_check_and_close_open_positions()`, confirmed via a controlled,
deterministic reproduction — not a one-off environmental fluke.

**Root cause**: `Trade.opened_at` is declared `DateTime(timezone=True)`
(`backend/app/database/models.py`), but SQLite's SQLAlchemy dialect does
not actually preserve timezone-awareness across a write/read round-trip
— `TradeTracker.get_open_positions()` returns `opened_at` as a
timezone-**naive** datetime regardless of the column's declared type.
`_check_and_close_open_positions()` (`scripts/run_paper.py` line ~288)
computes `closed_at = datetime.now(timezone.utc)` (timezone-**aware**)
and then, at line 297, computes `(closed_at - opened_at).total_seconds()`
for `holding_time_seconds` — subtracting an aware datetime from a naive
one raises `TypeError: can't subtract offset-naive and offset-aware
datetimes`.

**Impact, precisely**: the crash happens at line 296-297, **before**
`TradeTracker.close_trade()` is ever called (line 299). This means:
1. The position is **never actually closed** when this triggers — no
   `close_trade()` call happens at all, the trade stays `status="open"`
   in the database forever.
2. `run_once()`'s own concurrency guard (`scripts/run_paper.py`'s
   documented "one-trade-open-at-a-time" design) skips ALL signal
   generation on every subsequent pass while ANY position remains open.
3. **The first time this bug triggers in real production, the paper
   trader stops generating any new signals, permanently**, until
   manually intervened — it does not self-recover, because the
   position that should have closed (and cleared the guard) never does.

**This bug only triggers when an exit condition is actually met**
(`PaperBroker.check_exit()` returns non-`None`) — a position that never
reaches its stop-loss or take-profit can stay open indefinitely without
crashing. This is consistent with, and directly explains, why the
production database's empty `trades` table (Finding #4) never surfaced
this bug before: no trade has ever been recorded as opened at all, so
no trade has ever reached the exit-check code path that crashes.

**Reproduction** (verified twice, independently, in this round):
1. Via the real `run_once()` pipeline itself: opened a synthetic trade
   through the REAL, unmodified signal → risk → execute → persist chain
   (`scripts/verify_signal_to_fill.py` Phase 1, against a throwaway temp
   SQLite DB created by real `alembic upgrade head` — never the
   production DB), then called `run_once()` again — the exit-check step
   that runs at the start of every pass crashed with the exact
   `TypeError` above.
2. Via a direct call to `_check_and_close_open_positions()` with a price
   forced past the take-profit level (Phase 3) — identical crash, same
   line, confirming one root cause, not two separate issues.

**Why this was never caught**: `scripts/run_paper.py` had **no direct
pytest coverage of any kind** before this validation round (confirmed by
exhaustive search; matches `CLAUDE.md`'s own prior disclosure). Every
individual component this bug touches (`TradeTracker`, `PaperBroker`,
`RiskManager`) is well-tested in isolation — 789 passing tests — but the
ORCHESTRATION wiring between them, exercised only by actually running
the script, had never been exercised by an automated test until this
round.

**A permanent regression test was added**,
`backend/tests/test_run_paper_exit_check.py`, marked `@pytest.mark.xfail(strict=True)`
with the full root-cause explanation inline — it reproduces the bug
deterministically against a throwaway temp DB (the `migrated_db`
fixture every `app.portfolio.*` test already uses) and will
automatically flip to a hard failure (catching any accidental
re-introduction) once someone removes the `xfail` marker after a real
fix, and to a pass once the fix is correct. This keeps the "full suite
passing" convention intact (`xfail` is not a failure) while making the
bug permanently visible in CI rather than only in this document.

**Not fixed in this round.** `scripts/run_paper.py` is one of the two
files `CLAUDE.md` section 2 explicitly gates behind operator sign-off
before modification, and this session's own instruction was explicit:
"do not modify production trading logic." **This is the single most
important remaining blocker before any further live-trading escalation**
— recommended fix direction (not implemented): read `opened_at` back as
UTC-aware explicitly (e.g. `opened_at.replace(tzinfo=timezone.utc)` if
naive) before the subtraction, the standard fix for this exact
SQLAlchemy+SQLite class of bug.

---

## Finding #2 (CRITICAL, unresolved): cannot confirm which timeframe the actual live process has been running

`app.config.Settings.DEFAULT_TIMEFRAME` defaults to `"5m"` — confirmed
both in source and at runtime during this round's live measurements
(`scripts/reports/paper_pipeline_latency.json`: `"default_timeframe":
"5m"`). `.env.example` documents `DEFAULT_TIMEFRAME=5m` as the standard
value, not an accidental default.

**Nearly the entire delay-fragility research body — the evidentiary
basis for `docs/live_trading_checklist.md`'s Gate #4 hardening — was
conducted at 15m** (`docs/LEGACY_DELAY_ROBUSTNESS.md`,
`docs/ATR_FLOOR_EVALUATION.md`, and every hypothesis H1-H8 in this
project's evidence base standardized on "BTCUSDT 15m" anchors). The
platform's very first profitability validation
(`docs/PROFITABILITY_EXPERIMENT_REPORT.md`/`docs/ROBUSTNESS_REPORT.md`)
was itself conducted at 5m — meaning the 5m-vs-15m split is not a typo,
it reflects two genuinely different points in this project's history
that were never explicitly reconciled.

**This review could not determine which timeframe the actual,
historically-running production process used.** `docker-compose.yml`
points the backend service at a `.env` file; no `.env` file exists in
this repository (only `.env.example`, a template) and `.env`/`.env.local`
are both gitignored by design (`.gitignore` lines 13-14) — the real
runtime configuration was never committed, and the process that used it
is not currently running (Finding #4), so there is no way to inspect its
actual launch environment from this repository alone.

**Why this matters**: if the real deployed process has been running at
`DEFAULT_TIMEFRAME=5m` (the code default), then "one candle of delay" in
that deployment is a 5-minute delay, not the 15-minute figure Gate #4's
entire hardened requirement is built around — and the strategy's own
stop/target/structural-level computations (which are timeframe-relative,
not absolute) would differ meaningfully between the two timeframes. The
delay-fragility findings, exactly as stated, may not describe the
deployed configuration at all. **This needs explicit operator
confirmation before any further live-trading escalation** — this review
recommends verifying (and, if necessary, aligning) the real `.env`'s
`DEFAULT_TIMEFRAME` against the 15m standard the safety research assumes,
or re-running the core delay-fragility check at 5m if 5m is confirmed to
be the real deployed value.

---

## Finding #3: Gate #4's "measured signal-to-fill latency" cannot be produced by the current architecture at all

Verified by direct source inspection: `app.execution.paper_broker.PaperBroker`
contains no `requests`/`httpx`/`aiohttp`/network call of any kind — its
`fill_entry()`/`check_exit()` methods are pure in-memory arithmetic
(confirmed: the module's own docstring already states "No real
HTTP/exchange calls anywhere in this module"). The ONLY real network
call anywhere in the paper-trading pipeline is
`CandleFetcher.fetch_ohlcv()`'s market-data fetch from OKX's public REST
API.

**This means Gate #4's own hardened requirement** (`docs/live_trading_checklist.md`:
"verified low-latency (sub-candle, ideally seconds-scale) execution
infrastructure is a hard prerequisite, measured signal-to-fill latency,
not assumed") **cannot be satisfied by running or measuring the existing
pipeline more, no matter how carefully.** There is no real exchange
order-placement round-trip anywhere in this codebase to measure yet —
this is a real infrastructure gap, not a measurement gap. Producing a
genuine number requires new infrastructure (at minimum, a real
demo/paper-mode order-placement integration against OKX's actual trading
API, not the current in-memory simulation) before Gate #4 can ever be
cleared on real evidence. This is the single most consequential,
previously-undocumented structural fact this validation round
surfaces — everything measured below is honest about not being that
number.

---

## Finding #4: the paper-trading process was not observably running during this validation

Checked directly (`tasklist`, this environment): no matching process for
`PROJECT_STATUS.md`'s last-recorded PID (24616, as of Milestone 28).
`backend/paper_validation.db`'s `regime_snapshots` table (populated
every real pass, `ENABLE_SHADOW_STRATEGY_SIGNALS` observability) shows
activity from 2026-07-16 02:14:44 through 2026-07-18 00:41:05, then
nothing — roughly 29-30 hours stale as of this validation
(2026-07-19 ~05:00-11:00). `bot_state.updated_at` is even older
(2026-07-12 10:29:12). **This review cannot distinguish an actual
production outage from this review simply running in a different
environment than wherever the real process was deployed** — flagged for
operator confirmation, not asserted as an incident.

**Separately, and independent of whether the loop-mode process is
currently running**: `trades` and `signals` are both completely empty
(0 rows) in the current database, despite ~2 days of recorded
regime/shadow-signal activity. This means, as of this validation, **no
real Legacy trade has ever opened in the recorded history of this
specific database** — consistent with Legacy's known low signal rate
(historically ~1 signal every 1-4 days per backtest evidence), not
necessarily anomalous, but it also means Finding #1's crash has never
yet had the opportunity to occur in real production, only in this
round's controlled reproduction.

---

## Finding #5: two real, disclosed dead observability tables

`strategy_logs` and `risk_events` are both real tables in the database
schema (migration-created, with thoughtfully-designed columns —
`strategy_logs`: module/decision/reason/candle_context/signal_id;
`risk_events`: event_type/message/severity/timestamp) that **no code
anywhere in this repository writes to** (confirmed via exhaustive
`grep` across `backend/` and `scripts/` for both table/model names — zero
matches beyond the schema/migration definitions themselves). Schema
exists; nothing populates it. Not fixed in this round (would require
editing `scripts/run_paper.py`, the gated file) — recommended as a
concrete, low-risk observability improvement for a future, explicitly
operator-approved change.

---

## Finding #6: signal → risk → execute → persist math is verified correct

`scripts/verify_signal_to_fill.py` Phase 1, against a real (throwaway)
database, using the REAL unmodified `RiskManager.evaluate()` →
`ExecutionEngine.execute()` → `PaperBroker.fill_entry()` →
`TradeTracker.record_trade()` chain:

| Check | Expected (hand-computed) | Actual (from DB) | Match |
|---|---|---|---|
| Signal generated / approved / executed | True / True / True | True / True / True | ✅ |
| Fill price (long, 0.02% unfavorable slippage) | 50,010.0 | 50,010.0 | ✅ |
| Position size (0.25% risk / $1,000 stop distance) | 0.025 | 0.025 | ✅ |
| Fee (0.05% flat taker, entry-leg notional) | 0.625125 | 0.625125 | ✅ |
| Slippage (fill − planned entry) | 10.0 | 10.0 | ✅ |
| stop_loss / take_profit persisted | match signal | match signal | ✅ |
| status / mode | open / paper | open / paper | ✅ |

Every one of these matched exactly. **The open-side pipeline (signal
through persisted position) is confirmed mathematically correct** — the
bug in Finding #1 is specifically in the CLOSE-side exit-check step, not
here.

**Concurrency-guard verification: inconclusive, blocked by Finding #1.**
The intended Phase 2 check (a second pass, with a position already open,
should set `skipped_signal_generation=True` without attempting a new
signal) could not be observed cleanly — the real current market price at
test time had already moved past one of the synthetic position's
stop/target levels, so the exit-check step (which runs before the
concurrency guard on every pass) crashed via Finding #1 before the
guard's own logic was ever reached. This should be re-verified once
Finding #1 is fixed.

---

## Latency measurements (with Finding #3's scope limit applied honestly)

`scripts/measure_pipeline_latency.py`, live, against real OKX data, 2026-07-19:

| Measurement | n | min | median | mean | p95 | max |
|---|---|---|---|---|---|---|
| OKX candle-fetch round-trip (isolated) | 10 | 98.3ms | 107.3ms | 120.1ms | 195.8ms | 195.8ms |
| Full `run_once()` pipeline (one warm process, matching real loop-mode cost) | 10 | 210.5ms | 235.8ms | 333.5ms | 745.2ms | 745.2ms |

All 10 `run_once()` passes completed with `exit_code=0`, no errors — the
fetch → signal-generation portion of the pipeline runs cleanly against
live data today. **Neither number is real exchange order latency** (Finding
#3) — both are network-fetch and in-process compute time only. The
`run_once()` distribution's higher variance/tail (p95 more than 3x the
median) is consistent with two independent real network fetches per pass
(LTF + HTF) plus signal-generation compute, not a single clean call.

---

## Summary of completed work this round

1. Verified the paper-trading pipeline end-to-end — found it not
   currently running (Finding #4), but confirmed the fetch → signal
   portion runs cleanly against live data today (10/10 real passes,
   `exit_code=0`).
2. Verified signal → order → fill correctness with real, hand-checked
   math (Finding #6) — and, in the process, found and precisely
   root-caused a critical, previously-undetected bug that would
   permanently halt the paper trader the first time a real trade's exit
   level is reached (Finding #1), added as a permanent regression test.
3. Measured real, honestly-scoped latency (network fetch + in-process
   pipeline) and explicitly disclosed why real exchange order latency —
   the actual Gate #4 requirement — cannot be produced by the current
   architecture at all (Finding #3).
4. Found a critical, unresolved configuration ambiguity between the
   platform's safety research (15m) and the code's/documented default
   (5m) that could not be resolved from the repository alone (Finding
   #2).
5. Found two dead observability tables (Finding #5).
6. Added the first-ever automated test coverage for
   `scripts/run_paper.py`'s own orchestration logic.

No production trading logic was modified. `RiskManager.evaluate()` and
`scripts/run_paper.py` were read and run, never edited.
