# ENGINEERING_DECISIONS — JadeCap Automated Trading Bot

Architecture-decision-record style log, organized by TOPIC (not
chronologically — see `CHANGELOG.md`/`HANDOFF.md` for the timeline).
Each entry: the decision, why it was made, what alternatives were
considered, and the trade-off accepted. Written so a new engineer never
has to ask "why is it built this way?"

---

## 1. Zone-mitigation filtering lives in `SignalEngine`, not inside the detectors

**Decision**: `is_zone_mitigated()` (`app/strategy/utils.py`) is applied
in `SignalEngine.generate_signal()`, AFTER calling
`detect_fair_value_gap()`/`detect_order_block()`, not inside those
functions themselves.

**Why**: `detect_breaker_block()` depends on `detect_order_block()`
returning the RAW, unfiltered order block so it can independently check
whether that same zone was later closed-through and retested (a breaker
pattern is specifically defined in terms of a mitigated OB reversing).
Filtering mitigation out at the detector level would silently break that
downstream consumer.

**Alternative considered**: add a `mitigated: bool` field to the
returned zone dict instead of filtering. Rejected — would require every
caller (including tests) to remember to check the flag, whereas
filtering at the orchestration layer means `build_entry_model()` (a pure
function) never has to know mitigation exists at all.

**Trade-off accepted**: `detect_fair_value_gap`/`detect_order_block`'s
own return values are honest about "what structure exists" but not
"what's tradeable right now" — a caller that imports them directly
(bypassing `SignalEngine`) gets unmitigated-aware raw zones. Acceptable
since nothing in the codebase currently does that except `detect_breaker_block`,
which needs exactly that raw behavior.

---

## 2. `ltf_bias` reuses `detect_htf_bias()` on the LTF candle series

**Decision**: `/dashboard/bias`'s `ltf_bias` field runs the SAME
structural-bias algorithm (`detect_htf_bias()`) against LTF candles
instead of HTF candles.

**Why**: `docs/strategy_spec.md`/`signal_engine.py` never define an "LTF
bias" concept — `detect_htf_bias()` is called ONLY on HTF candles in the
real strategy; LTF candles feed the sweep/CHoCH/FVG/order-block
detectors instead. The `ltf_bias` API field predates this design (an
early Milestone-1-era contract field) and was kept for API-contract
stability rather than removed.

**Alternative considered**: remove the field entirely (breaking the
frontend type contract), or hardcode it to always be `"neutral"`.
Rejected both — reusing the real, generic structural-bias algorithm on a
second real dataset produces a genuine (if differently-scoped) reading,
not fabricated data.

**Trade-off accepted**: this is a judgment call, not a spec-derived
decision — made without operator sign-off since it fell outside the
explicit approval-required categories (API credentials, live trading,
paid services, security, destructive ops). Flagged in `ROADMAP.md`/`PROJECT_STATUS.md`
as worth reconfirming if this field ever drives an actual trading
decision rather than just dashboard display.

---

## 3. `PLACEHOLDER_ACCOUNT_BALANCE` centralized in `settings`, not duplicated

**Decision**: moved from a private constant in `scripts/run_paper.py`
into `settings.PLACEHOLDER_ACCOUNT_BALANCE` (`app/config.py`).

**Why**: `/dashboard/risk-status` needed the exact same fixed
denominator `run_paper.py`'s `_pnl_to_percent()` uses to convert
realized PnL into daily/weekly loss-limit percentages. Two independent
copies of the same "no real account-balance source exists yet" constant
would silently drift the moment one was changed and the other wasn't.

**Trade-off accepted**: none significant — this is a pure DRY win, no
behavior change for existing callers.

---

## 4. Backtest daily/weekly loss-limit denominator is the run's STARTING balance, not the compounding one

**Decision**: `BacktestEngine.run()`'s daily/weekly PnL% (fed to
`risk_manager.evaluate()`) divides realized PnL by the `account_balance`
value passed into `run()` at the start — a fixed number — even though
position sizing within the same run uses the COMPOUNDING running
balance.

**Why**: mirrors `scripts/run_paper.py`'s `PLACEHOLDER_ACCOUNT_BALANCE`-based
`_pnl_to_percent()` (also fixed, not compounding), so backtest and paper
loss-limit percentages stay comparable to each other and to what an
operator would actually see triggering a real halt in paper/live.

**Alternative considered**: use the compounding balance (consistent with
position sizing in the same engine). Rejected — would make backtest
loss-limit percentages diverge from paper's real behavior, defeating the
point of backtesting as a predictor of paper/live outcomes.

**Trade-off accepted**: backtest's OWN internal consistency is slightly
uneven (sizing compounds, loss-limit-% does not) in exchange for
cross-engine (backtest vs. paper) consistency, which was judged more
important.

---

## 5. `CandleFetcher` uses two different OKX endpoints for two different jobs

**Decision**: `fetch_ohlcv()` (single page, used by paper trading's
"give me the latest N candles" need) hits `/market/candles`.
`fetch_ohlcv_history()` (deep pagination, used by backtesting) hits the
separate `/market/history-candles` endpoint.

**Why** (confirmed empirically against the real OKX API, not assumed
from documentation): `/market/candles` is hard-capped at ~1440 total
candles regardless of how many pages are fetched (repeated `after`-cursor
pagination against it returns an empty page after exactly 1440 candles,
every time, verified directly). `/market/history-candles` has the same
request/response shape and cursor semantics but pages back reliably far
deeper (verified 3000 candles / ~125 days with no early cutoff).

**Also fixed in the same pass**: `fetch_ohlcv`'s `since` parameter was
wired to OKX's `before` query param, which (confirmed empirically)
returns candles NEWER than the given timestamp — the opposite of
backward pagination. Now correctly maps to `after`.

**Trade-off accepted**: two code paths instead of one, but they serve
genuinely different needs (paper trading never needs more than the
latest window; backtesting needs deep history) and unifying them behind
one method would obscure the real difference in guarantees between the
two OKX endpoints.

---

## 6. Break-even stop management implemented independently in `BacktestEngine`, not by reusing `OrderManager.move_to_breakeven()`

**Decision**: `BacktestEngine._simulate_trade()`'s break-even logic
(effective-stop tracking, trigger detection) is implemented inline,
rather than calling the existing `OrderManager.move_to_breakeven(position)`.

**Why**: `move_to_breakeven()`'s contract is a one-shot call against a
DB-row-shaped `position` dict — designed to be invoked externally,
once, when a caller (paper/live loop) decides "move this now."
`_simulate_trade()`'s candle-scanning loop needs to check the trigger
condition on EVERY candle internally as part of a tight forward scan;
forcing that loop to construct/mutate position-dict-shaped objects on
every iteration just to call a function designed for a different calling
pattern would add complexity without benefit.

**Trade-off accepted**: `OrderManager.move_to_breakeven()` remained
unused for the rest of that round. **Update**: now consumed exactly as
anticipated — `scripts/run_paper.py::_maybe_move_to_breakeven()` calls
`OrderManager(PaperBroker()).move_to_breakeven(position)` to compute the
new stop, then persists it via the new
`TradeTracker.update_stop_loss()`. The one-shot-call contract fits
paper trading's DB-row positions naturally, exactly as predicted; only
the "should we call this right now" trigger/idempotency logic (1R
distance, already-at-breakeven check) is new, since `move_to_breakeven()`
itself has no concept of a trigger condition — it just moves the stop
unconditionally whenever called.

---

## 7. Signal persistence (`/dashboard/signals`) scoped to `run_paper.py` only, not `run_backtest.py`

**Decision**: `SignalTracker.record_signal()` is called from
`scripts/run_paper.py`'s `run_once()`, never from `scripts/run_backtest.py`.

**Why**: backtest signals are simulation output, already exported via
CSV/markdown reports per backtest run. The `signals` DB table (and
`Signal` model) has no `mode` column (unlike `Trade`, which does), so
persisting backtest signals into the same table as real paper signals
would make the live dashboard unable to distinguish "a real signal from
the currently-running paper bot" from "a signal from someone's backtest
three weeks ago." Solving that properly needs a `mode` column addition
first — a deliberate, deferred scope boundary, not an oversight.

---

## 8. Out-of-sample validation is period-splitting, not walk-forward parameter refitting

**Decision**: `scripts/run_backtest.py --periods N` splits fetched
history into `N` equal, non-overlapping chronological chunks and runs
each independently (fresh account balance, no shared state) — NOT a
rolling walk-forward window that refits parameters on each window before
testing the next.

**Why**: the strategy currently has no tunable/fitted parameters
(`_LOOKBACK`, `_IMPULSE_MULT`, `_STOP_BUFFER`, `_RR`, `BREAKEVEN_TRIGGER_R`
are all fixed constants, explicitly disclosed in-code as "reasonable
defaults, not tuned"). A walk-forward refitting loop would have nothing
to refit yet — building one now would be premature machinery for a
capability the strategy doesn't have. Period-splitting still achieves
the real goal (checking whether results are consistent across
genuinely disjoint historical windows rather than resting on one
continuous sample) without that unused complexity.

**Future note** (see `ROADMAP.md` item #6): the MOMENT any parameter
tuning/sweeping work begins, this tool's held-out periods become
load-bearing for avoiding overfitting — tune only against a subset of
periods, verify only against periods never inspected during tuning.
Skipping this discipline defeats the entire reason the tool exists.

**Follow-up (walk-forward validation built as Phase 1 gate #2)**: the
operator's scope-lock directive named "walk-forward validation" as an
explicit, required Phase 1 deliverable distinct from backtesting. Rather
than build a refitting loop with nothing to refit (which this decision
already rejected), `run_backtest.py::walk_forward_report()` was added on
TOP of the existing period-splitting: it takes the same chronological
period sequence and checks it against explicit PASS/FAIL criteria
(minimum profitable-period ratio, maximum consecutive losing periods, a
first-half-vs-second-half degradation check) instead of just printing an
aggregate sum. This satisfies the actual intent behind "walk-forward
validation" (does performance hold up moving forward through time,
un-hidden by averaging) without pretending there's parameter-refitting
happening where there isn't. First real result: BTCUSDT 2026 baseline
PASSED (6/6 profitable, 0 losing streak, second half outperformed the
first). The distinction this decision draws (no refitting mechanism
exists) remains accurate and unchanged — this follow-up adds a
validation GATE on top of period-splitting, not a refitting loop.

---

## 9. Conservative same-candle ordering for simultaneous stop/target/breakeven touches

**Decision**: when a single candle's `[low, high]` range would trigger
more than one exit-relevant condition in the same bar (original
stop-loss AND take-profit; or original stop-loss AND the break-even
trigger level), `BacktestEngine._simulate_trade()` always resolves in
favor of the WORSE outcome for the trader — stop-loss over take-profit,
and the original stop over an "optimistically triggered then saved by
breakeven" outcome.

**Why**: OHLC candle data cannot reveal the true intra-candle
sequencing of price action. Assuming the favorable order whenever
ambiguous would systematically bias backtest results optimistic in a way
that could never be verified or corrected later. This principle
predates the break-even feature (the SL-before-TP assumption was already
in place) and was extended to cover the new breakeven-trigger-vs-original-stop
case using the identical reasoning.

**Trade-off accepted**: real fills might occasionally be more favorable
than this pessimistic assumption produces — deliberately, since a
backtest that's too optimistic is more dangerous than one that's overly
cautious.

---

## 10. Every new strategy-behavior change ships as an opt-in flag, threaded end-to-end, before any default changes

**Decision**: break-even (`use_breakeven`) and Breaker Block
(`use_breaker_block`) both follow the identical pattern: a `False`-
default parameter on `SignalEngine.generate_signal()`/`BacktestEngine.run()`,
threaded through to a `scripts/run_backtest.py` CLI flag, so the exact
same `--symbol`/`--timeframe`/`--candles`/`--periods` invocation can be
re-run with only that one flag toggled for a clean A/B comparison.

**Why**: this is the only way to make "compare before vs. after" (an
explicit operator requirement) a literal, mechanical, repeatable
operation rather than an informal eyeball comparison across separate
runs that might differ in other ways. It also means a feature that
turns out NOT to help (see decision #11 below) costs nothing to keep in
the codebase — it's inert until explicitly requested, and remains
available for re-testing against future, larger, or differently-timed
samples without writing new code.

**Alternative considered**: implement directly as new default behavior,
then revert via `git` if a backtest comparison looked bad. Rejected —
requires re-running the *entire* validation after implementation to
decide "was this real," rather than being able to compare in one
invocation-pair; also leaves no reusable, permanent lever for re-testing
under different future conditions (a git-reverted feature is gone, an
opt-in flag is dormant and instantly available again).

**Trade-off accepted**: every new strategy behavior adds one more
boolean parameter threaded through several layers (`SignalEngine` →
`BacktestEngine` → CLI). Accepted as a small, mechanical cost against the
alternative of ad-hoc, harder-to-reproduce comparisons.

---

## 11. A "no measurable effect" A/B result is documented as a finding, not silently discarded

**Decision**: when Breaker Block's A/B backtest showed literally zero
difference in trade count/PnL/win-rate across all 6 tested periods, the
response was NOT to assume the feature doesn't work and move on
silently. Instead: (a) directly scanned every walk-forward step of a
real dataset to confirm the detector fires and CAN change output (it
does — 124/970 raw detections, 29 unmitigated, 2 confirmed signal-level
differences), then (b) determined precisely why those 2 differing
moments never affected the actual backtest (both fell inside an
already-open trade's window, per the one-trade-at-a-time concurrency
guard).

**Why**: "no effect measured" and "proven not to work" are different
claims, and conflating them would either (a) wrongly discard a feature
that might matter in a different sample, or (b) leave a future engineer
unable to tell whether "we tried this and it failed" or "we tried this
and got inconclusive results due to how the test sample happened to be
shaped." The diagnostic step turns an ambiguous null result into a
precise, falsifiable, reusable piece of evidence: "this feature is
functionally correct; it needs a sample with more idle time between
trades to get a fair test."

**Trade-off accepted**: the diagnostic scan (re-running detection/signal
generation at every step outside the normal backtest flow) is extra work
beyond what the operator's instructions strictly required ("document the
evidence and keep it optional" would have been satisfiable with just the
null aggregate result). Accepted because a coverage-audit/research
project's entire value proposition is evidence quality, not
throughput — an unexplained null result is much weaker evidence than an
explained one.

---

## 12. Partial-TP checked BEFORE take-profit within a candle, not after

**Decision**: in `BacktestEngine._simulate_trade()`, the per-candle check
order is: original stop-loss (worst case) → partial-TP trigger (if not
yet triggered) → take_profit → break-even trigger. Partial-TP
deliberately comes BEFORE take_profit, not after.

**Why**: `PARTIAL_TP_TRIGGER_R` (1R) is always closer to entry than
`take_profit` (`RR * 1R`, and `_RR = 2.0` in this codebase) for any
RR > 1. That means any real, monotonic price path that reaches
take_profit necessarily passed through the partial-TP trigger price
first. If the code checked take_profit before the partial trigger, a
single candle whose range happened to span both levels would close the
FULL size at take_profit and skip the partial leg entirely — silently
wrong, since in reality the partial trigger would have executed on the
way there. Checking partial-TP first ensures a same-candle jump straight
to take_profit still correctly banks the partial leg at its own, nearer
price before the remaining size continues to take_profit.

**Alternative considered**: treat a same-candle multi-level touch as
ambiguous and resolve conservatively in the "worse" direction, the same
policy already used for stop-loss-vs-take-profit ambiguity. Rejected
here specifically — unlike stop-vs-target (where either order is
physically plausible and unknowable from OHLC), partial-trigger-then-
target is not actually ambiguous: the price LEVELS themselves guarantee
the ordering (partial trigger is strictly between entry and target), so
assuming it is not a favorable-case guess, it's a certainty derivable
from the trade's own parameters.

**Trade-off accepted**: none — this ordering is not a probabilistic
assumption like the SL-vs-TP one, it's a deterministic consequence of
`PARTIAL_TP_TRIGGER_R < RR`. (If a future change ever made
`PARTIAL_TP_TRIGGER_R >= RR` for some configuration, this ordering
argument would no longer hold and would need to be revisited.)

---

## 13. HTF fetch size is derived from the LTF request's real time span, not copied from its candle count

**Decision**: `scripts/run_backtest.py` no longer requests the same
candle COUNT for the HTF fetch as the LTF fetch. `htf_candle_count_for_span()`
converts the LTF request into a real time span (via the new
`app.data.candle_fetcher.timeframe_to_timedelta()`) and divides by the
HTF bar's own duration to get the right HTF candle count for that same
span, with a 300-candle floor.

**Why**: discovered as a real bug, not a theoretical concern -- a
6-period/3000-candles-per-period regime-validation run (`--candles 3000
--periods 6`) requested 18000 candles for BOTH the `15m` LTF fetch
(correctly ~187 days) and the `4h` HTF fetch (~8.2 years, since a fixed
candle count means wildly different real time spans across timeframes).
The HTF fetch consequently paged through far more history than needed
and had to be killed after 10+ minutes with no output. A candle COUNT is
not a portable unit of "how much history do I need" across different
timeframes; a time SPAN is.

**Alternative considered**: cap the HTF request at some fixed maximum
(e.g. `min(total_requested, 2000)`) rather than computing the real
span. Rejected — an arbitrary cap either over-fetches for small LTF
requests (wasteful) or under-fetches for large ones (risks starving
`detect_htf_bias()` of real runway for genuinely long backtests), while
computing the actual required span gets the right answer in both
directions automatically.

**Trade-off accepted**: none significant — `timeframe_to_timedelta()`
only supports the same timeframe formats `to_okx_timeframe()` already
does (`m`/`h`/`d`/`w` suffixes), so no new format support was needed to
implement this.

---

## 14. Out-of-sample results are re-validated at larger scale before being trusted, not assumed to generalize

**Decision**: after the initial A/B tests for break-even/Breaker Block/
partial-TP (all on a single ~31-day/3-period sample), the SAME three
experiments were re-run on a 6-month/6-period sample before treating any
of the three conclusions as settled.

**Why**: this is not redundant busywork -- it changed one of the three
conclusions. Break-even and partial-TP reproduced almost exactly (+13.5%
-> +9.2%; -31.4% -> -32.6%), which is real evidence those effects are
robust, not sample-specific flukes. Breaker Block did NOT reproduce as
"neutral" -- on the larger sample it fired for real once and the effect
was negative. Had the project stopped at the first (smaller) sample and
called Breaker Block's result final, it would have carried a materially
wrong (too optimistic) belief about that feature forward. The entire
point of building out-of-sample tooling (see decision #8) is defeated if
its output is only ever checked once and then trusted indefinitely.

**Alternative considered**: treat the first sample as sufficient once
each experiment showed SOME result (positive/neutral/negative) and move
on to the next roadmap item. Rejected — a single sample, however
carefully split into non-overlapping periods, is still one dataset from
one continuous slice of history; "reproduces on an independent, larger,
more varied sample" is a categorically stronger evidentiary bar than
"produced a result once."

**Trade-off accepted**: real time and API calls spent re-running
experiments that had already produced results once. Accepted because
the Breaker Block revision alone justified the cost -- it changed a
real conclusion this project would otherwise be carrying forward
incorrectly.

---

## 15. "Reproduced" must specify what varied between samples -- a second time window is not a second asset

**Decision**: when re-validating an A/B finding, the writeup (CHANGELOG.md/
PROJECT_STATUS.md/ROADMAP.md) always states explicitly what changed
between the two samples being compared (same asset/different time window,
vs. different asset/same time window, vs. both) rather than saying only
"reproduced" or "did not reproduce."

**Why**: decision #14 re-ran break-even/Breaker Block/partial-TP on a
6-month BTCUSDT sample and called break-even "the most robust of the
three findings -- same direction on two independent datasets," since it
reproduced its small-sample result (+13.5% -> +9.2%). That phrasing was
technically true but misleading: both of those "independent datasets"
were BTCUSDT, just different time windows. When break-even was then
tested on a 6-month ETHUSDT sample (same methodology, different asset),
it came back slightly NEGATIVE (-1.9%, mixed per-period) -- the opposite
conclusion. Partial-TP and Breaker Block, by contrast, reproduced their
negative verdicts on ETHUSDT too (even more strongly), so the SAME
"reproduced across two independent samples" language that turned out to
be fragile for break-even turned out to be genuinely robust for the
other two. The lesson is not "re-validation failed" -- it's that
asset-generalization and time-generalization are different claims with
different strength, and collapsing them into one word ("reproduced")
let an overconfident claim about break-even stand for one release cycle
longer than it should have.

**Alternative considered**: treat any second confirming sample,
regardless of what varied, as sufficient to call a finding "robust."
Rejected — this is exactly the failure mode that just occurred: two time
windows on a correlated single asset gave false confidence that would
not have survived a single additional asset test.

**Trade-off accepted**: writeups are longer and more hedged than a flat
"positive"/"negative" verdict would be. Accepted because the entire
point of this project's evidence-over-assumption philosophy (see
`ROADMAP.md`'s guiding principle) is defeated if "reproduced" is used
loosely enough to paper over exactly the kind of gap this decision
describes. `ENABLE_BREAKEVEN` shipping off-by-default (decision area:
see paper-trading wiring in CHANGELOG.md) is a direct, practical
consequence of taking this distinction seriously — an operator reading
only the headline verdict, not the fine print, still gets the safe
default.

**Follow-up (SOLUSDT then XRPUSDT rounds)**: the same lesson recurred one
level up. After a 3rd asset (SOLUSDT), break-even looked like it had a
real negative LEAN (2 of 3 assets negative) rather than being purely
asset-dependent noise — a 4th asset (XRPUSDT, +5.4%) broke that lean
back to a genuine 2-of-4/2-of-4 split. A small COUNT OF ASSETS can
manufacture the appearance of a trend exactly the way a small count of
PERIODS can (the original concern this decision was written for) —
"how many assets have been tested" needs the same explicit skepticism
as "how many periods have been tested." Breaker Block showed the same
pattern in miniature: unanimously negative across 3 assets, then a 4th
(XRPUSDT, +1.5%) broke the unanimity. Partial TP is the calibration
case that shows this ISN'T just "more data always overturns findings" —
it has now stayed negative on all 4 assets and 24 of 24 periods with no
sign of reverting, so a real, robust effect and an apparent-but-fragile
trend look different once enough independent samples exist; the risk is
mistaking the latter for the former too early.

**Follow-up (time-anchored `--end-date` testing)**: a third dimension
was added -- `CandleFetcher.fetch_ohlcv_history()` gained `end_time_ms`,
letting a fetch be anchored to a specific past date instead of always
"now". The very first cross-year test (BTCUSDT, 2025-07-10 vs.
2026-07-10) produced the single clearest data point yet: break-even
flipped sign on the SAME asset (+9.2% in 2026, -1.9% in 2025). Combined
with the cross-asset coin flip above, break-even has now shown no
reliable direction along either axis that's been tested (asset, or
time on the one asset checked both ways). Partial TP, again, held:
-32.6% (2026) vs. -32.1% (2025), nearly identical. The practical lesson
compounds: "how many time windows have been tested" needs the same
skepticism as asset count and period count -- and, notably, ONE
time-anchored test on ONE asset moved the break-even conclusion further
than THREE additional assets did, suggesting time/regime may be a
bigger driver of these effects than asset choice. This directly
reprioritized `ROADMAP.md` toward more `--end-date` testing over more
assets.
