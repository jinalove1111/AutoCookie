"""Top-level Strategy Engine orchestrator.

This engine only produces signals. It must never place orders directly —
signals are validated by the Risk Engine before reaching Execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bias import detect_htf_bias
from .entry_model import build_entry_model
from .exit_point_engine import find_exit_targets
from .fvg import find_latest_unmitigated_fvg_zone
from .jade_trade_plan import build_trade_plan
from .liquidity import detect_liquidity_sweep
from .market_structure import (
    detect_choch_mss,
    find_previous_swing_high,
    find_previous_swing_low,
)
from .order_block import detect_breaker_block, detect_order_block
from .premium_discount import calculate_premium_discount
from .session_liquidity import _ASIAN_SESSION, _LONDON_SESSION
from .utils import average_true_range, cf, is_zone_mitigated

_SESSION_WINDOWS = {"asian": _ASIAN_SESSION, "london": _LONDON_SESSION}


def _select_unmitigated_fvg_zones(ltf_candles: list, bias: str) -> list[dict]:
    """Return the (at most one) FVG zone `build_entry_model` will actually
    use, computed with far less work than eagerly detecting/filtering
    every zone in history.

    PERFORMANCE (2026-07-17, Performance round 2 / Milestone 22 -- see
    ENGINEERING_DECISIONS.md and the M19 precedent
    `order_block.detect_order_block`'s reverse-scan early-exit):
    profiling a 3000-candle walk-forward (see docs/PERFORMANCE_M22.md)
    found `is_zone_mitigated` at 22.2% of total runtime, called ~350
    times per step -- one call per FVG zone `detect_fair_value_gap`
    returned (O(n) zones), because the OLD code here eagerly filtered
    EVERY zone (both bullish and bearish) for mitigation before handing
    the whole list to `build_entry_model`.

    `build_entry_model` (entry_model.py) only ever extracts ONE fact from
    that list: `matching_fvgs = [z for z in fvg if z["type"] ==
    wanted_type]; fvg_zone = max(matching_fvgs, key=lambda z:
    z["index"])` -- the HIGHEST-index zone whose `type` matches
    `wanted_type`. `wanted_type` is provably identical to `bias` itself:
    `build_entry_model` returns `None` before `wanted_type` is ever
    derived unless `bias in ("bullish", "bearish")`, and for those two
    surviving values `wanted_type = "bullish" if direction == "long"
    else "bearish"` collapses to exactly `bias` (`direction == "long"`
    iff `bias == "bullish"`). So the type this call needs is already
    known here, from `bias` (computed above, before this call) -- no
    need to wait for `build_entry_model` to filter it out downstream.

    `bias not in ("bullish", "bearish")` (neutral) short-circuits to `[]`
    immediately without even calling into `fvg.py` -- `build_entry_model`
    returns `None` on that condition before ever touching its `fvg`
    parameter, so the exact zones (if any) that would otherwise have been
    found are unobservable in that case.

    `fvg.find_latest_unmitigated_fvg_zone` does the actual work: a single
    reverse scan (newest candle first) that fuses gap detection, type
    filtering, and mitigation checking with an early exit at the first
    match -- see that function's own docstring for the full
    argmax-identity proof (this function used to do the reverse walk
    itself over `detect_fair_value_gap`'s full forward-scanned output;
    that intermediate step was folded into `fvg.py` once it became clear
    the forward scan itself was unnecessary work for this caller).

    Returned as a single-or-empty LIST (not a bare zone) to preserve
    `build_entry_model`'s existing list-based `fvg` parameter contract
    unchanged (entry_model.py is not touched by this optimization) --
    `build_entry_model`'s own `[z for z in fvg if z["type"] ==
    wanted_type]` filter is a no-op here since the zone in this list, if
    any, already has `type == bias == wanted_type`.

    See test_strategy_signal_engine.py's and test_strategy_fvg.py's
    property tests (verbatim reference copies of the old
    eager-detect-then-filter-both-types logic, 5,000+ seeded synthetic
    series each) for the bit-identical verification this docstring's
    claims were checked against.
    """
    if bias not in ("bullish", "bearish"):
        return []

    zone = find_latest_unmitigated_fvg_zone(ltf_candles, bias)
    return [zone] if zone is not None else []


@dataclass
class TradeSignal:
    """Data contract for a generated trade signal, matching the `signals` DB table.

    `jade_plan` (default `None`, additive -- see `generate_signal`'s
    `use_jade_engine` docstring and ENGINEERING_DECISIONS.md #34): the
    full `jade_trade_plan.build_trade_plan` result when the signal came
    from the Jade path, else `None`. Not a `signals` DB column -- carries
    the rich Jade-only detail (confidence score, ranked exit targets,
    HTF confluence, trendline/CRT/session-bias context, reason lists)
    that the DB-mapped fields below cannot represent, for any caller
    that wants it before it's persisted/discarded downstream.
    """

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
    jade_plan: dict | None = None


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
        use_structure_tp: bool = False,
        require_premium_discount_filter: bool = False,
        use_jade_engine: bool = False,
        structure_tp_max_r: float | None = None,
        require_session: str | None = None,
        atr_stop_multiplier: float | None = None,
    ) -> "TradeSignal | None":
        """Analyze market structure for `symbol` and produce a TradeSignal, or None.

        `use_jade_engine` (default `False`, opt-in -- see
        ENGINEERING_DECISIONS.md #34): when `True`, bypasses the entire
        legacy pipeline below (bias/sweep/CHOCH/FVG/OB/breaker via
        `entry_model.build_entry_model`) and instead calls
        `jade_trade_plan.build_trade_plan(ltf_candles, htf_candles)` --
        the complete Jade methodology (bias, all 5 entry models, exit
        targets, HTF confluence, trendline, CRT, session bias), reused
        unmodified. Every other parameter on this method is IGNORED when
        `use_jade_engine=True` (they only configure the legacy path).

        Field mapping onto `TradeSignal` (a real, if imperfect, fit --
        the Jade plan is far richer than this dataclass's fixed,
        DB-column-matched shape, see `TradeSignal.jade_plan`'s own
        docstring for how the full detail is preserved anyway):
        `entry_price` is the entry zone's edge closest to how a real
        order would fill (`top` for a long, `bottom` for a short -- the
        SAME convention `entry_model.build_entry_model` already uses,
        not the "zone midpoint" convention `exit_point_engine`/
        `htf_ltf_confluence` use internally for a different problem --
        see ENGINEERING_DECISIONS.md #34). `take_profit` is the NEAREST
        exit target (`exit_targets[0]`, already ranked nearest-to-
        farthest by `find_exit_targets`); if `exit_targets` is empty,
        this returns `None` rather than fabricate a target the Jade
        system itself didn't find. `rr` is the REAL reward:risk implied
        by that specific entry/stop/target (not a fixed constant -- same
        "recompute rr against the Risk Engine's real MIN_RR gate"
        discipline `use_structure_tp` already established). `sweep_type`/
        `choch_detected` are legacy-pipeline-specific concepts with no
        clean Jade equivalent -- always `None`/`False` on this path,
        never meaningfully wrong (just not applicable). `fvg_zone`
        carries the Jade entry zone (`{"top", "bottom"}`) -- the same
        ROLE this field already plays (the zone the engine actually
        used), even though its shape differs slightly from the legacy
        zone dicts (no `type`/`index`).

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

        `use_structure_tp` (default `False`, opt-in -- see
        `entry_model.build_entry_model`'s docstring, and docs/ROADMAP.md
        "Core Rule MVP completion" item #4): when `True`,
        `find_previous_swing_high`/`find_previous_swing_low`/
        `calculate_premium_discount` are each computed once against
        `ltf_candles` (same series every other structural detector here
        already uses) and passed through to `build_entry_model`, which
        uses them to target real structure for `take_profit` instead of
        the fixed-`_RR` target. Default `False` preserves the exact prior
        behavior for every existing caller.

        `require_premium_discount_filter` (default `False`, opt-in -- see
        `entry_model.build_entry_model`'s docstring): when `True`,
        `calculate_premium_discount` is computed against `ltf_candles`
        (same computation `use_structure_tp` already triggers -- computed
        at most once per call even if BOTH parameters are `True`) and
        passed through to `build_entry_model`, which rejects a `long`
        entered from the premium half of the range or a `short` entered
        from the discount half. Default `False` preserves the exact prior
        behavior for every existing caller.

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

        if use_jade_engine:
            return self._generate_signal_via_jade_engine(symbol, ltf_candles, htf_candles)

        # require_session (opt-in, default None -- 2026-07-14 continuous
        # research mode, docs/CONTINUOUS_RESEARCH_LOG.md experiment 3):
        # reuses session_liquidity.py's ALREADY-DISCLOSED Asian/London
        # window constants (not a new indicator) as an ENTRY-TIMING gate --
        # rejects a signal outright if the current (most recent) LTF
        # candle's timestamp falls outside the named session, exactly the
        # same "missing/failing structure never produces a signal" pattern
        # every other detector in this pipeline already follows. Motivated
        # directly by docs/ROBUSTNESS_REPORT.md test 6, which found the
        # Asian session dominates both trade volume and quality for the
        # production candidate (PF 4.65 vs London's 2.41). Gracefully
        # skipped (no rejection) if the candle's timestamp isn't a real
        # `datetime` -- same degradation this package's other session-aware
        # code already uses (ENGINEERING_DECISIONS.md #27), since every
        # hand-built test fixture elsewhere in this package uses plain
        # string timestamps.
        if require_session is not None:
            window = _SESSION_WINDOWS.get(require_session)
            if window is None:
                raise ValueError(
                    f"require_session must be one of {list(_SESSION_WINDOWS)}, got {require_session!r}"
                )
            ts = cf(ltf_candles[-1], "timestamp")
            try:
                current_time = ts.time()
            except AttributeError:
                current_time = None
            if current_time is not None:
                start, end = window
                in_window = start <= current_time < end
                if not in_window:
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
        fvg_zones = _select_unmitigated_fvg_zones(ltf_candles, bias)
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

        previous_swing_high = None
        previous_swing_low = None
        premium_discount = None
        if use_structure_tp:
            previous_swing_high = find_previous_swing_high(ltf_candles)
            previous_swing_low = find_previous_swing_low(ltf_candles)
        if use_structure_tp or require_premium_discount_filter:
            premium_discount = calculate_premium_discount(ltf_candles)

        atr = average_true_range(ltf_candles) if atr_stop_multiplier is not None else None

        model = build_entry_model(
            bias,
            sweep,
            choch,
            fvg_zones,
            order_block,
            breaker_block,
            require_full_confluence=require_full_confluence,
            require_ob_fvg_confluence=require_ob_fvg_confluence,
            previous_swing_high=previous_swing_high,
            previous_swing_low=previous_swing_low,
            premium_discount=premium_discount,
            use_structure_tp=use_structure_tp,
            require_premium_discount_filter=require_premium_discount_filter,
            structure_tp_max_r=structure_tp_max_r,
            atr=atr,
            atr_stop_multiplier=atr_stop_multiplier,
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

    def _generate_signal_via_jade_engine(
        self, symbol: str, ltf_candles: list, htf_candles: list
    ) -> "TradeSignal | None":
        """The `use_jade_engine=True` path -- see `generate_signal`'s own
        docstring for the full field-mapping rationale
        (ENGINEERING_DECISIONS.md #34). Kept as a separate method (not
        inlined into `generate_signal`) so the legacy pipeline above it
        stays completely untouched and easy to read in isolation.

        Deliberately does NOT reuse `plan["exit_targets"]` as-is: those
        were computed by `build_trade_plan` against the entry ZONE'S
        MIDPOINT (decision #25/#28's convention, chosen for the
        different "is there room beyond this zone at all" question).
        This method's `entry_price` is the zone's TOP (long) / BOTTOM
        (short) edge instead -- matching `entry_model.build_entry_model`'s
        own convention (the more conservative, worse-case realistic fill
        assumption) -- which is CLOSER to the far edge of the zone than
        the midpoint is. A target that clears the midpoint does not
        necessarily also clear this closer, more conservative entry
        price, so exit targets are RECOMPUTED here
        (`find_exit_targets(..., entry_price=<the real one>)`) against
        the actual `entry_price` this signal uses -- reusing the
        midpoint-based list would risk a `take_profit` that sits on the
        WRONG side of `entry_price` (e.g. below it for a long), which
        very nearly shipped: caught during this integration's own
        testing (ENGINEERING_DECISIONS.md #34).
        """
        plan = build_trade_plan(ltf_candles, htf_candles)
        if plan is None:
            return None

        direction = plan["direction"]
        entry_zone = plan["entry_zone"]
        entry_price = entry_zone["top"] if direction == "long" else entry_zone["bottom"]
        stop_loss = plan["stop_loss"]

        exit_targets = find_exit_targets(ltf_candles, direction, entry_price)["targets"]
        if not exit_targets:
            return None
        take_profit = exit_targets[0]["level"]

        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return None
        rr = abs(take_profit - entry_price) / risk

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            timestamp=cf(ltf_candles[-1], "timestamp"),
            htf_bias=plan["htf_bias"],
            sweep_type=None,
            choch_detected=False,
            fvg_zone=entry_zone,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr=rr,
            status="pending",
            jade_plan=plan,
        )
