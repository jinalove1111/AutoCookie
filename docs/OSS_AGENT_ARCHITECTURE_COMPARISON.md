# Open-Source Agent Architecture Comparison (Priority 3)

CTO deliverable (2026-07-19), operator directive: "Review the current
architecture. Compare it with proven open-source AI development
workflows such as multi-agent software teams, debate-based decision
systems, autonomous engineering workflows. Adopt only components that
provide measurable value. Do NOT duplicate functionality already
present." Grounded in a current web search (2026), not solely prior
training data — sources listed at the end.

---

## 1. What already exists in this repo (`.claude/`)

Per `CLAUDE.md`'s own pointer and this session's system reminders, this
repo already runs a hierarchical, role-specialized multi-agent harness:
a **CTO** skill that decomposes and routes work to **department Heads**
(`planning-agent`, `engineering-head` with backend/frontend sub-agents,
`security-head` with bughunter/auditor/compliance-auditor/threat-modeler/
secret-scanner sub-agents, `qa-head`), which further delegate to
sub-agents — plus a `round-loop` skill (N-round autonomous loops with a
5-gate convergence check: AC/similarity/stagnation/oscillation/max_gen)
and a `nexus-orchestration` 7-phase pipeline for large multi-department
projects. Sonnet implements, Opus plans/verifies, commit/push require
explicit operator approval.

**This is already, structurally, the same core idea** several of the
frameworks below are built around: a simulated organization of
role-specialized agents under hierarchical delegation. Any comparison
below is scoped to "is there a genuinely different, missing capability,"
not "should we replace this with a framework" — replacing a
working, already-integrated system with a second, overlapping one is
exactly the complexity this task explicitly warns against adopting.

---

## 2. Landscape survey (2026, current)

| Project | Core idea | Notable stats (2026) |
|---|---|---|
| **CrewAI** | Role-playing agent "crews," lowest learning curve, role-based DSL | 52,800+ GitHub stars, 5.2M monthly downloads |
| **LangGraph** | Graph-based agent orchestration, durable state, checkpointing with "time travel," human-in-the-loop | 34.5M monthly downloads (leads enterprise adoption) |
| **AutoGen** | Conversable multi-agent framework | Microsoft merged it into "Microsoft Agent Framework" (with Semantic Kernel) in Oct 2025; AutoGen itself is now in maintenance mode (bug fixes/security only) |
| **MetaGPT** | Simulates a software company (PM/architect/engineer roles) for project generation | Recommended specifically for software project generation |
| **ChatDev** | Simulates an entire software company as a chat-driven organization | Full-organization simulation, similar spirit to MetaGPT |
| **Dify** | Low-code agent/workflow builder | 144k GitHub stars (leads on stars specifically) |

**Trend worth noting, not adopting yet**: MCP (Model Context Protocol)
native support is becoming a dividing line between "production-ready"
and "experimental" frameworks for tool/data connectivity. Relevant to
this project's own near-future plans (`docs/EXCHANGE_LAYER_IMPLEMENTATION_ROADMAP.md`
proposes hand-rolled REST clients, matching `CandleFetcher`'s existing
pattern) — worth watching, not worth adopting now: introducing MCP as a
dependency for a single exchange integration would be new infrastructure
complexity for a problem the existing pattern already solves adequately.

---

## 3. Multi-agent software teams (MetaGPT / ChatDev / CrewAI)

**Comparison**: all three simulate role-specialized software-team
members collaborating on a deliverable. This repo's `.claude/` harness
already does this — CTO → department Heads → sub-agents is the same
shape as MetaGPT's PM/architect/engineer roles or ChatDev's simulated
organization, just implemented as Claude Code skills/sub-agents instead
of a standalone framework.

**Recommendation: do not adopt.** Nothing in this category offers a
capability this repo's harness lacks; adopting one would duplicate an
already-working system, directly contradicting this task's own "do not
duplicate functionality already present" instruction.

---

## 4. Debate-based decision systems

**What this actually is** (grounded in the 2026 search above, not the
"multi-agent software team" idea): having multiple agent instances
independently argue FOR and AGAINST a candidate answer/conclusion before
accepting it, shown in the literature to reduce hallucination and
improve reasoning specifically on questions with a checkable answer
(math, logic, factual QA) — a verification pattern, not a team-simulation
pattern. Recent refinements (Adaptive Heterogeneous Multi-Agent Debate)
outperform standard debate by 4-6 percentage points on benchmarks like
GSM8K.

**This is the one genuinely-not-yet-present idea worth naming
concretely.** This project's own evidence base already shows the VALUE
of exactly this pattern, just performed manually by one agent
self-scrutinizing instead of two agents formally arguing:

- H7's literal keep-rule mechanically resolved `RISK_GATING_DOMINANT`,
  but re-examining the SAME data by category (not exact string) flipped
  the substantive conclusion to RR-geometry-dominant.
- H8's literal keep-rule mechanically resolved `PARAMETER_SENSITIVE`,
  but scrutinizing WHICH dimension actually drove the number (target
  index, not stop_model — the question H7 actually raised) reversed
  which finding should be trusted.

Both catches happened because one agent (this session) deliberately
re-examined its own literal result before reporting it — not because a
second, independent agent argued the other side. **A lightweight,
optional "adversarial review" step for exactly this class of
decision** (a pre-registered hypothesis's literal keep-rule result,
before it's written into a results doc as final) is a concrete,
bounded, measurable-value candidate: a second agent instance, given only
the raw data and the pre-registered keep-rule text (not the first
agent's own narrative), independently checks whether the literal verdict
survives scrutiny — closer to this repo's own existing
`code-review`/`security-review` skill pattern (already adversarial-review-shaped)
than to a wholesale framework adoption.

**Recommendation**: worth a small, bounded pilot on a FUTURE hypothesis
round specifically (not a retrofit of H1-H8, which already went through
this manually) — NOT a new dependency or framework, just a documented
convention: pre-registered keep-rule results get one independent
re-check pass before being called final, the same way `code-review`
already gets invoked for code changes. This is process discipline, not
infrastructure — genuinely low-cost to try, does not require adopting
any external framework.

---

## 5. Autonomous engineering workflows

**Comparison**: LangGraph's durable state + checkpointing/"time travel"
is the closest match to what a fully autonomous, long-running
engineering agent would need. This project's own equivalent is its
append-only documentation set (`PROJECT_STATUS.md`/`ROADMAP.md`/
`CHANGELOG.md`/`ENGINEERING_DECISIONS.md`/`HANDOFF.md`) — arguably a
**stronger** fit for this project's actual need (cross-SESSION
continuity for a human-readable, git-versioned audit trail that a fresh
Claude Code session can read cold) than a framework's internal state
graph, which is typically scoped to a single run's execution state, not
multi-week human-auditable history.

**Recommendation: do not adopt.** The existing documentation discipline
already outperforms what a framework's state-management layer would add
for this project's specific need (long-horizon, cross-session,
human-readable audit trail) — this is a case where the "proven OSS
workflow" and this project's own bespoke solution solve genuinely
different problems, not a gap to fill.

---

## 6. Summary recommendation

| Category | Adopt? | Why |
|---|---|---|
| Multi-agent software teams (MetaGPT/ChatDev/CrewAI) | **No** | Already present (`.claude/` harness) |
| Debate-based decision systems | **Partial — process convention only, no new dependency** | Genuinely missing capability; this project's own H7/H8 findings already demonstrate its value manually |
| Autonomous engineering workflows (LangGraph-style state) | **No** | Existing documentation discipline already better-fits this project's cross-session audit-trail need |
| MCP (tool/data connectivity standard) | **Watch, not yet** | Relevant to future exchange integration, premature to adopt for one integration |

No dependency was added. No existing `.claude/` skill/agent was
modified. This section's only recommendation (a keep-rule adversarial
re-check convention) is a documentation/process suggestion for a FUTURE
hypothesis round, not something implemented in this round.

---

## Sources

- [The best open source frameworks for building AI agents in 2026](https://www.firecrawl.dev/blog/best-open-source-agent-frameworks)
- [Best Multi-Agent Frameworks in 2026: LangGraph, CrewAI...](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
- [Best AI Agent Frameworks 2026: 7 Compared](https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026)
- [CrewAI vs LangGraph vs AutoGen vs OpenAgents (2026)](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared)
- [The best AI agent frameworks in 2026 — LangChain](https://www.langchain.com/resources/ai-agent-frameworks)
- [Improving Factuality and Reasoning in Language Models through Multiagent Debate (ICML 2024, GitHub)](https://github.com/composable-models/llm_multiagent_debate)
- [Adaptive heterogeneous multi-agent debate for enhanced educational and factual reasoning](https://link.springer.com/article/10.1007/s44443-025-00353-3)
