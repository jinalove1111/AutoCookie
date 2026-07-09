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

    def generate_signal(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        """Analyze market structure for `symbol` and produce a TradeSignal, or None.

        `ltf_candles` and `htf_candles` must be genuinely distinct candle
        series (the project's `DEFAULT_TIMEFRAME` and `HTF_TIMEFRAME`
        respectively, e.g. `5m`/`4h`) — per docs/strategy_spec.md section 1,
        HTF bias must come from a real higher-timeframe series, not the LTF
        series relabeled. `detect_htf_bias()` is called on `htf_candles`
        only; every other detector (liquidity sweep, CHOCH/MSS, FVG, order
        block) stays on `ltf_candles`, matching how those concepts are
        actually traded (structure/entries on the execution timeframe,
        bias from the higher one).

        This is Backtest Mode analysis only: it never places orders. The
        returned TradeSignal is downstream input to the Risk Engine, which
        must approve it before Execution ever sees it.
        """
        if not ltf_candles or not htf_candles:
            return None

        bias = detect_htf_bias(htf_candles)
        sweep = detect_liquidity_sweep(ltf_candles)
        # CHoCH must reflect structure that formed at or after the actual
        # swept point (see market_structure.detect_choch_mss docstring and
        # docs/strategy_spec.md section 3), not any arbitrary earlier
        # structural shift -- so the sweep (if any) is resolved first and
        # its swept_index is threaded into the CHoCH call.
        choch = detect_choch_mss(
            ltf_candles, swept_index=sweep["swept_index"] if sweep else None
        )
        fvg_zones = detect_fair_value_gap(ltf_candles)
        order_block = detect_order_block(ltf_candles)

        model = build_entry_model(bias, sweep, choch, fvg_zones, order_block)
        if model is None:
            return None

        return TradeSignal(
            symbol=symbol,
            direction=model["direction"],
            timestamp=cf(ltf_candles[-1], "timestamp"),
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
