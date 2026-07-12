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
from .order_block import detect_breaker_block, detect_order_block
from .utils import cf, is_zone_mitigated


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
        self,
        symbol: str,
        ltf_candles: list,
        htf_candles: list,
        use_breaker_block: bool = False,
        require_full_confluence: bool = False,
        require_ob_fvg_confluence: bool = False,
    ) -> "TradeSignal | None":
        """Analyze market structure for `symbol` and produce a TradeSignal, or None.

        `use_breaker_block` (default `False`, opt-in -- see
        docs/strategy_coverage_audit.md and docs/ROADMAP.md item #1):
        when `True`, a detected, unmitigated breaker block
        (`detect_breaker_block`) is offered to `build_entry_model` as a
        second zone candidate alongside the order block. `detect_breaker_block`
        has existed and been unit-tested since this project's Milestone 2
        but was never wired into signal generation until this parameter
        was added -- default `False` preserves the exact prior behavior
        for every existing caller (`scripts/run_paper.py`,
        `BacktestEngine.run()`'s own default) while this is A/B tested,
        same discipline as `BacktestEngine`'s `use_breakeven`.

        `require_full_confluence` (default `False`, opt-in -- see
        `entry_model.build_entry_model`'s docstring for the full
        rationale): resolves a real spec/code ambiguity in
        docs/strategy_spec.md section 6 by requiring BOTH a matching
        sweep AND a matching CHOCH (not just one) before a signal is
        produced. Passed straight through to `build_entry_model`.

        `require_ob_fvg_confluence` (default `False`, opt-in -- see
        `entry_model.build_entry_model`'s docstring, and docs/ROADMAP.md
        "Core Rule MVP completion" item #3): requires BOTH a matching
        order block/breaker block AND a matching FVG (not just one)
        before a signal is produced. Passed straight through to
        `build_entry_model`.

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

        Zone mitigation filter (correctness fix, not an optional
        refinement -- see `app.strategy.utils.is_zone_mitigated`'s
        docstring for the full rationale): `detect_fair_value_gap`/
        `detect_order_block` report a zone for as long as it remains
        anywhere in the given `ltf_candles` window, with no awareness of
        whether price has already traded back into it since it formed.
        Without this filter, a still-visible-but-already-tested zone kept
        re-qualifying as "the most recent zone" on consecutive
        walk-forward steps -- confirmed empirically in a real deep
        backtest (see CHANGELOG.md/HANDOFF.md): ~36% of trades in one
        sample were exact duplicate re-entries of a just-failed setup,
        immediately after being stopped out of the identical zone. Any
        FVG/order-block zone already mitigated (price has already
        overlapped it since it formed) is excluded here, BEFORE
        `build_entry_model` ever sees it -- `build_entry_model` itself
        stays a pure function of whatever zones it's handed, unaware of
        mitigation. `detect_fair_value_gap`/`detect_order_block`
        themselves are also left unchanged (mitigation-unaware) since
        `detect_breaker_block` depends on `detect_order_block` returning
        the raw, un-filtered zone to do its own closed-through/retest
        analysis on top of it.
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

        # FVG mitigation window starts right after the 3-candle gap itself
        # (index + 2 -- the candle after the one that completes the gap);
        # order-block mitigation window starts right after the CONFIRMING
        # impulse candle, not the base/zone candle -- see
        # `detect_order_block`'s docstring for why that distinction matters
        # (the impulse candle's own range routinely overlaps the base zone
        # it originated from, which is not mitigation).
        fvg_zones = [
            zone
            for zone in detect_fair_value_gap(ltf_candles)
            if not is_zone_mitigated(ltf_candles, zone["index"] + 2, zone["top"], zone["bottom"])
        ]
        order_block = detect_order_block(ltf_candles)
        if order_block is not None and is_zone_mitigated(
            ltf_candles, order_block["impulse_index"] + 1, order_block["top"], order_block["bottom"]
        ):
            order_block = None

        # Breaker block mitigation window starts right after its RETEST
        # candle (the one that confirmed the flip), not the original
        # order block's base candle -- mirrors the order-block
        # impulse_index reasoning above: the retest candle IS the
        # event that made this zone tradeable, so mitigation can only
        # happen strictly after it.
        breaker_block = None
        if use_breaker_block:
            breaker_block = detect_breaker_block(ltf_candles)
            if breaker_block is not None and is_zone_mitigated(
                ltf_candles,
                breaker_block["retest_index"] + 1,
                breaker_block["top"],
                breaker_block["bottom"],
            ):
                breaker_block = None

        model = build_entry_model(
            bias,
            sweep,
            choch,
            fvg_zones,
            order_block,
            breaker_block,
            require_full_confluence=require_full_confluence,
            require_ob_fvg_confluence=require_ob_fvg_confluence,
        )
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
