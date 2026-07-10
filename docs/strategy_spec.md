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

## Milestone Note

No detection logic (bias/liquidity/CHOCH/FVG/OB/entry/signal) is implemented
as of Milestone 1. This spec exists purely as the contract that Milestone 2
implementation work will be built and tested against.
