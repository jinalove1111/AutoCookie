# Strategy Engine — Spec / Contract

Status: **SPEC ONLY — NO IMPLEMENTATION EXISTS YET.** Detection logic is
scheduled for Milestone 2+ (see `next_milestone_plan.md`). This document
defines the intended contract (conceptual inputs/outputs) for each detection
module so that Milestone 2 implementation has a fixed target.

The Strategy Engine never places orders directly. It only ever produces a
`TradeSignal` (or `None`), which is passed to the Risk Engine for validation.

## 1. HTF Bias Detection
- Purpose: determine the higher-timeframe directional bias.
- Inputs (conceptual): candle series for the HTF timeframe (`HTF_TIMEFRAME`
  config, e.g. `4h`).
- Outputs (conceptual): a bias value (e.g. bullish / bearish / neutral) plus
  supporting context (last structural high/low).
- **Real HTF/LTF separation (implemented):** `SignalEngine.generate_signal`
  takes two genuinely distinct candle series — `ltf_candles`
  (`DEFAULT_TIMEFRAME`, e.g. `5m`) and `htf_candles` (`HTF_TIMEFRAME`, e.g.
  `4h`). `detect_htf_bias()` is called on `htf_candles` only; every other
  detector (liquidity sweep, CHOCH/MSS, FVG, order block) runs on
  `ltf_candles`. The two series are never the same list, and one must never
  be substituted for the other — reusing `ltf_candles` as a stand-in for
  `htf_candles` (or vice versa) defeats the entire purpose of this
  separation and is treated as a bug, not a fallback. Callers (e.g.
  `scripts/run_paper.py`) fetch both series independently via
  `CandleFetcher`; an empty/failed HTF fetch is treated as a hard failure
  identically to an empty/failed LTF fetch, never silently defaulted to the
  LTF series.

## 2. Liquidity Sweep Detection
- Purpose: detect sweeps of prior highs/lows (liquidity grabs).
- Inputs (conceptual): candle series, known swing highs/lows, HTF bias.
- Outputs (conceptual): whether a liquidity sweep occurred, at which level,
  and in which direction.
- **Direction-matching confluence rule (implemented, in
  `entry_model.build_entry_model`):** a sweep only counts as valid
  confluence if its type agrees with the bias-derived trade direction. A
  `sell_side` sweep (price sweeps below a prior swing low, grabbing
  resting sell-side liquidity) is the setup that precedes a bullish
  reversal, so it is only valid confluence for a `long`/bullish-bias entry.
  A `buy_side` sweep (grabs liquidity above a prior high) is only valid
  confluence for a `short`/bearish-bias entry. A sweep whose type conflicts
  with the bias-derived direction is treated as if absent — not an error,
  it simply doesn't count toward confluence. (Rationale: without this
  check, the engine could enter a trade directly against the liquidity
  grab it just detected — e.g. going long right after detecting a
  buy-side sweep, which is the setup for a bearish move.)
- **Equal High / Equal Low detection (implemented, ROADMAP "Core Rule MVP
  completion" item #5):** `app.strategy.liquidity.detect_equal_highs`/
  `detect_equal_lows` report resting liquidity pools — ADJACENT confirmed
  swing highs (or lows) sitting within a `tolerance` (fractional, default
  0.1%) of each other, standard ICT/SMC "equal highs/lows" concept: price
  failing to make a clean new high (or low) twice near the same level
  leaves a pool of resting liquidity just beyond both, a common sweep
  target. Only adjacent pairs in the swing-point sequence are compared
  (not every possible pair), matching how equal highs/lows are read in
  practice. Returns a list of `{"type": "equal_highs"|"equal_lows",
  "level", "first_index", "second_index"}` zones — `level` is the
  higher (for highs) or lower (for lows) of the two matched prices, kept
  as a real printed price rather than an average. Status: detection
  implemented and unit-tested (`tests/test_strategy_liquidity.py`). NOT
  YET wired into `SignalEngine`/`build_entry_model` — same detection-only
  status Premium/Discount (section 8) shipped with.

## 3. CHOCH/MSS Detection
- Purpose: detect Change of Character / Market Structure Shift following a
  liquidity sweep.
- Inputs (conceptual): candle series, swept liquidity level, HTF bias.
- Outputs (conceptual): whether a CHOCH/MSS occurred and the resulting
  short-term structural bias.
- **Direction-matching confluence rule (implemented):** symmetrically to
  the sweep rule above, `bullish_choch` is only valid confluence for a
  `long` entry and `bearish_choch` only for a `short` entry. A
  direction-mismatched CHoCH is treated as absent for confluence purposes.
- **CHoCH-must-follow-swept-index rule (implemented):**
  `detect_choch_mss(candles, n=2, swept_index=None)` accepts an optional
  `swept_index`. When provided (by `SignalEngine`, from the preceding
  `detect_liquidity_sweep()` call's `"swept_index"`), only swing
  highs/lows at candle index `>= swept_index` are eligible to be the
  broken level — the returned CHOCH must reflect structure that formed at
  or after the actual sweep, not an arbitrary earlier structural shift
  that happens to be the most recent one on record. When `swept_index` is
  `None` (e.g. standalone calls, as the unit tests do), behavior is
  unchanged from before this parameter existed — all swing points remain
  eligible. `SignalEngine` always calls `detect_liquidity_sweep(ltf_candles)`
  first and threads its `swept_index` (or `None` if no sweep) into
  `detect_choch_mss`.
- **Previous swing high / previous swing low (implemented, ROADMAP "Core
  Rule MVP completion" item #2):** `app.strategy.market_structure.
  find_previous_swing_high`/`find_previous_swing_low` report the single
  MOST RECENTLY confirmed swing high/low (same `find_swing_highs`/
  `find_swing_lows` this section's swing-point helpers already use),
  independent of whether a swing point of the other kind has formed yet.
  Returns `{"price", "index"}` or `None`. Exposed as its own detector
  because structure-based take-profit (section 6 below) needs just the
  high (or low) side as a resting-liquidity TP target, not the full
  premium/discount range. Status: implemented and unit-tested
  (`tests/test_strategy_market_structure.py`).

## 4. FVG Detection
- Purpose: detect Fair Value Gaps left behind by the CHOCH/MSS move.
- Inputs (conceptual): candle series, CHOCH/MSS move.
- Outputs (conceptual): zero or more FVG zones (price range + candle
  indices).
- **Zone mitigation filter (implemented, in `SignalEngine.generate_signal`,
  not inside `detect_fair_value_gap` itself):** `detect_fair_value_gap`
  reports a zone for as long as it remains anywhere in the given candle
  window, with no awareness of whether price has already retraded back
  into it. Without a freshness check, the same still-visible zone kept
  re-qualifying as "the most recent zone" on consecutive walk-forward
  steps even after a trade off it had already failed and price had moved
  back through it -- confirmed empirically in a real deep backtest (see
  CHANGELOG.md/HANDOFF.md): a large fraction of trades in one sample were
  exact duplicate re-entries of a just-failed setup. `SignalEngine` now
  excludes any FVG already "mitigated" -- overlapped by a candle strictly
  between the zone's formation and the current (most recent) candle,
  which is excluded from the check since the current candle touching a
  zone as part of triggering a signal (e.g. a sweep wick that taps
  straight into a nearby FVG in the same candle) is the setup itself, not
  a disqualifying prior retest. See `app.strategy.utils.is_zone_mitigated`.
  `detect_fair_value_gap` itself stays unchanged/mitigation-unaware.

## 5. Order Block / Breaker Block Detection
- Purpose: detect the Order Block or Breaker Block associated with the
  CHOCH/MSS move.
- Inputs (conceptual): candle series, CHOCH/MSS move, FVG zones.
- Outputs (conceptual): zero or more OB/Breaker zones (price range + type).
- **Zone mitigation filter (implemented, same rationale/mechanism as FVG
  above):** `SignalEngine` excludes an order block already mitigated
  since its CONFIRMING IMPULSE candle (not the base/zone candle -- the
  impulse candle's own range routinely overlaps the base zone it
  originated from, which would make every fresh order block look
  immediately "mitigated" by its own confirming move; `detect_order_block`
  returns `impulse_index` specifically so this distinction can be made).
  `detect_order_block`/`detect_breaker_block` themselves stay unchanged/
  mitigation-unaware -- `detect_breaker_block` specifically depends on
  `detect_order_block` returning the raw, un-filtered zone so it can do
  its own closed-through/retest analysis on top of it.

## 6. Entry Model
- Purpose: define the precise entry condition once bias, liquidity sweep,
  CHOCH/MSS, FVG, and OB/Breaker Block have confluence.
- Inputs (conceptual): all detection outputs above, current candle series.
- Outputs (conceptual): an entry trigger condition (price level, entry type)
  or `None` if confluence is not met.
- **Confluence strength — resolved, spec clarified against the
  implementation (was ambiguous, now settled with A/B evidence; see
  `docs/strategy_coverage_audit.md` row #9 and `ENGINEERING_DECISIONS.md`
  for the full history):** the prose above ("bias, liquidity sweep,
  CHOCH/MSS, FVG, and OB/Breaker Block have confluence") previously read
  as requiring ALL of sweep AND CHOCH. The actual, correct rule —
  confirmed by A/B backtesting `require_full_confluence=True` (require
  BOTH) against the existing default (require EITHER) across 4 assets,
  6-month/6-period each — is: bias must not be neutral, AND **at least
  one** of liquidity sweep / CHOCH must be present and direction-matching
  (not both), AND at least one FVG, order block, or breaker block must
  agree with the bias direction. Requiring both sweep AND CHOCH cuts
  trade frequency by ~76% (457 -> 110 trades across the 4-asset sample)
  while producing an average per-trade PnL within 4% of the looser rule
  (statistically indistinguishable given the resulting small per-period
  sample sizes, some down to 0-2 trades) — i.e. it does not produce
  meaningfully HIGHER-QUALITY trades, it just produces far FEWER of
  essentially the same quality, cutting total realized profit by ~75%
  in the process. `build_entry_model`'s default behavior (require
  either) is therefore the correct, spec-conforming rule; the stricter
  mode remains available as an opt-in (`require_full_confluence=True` /
  `run_backtest.py --strict-confluence`) for further research but is not
  recommended.
- **OB + FVG confluence — opt-in, implemented (ROADMAP "Core Rule MVP
  completion" item #3):** the "FVG/OB" phrasing above (a slash, not
  "and") has always been implemented as alternatives — either a matching
  order block/breaker OR a matching FVG is enough, whichever has the
  more recent candle index wins zone selection. `require_ob_fvg_
  confluence=True` (opt-in, default `False`; `run_backtest.py
  --ob-fvg-confluence`) changes this to "both agree": a matching order
  block (or breaker block) AND a matching FVG must BOTH be present, or
  no entry is produced. The zone actually used for entry is still
  whichever of the two has the more recent index — this parameter only
  gates whether both must be present, same treatment as
  `require_full_confluence` above narrowing sweep/CHOCH from "either" to
  "both". Ships opt-in and default `False`, same discipline as every
  other experimental flag (`use_breaker_block`, `require_full_
  confluence`) — not yet A/B backtested, so not recommended as a default
  pending real evidence.
- **Structure-based take-profit — opt-in, implemented (ROADMAP "Core
  Rule MVP completion" item #4):** `use_structure_tp=True` (opt-in,
  default `False`; `run_backtest.py --structure-tp`) replaces the
  fixed-RR `take_profit` target with a real structure target: a `long`
  targets the previous swing high first (section 3's `find_previous_
  swing_high`), extending further to the premium/discount equilibrium
  (section 8's `calculate_premium_discount`) when that reaches farther;
  `short` mirrors this to the downside. Only candidates strictly beyond
  `entry_price` in the trade's favor are valid forward targets; if
  neither candidate is valid (missing, or already behind price), this
  falls back to the exact fixed-RR target rather than rejecting an
  otherwise-valid entry. Whenever a structure target IS used, `rr` is
  recomputed as the trade's REAL reward:risk instead of the fixed `_RR`
  constant, since the Risk Engine's `MIN_RR` gate (`risk_manager.py`)
  reads that exact field — reporting the fixed constant would
  misrepresent the trade. Ships opt-in and default `False`, not yet A/B
  backtested.

## 7. Signal Engine
- Purpose: aggregate all detection modules into a final trade signal.
- Inputs (conceptual): candle series, HTF timeframe config, all detection
  module outputs.
- Outputs (conceptual): a `TradeSignal` (direction, entry, stop loss, take
  profit target(s), reasoning/context for the journal) **or** `None` if no
  valid setup exists.
- Constraint: the Signal Engine (and the Strategy Engine as a whole) never
  places orders directly. Its only output is a `TradeSignal` object passed
  downstream to the Risk Engine.

## 8. Premium / Discount Zones

- Purpose: classify where the latest price sits within the current swing
  range, as an entry-quality signal and (per ROADMAP) a candidate
  take-profit extension target.
- Implemented in `app.strategy.premium_discount.calculate_premium_discount`.
- Inputs (conceptual): candle series, swing-high/swing-low detection
  (reuses `find_swing_highs`/`find_swing_lows` from
  `app.strategy.market_structure`, the same helpers `bias.py` uses).
- Definition: the "current swing range" is bounded by the MOST RECENT
  swing high and MOST RECENT swing low in the series (independently —
  they are not required to alternate strictly). Its midpoint is the
  **equilibrium** (`(top + bottom) / 2`). The upper half of the range
  (above equilibrium) is **premium**; the lower half (below equilibrium)
  is **discount**; exactly at the midpoint is **equilibrium**.
- Standard ICT/SMC rationale: discount is the "cheap" half of the range
  and favors long entries; premium is the "expensive" half and favors
  short entries — entering from the wrong half of the range means buying
  into supply or selling into demand that the range itself already
  contains.
- Degenerate-range guard: if the most recent swing high's value is at or
  below the most recent swing low's value (`top <= bottom` — e.g. the
  most recent swing high has already been broken below the most recent
  swing low), there is no coherent current range to classify against, so
  the function returns `None` rather than a misleading zone. Also returns
  `None` if fewer than one swing high or one swing low exists yet.
- Outputs (conceptual): `{top, bottom, equilibrium, zone, range_high_index,
  range_low_index}` or `None`.
- Status: detection implemented and unit-tested
  (`tests/test_strategy_premium_discount.py`). Wired into `build_entry_
  model` as an opt-in take-profit extension target (section 6's
  `use_structure_tp`, ROADMAP item #4) — still NOT wired as an
  entry-quality FILTER (i.e. rejecting a signal for entering from the
  "wrong" half of the range), which remains unimplemented and would be a
  separate, currently unplanned addition.

## Milestone Note

No detection logic (bias/liquidity/CHOCH/FVG/OB/entry/signal) is implemented
as of Milestone 1. This spec exists purely as the contract that Milestone 2
implementation work will be built and tested against.
