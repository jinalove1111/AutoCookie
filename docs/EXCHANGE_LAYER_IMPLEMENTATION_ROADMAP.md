# Exchange Layer Implementation Roadmap (Priority 1)

> **UPDATE (2026-07-20, Milestone 41)**: Phase 1 (order placement/
> cancellation against OKX's demo-trading API) is now **implemented AND
> live-verified**, not just implemented -- operator granted OKX Demo API
> Trade permission (previously Read-only), and
> `scripts/verify_demo_order_lifecycle.py` completed a full 11-step
> PASS against the real demo endpoint (`x-simulated-trading: 1`, never
> real capital): a real order was placed (ordId=`3757771015088525312`),
> verified live, cancelled, verified canceled, with position sync and an
> informational (non-gating) `RiskManager.evaluate()` call all clean. An
> earlier attempt this round failed on a real bug -- the verification
> script's order sizing used only OKX's `minSz` (quantity granularity),
> missing OKX's separate, undocumented minimum order *notional value*
> floor (`sCode="51020"`) -- fixed with a new `compute_order_size()`
> helper in the test script only, `OkxClient` itself unchanged. An
> independent post-run sweep confirmed 0 pending orders account-wide, 0
> open positions, and a balance identical to Phase 0's original
> snapshot. Full test suite 882/882. Full detail:
> `docs/OKX_DEMO_ORDER_LIFECYCLE_RESULTS.md`, `PROJECT_STATUS.md`
> Milestone 41, `ENGINEERING_DECISIONS.md` #79. **Phases 2-3 remain
> unchanged and still require their own separate approval** -- this
> milestone does not implement `LiveBroker`, does not decide the SL/TP
> order mechanism (section 3 below), and does not wire anything into
> `scripts/run_paper.py`.

> **UPDATE (2026-07-19, Milestone 37)**: operator approval received for
> "Demo Trading readiness" work that stops short of real credentials/live
> secrets. Phase 0's read-only scope (`OkxClient.fetch_ohlcv`/
> `get_balance`/`get_open_positions`, real HTTP + real OKX v5 auth
> signing, `place_order`/`cancel_order` still `NotImplementedError`) is
> now **implemented and unit-tested against mocked HTTP responses**
> (`backend/tests/test_okx_client.py`, 17 tests) — see
> `PROJECT_STATUS.md` Milestone 37. No real network call has ever been
> made by this code or its tests; nothing is wired into
> `scripts/run_paper.py`. The standalone measurement harness Phase 0
> calls for also now exists (`scripts/measure_exchange_readonly_latency.py`)
> and correctly refuses to run without real
> `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` — those three
> values, and the decision to actually exercise this against OKX's demo
> endpoint, remain an explicit operator action this milestone does not
> take. Section 2's header names below have also been corrected
> (`OK-ACCESS-KEY`, not `OKX-ACCESS-KEY`) after verifying against OKX's
> live v5 API docs during implementation. Phases 1-3 are unchanged and
> still require their own separate approval.

CTO deliverable (2026-07-19), operator directive: "Inspect the existing
Exchange Layer. Reuse the existing `BaseExchange`, `OKXClient`,
`OrangeClient` and `LiveBroker` interfaces. Do not redesign or replace
them. Prepare a production-ready implementation roadmap... Do NOT
implement yet. Request approval before touching production trading."

**This document is a plan. No code in this document has been written to
the repository.** It builds directly on `docs/CTO_PLATFORM_EVALUATION.md`
(Milestone 35), which first surfaced that `app.exchange.base_exchange.BaseExchange`,
`app.exchange.okx_client.OkxClient`, `app.exchange.orangex_client.OrangexClient`,
and `app.execution.live_broker.LiveBroker` are complete, already-designed
interfaces sitting 100% `NotImplementedError`, referenced nowhere in the
active codebase, with zero test coverage — this roadmap does not
re-discover that finding, it plans against it.

---

## 0. A precondition this roadmap found, not previously documented: `LiveBroker`'s stub does not yet match its own stated contract

`LiveBroker`'s docstring already states its purpose: *"Real-money broker
matching the paper broker's interface shape."* But its current stub
methods (`place_order`/`cancel_order`/`get_balance`/`get_open_positions`)
match **`BaseExchange`'s** shape, not **`PaperBroker`'s**. The actual
call chain every trade goes through today is:

```
ExecutionEngine(broker=PaperBroker())  # default
  -> OrderManager(self.broker)
    -> order_manager.place_entry(signal) -> self.broker.fill_entry(signal)
    -> order_manager.place_stop_loss/take_profit(position)  # no-ops for PaperBroker
_check_and_close_open_positions() -> broker.check_exit(position, current_price)
```

`PaperBroker` implements `fill_entry(signal)` and `check_exit(position,
current_price)`. `LiveBroker` currently implements neither — it has
`place_order`/`cancel_order`/`get_balance`/`get_open_positions` instead,
which is `BaseExchange`'s contract, not the one `ExecutionEngine`/
`OrderManager` actually call.

**This is not a redesign — it is completing `LiveBroker` to match the
shape its own docstring already promises.** The correct reading, fully
consistent with "reuse the existing interfaces, do not redesign them":
`LiveBroker` should be an **adapter** that holds a `BaseExchange`
instance (`OkxClient` or `OrangexClient`) internally and implements
`fill_entry`/`check_exit` externally by translating to/from
`place_order`/`get_open_positions`/etc. `BaseExchange` stays exactly the
raw exchange-client contract it already is; `LiveBroker` becomes the
translation layer between that contract and what `ExecutionEngine`
already expects, unchanged. Every other file in the chain
(`ExecutionEngine`, `OrderManager`, `safety_checks.verify_safe_to_trade`,
`RiskManager.evaluate()`) needs **zero changes** under this reading —
they already only depend on the `fill_entry`/`check_exit` shape, which
`LiveBroker` will now actually provide.

---

## 1. Phased rollout — the approval boundary running through everything below

| Phase | What it does | Touches real capital? | Touches `scripts/run_paper.py`'s live path? | Approval needed |
|---|---|---|---|---|
| **Phase 0** | Implement `OkxClient` (read-only: `fetch_ohlcv` delegates to the already-working `CandleFetcher`, `get_balance`/`get_open_positions` real but read-only) against OKX's **demo-trading API**. New, standalone measurement harness only (same pattern as `scripts/measure_pipeline_latency.py`). | No | No | **Yes** — real API credentials, even demo-mode |
| **Phase 1** | Implement `OkxClient.place_order`/`cancel_order` against OKX's **demo-trading API** only. Implement `LiveBroker` as the adapter (section 0). New harness places/cancels DEMO orders to produce Gate #4's real measured signal-to-fill latency number. Still never wired into `run_paper.py`. | No (demo account) | No | **Yes** |
| **Phase 2** | Wire `LiveBroker` into `run_paper.py` as an alternate `broker=` argument, gated behind a NEW settings flag (default off, byte-identical when unset — same discipline every backtest flag in this project already follows), still pointed at the demo endpoint for a soak-test period. | No (demo account) | **Yes, but default-off** | **Yes** |
| **Phase 3** | Point the same code at OKX's real-money endpoint, `LIVE_TRADING_ENABLED=true` + `TRADING_MODE=live`, only after every item in `docs/live_trading_checklist.md` (all 10 gates, including the hardened Gate #4) is satisfied with real evidence. | **Yes** | Yes | **Yes — this is Gate #4 itself** |

Phases 0-1 are what actually unblocks Gate #4's measurement requirement
(`docs/CTO_PLATFORM_EVALUATION.md` section 3's "top-ranked item"). Phases
2-3 are materially larger, separate approval conversations that should
not be pre-authorized by approving Phase 0/1 — this roadmap treats them
as distinct gates, not one bundled yes/no.

---

## 2. Authentication

- **Scheme**: OKX's REST API uses `OKX-ACCESS-KEY` / `OKX-ACCESS-SIGN`
  (HMAC-SHA256 of `timestamp + method + requestPath + body`, base64-encoded)
  / `OKX-ACCESS-TIMESTAMP` / `OKX-ACCESS-PASSPHRASE` headers on every
  private (authenticated) call. `OrangexClient` will need its own
  exchange's equivalent scheme (not assumed identical — to be confirmed
  from OrangeX's own API docs before Phase 0 implementation, not guessed).
- **Credential source**: `Settings.OKX_API_KEY`/`OKX_API_SECRET`/
  `OKX_API_PASSPHRASE` (and the `ORANGEX_*` equivalents) already exist in
  `app/config.py`, already env-var-sourced, already excluded from
  version control (`.env`/`.env.local` gitignored) — **no new credential
  storage mechanism needed**, reuse verbatim per `docs/api_keys_security.md`.
- **Demo vs. real endpoint selection**: OKX exposes the exact same REST
  paths for demo and real trading, distinguished by a header
  (`x-simulated-trading: 1`) or a separate demo API key pair (to be
  confirmed against current OKX docs before implementation — this
  roadmap does not assume which without checking at build time). Whichever
  it is, the selection must be a single, obvious, fail-closed setting
  (defaults to demo, requires deliberate override to real) — mirroring
  `LIVE_TRADING_ENABLED`'s existing "must deliberately opt in" pattern.
- **Never logged**: `docs/api_keys_security.md`'s existing rule
  ("live API keys must never appear in logs, error messages, stack
  traces") applies directly to every new call site — HMAC signatures and
  raw secrets must be redacted from any exception message or debug log
  a new retry/error-handling layer might add.
- **IP allowlisting**: `docs/api_keys_security.md` already recommends
  this "where supported by the exchange" — worth confirming as a
  concrete pre-Phase-0 checklist item (restrict the demo key to this
  deployment's outbound IP) rather than leaving it a soft suggestion.

---

## 3. Order lifecycle

- **Entry**: `LiveBroker.fill_entry(signal)` calls
  `self.exchange_client.place_order(symbol, side, order_type, size,
  price)` (market or limit, matching whatever `signal`/`ExecutionEngine`
  already decide — no new decision logic here, purely a translation),
  then must resolve the REAL fill price/time from the exchange's order
  response (or a follow-up order-status poll if the initial response
  doesn't include it) before returning the same `{"order_id",
  "fill_price", "fee_percent", "filled_at"}` shape `PaperBroker.fill_entry`
  already returns — `ExecutionEngine`/the trade-persistence step in
  `run_paper.py` depend on exactly this shape and must not need to
  change.
- **Stop-loss / take-profit**: `OrderManager.place_stop_loss`/
  `place_take_profit` are currently documented no-ops ("brokers like
  PaperBroker... enforce via check_exit rather than a standalone order...
  A real exchange broker would need a real order call here" — the
  code's own words). Real exchanges support native resting stop/limit
  orders — this is a genuine design decision to make explicitly, not
  silently: (a) place real resting SL/TP orders on the exchange at entry
  time (more robust — protection persists even if this process crashes),
  or (b) keep polling-based `check_exit` and fire a market order only
  when triggered (simpler, matches the existing paper-mode mental model
  exactly, but leaves positions unprotected between polls if the process
  is down). **Recommend (a)** for anything beyond Phase 1's demo-only
  measurement work — real capital should never depend on this process's
  uptime for stop-loss protection. This is a real, new behavior decision
  that needs its own sign-off at Phase 2, not bundled into "just
  implement the stub."
- **Idempotency**: every `place_order` call must carry a client-generated
  order ID (OKX supports `clOrdId`) so a retried request (section 6)
  after an ambiguous network failure cannot result in a duplicate real
  order — this is the single most important correctness property of the
  entire order-lifecycle design, given the financial stakes of a
  duplicate fill.
- **Cancellation**: `cancel_order` needs the same idempotency treatment
  (cancelling an already-filled or already-cancelled order must be a
  safe no-op, not an error that propagates as a pipeline failure).

---

## 4. Position synchronization

`PaperBroker` never had this problem — paper positions are pure local
DB state, always in sync with themselves by construction. A real
exchange position can drift from the local `trades` table's `status="open"`
row (partial fills, exchange-side stop/TP triggers, manual intervention,
a missed webhook/poll). Needed:

- A reconciliation pass (`LiveBroker.get_open_positions()`, already in
  `BaseExchange`'s contract) that runs on a schedule (e.g. once per
  `run_once()` pass, alongside the existing exit-check step) and
  compares real exchange state against the local `trades` table,
  flagging (not silently auto-correcting) any mismatch via the existing
  `risk_events` table (`docs/CTO_PLATFORM_EVALUATION.md`/decision #71's
  Finding #5 — this reconciliation work is precisely the kind of thing
  that dead table should exist for).
- A defined, disclosed policy for what happens on a mismatch — fail
  closed (halt new signal generation until a human resolves it) is the
  recommended default, consistent with this project's existing
  circuit-breaker philosophy (`docs/risk_rules.md`: "requiring a human
  to look at *why* a loss limit was hit before resuming may well be the
  right design, not a gap").

---

## 5. WebSocket / data flow

- **Phase 0-1 recommendation: stay on REST.** `CandleFetcher`'s existing
  REST-polling pattern already produces a real, measured latency number
  (`docs/PAPER_TRADING_VALIDATION_REPORT.md`: median 107ms, p95 196ms)
  — sufficient to get Gate #4's FIRST real number without adding
  websocket complexity to the very first iteration of this work.
- **Later phase, if REST proves too slow once real order-placement
  latency is measured**: OKX's public and private WebSocket APIs
  (`wss://ws.okx.com:8443/ws/v5/public` / `.../private`) would reduce
  market-data and order-status latency materially. This is explicitly
  deferred, not because it lacks value, but because Phase 0-1's job is
  to PRODUCE the first real number before deciding whether the REST
  path is fast enough — building a websocket layer before that number
  exists would be optimizing blind.
- **If/when built**: `OkxClient` already has room for this under the
  same `BaseExchange` contract (a new internal connection-management
  concern, not a new abstract method — `fetch_ohlcv` stays the public
  contract regardless of REST vs. WebSocket transport underneath it).

---

## 6. Retry logic

- **Confirmed gap, not assumed**: `CandleFetcher` (the one REAL, working
  network call in this codebase today) has a `timeout` but **no retry/backoff
  logic at all** — a raw `httpx.get(...)` that raises straight through
  on any `httpx.HTTPError`. This is a real, pre-existing gap even in the
  read-only path, worth fixing alongside (not instead of) the new
  order-placement retry logic, since both share the same underlying need.
- **Recommended policy**: exponential backoff with a small, disclosed
  cap (e.g. 3 attempts, base 200ms, matching typical exchange
  rate-limit recovery windows) for read operations (`fetch_ohlcv`,
  `get_balance`, `get_open_positions`) — safe to retry, idempotent by
  nature.
- **Order placement must NOT blindly retry** on an ambiguous failure
  (timeout with no response body) — the idempotent `clOrdId` from
  section 3 must be checked against the exchange's order-status endpoint
  BEFORE any retry, to distinguish "never reached the exchange" (safe to
  retry) from "reached the exchange but the response was lost" (must not
  retry — a blind retry could double-fill). This is the single most
  safety-critical piece of logic in this entire roadmap.

---

## 7. Error recovery

- **Fail-closed philosophy throughout**, matching the existing codebase's
  own conventions (`_FetchFailureAlerter`'s existing pattern in
  `scripts/run_paper.py`, the circuit breaker's "stay tripped until a
  human resets it" behavior): an exchange-layer error should default to
  "stop, alert, wait for a human" rather than "guess and continue,"
  anywhere real capital is involved (Phase 2+; Phase 0-1's demo-only
  work can be more permissive since nothing real is at stake).
- **Alerting**: `send_telegram_alert`/`send_discord_alert` already exist
  and are already wired into trade-open/trade-close events in
  `run_paper.py` — extend the same alert calls to cover new
  exchange-layer failure modes (auth failure, reconciliation mismatch,
  repeated retry exhaustion), reusing the existing notification
  functions rather than building new ones.
- **Explicit non-goal**: this roadmap does not propose automatic
  position-flattening or automatic order cancellation on error recovery
  — that is itself a real-money decision requiring its own explicit
  design and sign-off, not something to bundle into "error recovery"
  generically.

---

## 8. Risk gates

**Nothing changes here — this is the load-bearing constraint of the
entire roadmap.** `RiskManager.evaluate()` remains the single approval
gate every signal passes through before `ExecutionEngine.execute()` is
ever called, completely unmodified by anything in this document.
`safety_checks.verify_safe_to_trade()` already has the right shape for
this work specifically: its `exchange_healthy` parameter currently
always defaults to `True` (unconnected to any real check) — a real
`LiveBroker`-backed health check (e.g. `get_balance()` succeeding
recently) is a natural, additive wiring point, tightening an existing
gate rather than adding a new one. `PLACEHOLDER_ACCOUNT_BALANCE`
(`app/config.py`) is already explicitly scoped in this project's own
prior decisions to be replaced by a real, live-queried balance
specifically "at Phase 1 gate #4" — this roadmap's Phase 1
`LiveBroker.get_balance()` work is exactly that already-planned
replacement, not a new scope addition.

---

## 9. Testing strategy

- **Unit tests for `OkxClient`/`OrangexClient`**: mock the HTTP layer
  (matching this project's existing `unittest.mock`/`httpx` testing
  conventions already used throughout `backend/tests/`) — verify request
  signing, retry/backoff behavior, and response parsing without any real
  network call, the same way `CandleFetcher` itself should probably gain
  equivalent coverage (currently has none either — a pre-existing gap,
  not new to this roadmap).
- **Unit tests for `LiveBroker`**: verify the `fill_entry`/`check_exit`
  translation layer against a mocked `BaseExchange`, confirming the
  returned shape exactly matches `PaperBroker`'s contract byte-for-byte
  (same discipline this project already applies to every opt-in backtest
  flag: "byte-identical when unset" — here, "byte-shape-identical
  regardless of broker").
- **Integration tests against OKX's real demo-trading API**: a small,
  clearly-labeled, network-dependent test tier (skipped by default in
  CI, matching how `scripts/run_paper.py` itself needs a live feed and
  has no CI coverage today) — run manually/on-demand against demo
  credentials, verifying the full place→confirm→cancel/close cycle
  produces the expected local state.
- **The `verify_signal_to_fill.py` pattern from the validation phase
  generalizes directly**: that script already proved the technique
  (inject a synthetic signal, run the real pipeline, assert hand-computed
  math) — the same approach, pointed at a `LiveBroker`-backed
  `ExecutionEngine` against the demo endpoint, is the natural Phase 1
  acceptance test.
- **Regression coverage for the retry/idempotency logic specifically**
  (section 6) deserves its own dedicated test file given how
  safety-critical it is — simulated timeout-then-late-response scenarios,
  verifying no duplicate order is ever placed.

---

## 10. Rollback strategy

- **Phase 2's own default-off flag is the rollback mechanism for Phases
  0-2**: if `LiveBroker` wiring is ever suspect, flipping the new
  settings flag back to its default (off) instantly reverts
  `run_paper.py` to `PaperBroker`, byte-identical to today's behavior —
  the same "new flag, default off, byte-identical when unset" discipline
  this project already applies to every backtest feature, extended here
  to the execution layer.
- **Phase 3 (real capital) rollback**: `LIVE_TRADING_ENABLED=false` is
  already the existing, tested kill switch (`README.md`'s "Safety Note")
  — this roadmap does not need to invent a new one, only ensure
  `LiveBroker`'s own code paths respect it exactly as
  `safety_checks.verify_safe_to_trade()` already does today for any
  future broker.
- **Position-level rollback**: if a real position is opened and this
  process needs to be rolled back/redeployed, the reconciliation pass
  (section 4) is the mechanism that lets a fresh process instance
  rediscover real exchange state on restart, rather than assuming local
  DB state is authoritative — this must be verified explicitly as part
  of Phase 2's acceptance criteria, not assumed to work.
- **Database rollback**: no new migration risk beyond what this project
  already handles routinely (alembic, already in place) — no schema
  changes are anticipated for Phases 0-1; Phase 2 may need a new column
  or two (e.g. a real `exchange_order_id` distinct from the currently
  synthetic `order_id`) via the existing, already-proven migration
  discipline.

---

## 11. What this roadmap explicitly does NOT propose

- No change to `RiskManager.evaluate()`.
- No change to Legacy's signal-generation logic, or any strategy code.
- No real order placement of any kind in Phases 0-1 — demo-trading
  endpoint only.
- No automatic promotion from Phase to Phase — each phase boundary in
  section 1's table is its own approval gate.
- No redesign of `BaseExchange`/`OkxClient`/`OrangexClient`/`LiveBroker`'s
  existing method signatures — this roadmap fills in stubs and adds one
  adapter role (`LiveBroker` wrapping a `BaseExchange` instance) that
  the existing docstrings already implied but never implemented.
