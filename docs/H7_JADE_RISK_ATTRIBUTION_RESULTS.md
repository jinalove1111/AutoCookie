# H7 — RiskManager/Pipeline-Gating Attribution for Jade — Milestone 31

Evaluation deliverable (2026-07-19). This closes out `docs/HYPOTHESES_ROUND_2.md`
section 3 (H7): attributing the gap H6 (Milestone 30) disclosed but
explicitly did not measure — 8,312 step-level `signal_would_generate`
events versus decision #36's 6 recorded Jade trades. New thin wrapper
script `scripts/research_h7_jade_risk_attribution.py` (+
`backend/tests/test_research_h7_jade_risk_attribution.py`, 7 tests)
reuses `run_backtest.py`'s own already-existing `run_backtest(...,
use_jade_engine=True)` and `aggregate_risk_rejections()` verbatim — zero
new production code, zero new `BacktestEngine` parameter. Full suite:
780/780 passed (773 prior + 7 new), 0 failures. Every number below is
transcribed from `scripts/reports/research_h7_jade_risk_attribution.json`.

## 1. Purpose and methodology

**The gap this closes**: H6 found 8,312 steps across 3 anchors where
Jade's entry-model pipeline would generate a `TradeSignal`, but decision
#36's real backtest produced only 6 actual trades on one anchor. H6
explicitly disclosed three un-measured reasons for the gap and named
them as the next hypothesis's job, not its own: open-trade-state
tracking, Jade's own zone-persistence (repeated retest not invalidating
a setup), and `RiskManager.evaluate()` gating.

**Why this needed no new production code**: `BacktestResult.risk_rejections`
(Milestone 23, decision #61(b)) is generic, engine-agnostic
instrumentation — it observes whatever `RiskManager.evaluate()` decides
on whatever signal `SignalEngine.generate_signal()` produces, regardless
of `use_jade_engine`. Decision #36's original A/B test (2026-07-12)
simply predates this instrumentation (shipped 2026-07-17) by 5 days —
this round is the first time anyone has looked at Jade's own
risk-rejection breakdown, not a re-run of a decided comparison.

**Anchors**: BTCUSDT 15m, `--candles 3000 --periods 6`, `--end-date
2026-07-10 / 2025-07-10 / 2024-07-10` — this project's standard 3-anchor
set, `use_jade_engine=True`, matching decision #36's original scope
extended for cross-year confirmation, the same choice H6 made.

**Disclosed limitation on this round's own "reproduce decision #36
first" intent**: H7's own pre-registered text said it would confirm
reproducing decision #36's 6-trade result before trusting new numbers.
That check as literally described was not actually possible — decision
#36 used no explicit `--end-date` (fetching candles ending at "now" on
2026-07-12), not this document's `2026-07-10` anchor. The two windows
differ by roughly 2 days out of an ~18,000-candle (~187-day) span. This
round's 2026 anchor produced 22 trades, not 6 — a real, disclosed
discrepancy from decision #36's original number, most plausibly
explained by the anchor-date shift interacting with Jade's own
RR-sensitivity (section 3) rather than any code change (no commit
between decision #36 and this round modified any Jade module — H6 only
read them). **This does not undermine H7's own findings below**, which
are about REJECTION-REASON COMPOSITION and rejection RATE, not about
matching one historical trade count — but it means this round's 57
pooled trades (22+10+25) should be read as new, standalone 3-anchor
measurements, not a byte-identical replication of decision #36.

## 2. Results, all three anchors

| Anchor | Total trades | Total signals reaching RiskManager | Approved | Rejected | Reject rate | % of H6's `signal_would_generate` |
|---|---|---|---|---|---|---|
| 2026-07-10 | 22 | 3,567 | 22 | 3,545 | 99.4% | 97.3% |
| 2025-07-10 | 10 | 2,084 | 10 | 2,074 | 99.5% | 97.3% |
| 2024-07-10 | 25 | 2,370 | 25 | 2,345 | 98.9% | 94.6% |
| **3-year total** | **57** | **8,021** | **57** | **7,964** | **99.3%** | **96.5%** |

## 3. Primary keep-rule verdict, applied literally — then a disclosed correction

Quoting `docs/HYPOTHESES_ROUND_2.md` section 3's keep-rule verbatim:

> **RiskManager-gating-dominant** if ... `rejected / total_signals >= 0.5`
> ... AND `MAX_TRADES_PER_DAY` is the single most frequent `by_reason`
> entry ... **Open-trade/zone-persistence-dominant** if `total_signals`
> ... is less than 25% of H6's own `signal_would_generate` count.

**Open-trade/zone-persistence branch: cleanly REJECTED.** `total_signals`
is 94.6-97.3% of H6's step-level count in every year, nowhere close to
the <25% threshold. Open-trade-state tracking barely changes the
picture at all — because the approval rate is so low (0.7% of signals
that reach RiskManager), a trade is almost never open, so the
walk-forward loop almost never has anything to skip past. H6's raw step
counts were NOT mostly duplicate/overlapping zone retests; the vast
majority represent genuinely distinct signal-generation attempts.

**RiskManager-gating branch, applying the rule's literal text: TRUE.**
`reject_rate` (99.3%) clears 0.5 easily, and `MAX_TRADES_PER_DAY`
("trades_today 2 reached MAX_TRADES_PER_DAY 2") is, character-for-character,
the single most frequent individual string in `by_reason`. Per the rule
as pre-registered, this is **RISK_GATING_DOMINANT**.

**This mechanical result is misleading, and this document does not let
it stand as the substantive finding.** `RiskManager.evaluate()`'s own
RR-below-minimum rejection reason embeds the exact numeric RR value in
its string ("rr 0.052 is below required MIN_RR 2.0"), so it is
fragmented across thousands of distinct near-unique strings, each with a
small individual count — while `MAX_TRADES_PER_DAY`'s reason string never
varies, so every one of its occurrences accumulates under one key. A
"single most frequent exact string" comparison structurally favors
whichever reason happens to have a fixed string, independent of which
reason is actually more common in substance. **Re-aggregating
`by_reason` by CATEGORY instead of exact string, pooled across all 3
anchors** (8,589 total reason-instances — more than `aggregate_rejected`
7,964 because `RiskManager.evaluate()` collects every failing check per
signal, not just the first, so one rejected signal can carry multiple
reasons):

| Category | Reason-instances | Share |
|---|---|---|
| **RR below minimum (pooled, all embedded values)** | **7,929** | **92.3%** |
| `MAX_TRADES_PER_DAY` cap | 624 | 7.3% |
| Daily loss limit | 36 | 0.4% |

**Corrected finding: Jade's dominant rejection reason is overwhelmingly
RR-below-minimum (92.3%), not `MAX_TRADES_PER_DAY` (7.3%).** The keep-rule
as literally written technically resolves to RISK_GATING_DOMINANT, but
its "top single reason string" operationalization has a design flaw
this round discovered on contact with the real data — this is disclosed
plainly rather than hidden behind the literal mechanical answer,
matching this project's own precedent of treating a keep-rule's literal
result as a starting point for honest analysis, not the end of it (H3's
aggregate-vs-per-bucket footnote; H6's own aggregate-masks-heterogeneity
finding).

## 4. The substantive finding: Jade's real bottleneck is a reward:risk geometry problem, not the shared cap

Unlike Legacy, whose own raw-signal rejection is 100% `MAX_TRADES_PER_DAY`-driven
(decision #62: 89-92% of Legacy's signals rejected, every fired reason
the daily cap), **Jade's scarcity is a completely different mechanism**:
the vast majority of Jade's own generated entry/stop/target combinations
simply never clear this platform's 1:2 minimum reward:risk requirement.
This is consistent with everything else this evidence base has found
about Jade — its stop/target construction (`entry_point_engine.py`'s
zone-boundary-based stops, `exit_point_engine.find_exit_targets`'s
liquidity/swing/premium-discount target candidates) has never been
swept or tuned the way Legacy's own `_RR`/`_STOP_BUFFER` parameters were
(`docs/parameter_sweep_report.md`). **Two independently-built strategies
on this platform are bottlenecked by two DIFFERENT gates** — Legacy by
trade-frequency throughput under a fixed cap, Jade by trade-quality
geometry under the fixed minimum RR — which is itself a disclosed,
platform-level finding worth carrying into any future Strategy Selection
Engine design conversation, distinct from (and more actionable-shaped
than) the "shared bottleneck" hypothesis this round originally set out
to test.

## 5. Promotion path

**NONE — this is a diagnostic, not a promotion candidate.** The
corrected finding (section 4) does not itself validate or invalidate any
fix — it only identifies where the real bottleneck sits (RR geometry,
not zone-detection timing per H6, not the shared cap per this round's
literal-but-misleading result). A well-grounded future hypothesis could
ask whether Jade's stop/target construction can be adjusted to raise its
own RR distribution — that is a new, separately pre-registerable
question, not answered here. `use_jade_engine` stays `False`;
`RiskManager.evaluate()` and `scripts/run_paper.py` are completely
unmodified by this round.

**Legacy's live/paper trading behavior is completely unchanged.** 100%
backtest-only, read-only research round: no `BacktestEngine` parameter
or CLI flag was added (this round needed even less new code than H6 —
one thin wrapper script reusing two already-existing functions
verbatim). No orders placed, no writes to `backend/paper_validation.db`.

## 6. Caveats

- **The anchor-date mismatch (section 1) means this round's 57 pooled
  trades are not a confirmed byte-identical replication of decision
  #36's original 6.** The rejection-rate and reason-composition findings
  (sections 3-4) do not depend on matching that historical number and
  are not weakened by this caveat, but it should not be cited as
  "reproducing decision #36" without this qualification.
- **This hypothesis diagnoses a mechanism; it fixes nothing.** The
  RR-geometry finding does not itself validate any specific stop/target
  adjustment — that would be a new, separately pre-registered hypothesis.
- **One asset (BTCUSDT), one timeframe (15m)** — matching every hypothesis
  in this evidence base so far. Whether Jade's RR-geometry problem is
  BTC-specific or general is open, and now a better-grounded reason to
  eventually run the deferred Jade cross-asset check
  (`docs/HYPOTHESES_ROUND_2.md` section 4) than the original
  zone-scarcity framing alone provided.
- **The keep-rule design flaw disclosed in section 3 (string
  fragmentation defeating a "top single reason" comparison) should be
  treated as a standing caution for any future hypothesis that compares
  `RiskManager.evaluate()` rejection reasons by exact string** — pool by
  category first, the way this document did, before trusting which
  reason is "most common."
- **No code changed production behavior.** `scripts/research_h7_jade_risk_attribution.py`
  is a new research-only script that calls only already-existing,
  already-tested functions; no Jade module or `RiskManager` code was
  modified.
