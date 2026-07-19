# OKX Demo Integration — Resumption Checklist

Milestone 38 (Priority 5, "prepare a clear checklist for resuming OKX
Demo integration later"). OKX Demo API credentials are not available as
of this writing (2026-07-19) -- this doc is what to do the moment they
are, without needing to re-derive the plan from scratch. Cite, don't
duplicate: the full design reasoning lives in
`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`; this is the short,
actionable checklist version of that document's Phase 0/1, plus what's
already done as of milestone 37/38.

## What's already done (code-complete, tested, waiting on credentials only)

- [x] `backend/app/exchange/okx_client.py` -- `OkxClient.fetch_ohlcv`
  (delegates to `CandleFetcher`, public, no auth) and
  `get_balance`/`get_open_positions` (real OKX v5 authenticated REST:
  `OK-ACCESS-KEY`/`OK-ACCESS-SIGN`/`OK-ACCESS-TIMESTAMP`/
  `OK-ACCESS-PASSPHRASE`, HMAC-SHA256, verified against OKX's own live
  v5 docs, milestone 37) are implemented and real.
- [x] `backend/tests/test_okx_client.py` -- 17 tests, all mocking
  `httpx.get`, zero real network calls.
- [x] `scripts/measure_exchange_readonly_latency.py` -- the standalone
  measurement harness Phase 0 needs. Refuses to run without real
  `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE` (verified: it does
  refuse, in an environment with none set).
- [x] Demo-mode is the default (`OkxClient(demo=True)` sends
  `x-simulated-trading: 1`) -- fail-closed toward demo, matching
  `LIVE_TRADING_ENABLED`'s "must deliberately opt in" pattern.

## Step-by-step: the moment credentials exist

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

## What comes after (separate approval gates, not pre-authorized by the above)

Per `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` section 1's phase
table -- each row below is its own approval conversation, not unlocked
by finishing the row above it:

- **Phase 1**: `OkxClient.place_order`/`cancel_order` against the demo
  endpoint, `LiveBroker` built as the adapter wrapping `OkxClient`
  (roadmap section 0's finding -- `LiveBroker`'s current stub interface
  doesn't match what `ExecutionEngine`/`OrderManager` actually call).
  Also requires a real design decision on SL/TP mechanism (native
  resting orders vs. polling `check_exit` -- roadmap section 3,
  explicitly flagged as needing its own sign-off).
- **Phase 2**: wire `LiveBroker` into `scripts/run_paper.py` behind a
  new, default-off settings flag, still pointed at the demo endpoint.
  This is the first phase that touches the gated live-trading file at
  all.
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
