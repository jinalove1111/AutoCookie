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

## 2. Liquidity Sweep Detection
- Purpose: detect sweeps of prior highs/lows (liquidity grabs).
- Inputs (conceptual): candle series, known swing highs/lows, HTF bias.
- Outputs (conceptual): whether a liquidity sweep occurred, at which level,
  and in which direction.

## 3. CHOCH/MSS Detection
- Purpose: detect Change of Character / Market Structure Shift following a
  liquidity sweep.
- Inputs (conceptual): candle series, swept liquidity level, HTF bias.
- Outputs (conceptual): whether a CHOCH/MSS occurred and the resulting
  short-term structural bias.

## 4. FVG Detection
- Purpose: detect Fair Value Gaps left behind by the CHOCH/MSS move.
- Inputs (conceptual): candle series, CHOCH/MSS move.
- Outputs (conceptual): zero or more FVG zones (price range + candle
  indices).

## 5. Order Block / Breaker Block Detection
- Purpose: detect the Order Block or Breaker Block associated with the
  CHOCH/MSS move.
- Inputs (conceptual): candle series, CHOCH/MSS move, FVG zones.
- Outputs (conceptual): zero or more OB/Breaker zones (price range + type).

## 6. Entry Model
- Purpose: define the precise entry condition once bias, liquidity sweep,
  CHOCH/MSS, FVG, and OB/Breaker Block have confluence.
- Inputs (conceptual): all detection outputs above, current candle series.
- Outputs (conceptual): an entry trigger condition (price level, entry type)
  or `None` if confluence is not met.

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
