"""verify_demo_order_lifecycle.py

Phase 1 (order lifecycle) of `docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`
verification: a standalone script that exercises `OkxClient.place_order`/
`cancel_order`/`get_order_status` end-to-end against OKX's real
**demo-trading** environment (`x-simulated-trading: 1`, never real
capital) -- place a resting limit-buy order, verify it, cancel it, verify
the cancellation, and check position sync, plus a read-only informational
pass through `RiskManager.evaluate()`. Same pattern as
`scripts/measure_exchange_readonly_latency.py`: standalone, additive,
never touches `scripts/run_paper.py` or any live-trading path.

**Refuses to run without real OKX demo credentials configured**
(`OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE`), matching this
repo's established fail-closed safety-check pattern.

**`demo=True` is hardcoded when constructing `OkxClient` below -- no CLI
flag or environment variable in this script can ever change that.** This
is deliberate defense-in-depth, not an oversight: even if credentials
supplied to this script were ever real-money credentials by operator
mistake, this script is structurally incapable of routing a request at
OKX's real-money endpoint, because the one line that constructs the
client never reads a `demo` value from argv or the environment.

This does NOT place this platform on OKX in any way: `OkxClient` is not
imported by `scripts/run_paper.py` or any other live-trading path. This
script performs at most one order placement per run and always attempts
to cancel it before exiting.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.data.candle_fetcher import to_okx_symbol  # noqa: E402
from app.exchange.okx_client import OKX_BASE_URL, OkxClient  # noqa: E402
from app.risk.risk_manager import RiskManager, SignalLike  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

OUTPUT_PATH = SCRIPT_DIR / "reports" / "demo_order_lifecycle_verification.json"
OKX_PUBLIC_INSTRUMENTS_PATH = "/api/v5/public/instruments"

# How far below the last close to place the resting limit-buy, and why
# 10% specifically: deep enough that the order will not fill during this
# script's short runtime (avoiding an accidental real-ish demo fill mid-
# verification), but not so deep that OKX's price-band validation on spot
# BTC-USDT limit orders is likely to reject it outright. If OKX does
# reject it for a price-band reason, that surfaces as a plain, non-
# swallowed RuntimeError from `OkxClient.place_order` -- this script does
# not retry at a different price (order placement must not blindly
# retry, per `okx_client.py`'s own documented POST-idempotency policy;
# see its `_private_post` docstring).
LIMIT_PRICE_PCT_BELOW_CLOSE = Decimal("0.10")

# OKX enforces a minimum order *notional* value (price x size) on top of
# minSz's quantity-granularity floor, but does NOT expose it via
# GET /api/v5/public/instruments -- confirmed via a real live rejection
# (sCode 51020, "Your order should meet or exceed the minimum order
# amount") when this script sized its BTC-USDT test order at exactly
# minSz (0.00001 BTC, ~$0.65 notional at the time). $10 is not OKX's
# exact undocumented threshold (unknown, somewhere between that observed
# ~$0.65 rejection and this value) -- it is a conservative floor
# comfortably above any realistic minimum, chosen to avoid a second round
# of live trial-and-error against the real exchange to pin the exact
# number down, while remaining trivial demo money either way.
MIN_NOTIONAL_USDT_FLOOR = Decimal("10")

# `RiskManager.evaluate()`'s informational demo signal (step 10): stop
# 1% below the order's own limit price, take-profit set with a small
# margin above `settings.MIN_RR` so it clears the gate even accounting
# for float rounding at the exact boundary.
RISK_DEMO_SL_PCT = Decimal("0.01")
RISK_DEMO_RR_MARGIN = Decimal("0.1")


# --- Pure helpers (unit-tested in backend/tests/test_verify_demo_order_lifecycle.py) ---


class PlainDecimalFloat(float):
    """A `float` subclass whose `str()` always renders as a plain fixed-
    point decimal, never Python's default scientific notation.

    Needed because `OkxClient.place_order`'s request body builds
    `"sz": str(size)` and `"px": str(price)` directly (see
    `backend/app/exchange/okx_client.py`, out of scope to modify here),
    and Python's default `float.__str__` switches to scientific notation
    for small magnitudes -- e.g. `str(0.00001) == "1e-05"` -- which OKX's
    order-size/price fields do not accept. BTC-USDT's real `minSz` is
    exactly this kind of small value (confirmed via the public
    instruments endpoint at step 3, not guessed), so this is a real,
    not hypothetical, formatting bug this script must avoid triggering.

    This class owns the workaround locally (in this new, in-scope
    script) rather than editing `okx_client.py`, which is out of this
    change's allowed scope.
    """

    def __new__(cls, decimal_str: str) -> "PlainDecimalFloat":
        obj = super().__new__(cls, decimal_str)
        return obj

    def __init__(self, decimal_str: str) -> None:
        self._decimal_str = decimal_str

    def __str__(self) -> str:
        return self._decimal_str

    def __repr__(self) -> str:
        return f"PlainDecimalFloat({self._decimal_str!r})"


def parse_instrument_specs(instrument: dict[str, Any]) -> dict[str, str]:
    """Extract `minSz`/`lotSz`/`tickSz` as their original decimal strings
    (never round-tripped through a lossy Python float) from one entry of
    OKX's `GET /api/v5/public/instruments` response.

    Raises `ValueError` if the required fields are missing -- callers
    must not fall back to a guessed size.
    """
    min_sz = instrument.get("minSz")
    lot_sz = instrument.get("lotSz")
    tick_sz = instrument.get("tickSz")
    if not min_sz or not lot_sz:
        raise ValueError(
            f"OKX instrument response missing minSz/lotSz, refusing to guess: {instrument!r}"
        )
    return {"min_sz_str": min_sz, "lot_sz_str": lot_sz, "tick_sz_str": tick_sz or ""}


def compute_limit_buy_price(
    last_close: float,
    tick_sz_str: str = "",
    pct_below: Decimal = LIMIT_PRICE_PCT_BELOW_CLOSE,
) -> Decimal:
    """Compute a limit-buy price `pct_below` (default 10%) under
    `last_close`, floored to the nearest `tick_sz_str` multiple if one is
    supplied (so the price OKX actually validates is a legal increment).
    Flooring (never rounding up) guarantees the result stays at or below
    the target 10%-below level, never closer to market than requested.

    Returns a `Decimal` (exact); callers that need to hand this to
    `OkxClient.place_order` should wrap it in `PlainDecimalFloat` via
    `format(price, "f")` to avoid scientific-notation formatting.
    """
    raw = Decimal(str(last_close)) * (Decimal("1") - pct_below)
    if tick_sz_str:
        tick = Decimal(tick_sz_str)
        if tick > 0:
            raw = (raw / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return raw


def compute_order_size(
    min_sz_str: str,
    lot_sz_str: str,
    price: Decimal,
    min_notional: Decimal = MIN_NOTIONAL_USDT_FLOOR,
) -> Decimal:
    """Compute an order size that satisfies both OKX's `minSz` quantity
    floor and a minimum order-notional floor (`min_notional`, default
    `MIN_NOTIONAL_USDT_FLOOR`) that OKX enforces but does not expose via
    `GET /api/v5/public/instruments` -- see `MIN_NOTIONAL_USDT_FLOOR`'s
    comment for the real rejection this fixes.

    Starts from `min_sz_str`. If `min_sz_str * price` already clears
    `min_notional`, returns it unchanged (no lot-size rounding applied --
    `minSz` as returned by OKX is already a legal size). Otherwise scales
    up to `min_notional / price` and rounds UP to the nearest
    `lot_sz_str` increment -- the mirror image of
    `compute_limit_buy_price`'s round-down-for-price logic: there,
    rounding toward market would defeat the "rest as live, don't fill"
    goal, so it floors; here, rounding size *down* could drop the final
    size back below the notional floor, so it must round up instead.

    `lot_sz_str` of `""`/falsy is treated as "no rounding constraint", not
    an error -- a size scaled up from live minSz/price data has no legal-
    increment information to round to in that case, and refusing to place
    any order at all over a missing formatting field would be a worse
    failure mode than an unrounded (but still notional-floor-clearing)
    size; OKX's own order-placement call remains the final validator
    either way.

    Returns a `Decimal` (exact); callers that need to hand this to
    `OkxClient.place_order` should wrap it in `PlainDecimalFloat` via
    `format(size, "f")`, same as `compute_limit_buy_price`.
    """
    if price <= 0:
        raise ValueError(f"price must be positive to compute order size, got {price!r}")
    size = Decimal(min_sz_str)
    if size * price >= min_notional:
        return size
    size = min_notional / price
    if lot_sz_str:
        lot = Decimal(lot_sz_str)
        if lot > 0:
            size = (size / lot).to_integral_value(rounding=ROUND_UP) * lot
    return size


def build_risk_demo_signal(
    entry_price: Decimal,
    min_rr: float,
    sl_pct: Decimal = RISK_DEMO_SL_PCT,
    rr_margin: Decimal = RISK_DEMO_RR_MARGIN,
) -> SimpleNamespace:
    """Build a local `SignalLike`-shaped object from an order's own limit
    price, for `RiskManager.evaluate()`'s read-only informational demo
    call (step 10 -- this never gates anything real, `run_paper.py` is
    never imported here).

    Stop-loss `sl_pct` (default 1%) below entry; take-profit set so RR
    clears `min_rr` with `rr_margin` headroom (default +0.1), avoiding a
    boundary-exact RR that could fail on float rounding.
    """
    entry = float(entry_price)
    stop_loss = entry * (1 - float(sl_pct))
    risk_distance = entry - stop_loss
    reward_distance = risk_distance * (min_rr + float(rr_margin))
    take_profit = entry + reward_distance
    rr = reward_distance / risk_distance if risk_distance else 0.0
    return SimpleNamespace(stop_loss=stop_loss, take_profit=take_profit, rr=rr)


# --- Orchestration ---


def _fetch_instrument_specs(inst_id: str) -> dict[str, str]:
    """Call OKX's public (unauthenticated) instruments endpoint and parse
    the real minSz/lotSz/tickSz for `inst_id`. Aborts (raises) on any
    failure -- no guessed-size fallback."""
    response = httpx.get(
        f"{OKX_BASE_URL}{OKX_PUBLIC_INSTRUMENTS_PATH}",
        params={"instType": "SPOT", "instId": inst_id},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "0":
        raise RuntimeError(
            f"OKX public instruments call failed for {inst_id}: "
            f"code={payload.get('code')!r} msg={payload.get('msg')!r}"
        )
    data = payload.get("data", [])
    matching = [entry for entry in data if entry.get("instId") == inst_id]
    if not matching:
        raise RuntimeError(
            f"OKX public instruments call returned no entry for {inst_id}: {payload!r}"
        )
    return parse_instrument_specs(matching[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbol",
        default=settings.SYMBOL,
        help="Project-style symbol to test (default: settings.SYMBOL, e.g. BTCUSDT). "
        "Never controls demo-vs-real routing -- that is hardcoded.",
    )
    args = parser.parse_args()
    symbol = args.symbol

    if not (settings.OKX_API_KEY and settings.OKX_API_SECRET and settings.OKX_API_PASSPHRASE):
        print(
            "REFUSING TO RUN: OKX_API_KEY/OKX_API_SECRET/OKX_API_PASSPHRASE must "
            "all be set (OKX demo-trading credentials -- see "
            "docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md). This script requires "
            "real (demo) credentials before it can produce a result, and does not "
            "fabricate them."
        )
        return 1

    # Hardcoded demo=True -- see module docstring "defense-in-depth" note.
    # This is the ONLY place OkxClient is constructed in this script; no
    # CLI flag or env var feeds into this argument.
    client = OkxClient(demo=True)
    logger.info(
        "Using OKX demo-trading endpoint (x-simulated-trading: 1) for symbol=%s", symbol
    )

    steps: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: Any = None) -> None:
        steps.append({"step": name, "passed": passed, "detail": detail})
        marker = "PASS" if passed else "FAIL"
        logger.info("[%s] %s: %s", marker, name, detail)

    record(
        "credentials_check",
        True,
        "OKX_API_KEY/OKX_API_SECRET/OKX_API_PASSPHRASE all present (values never logged)",
    )
    record("demo_mode_lock", True, "OkxClient constructed with demo=True (hardcoded)")

    inst_id: str | None = None
    order_id: str | None = None
    client_order_id: str | None = None
    exit_code = 1

    try:
        inst_id = to_okx_symbol(symbol)

        # Step 3: discover real minimum order size (never guessed).
        specs = _fetch_instrument_specs(inst_id)
        record(
            "discover_instrument_specs",
            True,
            {
                "instId": inst_id,
                "minSz": specs["min_sz_str"],
                "lotSz": specs["lot_sz_str"],
                "tickSz": specs["tick_sz_str"],
            },
        )

        # Step 4: current price + computed limit-buy price.
        candles = client.fetch_ohlcv(symbol, "1m", limit=1)
        if not candles:
            raise RuntimeError("fetch_ohlcv returned no candles; cannot determine current price")
        last_close = candles[-1]["close"]
        limit_price_decimal = compute_limit_buy_price(last_close, specs["tick_sz_str"])
        limit_price = PlainDecimalFloat(format(limit_price_decimal, "f"))
        record(
            "compute_limit_price",
            True,
            {
                "last_close": last_close,
                "pct_below": str(LIMIT_PRICE_PCT_BELOW_CLOSE),
                "limit_price": str(limit_price),
            },
        )

        # Step 4b: order size that clears both minSz AND OKX's separate,
        # undocumented minimum-notional floor -- see
        # MIN_NOTIONAL_USDT_FLOOR's module-level comment. minSz alone was
        # confirmed insufficient by a real, diagnosed live rejection
        # (sCode 51020) prior to this fix.
        order_size_decimal = compute_order_size(
            specs["min_sz_str"], specs["lot_sz_str"], limit_price_decimal
        )
        order_size = PlainDecimalFloat(format(order_size_decimal, "f"))
        notional = order_size_decimal * limit_price_decimal
        record(
            "compute_order_size",
            notional >= MIN_NOTIONAL_USDT_FLOOR,
            {
                "min_sz": specs["min_sz_str"],
                "lot_sz": specs["lot_sz_str"],
                "size": str(order_size),
                "notional_usdt": str(notional),
                "min_notional_floor": str(MIN_NOTIONAL_USDT_FLOOR),
            },
        )
        if notional < MIN_NOTIONAL_USDT_FLOOR:
            raise RuntimeError(
                f"Computed order size {order_size_decimal} at price "
                f"{limit_price_decimal} yields notional {notional}, still below "
                f"required floor {MIN_NOTIONAL_USDT_FLOOR} -- refusing to place."
            )

        # Position snapshot before order placement (step 9 baseline).
        positions_before = client.get_open_positions()
        logger.info("Open positions before order placement: %d", len(positions_before))

        # Step 5: place the order.
        place_result = client.place_order(
            symbol, "buy", "limit", size=order_size, price=limit_price
        )
        order_id = place_result.get("ordId")
        client_order_id = place_result.get("clOrdId")
        record(
            "place_order",
            True,
            {
                "ordId": order_id,
                "clOrdId": client_order_id,
                "sCode": place_result.get("sCode"),
                "sMsg": place_result.get("sMsg"),
                "size": str(order_size),
                "price": str(limit_price),
            },
        )

        # Step 6: verify order status is "live".
        status = client.get_order_status(symbol, order_id)
        state = status.get("state")
        if state == "partially_filled":
            record(
                "verify_order_live",
                False,
                {
                    "state": state,
                    "alert": "ABORT: order partially filled -- capital-analog "
                    "exposure exists (safe here, demo money only, but this is "
                    "logged loudly per spec). Stopping before further steps.",
                },
            )
            raise RuntimeError(
                f"Order {order_id} is partially_filled -- hard-abort per policy, "
                "not proceeding to cancellation silently."
            )
        if state != "live":
            record("verify_order_live", False, {"state": state, "raw": status})
            raise RuntimeError(
                f"Order {order_id} has unexpected state {state!r} (expected 'live'): {status!r}"
            )
        record("verify_order_live", True, {"state": state})

        # Step 7: cancel the order.
        cancel_result = client.cancel_order(symbol, order_id)
        record("cancel_order", cancel_result is True, {"result": cancel_result})
        if cancel_result is not True:
            raise RuntimeError(
                f"cancel_order({order_id!r}) returned {cancel_result!r}, expected True"
            )

        # Step 8: verify order status is now "canceled".
        status_after_cancel = client.get_order_status(symbol, order_id)
        state_after_cancel = status_after_cancel.get("state")
        record(
            "verify_order_canceled",
            state_after_cancel == "canceled",
            {"state": state_after_cancel},
        )
        if state_after_cancel != "canceled":
            raise RuntimeError(
                f"Order {order_id} state after cancel is {state_after_cancel!r}, "
                f"expected 'canceled': {status_after_cancel!r}"
            )

        # Step 9: verify position list is unchanged (this order never fills).
        positions_after = client.get_open_positions()
        sync_ok = positions_before == positions_after
        record(
            "position_sync_check",
            sync_ok,
            {
                "positions_before": positions_before,
                "positions_after": positions_after,
                "sync": "OK" if sync_ok else "MISMATCH",
            },
        )
        if not sync_ok:
            raise RuntimeError(
                "Open positions changed across a non-filling limit order's "
                "lifecycle -- position sync MISMATCH."
            )

        # Step 10: read-only risk-gate sanity check (informational only;
        # never imports/touches scripts/run_paper.py or gates anything real).
        risk_signal = build_risk_demo_signal(limit_price_decimal, settings.MIN_RR)
        assert isinstance(risk_signal, SignalLike)  # structural shape check
        decision = RiskManager().evaluate(risk_signal)
        record(
            "risk_gate_demo",
            True,
            {
                "signal": {
                    "stop_loss": risk_signal.stop_loss,
                    "take_profit": risk_signal.take_profit,
                    "rr": risk_signal.rr,
                },
                "approved": decision.approved,
                "reasons": decision.reasons,
            },
        )

        exit_code = 0

    except Exception as exc:
        logger.error("Verification failed: %s", exc)
        steps.append({"step": "unhandled_error", "passed": False, "detail": str(exc)})
        exit_code = 1

    finally:
        # Best-effort cleanup: never leave a live/partially-filled demo
        # order dangling. A failure here must not mask the original error.
        if order_id is not None:
            try:
                final_status = client.get_order_status(symbol, order_id)
                final_state = final_status.get("state")
                if final_state not in ("canceled", "filled"):
                    logger.warning(
                        "Cleanup: order %s still in state %r, attempting best-effort cancel",
                        order_id,
                        final_state,
                    )
                    cleanup_result = client.cancel_order(symbol, order_id)
                    logger.warning("Cleanup cancel result for %s: %s", order_id, cleanup_result)
                    steps.append(
                        {
                            "step": "cleanup_cancel",
                            "passed": cleanup_result is True,
                            "detail": {"order_id": order_id, "result": cleanup_result},
                        }
                    )
            except Exception as cleanup_exc:
                logger.error(
                    "Cleanup attempt for order %s FAILED -- manual check required: %s",
                    order_id,
                    cleanup_exc,
                )
                steps.append(
                    {
                        "step": "cleanup_cancel",
                        "passed": False,
                        "detail": f"cleanup raised: {cleanup_exc}",
                    }
                )

    report = {
        "disclosed_scope": (
            "Phase 1 order-lifecycle verification only: place_order (limit "
            "buy, minimum discovered size, ~10% below market so it rests "
            "as 'live'), get_order_status, cancel_order, get_order_status "
            "again, plus a read-only get_open_positions sync check and an "
            "informational (non-gating) RiskManager.evaluate() pass. "
            "Never wired into scripts/run_paper.py or any live-trading path."
        ),
        "demo_mode": True,
        "symbol": symbol,
        "inst_id": inst_id,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "steps": steps,
        "overall_result": "PASS" if exit_code == 0 else "FAIL",
        "exit_code": exit_code,
    }
    print("\n### Summary ###")
    print(json.dumps(report, indent=2, default=str))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWritten to {OUTPUT_PATH}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
