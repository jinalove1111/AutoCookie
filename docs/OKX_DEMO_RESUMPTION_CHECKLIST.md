# OKX Demo Integration — Resumption Checklist

Milestone 38 (Priority 5, "prepare a clear checklist for resuming OKX
Demo integration later"). OKX Demo API credentials became available as
of Milestone 41 (2026-07-20, operator granted Trade permission -- Read
permission was already available earlier); this doc originally covered
the "credentials not yet available" state and now reflects Phase 1 as
code-complete AND live-verified, not just waiting. Cite, don't
duplicate: the full design reasoning lives in
`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`; the full per-step
verification numbers live in `docs/OKX_DEMO_ORDER_LIFECYCLE_RESULTS.md`;
this is the short, actionable checklist version, plus what's already
done as of milestone 37/38/41.

## What's already done (Phase 0 and Phase 1, both live-verified against the real OKX demo API)

- [x] `backend/app/exchange/okx_client.py` -- `OkxClient.fetch_ohlcv`
  (delegates to `CandleFetcher`, public, no auth) and
  `get_balance`/`get_open_positions` (real OKX v5 authenticated REST:
  `OK-ACCESS-KEY`/`OK-ACCESS-SIGN`/`OK-ACCESS-TIMESTAMP`/
  `OK-ACCESS-PASSPHRASE`, HMAC-SHA256, verified against OKX's own live
  v5 docs, milestone 37) are implemented and real.
- [x] `backend/tests/test_okx_client.py` -- 31 tests (17 Phase 0 + 14
  Phase 1), all mocking `httpx.get`/`httpx.post`, zero real network
  calls.
- [x] `scripts/measure_exchange_readonly_latency.py` -- the standalone
  measurement harness Phase 0 needs. Refuses to run without real
  `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` (verified: it does
  refuse, in an environment with none set).
- [x] Demo-mode is the default (`OkxClient(demo=True)` sends
  `x-simulated-trading: 1`) -- fail-closed toward demo, matching
  `LIVE_TRADING_ENABLED`'s "must deliberately opt in" pattern.
- [x] **Phase 1, live-verified (Milestone 41, 2026-07-20)**:
  `OkxClient.place_order`/`cancel_order`/`get_order_status` and
  `scripts/verify_demo_order_lifecycle.py` completed a full 11-step PASS
  against the real OKX demo-trading endpoint -- an order was placed,
  verified live, cancelled, and verified canceled, with position sync
  and an informational (non-gating) `RiskManager.evaluate()` call all
  clean. Along the way, a real order-sizing bug (OKX's undocumented
  minimum order *notional value* floor, distinct from `minSz`'s
  quantity-granularity floor) was found and fixed in the verification
  script only -- `OkxClient` itself was not touched. Independent
  post-run sweep confirmed 0 pending orders account-wide, 0 open
  positions, and a balance identical to Phase 0's original snapshot.
  Full suite 882/882. Full numbers:
  `docs/OKX_DEMO_ORDER_LIFECYCLE_RESULTS.md`.

## Step-by-step: the moment credentials exist (now historical -- executed, Phase 0 and Phase 1 both complete and live-verified as of Milestone 41)

1. **Obtain OKX demo-trading API keys** (not real-money keys): API key,
   secret, passphrase, with **withdrawal disabled** (same requirement
   `docs/live_trading_checklist.md` item 3 already states for eventual
   real-money keys -- apply it here too, defense in depth even though
   demo funds have no real value).
2. **Set env vars** (never commit these -- `.env`/`.env.local` are
   gitignored, per `docs/api_keys_security.md`):
   ```
   OKX_API_KEY=<demo key>
   OKX_API_SECRET=<demo secret>
   OKX_API_PASSPHRASE=<demo passphrase>
   ```
3. **Run the measurement harness** (this is the actual Phase 0
   deliverable -- the first real number):
   ```
   cd backend
   PYTHONPATH=<repo>/backend \
   OKX_API_KEY=... OKX_API_SECRET=... OKX_API_PASSPHRASE=... \
   python ../scripts/measure_exchange_readonly_latency.py
   ```
   Expect `get_balance`/`get_open_positions` latency stats written to
   `scripts/reports/exchange_readonly_latency.json`. This does NOT touch
   `scripts/run_paper.py` or any live path -- standalone script only.
4. **Sanity-check the response shape** against `OkxClient.get_balance`'s
   assumed schema (`data[].details[].{ccy,availBal}`) -- if OKX's live
   demo response doesn't match, that's real information (fix the parser,
   not the test mocks) and should be treated as a normal bug, not a
   blocker requiring a redesign.
5. **Report the number** -- median/p95 `get_balance`/`get_open_positions`
   latency is Gate #4's first real measured-infrastructure data point
   (`docs/live_trading_checklist.md`'s Gate #4 hardening section).

## What comes after (separate approval gates, not pre-authorized by Phase 1)

Per `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` section 1's phase
table -- each row below is its own approval conversation, not unlocked
by finishing the row above it. **Phase 1's order placement/cancellation
against the demo endpoint is now DONE and live-verified (Milestone 41,
`docs/OKX_DEMO_ORDER_LIFECYCLE_RESULTS.md`)** -- what remains before
Phase 2 can start:

- **Still needed before Phase 2**: `LiveBroker` built as the adapter
  wrapping `OkxClient` (roadmap section 0's finding -- `LiveBroker`'s
  current stub interface doesn't match what `ExecutionEngine`/
  `OrderManager` actually call) -- not built this round. Also requires a
  real design decision on the SL/TP mechanism (native resting orders vs.
  polling `check_exit` -- roadmap section 3, explicitly flagged as
  needing its own sign-off) -- not decided this round.
- **Phase 2**: wire `LiveBroker` into `scripts/run_paper.py` behind a
  new, default-off settings flag, still pointed at the demo endpoint.
  This is the first phase that touches the gated live-trading file at
  all -- the next possible step in this line of work, pending its own
  separate approval gate, not implied as authorized or scheduled by
  Phase 1's completion.
- **Phase 3**: real capital. Requires every item in
  `docs/live_trading_checklist.md` satisfied, including the hardened
  Gate #4 with a real measured order-placement latency number (not just
  the read-only number Phase 0 produces).

## Known open items to revisit alongside this work

- `OrangexClient` remains an intentionally untouched stub -- not
  referenced anywhere in production code, no established business need
  found (milestone 37 checked and declined to build it for exactly this
  reason). Re-evaluate only if a concrete reason to trade on OrangeX
  surfaces.
- Finding #2 (`docs/PAPER_TRADING_VALIDATION_REPORT.md`): which
  `DEFAULT_TIMEFRAME` production actually used historically is still
  unconfirmed -- worth resolving before Gate #4 evidence is finalized,
  since it affects how delay-fragility findings map to real deployed
  behavior.
