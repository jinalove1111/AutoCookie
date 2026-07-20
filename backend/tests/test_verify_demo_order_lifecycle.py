"""Tests for `scripts/verify_demo_order_lifecycle.py`'s pure-logic
helpers only: `PlainDecimalFloat`, `parse_instrument_specs`,
`compute_limit_buy_price`, and `build_risk_demo_signal`. The live
orchestration flow (`main()`) is NOT unit-tested here -- it requires a
real OKX demo-trading account and is verified by the actual supervised
run instead (per this script's own module docstring).

`scripts/` is a sibling directory to `backend/`, not a package under it
-- added to `sys.path` explicitly, same convention every other
`scripts/`-reaching test file in this suite already uses (see
`test_migrate_paper_db_cli.py`).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import verify_demo_order_lifecycle as lifecycle  # noqa: E402

from app.risk.risk_manager import RiskManager  # noqa: E402


# --- PlainDecimalFloat ---


def test_plain_decimal_float_str_avoids_scientific_notation():
    value = lifecycle.PlainDecimalFloat("0.00001")
    assert str(value) == "0.00001"
    # And it still behaves as a real float numerically.
    assert float(value) == pytest.approx(0.00001)


def test_plain_decimal_float_preserves_normal_magnitudes():
    value = lifecycle.PlainDecimalFloat("43250.5")
    assert str(value) == "43250.5"
    assert float(value) == pytest.approx(43250.5)


def test_plain_decimal_float_default_str_would_have_used_scientific_notation():
    # Sanity check that this is a real bug being worked around, not a
    # hypothetical one: plain float str() really does do this.
    assert str(0.00001) == "1e-05"


# --- parse_instrument_specs ---


def test_parse_instrument_specs_happy_path():
    instrument = {
        "instId": "BTC-USDT",
        "minSz": "0.00001",
        "lotSz": "0.00001",
        "tickSz": "0.1",
    }
    specs = lifecycle.parse_instrument_specs(instrument)
    assert specs == {
        "min_sz_str": "0.00001",
        "lot_sz_str": "0.00001",
        "tick_sz_str": "0.1",
    }


def test_parse_instrument_specs_missing_min_sz_raises():
    with pytest.raises(ValueError, match="minSz/lotSz"):
        lifecycle.parse_instrument_specs({"instId": "BTC-USDT", "lotSz": "0.00001"})


def test_parse_instrument_specs_missing_lot_sz_raises():
    with pytest.raises(ValueError, match="minSz/lotSz"):
        lifecycle.parse_instrument_specs({"instId": "BTC-USDT", "minSz": "0.00001"})


def test_parse_instrument_specs_missing_tick_sz_defaults_to_empty_string():
    instrument = {"instId": "BTC-USDT", "minSz": "0.00001", "lotSz": "0.00001"}
    specs = lifecycle.parse_instrument_specs(instrument)
    assert specs["tick_sz_str"] == ""


# --- compute_limit_buy_price ---


def test_compute_limit_buy_price_ten_percent_below_no_tick():
    price = lifecycle.compute_limit_buy_price(100.0, tick_sz_str="")
    assert price == Decimal("90.0")


def test_compute_limit_buy_price_floors_to_tick_size():
    # 100 * 0.9 = 90.0 exactly divisible by 0.1, so tick flooring should
    # not change the result in this case.
    price = lifecycle.compute_limit_buy_price(100.0, tick_sz_str="0.1")
    assert price == Decimal("90.0")


def test_compute_limit_buy_price_floors_down_not_up():
    # last_close chosen so 10%-below lands mid-tick: 43250.55 * 0.9 =
    # 38925.495, tick 0.1 -> floors to 38925.4 (never rounds up, which
    # would move the price closer to market than the requested 10%).
    price = lifecycle.compute_limit_buy_price(43250.55, tick_sz_str="0.1")
    assert price == Decimal("38925.4")
    assert price <= Decimal("43250.55") * Decimal("0.9")


def test_compute_limit_buy_price_custom_pct_below():
    price = lifecycle.compute_limit_buy_price(
        100.0, tick_sz_str="", pct_below=Decimal("0.05")
    )
    assert price == Decimal("95.0")


# --- compute_order_size ---


def test_compute_order_size_already_clears_notional_floor_stays_at_min_sz():
    # minSz=1, price=100 -> notional 100, well above the (default) $10
    # floor, so the result must be minSz unchanged (no lot-size rounding
    # applied at all -- OKX's minSz is already a legal size).
    size = lifecycle.compute_order_size("1", "0.1", Decimal("100"))
    assert size == Decimal("1")


def test_compute_order_size_real_observed_case_clears_notional_floor():
    # The real diagnosed rejection: minSz=0.00001 BTC, lotSz=0.00000001,
    # price~=64489.7, notional floor $10. minSz alone gives notional
    # ~$0.65 (the value OKX actually rejected), so this must scale up.
    min_sz_str = "0.00001"
    lot_sz_str = "0.00000001"
    price = Decimal("64489.7")
    size = lifecycle.compute_order_size(min_sz_str, lot_sz_str, price)
    notional = size * price
    assert size > Decimal(min_sz_str)
    assert notional >= Decimal("10")
    # Result must still be a legal lotSz increment.
    assert (size / Decimal(lot_sz_str)) == (size / Decimal(lot_sz_str)).to_integral_value()


def test_compute_order_size_rounds_up_not_down_at_lot_boundary():
    # min_notional / price lands mid-lot; rounding must move size UP to
    # the next lot increment so the final notional still clears the
    # floor (rounding down here would drop it back below $10, the
    # mirror-image failure to compute_limit_buy_price rounding toward
    # market).
    min_sz_str = "0.0001"  # deliberately small so scaling up is required
    lot_sz_str = "0.001"
    price = Decimal("33")  # 10 / 33 = 0.30303..., mid-lot for lotSz=0.001
    size = lifecycle.compute_order_size(min_sz_str, lot_sz_str, price, min_notional=Decimal("10"))
    # Raw unrounded target would be 10/33 = 0.303030... -> rounds UP to 0.304,
    # not DOWN to 0.303 (which would leave notional = 0.303*33 = 9.999 < 10).
    assert size == Decimal("0.304")
    assert size * price >= Decimal("10")
    down_rounded = Decimal("0.303")
    assert down_rounded * price < Decimal("10")


def test_compute_order_size_missing_lot_sz_str_treated_as_no_rounding_constraint():
    # Documented choice: a falsy/missing lot_sz_str means "no rounding
    # constraint" rather than raising, since the size was scaled up from
    # real minSz/price data and OKX's own place_order call remains the
    # final validator either way.
    size = lifecycle.compute_order_size("0.00001", "", Decimal("64489.7"), min_notional=Decimal("10"))
    assert size == Decimal("10") / Decimal("64489.7")
    assert size * Decimal("64489.7") >= Decimal("10")


def test_compute_order_size_rejects_non_positive_price():
    with pytest.raises(ValueError, match="positive"):
        lifecycle.compute_order_size("0.00001", "0.00000001", Decimal("0"))


# --- build_risk_demo_signal ---


def test_build_risk_demo_signal_rr_clears_min_rr():
    signal = lifecycle.build_risk_demo_signal(Decimal("100.0"), min_rr=2.0)
    assert signal.stop_loss == pytest.approx(99.0)  # 1% below entry
    assert signal.rr > 2.0
    assert signal.take_profit > 100.0


def test_build_risk_demo_signal_matches_default_min_rr_example():
    # Spec example: "stop_loss 1% below entry, take_profit 2%+ above
    # entry so RR >= settings.MIN_RR" for the default MIN_RR=2 case.
    signal = lifecycle.build_risk_demo_signal(Decimal("100.0"), min_rr=2.0)
    assert signal.take_profit >= 102.0


def test_build_risk_demo_signal_passes_real_risk_manager_gate():
    # End-to-end (but still fully offline/pure) check: the signal this
    # helper builds is actually approved by the real RiskManager, not
    # just numerically plausible.
    signal = lifecycle.build_risk_demo_signal(Decimal("100.0"), min_rr=2.0)
    decision = RiskManager().evaluate(signal)
    assert decision.approved is True
    assert decision.reasons == []
