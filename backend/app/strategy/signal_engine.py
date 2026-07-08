"""Top-level Strategy Engine orchestrator.

This engine only produces signals. It must never place orders directly —
signals are validated by the Risk Engine before reaching Execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bias import detect_htf_bias
from .entry_model import build_entry_model
from .fvg import detect_fair_value_gap
from .liquidity import detect_liquidity_sweep
from .market_structure import detect_choch_mss
from .order_block import detect_order_block
from .utils import cf


@dataclass
class TradeSignal:
    """Data contract for a generated trade signal, matching the `signals` DB table."""

    symbol: str
    direction: str
    timestamp: str
    htf_bias: str
    sweep_type: str | None
    choch_detected: bool
    fvg_zone: dict | None
    entry_price: float
    stop_loss: float
    take_profit: float
    rr: float
    status: str


class SignalEngine:
    """Orchestrates bias/liquidity/structure/FVG/order-block analysis into a TradeSignal."""

    def generate_signal(self, symbol: str, candles: list) -> "TradeSignal | None":
        """Analyze market structure for `symbol` and produce a TradeSignal, or None.

        This is Backtest Mode analysis only: it never places orders. The
        returned TradeSignal is downstream input to the Risk Engine, which
        must approve it before Execution ever sees it.
        """
        if not candles:
            return None

        bias = detect_htf_bias(candles)
        sweep = detect_liquidity_sweep(candles)
        choch = detect_choch_mss(candles)
        fvg_zones = detect_fair_value_gap(candles)
        order_block = detect_order_block(candles)

        model = build_entry_model(bias, sweep, choch, fvg_zones, order_block)
        if model is None:
            return None

        return TradeSignal(
            symbol=symbol,
            direction=model["direction"],
            timestamp=cf(candles[-1], "timestamp"),
            htf_bias=bias,
            sweep_type=sweep["type"] if sweep else None,
            choch_detected=bool(choch),
            fvg_zone=model["zone"],
            entry_price=model["entry_price"],
            stop_loss=model["stop_loss"],
            take_profit=model["take_profit"],
            rr=model["rr"],
            status="pending",
        )
