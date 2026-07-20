# OKX Demo Order Lifecycle Verification Results — Milestone 41

Engineering deliverable (2026-07-20), operator directive: continue
Exchange Layer Phase 1 the moment OKX Demo API Trade permission is
available. This closes out
`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` section 1's Phase 1 row
(order placement/cancellation against OKX's demo-trading API) with a
real, live-verified end-to-end run — not just implemented code. Cite,
don't duplicate: the full phased-rollout design and its approval
boundaries live in `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`; the
resumption checklist's step-by-step lives in
`docs/OKX_DEMO_RESUMPTION_CHECKLIST.md`; this document is the full
numeric/factual record of what actually happened when Phase 1 was run
against the real demo endpoint.

## 1. Session context and starting point

Operator granted OKX Demo API Trade permission this round — previously
the account only had Read permission, which had already produced a live
401/`sCode=50120` rejection in an earlier round of this same work (that
finding is part of Phase 1 setup, not new here). This round continues:

- **Phase 0** (Milestone 37): `OkxClient.fetch_ohlcv`/`get_balance`/
  `get_open_positions` — real, read-only, already live-verified in an
  earlier session round.
- **Phase 1 code, already implemented but previously unverified**:
  `OkxClient.place_order`/`cancel_order`/`get_order_status`
  (`backend/app/exchange/okx_client.py`), backed by 31 mocked unit tests
  in `backend/tests/test_okx_client.py` — zero real network calls in
  that test file, unchanged this round.

## 2. First live attempt this round — FAILED, root cause confirmed

After Trade permission was granted, the first real attempt to place a
demo order via `scripts/verify_demo_order_lifecycle.py` failed. OKX
returned:

- Top-level `code="1"`
- Per-order `sCode="51020"`
- `sMsg="Your order should meet or exceed the minimum order amount."`

**Root cause, confirmed via a live diagnostic probe reading OKX's actual
per-order response body directly (not guessed)**:
`scripts/verify_demo_order_lifecycle.py` sized its test order using only
OKX's `minSz` (0.00001 BTC for BTC-USDT, approximately $0.65 notional at
the time) fetched from `GET /api/v5/public/instruments`. `minSz`
enforces quantity-granularity only — OKX separately enforces a minimum
order *notional value* (price × size), and this endpoint does not
expose that second, independent floor.

A `code="1"` top-level rejection means OKX created no order at all — no
cleanup was required for this failed attempt.

## 3. Fix — scoped to the test script only

`backend/app/exchange/okx_client.py` was **not** touched by this fix —
this was a test-harness sizing bug, not an `OkxClient` bug.

New pure helper in `scripts/verify_demo_order_lifecycle.py`:

```
compute_order_size(min_sz_str, lot_sz_str, price, min_notional=Decimal("10"))
```

- Returns `minSz` unchanged if its notional already clears the $10 USDT
  floor.
- Otherwise scales the size up to `$10 / price` and rounds **UP** to the
  nearest `lotSz` increment.
- Mirrors the existing `compute_limit_buy_price` helper's round-DOWN-
  for-price logic, but rounds up here — rounding size down could drop
  the order back below the notional floor, defeating the purpose.

**$10 is an explicitly-disclosed conservative choice, not OKX's exact
undocumented threshold** — the true threshold is unknown, somewhere
between the observed ~$0.65 rejection and this $10 floor.

5 new unit tests added to
`backend/tests/test_verify_demo_order_lifecycle.py` (file total went
from 14 to 19 tests, all passing). Full backend suite after this fix:
**882 passed** (up from 877).

## 4. Second live attempt this round — the successful, final one

Full **PASS**, all 11 steps green, a real order placed and cleanly
closed out against OKX's demo-trading endpoint
(`x-simulated-trading: 1` header, never real capital):

| Step | Result |
|---|---|
| `discover_instrument_specs` | minSz=0.00001, lotSz=0.00000001, tickSz=0.1 (BTC-USDT) |
| `compute_limit_price` | last_close=64528.8, limit_price=58075.9 (10% below market, so the order rests as "live" rather than filling) |
| `compute_order_size` | size=0.00017219 BTC, notional_usdt≈10.000089221 (clears the $10 floor) |
| `place_order` | ordId=`3757771015088525312`, clOrdId=`31ac6c168a0d4ca39000970ea3f5dd1b`, sCode="0", sMsg="Order placed" |
| `verify_order_live` | state="live" |
| `cancel_order` | True |
| `verify_order_canceled` | state="canceled" |
| `position_sync_check` | positions before=[], after=[] — sync OK, no position was ever created (the order never filled) |
| `risk_gate_demo` | read-only, informational, non-gating `RiskManager.evaluate()` call — never wired into `run_paper.py`, never touches production risk gating: stop_loss=57495.141, take_profit=59295.4939, rr=2.1, approved=True, reasons=[] |
| **Overall result** | **PASS**, exit_code 0 |

Full JSON report at `scripts/reports/demo_order_lifecycle_verification.json`
(gitignored, same convention as `exchange_readonly_latency.json`).

The order never filled at any point — it stayed "live" until the script
canceled it, so the fill-before-cancel contingency was never triggered
and there is nothing to report on that path.

## 5. Independent post-run verification

Done directly against the live OKX demo account, separate from the
script's own checks:

- `GET /api/v5/trade/orders-pending` → **0 pending orders account-wide**
  (a full account sweep, not just this one order).
- `get_open_positions()` → **0**.
- `get_balance()` → `{BTC: 1.0, ETH: 1.0, OKB: 100.0, USDT: 5000.0}`,
  **identical** to the very first Phase 0 balance snapshot from an
  earlier session round — confirms no capital-analog change occurred;
  nothing was ever actually filled or spent.

## 6. Safety and scope discipline

- `RiskManager.evaluate()` and `scripts/run_paper.py` were **not
  modified** in any way, and **neither is imported** by any of this new
  code (`okx_client.py`, `verify_demo_order_lifecycle.py`) — nothing
  from this milestone is wired into any live/paper-trading path.
- No real (non-demo) OKX endpoint was ever reached —
  `demo=True`/`x-simulated-trading: 1` is hardcoded in the verification
  script's only `OkxClient` construction site, not configurable via
  CLI/env.
- No real capital at risk (demo account only).
- No architecture redesign — `BaseExchange`'s abstract contract was not
  modified (`get_order_status` is a concrete `OkxClient`-only addition,
  deliberately not added to the shared interface so `OrangexClient`'s
  stub remains untouched).
- Full test suite: **882/882 passing**.
- No secrets printed or logged at any point (verified — all diagnostic
  output either omits credential values entirely or only ever surfaces
  OKX's own non-secret response bodies/order IDs).

## 7. What Phase 1 explicitly does NOT include

Per `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md` section 1's phase
table — do not read anything below as done:

- `LiveBroker` adapter implementation (`fill_entry`/`check_exit`
  translation layer).
- The SL/TP order mechanism design decision (roadmap section 3,
  explicitly flagged as needing its own separate sign-off).
- Any wiring into `scripts/run_paper.py` — that is Phase 2, "the first
  phase that touches the gated live-trading file at all."
- Real capital — that is Phase 3.

## 8. Summary

Phase 1 order placement/cancellation against OKX's demo-trading API is
implemented and now live-verified end-to-end, with a real,
previously-undocumented order-sizing floor (OKX's minimum notional
value) found and fixed along the way in the verification tooling, not
in production exchange-client code. `RiskManager.evaluate()`/
`scripts/run_paper.py` remain completely untouched and unwired. See
`ENGINEERING_DECISIONS.md` #79 for the full rationale writeup,
`PROJECT_STATUS.md` milestone 41 for the snapshot entry, and
`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`'s Milestone 41 UPDATE
banner for the phase-table context.
