# Performance Round 2 (Milestone 22) — FVG Mitigation-Scan Quadratic Term Eliminated

2026-07-17. Companion to `docs/EXPERIMENTAL_STRATEGY_EVALUATION.md`-style
evidence docs, but for the backtester's own runtime rather than a
strategy's PnL. Closes the item Milestone 19 (`ENGINEERING_DECISIONS.md`
#59) left deferred: "Fix B," the incremental zone-mitigation caching for
`is_zone_mitigated()` that round 1's profiling identified as the #2 cost
center (22.2% of runtime) after `detect_order_block()` itself. Full
rationale: `ENGINEERING_DECISIONS.md` #61(a). This document is the
narrative: what round 1 assumed, what turned out to be true instead, the
fix, and how it was verified.

## 1. Where round 1 left off

Milestone 19's profiling (BTCUSDT real data, 500/1000/2000/3000-candle
runs) measured `is_zone_mitigated()` at 22.2% of total backtest runtime,
called roughly 350 times per walk-forward step -- one call per FVG zone
`detect_fair_value_gap()` returned, because `signal_engine.py`'s old code
eagerly filtered EVERY zone (both bullish and bearish) for mitigation
before handing the resulting list to `entry_model.build_entry_model`.

Round 1's own writeup deferred fixing this, stating the reason plainly:
"Fix B ... needs cross-step state inside a currently-stateless
`SignalEngine`" -- a materially higher-risk change than the pure,
single-function algorithmic rewrite `detect_order_block()` had just
received. This was recorded as a considered, honest engineering judgment,
not a placeholder -- and it was **wrong**, though not carelessly so: it
was a guess about the shape of the fix, made without inspecting what the
actual downstream consumer does with the eagerly-computed list. Round 1's
own scope was `order_block.py`; nobody had yet read `build_entry_model`'s
FVG-consumption logic closely enough to notice what round 2 found.

## 2. The consumer-semantics discovery

Reading `entry_model.build_entry_model` closely (rather than assuming its
shape from `order_block.py`'s analogous case) surfaces one fact that
changes everything: it only ever extracts a SINGLE zone from the FVG list
it's handed --

```python
matching_fvgs = [z for z in fvg if z["type"] == wanted_type]
fvg_zone = max(matching_fvgs, key=lambda z: z["index"])
```

-- the highest-index zone whose `type` matches `wanted_type`. Every other
zone in the eagerly-filtered list `signal_engine.py` built (potentially
hundreds of them, each individually run through `is_zone_mitigated`) is
discarded the instant this line executes.

The second half of the discovery: `wanted_type` is **provably identical
to `bias`**, the value `signal_engine.py` already has in hand before it
ever calls into the FVG selection logic. `build_entry_model` returns
`None` before `wanted_type` is derived at all unless `bias in
("bullish", "bearish")`; for those two surviving values, `wanted_type =
"bullish" if direction == "long" else "bearish"`, and `direction ==
"long"` if and only if `bias == "bullish"` -- so `wanted_type` collapses
to exactly `bias` on every path that reaches it. The type filter
`build_entry_model` applies downstream is therefore already computable
by the caller, before `build_entry_model` is ever invoked.

Put together: the old code was solving a strictly harder problem than the
one that existed. It computed "every unmitigated FVG zone of both
types," when the only fact ever consumed was "the single newest
unmitigated zone of the one type `bias` already determines."

## 3. The transform

Two new functions, no state added anywhere:

- **`app.strategy.signal_engine._select_unmitigated_fvg_zones(ltf_candles,
  bias)`** -- short-circuits neutral bias to `[]` immediately (provably
  safe: `build_entry_model` returns `None` on that path before ever
  touching its `fvg` parameter, so whatever zones would otherwise have
  been found are unobservable). For `"bullish"`/`"bearish"`, delegates to
  `fvg.find_latest_unmitigated_fvg_zone(ltf_candles, bias)` and wraps its
  result in a single-or-empty list, preserving `build_entry_model`'s
  existing list-shaped `fvg` parameter contract unchanged (`entry_model.py`
  itself is not touched by this optimization at all).
- **`app.strategy.fvg.find_latest_unmitigated_fvg_zone(candles,
  wanted_type)`** -- a single reverse scan (newest candle first) that
  fuses gap detection, type filtering, and mitigation checking, with an
  early exit at the first match.

**Why the reverse scan is provably the same answer as the old
eager-forward-scan-then-filter-then-argmax pipeline, not just a faster
one** -- this is the exact M19 argument, re-derived for a different
function: `detect_fair_value_gap`'s loop body at a given index `i` reads
only `candles[i-1]`, `candles[i]`, `candles[i+1]` -- nothing carries
across iterations, no running total, no "last seen" state. The SET of
indices that qualify as a gap, and each one's computed `type`/`top`/
`bottom`, is therefore completely independent of which direction `i` is
visited in. Visiting `i` from `len(candles) - 2` down to `1` finds the
exact same zones the forward scan would, merely in reverse discovery
order -- so the FIRST one found (highest `index`) that also matches
`wanted_type` and passes `is_zone_mitigated` is, by construction, the
same zone `max(matching_fvgs, key=lambda z: z["index"])` would have
selected from the full eager-detect-then-filter result.

`detect_fair_value_gap()` itself is **completely untouched**. Its other
two consumers -- `entry_point_engine.py` and `htf_ltf_confluence.py` --
need the FULL ordered zone list for their own different consumption
patterns (a ranked-candidate model and a confluence check, respectively,
neither of which collapses to a single argmax the way
`build_entry_model` does). Every call site in the codebase was grepped
to confirm this before the change, not assumed.

## 4. Why this corrects, not contradicts, the round-1 deferral

Decision #59's deferral was an honest, reasonable inference at the time
it was made -- round 1's scope never required reading `build_entry_model`'s
FVG-consumption code, because `order_block.py`'s own fix didn't touch it.
Round 2's actual work was a SEMANTIC analysis of what the caller does
with an eagerly-computed result, not a caching-infrastructure build --
the same category of work that made round 1's own reverse-scan possible
for `detect_order_block` (verifying every consumer's needs before
touching the detector), applied one function deeper into the call graph
this time. The general lesson generalizes cleanly: **before assuming a
hot path needs new state or a fundamentally different algorithm, verify
exactly what the caller extracts from the eagerly-computed result** --
the answer is sometimes "far less than the eager computation produces,"
and when it is, a reverse-scan-with-early-exit can eliminate the
eagerness itself rather than requiring anything stateful to cache across
steps.

## 5. Full verification battery (the M19 bar, met the same way)

1. **Property test, `fvg.find_latest_unmitigated_fvg_zone`**
   (`test_strategy_fvg.py`): checked against a verbatim reference
   implementation of `detect_fair_value_gap()` + eager
   `is_zone_mitigated()` filtering + argmax selection, over 5,200 seeded
   synthetic candle series including adversarial modes. 0 mismatches. Now
   a permanent regression test.
2. **Property test, `signal_engine._select_unmitigated_fvg_zones`**
   (`test_strategy_signal_engine.py`): checked against a verbatim
   reference copy of the OLD inline `signal_engine.py` logic (eager
   detect-then-filter-both-types), over a second independent 5,200-case
   seeded series set. 0 mismatches. Now a permanent regression test.
3. **Golden run on anchored real data**: BTCUSDT, the same 4 flag
   combinations Milestone 19 used (default / `use_breaker_block` /
   `use_structure_tp` / `use_jade_engine`) -- old-vs-new trade lists
   compared deep-equal at exact float precision. 4/4.
4. **Namespace-binding check**: Milestone 19's golden run was caught out
   by three separate modules (`signal_engine`, `entry_point_engine`,
   `htf_ltf_confluence`) each binding `detect_order_block` into their own
   namespace at import time, requiring all three to be patched for a
   valid old-vs-new comparison. This round checked for the same trap
   rather than assuming it wouldn't recur: grepping every importer of
   `_select_unmitigated_fvg_zones` and `find_latest_unmitigated_fvg_zone`
   shows only `signal_engine.py` binds either -- a strictly simpler
   namespace picture than Milestone 19's, confirmed rather than assumed.

## 6. Before/after numbers

| Metric | Before | After | Change |
|---|---|---|---|
| Wall clock, n=1000 | 1.693s | 0.933s | 1.81x |
| Wall clock, n=2000 | 7.484s | 3.172s | 2.36x |
| `is_zone_mitigated` calls | 965,864 | 11,141 | ~87x fewer |
| FVG-mitigation chain, % of runtime | 22.2% | 1.68% | -20.5 pts |
| `detect_fair_value_gap` in hot path | yes (full forward scan every step) | no (never called from this path) | eliminated |

Combined with Milestone 19's 2.28-2.39x speedup on `detect_order_block`,
this project's standard evidence-round scale (`--candles 3000 --periods
6`) is now roughly **5x faster than the pre-Milestone-19 baseline**
(round 1 alone took evidence rounds from ~40 minutes to ~17; round 2
compounds a further reduction on top of that).

## 7. Remaining hotspots (out of scope this round, recorded for the next)

With both `detect_order_block` (Milestone 19) and the FVG-mitigation
chain (this round) no longer dominant, profiling attention shifts to two
new leading costs:

- **`find_swing_highs`/`find_swing_lows`** (`market_structure.py`) --
  consumed by multiple detectors (bias, premium/discount, liquidity
  sweep, regime detection) with no single obviously-dominant caller
  identified yet; would need its own profiling pass before any fix is
  attempted, not assumed from this round's numbers alone.
- **`cf()` OHLCV accessor** (`app.strategy.utils`) -- already flagged in
  Milestone 19 as a large constant factor in self-time (not the driver of
  either quadratic term fixed so far), now proportionally larger simply
  because the two prior dominant costs shrank around it.

Per this project's own "revisit only if the current speedup proves
insufficient for a future evidence round's actual needs" discipline
(the same condition Milestone 19 attached to Fix B), neither is scheduled
as a committed next round -- both are recorded here as candidates, to be
picked up only if a future evidence round's wall-clock cost actually
justifies the work.

## 8. Verification methodology as the reusable artifact

As with Milestone 19, the profiling script itself is not the durable
output -- the SEQUENCE is: profile against real, anchored data at
multiple candle counts to measure the actual cost distribution (not
assume it from reading code); read the actual downstream consumer's
semantics before assuming a fix requires new state or a fundamentally
different algorithm; when a reverse-scan-with-early-exit is possible,
verify it is provably equivalent (no cross-iteration state in the
original detector) rather than merely empirically similar; verify
bit-identical output two ways (a property test against a verbatim
reference implementation, plus a real-data golden run across every
meaningfully different flag combination); check for the specific
multi-namespace-binding trap Milestone 19 surfaced rather than assuming
it won't recur. Milestone 22 followed this sequence exactly and it
generalized cleanly one function deeper into the call graph.
