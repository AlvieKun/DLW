# AI Pattern Justification Report

> For every major subsystem in Learning Navigator, this document records:
> **Why chosen · Alternatives considered · Failure modes · Trust/explainability impact · Computational tradeoffs**

---

## Table of Contents

1. [Orchestrator & Communication Protocol](#1-orchestrator--communication-protocol)
2. [Learner State Model + Uncertainty](#2-learner-state-model--uncertainty)
3. [Core Agents](#3-core-agents)
4. [Debate Subsystem](#4-debate-subsystem)
5. [Skill State (BKT + Knowledge Graph)](#5-skill-state-bkt--knowledge-graph)
6. [Behavior Anomaly Detection](#6-behavior-anomaly-detection)
7. [Time Optimization](#7-time-optimization)
8. [Reflection Narrative](#8-reflection-narrative)
9. [RAG Subsystem](#9-rag-subsystem)
10. [Maker–Checker Validation + Adversarial Auditing](#10-makercheckervalidation--adversarial-auditing)
11. [Human-in-the-Loop Hooks](#11-human-in-the-loop-hooks)
12. [Decay Agent + Generative Replay](#12-decay-agent--generative-replay)
13. [Competitive Differentiator: Adaptive Agent Routing](#13-competitive-differentiator-adaptive-agent-routing)
14. [Competitive Differentiator: Dynamic Agent Confidence Weighting](#14-competitive-differentiator-dynamic-agent-confidence-weighting)
15. [Azure Integration + Event-Driven Consolidation](#15-azure-integration--event-driven-consolidation)

---

## 1. Orchestrator & Communication Protocol

### Why Chosen
A central orchestrator with an explicit message bus decouples agents, enabling independent development, testing, and replacement. The `MessageEnvelope` schema with versioning, correlation/causality chains, and provenance allows full distributed tracing even in a single-process deployment. This is critical for observability and debugging in a multi-agent system where emergent behavior is hard to predict.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Direct agent-to-agent calls | Creates tight coupling, makes routing logic implicit, breaks observability |
| Shared blackboard (tuple space) | Race conditions, no causal ordering, hard to trace provenance |
| Pure LLM orchestrator (e.g., AutoGPT style) | Non-deterministic routing, high cost, poor auditability |
| Static pipeline (DAG) | Too rigid — learner context requires dynamic routing decisions |

### Failure Modes
- **Message loss**: In-memory bus has no durability. Mitigation: history buffer + future Azure Service Bus adapter.
- **Handler deadlock**: Async handler that awaits publishing can create cycles. Mitigation: design discipline + cycle detection (future).
- **Schema drift**: Agents compiled against v1 schema receiving v2 messages. Mitigation: explicit `schema_version` field + graceful fallback.

### Trust / Explainability Impact
Correlation IDs and causality chains allow reconstructing *why* a recommendation was made — which events triggered which agents. This is essential for teacher verification and HITL review.

### Computational Tradeoffs
In-process async dispatch is near-zero overhead. The cost is no built-in durability or scale-out, which is acceptable for v1. Azure adapter provides the path to durable scale-out.

---

## 2. Learner State Model + Uncertainty

### Why Chosen
A unified `LearnerState` object that serves as the single source of truth for all agents. This avoids scattered state, ensures consistency, and makes it possible to serialize/persist/audit the complete learner picture at any point.

Key design choices:
- **BKT (Bayesian Knowledge Tracing)** for per-concept mastery: well-validated in educational research, interpretable probabilities, and supports principled uncertainty via binary entropy.
- **Entropy-based uncertainty**: at `p_know=0.5` uncertainty is maximal (1.0), at extremes it's zero. This drives adaptive routing — high uncertainty triggers more agents.
- **Knowledge graph as adjacency list**: captures prerequisite/corequisite/extends/related relationships without requiring a full graph DB. Sufficient for concept traversal (e.g., "what should I review before calculus?").
- **Motivation as a separate tracked signal** with level, score, trend, and confidence — not conflated with mastery.
- **Forgetting score** per concept (separate from mastery) — a dedicated field updated by the Decay Agent, enabling spaced-repetition scheduling.
- **Time budget constraints** as first-class data — the Time Optimizer needs this to produce feasible plans.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Simple mastery percentage | No uncertainty, no principled update rule, no basis for confidence scoring |
| Deep Knowledge Tracing (DKT) | Requires training data + GPU; opaque; poor interpretability; overkill for v1 |
| Item Response Theory (IRT) | Better for test design than ongoing tracking; doesn't model learning transitions |
| External graph DB (Neo4j) | Operational complexity; adjacency list sufficient for thousands of concepts |
| Flat session history only | No generalization across concepts; can't do prerequisite reasoning |

### Failure Modes
- **BKT parameter miscalibration**: If `p_slip`, `p_guess`, `p_transit` are wrong, mastery estimates drift. Mitigation: allow per-concept parameter overrides; cohort meta-learning (Differentiator D5) can improve priors.
- **Stale state**: If events are missed or delayed, state diverges from reality. Mitigation: inactivity detection triggers Decay Agent + Generative Replay.
- **Knowledge graph incompleteness**: Missing prerequisite edges cause bad recommendations. Mitigation: graph is editable by teachers (HITL); Reflection Agent flags when recommendations skip prerequisites.

### Trust / Explainability Impact
All state is inspectable and serializable as JSON. The Reflection Agent generates natural-language summaries from this state. Teachers can view BKT parameters and override them (HITL hooks). Uncertainty is explicit, not hidden — it drives system behavior and is surfaced in explanations.

### Computational Tradeoffs
BKT update is O(1) per observation — negligible. State serialization is O(n) where n = concept count, typically ~100-1000. JSON storage is acceptable for single-user; for cohorts, the Azure Blob adapter scales horizontally.

---

## 3. Core Agents

### Why Chosen
Five specialized agents implement the v1 pipeline: **Diagnoser** (BKT updates + event interpretation), **Drift Detector** (5 learning-drift heuristics), **Motivation Agent** (4-signal weighted inference), **Planner** (priority-ranked recommendations with motivation-adaptive session lengths), and **Evaluator** (6-check quality gate). Each agent is deterministic and rule-based for v1 — no LLM dependency — ensuring reproducibility, testability, and zero-cost inference.

The separation into five agents (rather than one monolithic "tutor" agent) provides:
- **Single responsibility**: Each agent's logic can be tested, iterated, and replaced independently.
- **Composability**: The pipeline order can be rearranged (Phase 8: adaptive routing) without rewriting agent internals.
- **Cost tiers**: Diagnoser/DriftDetector/Motivation are cost-tier-1 (fast heuristics); Planner/Evaluator are cost-tier-2 (more complex reasoning). This enables future cost-aware routing.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Single LLM-powered tutor | Expensive, non-deterministic, impossible to unit-test individual reasoning steps |
| Two-agent (diagnose + plan) | Conflates drift detection, motivation tracking, and quality evaluation into oversized agents |
| LLM-backed rule agents | Adds latency + cost for deterministic logic that can be implemented directly |
| Stateless agents (no LearnerState) | Agents need historical context (spacing history, practice count) for accurate recommendations |

### Failure Modes
- **BKT parameter bias**: Default `p_slip`/`p_guess` may not match real learner populations. Mitigation: per-concept parameter overrides; future cohort meta-learning.
- **Drift false positives**: Inactivity threshold too aggressive → normal weekends flagged. Mitigation: configurable `inactivity_threshold_hours` parameter (default 48h).
- **Motivation signal starvation**: New learners have no history → motivation defaults to MEDIUM. Mitigation: explicit default + confidence score reflects signal count.
- **Planner generates empty plan**: Learner has no concepts yet. Mitigation: Evaluator catches `empty_plan` issue; engine still produces a valid NextBestAction with fallback.
- **Evaluator too strict/lenient**: Fixed quality thresholds may not fit all contexts. Mitigation: configurable via Maker-Checker `min_quality_score`.

### Trust / Explainability Impact
Every agent returns a `rationale` field explaining its reasoning in natural language. The Diagnoser lists which concepts were updated and by how much. The Planner explains why each concept was prioritized. The Evaluator lists specific quality issues found. All of this feeds into the NextBestAction `debug_trace`, making the system fully inspectable.

### Computational Tradeoffs
All agents are O(n) where n = number of concepts in the learner's state (typically 10–1000). No network calls, no GPU, no LLM tokens. A full pipeline tick completes in <10ms on commodity hardware. This makes the system suitable for real-time response even on mobile backends.

---

## 4. Debate Subsystem

### Why Chosen
Learning plans involve inherent *strategic tradeoffs* that a single planning agent cannot resolve — should the learner spend time on depth vs breadth? Pursue exam-critical topics or shore up foundations? Push through hard content or protect against burnout? The strategic debate system resolves these tensions through a structured three-advocate + arbitrator architecture:

1. **Mastery Maximizer** — advocates for deep, durable understanding (prerequisite coverage, sufficient session depth, spaced repetition for at-risk concepts).
2. **Exam Strategist** — advocates for assessment-optimal study (priority coverage, deadline awareness, practice tests, avoiding over-maintenance).
3. **Burnout Minimizer** — advocates for sustainable engagement (session length caps by motivation level, cognitive load limits, stress-signal awareness).
4. **Debate Arbitrator** — resolves disagreements via contextually-weighted scoring. Weights shift based on learner state: near-deadline → exam weight increases; low motivation → burnout weight increases; cramming behaviours → burnout weight increases. All weights normalise to 1.0.

The **DebateEngine** orchestrates the loop: plan → fan-out to 3 advocates → collect critiques (with alignment scores) → if all aligned (≥0.85), approve immediately → otherwise arbitrate → if major revision and rounds remain, loop.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Single "balanced" planning agent | Collapses competing objectives into one opaque function; no transparency about *which* perspective dominated |
| Majority vote among agents | Doesn't weight perspectives contextually; burnout concerns ignored 2-to-1 even when learner is critical |
| LLM-based debate (multi-turn prompting) | Expensive, non-deterministic, slow; rule-based debate is sufficient for known tradeoff dimensions |
| User selects priority manually | Adds friction; learner often doesn't know optimal strategy; system should adapt automatically |
| Two-agent debate (mastery vs exam) | Misses the crucial third axis (wellbeing/burnout); learner welfare is a first-class concern |

### Failure Modes
- **All advocates always object**: Possible if plan is genuinely bad. Mitigation: Arbitrator's severity threshold filters low-weighted objections; only objections above `weighted_severity ≥ 0.3` are accepted.
- **Deadweight advocate**: An advocate with no relevant objections still runs. Mitigation: Aligned advocates (alignment ≥ 0.85) trigger early exit with no arbitration cost.
- **Arbitrator bias toward one perspective**: If weight adjustments are too aggressive, one perspective always dominates. Mitigation: Weights are normalised and base weights are configurable via constructor injection.
- **Infinite revision loop**: Major revision re-invokes debate. Mitigation: Hard cap on `max_debate_rounds` (default 2).

### Trust / Explainability Impact
The Reflection Agent now includes a "Strategic Debate" section in its narrative, reporting the debate outcome, perspective weights, and amendment count. Learners (and teachers via HITL) can see *which strategic perspective shaped the final plan* and why. This transparency is a significant differentiator over black-box planners.

### Computational Tradeoffs
The debate adds 4 agent invocations per plan (3 advocates + 1 arbitrator), all rule-based and sub-millisecond each. Total overhead: ~1-5ms per pipeline tick. With `debate_enabled=False`, overhead is zero (early return). When all advocates align, arbitrator is skipped entirely. Maximum cost: `max_debate_rounds × 4` agent calls = 8 with default settings.

---

## 5. Skill State (BKT + Knowledge Graph)

### Why Chosen
The Skill State Agent adds *relational analysis* on top of the Diagnoser's per-concept BKT updates. While the Diagnoser updates mastery for individual concepts, it doesn't reason about the *relationships* between concepts. The Skill State Agent fills this gap:

- **Concept readiness scoring**: Before recommending calculus, verify that algebra prerequisites are met. Readiness = min(prerequisite masteries), gated at a configurable threshold (default 0.6).
- **Prerequisite gap detection**: Identifies concepts that are blocked by under-mastered prerequisites, sorted by severity.
- **Cluster analysis**: Groups concepts into connected components via BFS on the knowledge graph. Reveals which knowledge clusters are strong vs weak.
- **Learning order suggestion**: Produces a priority-ranked list using `readiness x (1 - mastery)`, filtering out already-mastered concepts.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Graph DB (Neo4j) | Operational complexity; adjacency list sufficient for hundreds of concepts |
| LLM-based prerequisite inference | Expensive, non-deterministic; curriculum structure is known a priori |
| Topological sort only | Doesn't account for current mastery levels — a concept may be "next" but the learner isn't ready |
| Merge into Diagnoser | Violates single responsibility; graph analysis is orthogonal to BKT updates |

### Failure Modes
- **Incomplete knowledge graph**: Missing prerequisite edges lead to false "ready" signals. Mitigation: Evaluator checks for prerequisite violations; teachers can edit graph via HITL.
- **Circular prerequisites**: Would cause infinite loops in BFS. Mitigation: BFS uses visited set; cycles are harmless.
- **Stale readiness when mastery decays**: Readiness is snapshot-based. Mitigation: re-computed every pipeline tick.

### Trust / Explainability Impact
The Reflection Agent cites prerequisite gaps and learning order in its narrative. Teachers can see *why* a concept was recommended or blocked. The cluster visualization (future UI) makes knowledge structure transparent.

### Computational Tradeoffs
BFS is O(V + E) where V = concepts, E = relations. For typical learner graphs (100-1000 concepts), this is sub-millisecond. Readiness computation is O(V x max_prerequisites), also negligible.

---

## 6. Behavior Anomaly Detection

### Why Chosen
The Behavior Agent detects *how* a learner interacts, complementing the Diagnoser (*what* they know) and Drift Detector (*learning trajectory*). Five anomaly types are implemented:

1. **Cramming**: High practice volume concentrated near a deadline. Detected via session count + deadline proximity + practice concentration.
2. **Rapid guessing**: Very short response times suggesting random guessing rather than genuine engagement. Uses `response_time_seconds` from event data, cross-referenced with concept mastery.
3. **Concept avoidance**: Systematically skipping certain concepts while practicing others heavily. Detected via practice count disparity across concepts.
4. **Irregular sessions**: Highly variable spacing intervals (coefficient of variation > threshold). Consistent practice schedules improve retention.
5. **Late-night study**: Sessions at unusual hours (00:00-05:00 UTC), which correlate with reduced retention and fatigue.

Each anomaly returns a severity score and supporting evidence.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Statistical process control (SPC) | Too rigid for variable learner patterns; requires baseline calibration |
| ML anomaly detection (Isolation Forest) | Requires training data; opaque; overkill for v1 heuristics |
| Merge into Drift Detector | Different concerns: drift = learning trajectory, behavior = interaction patterns |
| LLM-based behavior analysis | Expensive, non-deterministic for pattern detection that's well-served by heuristics |

### Failure Modes
- **False positives**: Aggressive thresholds flag normal weekend breaks as "irregular." Mitigation: configurable thresholds; late-night detection respects UTC (future: learner timezone).
- **False negatives**: Subtle avoidance patterns missed if practice counts are close to threshold. Mitigation: `avoidance_practice_ratio` is tunable.
- **Missing event data**: `response_time_seconds` may not be available for all event types. Mitigation: each detector gracefully returns None when data is insufficient.

### Trust / Explainability Impact
Anomalies are surfaced in the Reflection Agent's narrative with actionable advice (e.g., "spread study sessions more evenly"). Evidence is logged for teacher review. Anomaly types are human-readable, not opaque model scores.

### Computational Tradeoffs
All detectors are O(n) where n = number of concepts. Coefficient of variation for irregular sessions is O(m) where m = total spacing intervals. Total: sub-millisecond.

---

## 7. Time Optimization

### Why Chosen
The Time Optimizer solves a constrained allocation problem: given limited session time, which concepts should receive how many minutes? It uses:

- **Urgency x importance scoring**: Urgency = mastery_gap x 2 + forgetting x 1.5. Importance = 1 + dependent_count x 0.5 + priority_boost (2.0 for flagged concepts).
- **Proportional allocation**: Minutes are distributed proportionally by score, with a minimum block size (5 min) and maximum 6 concepts per session to avoid fragmentation.
- **Motivation-adaptive sessions**: LOW motivation reduces session to 70%; CRITICAL to 50%.
- **Deadline analysis**: Exponential urgency curve as deadline approaches; checks if time budget is sufficient for remaining concepts.
- **Action type assignment**: `learn_new` (mastery < 0.3), `practice` (< 0.6), `deepen` (< 0.85), `maintain` (≥ 0.85), `spaced_review` (forgetting > 0.5).

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Linear programming (LP) | Over-engineered for v1; proportional allocation is interpretable and fast |
| Equal time per concept | Ignores urgency; wastes time on mastered concepts |
| LLM-based scheduling | Expensive, non-deterministic for a well-defined optimization problem |
| Merge into Planner | Planner decides *what* to study; Time Optimizer decides *how long*. Different concerns. |

### Failure Modes
- **Over-fragmentation**: Many concepts with similar scores get tiny time blocks. Mitigation: 5-min minimum block + 6-concept cap.
- **Deadline panic**: Very short deadline causes extreme urgency scores. Mitigation: urgency is clamped to [0, 1]; session length is bounded.
- **Motivation override**: Shortened sessions may be insufficient for complex topics. Mitigation: minimum session length of 10 minutes.

### Trust / Explainability Impact
The allocation plan shows exactly how many minutes each concept gets and why (score breakdown, priority flag, action type). The Reflection Agent narrates this as "Allocated N minutes across M concepts."

### Computational Tradeoffs
Scoring is O(n) with constant-factor graph lookups for dependents. Allocation is O(n log n) for sorting. Total: sub-millisecond for typical learner states.

---

## 8. Reflection Narrative

### Why Chosen
The Reflection Agent is the explainability layer of the system. It reads the outputs of *all* previous pipeline stages and synthesizes a coherent, human-readable narrative. This is critical because:

- **Multi-agent systems are hard to explain**: When 9 agents contribute to a recommendation, no single agent's output tells the full story.
- **Teacher trust requires transparency**: Educators need to understand *why* a recommendation was made before approving it.
- **Learner engagement**: Personalized narratives ("You improved on algebra this session") reinforce motivation better than raw scores.

The agent produces 8 sections: Progress Overview, This Session, Motivation, Learning Drift, Behavioral Patterns, Recommendations, Knowledge Graph, Looking Ahead. Empty sections are filtered out. Citations track which upstream agents contributed data.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| LLM-generated narratives | Would produce better prose but adds cost, latency, and non-determinism. Template-based is sufficient for v1; LLM upgrade is a future option. |
| Dashboard-only (no narrative) | Dashboards show *what* happened but not *why*. Narrative adds causal reasoning. |
| Per-agent explanations only | Fragmented; doesn't show cross-agent interactions (e.g., "low motivation + cramming suggests burnout risk"). |
| Merge into Evaluator | Evaluator judges quality; Reflection explains the full picture. Different audiences. |

### Failure Modes
- **Stale context**: If an upstream agent errored, its response is empty and the Reflection Agent produces a thinner narrative. Mitigation: graceful degradation — missing sections are simply omitted.
- **Generic narratives**: New learners with little data get bland summaries. Mitigation: "Early stage — start with the basics" messaging; richness increases as more data accumulates.
- **Incorrect citations**: If agent responses change format, citations may miss them. Mitigation: citation logic checks for non-empty dicts, independent of specific keys.

### Trust / Explainability Impact
The Reflection Agent *is* the trust mechanism for learner-facing deployments. Every recommendation is accompanied by a narrative explaining progress, motivation, drift signals, behavioral patterns, and the plan's rationale. Citations provide audit trail back to specific agents.

### Computational Tradeoffs
Pure string construction from pre-computed data. No network calls, no LLM tokens. Cost: O(n) string concatenation where n = number of concepts. Negligible latency (<1ms).

---

## 9. RAG Subsystem

### Why Chosen
Retrieval-Augmented Generation (RAG) grounds the system's recommendations in concrete supporting material from a knowledge base, rather than relying solely on agent heuristics. The key innovation is **learner-aware query construction**: queries are not just raw concept names, but contextually enriched based on:

- **Mastery level** — beginner learners get introductory/basics queries; advanced learners get deep-dive/application queries
- **Recommended action** — `learn_new` → tutorials; `practice` → exercises; `spaced_review` → summaries/flashcards
- **Difficulty awareness** — high-difficulty concepts get "simplified step by step" modifiers
- **Prerequisite gaps** — if weak prerequisites exist, queries include prerequisite material

This ensures retrieved content matches *where the learner is*, not just *what the topic is*.

The architecture uses a `RetrievalIndex` abstraction with two implementations:
- **LocalTfidfIndex** — full TF-IDF engine for local development (tokenisation, IDF computation, cosine similarity, metadata filtering, JSON persistence)
- **AzureAISearchIndex** — graceful stub for Azure AI Search (no-op when SDK not available, ready for Phase 9 deployment)

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Fixed content mapping (concept → document) | No relevance ranking, no learner awareness, doesn't scale |
| Embedding-based vector search only | Requires embedding model infrastructure; TF-IDF is sufficient for v1 and adds zero external dependency |
| No retrieval (pure rule-based) | Recommendations lack grounding; users can't see *why* or reference supporting material |
| Full semantic search with LLM reranking | Expensive, adds latency, overkill for deterministic v1 system |

### Failure Modes
| Failure | Mitigation |
|---|---|
| Empty knowledge base | RAG step is optional — engine works without retrieval index; empty citations list is valid |
| Low-relevance results | Min-score filtering (configurable threshold) + result deduplication |
| Query drift (irrelevant modifiers) | Queries are deterministic and testable; each modifier is unit-tested |
| Duplicate citations across concepts | Deduplication by doc_id, keeping highest-scoring entry |
| Azure SDK not installed | AzureAISearchIndex gracefully degrades to no-op with structured logging |

### Trust / Explainability Impact
Citations flow through the system in three ways:
1. **NextBestAction.citations** — doc_id keys attached to every recommendation, enabling frontend "why?" explanations
2. **Reflection Agent "Supporting Material" section** — human-readable narrative listing top citations with scores and snippets
3. **Debug trace** — RAG pipeline step logged with query count and citation count for observability

This creates a verifiable chain: learner state → learner-aware query → retrieved document → citation key → recommendation. Users and reviewers can trace exactly which material supports each recommendation.

### Computational Tradeoffs
- **LocalTfidfIndex**: O(n) search per query (full scan with cosine similarity). Acceptable for knowledge bases up to ~10K documents. IDF recomputation is lazy (only when corpus changes). Disk persistence via JSON adds ~50ms per write.
- **Per-turn cost**: One search per plan recommendation concept (typically 2-5 concepts × top_k=3 results). Total: ~5-15 similarity computations per turn.
- **Memory footprint**: TF-IDF vectors stored in-memory for fast retrieval; disk used only for persistence between restarts.
- The RAG step is skipped entirely when no retrieval_index is provided, adding zero overhead for users who don't need retrieval.

---

## 10. Maker–Checker Validation + Adversarial Auditing

### Why Chosen
The Maker-Checker pattern separates plan generation (Planner = maker) from plan validation (Evaluator = checker), creating a feedback loop that catches quality issues before recommendations reach the learner. The implementation supports configurable `max_rounds` (default 3) and `min_quality_score` (default 0.5), allowing the system to iterate until quality is acceptable or the budget is exhausted.

This pattern is well-established in financial systems and content moderation. In education, it prevents:
- Recommending content that violates prerequisite ordering
- Overloading demotivated learners with long sessions
- Cognitive overload from too many new concepts at once
- Empty or degenerate plans

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Single-pass planning (no checker) | No quality gate — bad plans go directly to learners |
| LLM-as-judge | Expensive, non-deterministic, requires prompt engineering for each quality criterion |
| Ensemble voting (multiple planners) | Heavier — v1 doesn't need multiple planning strategies yet (that's Phase 6 debate) |
| Post-hoc logging only | Catches issues too late — learner already received the bad recommendation |

### Failure Modes
- **Infinite rejection loop**: Evaluator always rejects → Planner can't satisfy criteria. Mitigation: hard `max_rounds` limit; last round's result is used even if imperfect.
- **Evaluator too lenient**: Low `min_quality_score` lets bad plans through. Mitigation: configurable threshold per deployment; HITL layer provides second check.
- **Evaluator-Planner collusion**: Both agents agree on bad plans. Mitigation: Evaluator checks are orthogonal to Planner logic; adversarial auditing (future) adds independent verification.

### Trust / Explainability Impact
The `MakerCheckerResult` includes full audit trail: number of rounds, maker/checker responses per round, final verdict, and quality score. This is logged to the portfolio and available in the debug trace. Educators can see *why* a plan was approved or revised, and how many iterations were needed.

### Computational Tradeoffs
Each round adds one Planner + one Evaluator invocation. With deterministic agents, this is <5ms per round. Typical convergence is 1 round (plan quality is usually acceptable on first pass). Worst case is `max_rounds` iterations — still <15ms total.

---

## 11. Human-in-the-Loop Hooks

### Why Chosen
The HITL subsystem provides a pluggable review layer between the Maker-Checker output and the final recommendation. The `HITLHook` abstract interface allows different review policies (auto-approve, strict review, escalation) without changing engine code. The default implementation uses a quality-score threshold: plans above the threshold are auto-approved, below it trigger human review.

Design choices:
- **Pluggable interface** (`HITLHook` ABC): Allows custom policies for different deployments (classroom vs self-study vs enterprise).
- **`should_require_review()` + `request_review()`** two-step API: First decides if review is needed (cheap), then performs the review (potentially blocking). This allows policies that combine quality score, error presence, and domain-specific rules.
- **Audit log** (`review_log`): Every HITL decision is logged with timestamp, quality score, decision, and reasoning. Supports compliance and teaching team oversight.
- **Decision enum** (APPROVE, REJECT, MODIFY, ESCALATE, AUTO_APPROVED): Rich decision vocabulary allows nuanced human feedback.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| No HITL (fully autonomous) | Unacceptable for educational contexts where teacher oversight is required |
| Mandatory review for every recommendation | Doesn't scale — HITL should be triggered by risk signals, not on every turn |
| External review service (webhook) | Over-engineering for v1; interface supports this as a future adapter |
| LLM-based auto-review | Adds cost and non-determinism to a quality gate that should be predictable |

### Failure Modes
- **Auto-approve threshold too permissive**: Bad plans slip through. Mitigation: threshold is configurable; `require_review_on_errors=True` escalates any plan with evaluator-flagged issues.
- **HITL bottleneck**: If human review is required for many plans, throughput drops. Mitigation: quality threshold can be tuned; majority of plans should auto-approve in a well-configured system.
- **Stale review**: Human reviews a plan after learner context has changed. Mitigation: future timestamp-based expiry on review requests.

### Trust / Explainability Impact
HITL is the primary trust mechanism for educator-facing deployments. Teachers can see every recommendation before it reaches learners, override decisions, and provide feedback that improves future plans. The audit log provides full accountability.

### Computational Tradeoffs
Auto-approve path: ~0ms (threshold comparison). Human review path: latency depends on response time. The engine is designed to be fully async, so HITL review doesn't block other learners' processing.

---

## 12. Decay Agent + Generative Replay

### Why Chosen
Forgetting is the silent failure mode of learning systems. Without explicit decay modelling, the system assumes knowledge persists indefinitely once acquired. The Decay Agent adds two critical capabilities:

1. **Ebbinghaus decay model**: `retention(t) = exp(-t / S)` where S (stability) is computed from repetition count, spacing quality, difficulty, and mastery. This produces a per-concept forgetting score (0 = retained, 1 = forgotten).
2. **Spaced-repetition scheduling**: From stability, compute the optimal next-review time: `t = -S * ln(target_retention)`. This tells the system exactly when to schedule review before knowledge drops below the target threshold (default 85%).

The Generative Replay Agent then creates *what to practice*:
- **Fragility-based selection**: Targets concepts with the highest `mastery * forgetting` product -- these are the most valuable to reinforce (well-learned but fading).
- **Typed exercises**: recognition, recall, application, synthesis -- calibrated by mastery level.
- **Interleaving**: Groups related concepts into interleaved practice sets using knowledge graph edges.
- **Difficulty calibration**: Exercises are tuned to the zone of proximal development (slightly above current mastery).

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| SM-2 / Anki algorithm | Requires explicit user ratings (1-5); our system infers from quiz data |
| FSRS (Free Spaced Repetition Scheduler) | More accurate but complex; v1 priorities are interpretability + correctness |
| LLM-generated exercises | Would produce richer content but adds cost, latency, non-determinism; exercise *specifications* are sufficient for v1 |
| Leitner box system | Too coarse (only 3-5 buckets); exponential decay gives continuous granularity |
| No decay modelling | The system would re-recommend mastered concepts or ignore fading ones — both waste learner time |

### Failure Modes
- **Inaccurate stability estimation**: Too few data points (new concepts) lead to unreliable stability. Mitigation: conservative base stability (24h); stability improves with more practice data.
- **Over-review**: Stability is underestimated, causing too-frequent review. Mitigation: stability has a floor of 1 hour; scheduling uses target retention of 85%, not 95%.
- **Replay fatigue**: Too many replay exercises frustrate learners. Mitigation: max 8 concepts per replay set; max 4 exercises per concept.
- **Stale forgetting scores**: If the Decay Agent runs infrequently, scores become outdated. Mitigation: re-computed every pipeline tick.

### Trust / Explainability Impact
The Reflection Agent's new "Memory & Retention" section surfaces at-risk concepts with their forgetting scores. The "Practice Exercises" section explains what exercises were generated and why. Teachers can see the review schedule and verify it matches pedagogical intuition. Fragility-based selection is transparent: "This concept was targeted because you learned it well but haven't practiced recently."

### Computational Tradeoffs
Decay computation is O(n) per concept with math.exp() and math.log1p() calls -- negligible overhead. Stability factors are simple arithmetic (no matrix operations). Generative Replay candidate selection is O(n log n) for sorting by fragility. Interleaving uses knowledge graph adjacency lookup (O(m) where m = edges). Total: sub-millisecond for typical learner states.

---

## 13. Competitive Differentiator: Adaptive Agent Routing

### Why Chosen
Standard multi-agent systems run all agents on every turn. This is wasteful when learner state is stable (low uncertainty) and expensive agents (e.g., debate) provide marginal value. Adaptive routing uses learner state uncertainty, drift signals, and a cost budget to select the minimal effective agent set per turn.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Always run all agents | High latency + cost with diminishing returns on stable states |
| Static routing rules | Brittle, can't adapt to learner-specific dynamics |
| LLM-based meta-reasoning | Adds another LLM call (cost), non-deterministic routing |

### Failure Modes
- **Under-routing**: Skipping a critical agent when uncertainty is underestimated → stale recommendations. Mitigation: periodic full-pipeline runs + uncertainty calibration.
- **Over-routing**: Cost budget too generous → no savings. Mitigation: budget tuning + telemetry.

### Trust / Explainability Impact
Routing decisions are logged with rationale, so HITL reviewers can see *why* certain agents were skipped (e.g., "debate skipped: uncertainty=0.12 < threshold=0.3").

### Computational Tradeoffs
Adds lightweight routing logic (~1ms) but can save 50-80% of agent execution time on stable-state turns. Net positive for cost-sensitive deployments.

---

## 14. Competitive Differentiator: Dynamic Agent Confidence Weighting

### Why Chosen
Agents self-report confidence, but self-assessment can be systematically biased. The `ConfidenceCalibrator` tracks actual prediction accuracy against outcomes and adjusts influence weights per agent, creating a **self-correcting ensemble** without retraining individual agents.

**Implementation details:**
- `CalibrationRecord` stores (reported_confidence, actual_accuracy, timestamp) per observation.
- `AgentCalibration` maintains a per-agent sliding window of records (default max 100).
- `trust_weight` is computed as the exponential-decay weighted average of `actual / reported` ratios, clamped to [0.3, 1.5].
- `calibrate(agent_id, raw_confidence)` multiplies raw confidence by trust_weight, clamped to [0, 1].
- **Cold start:** returns raw confidence (no adjustment) until `min_observations` (default 3) are reached.
- **Decay factor** (default 0.9): recent observations weigh more, creating an effective ~10-observation rolling window.
- The GPS Engine applies calibration to the final `NextBestAction.confidence` via `calibrate("engine", raw_confidence)`.

### Alternatives Considered
| Alternative | Why Rejected |
|---|---|
| Equal weighting | Ignores that some agents are better calibrated than others |
| Fixed weights | Can't adapt as learner context shifts or agents improve |
| Bayesian model averaging | Theoretically optimal but complex; too heavy for v1 |

### Failure Modes
- **Cold start**: No calibration data initially → fall back to equal weights.
- **Distribution shift**: Historical accuracy may not predict future accuracy. Mitigation: exponential decay on calibration history.

### Trust / Explainability Impact
Weight adjustments are logged and can be surfaced: "Planner confidence was reduced from 0.9 to 0.7 based on recent over-predictions." Increases system transparency.

### Computational Tradeoffs
Minimal: O(n) weight update per turn where n = number of active agents. Requires storing calibration history (~KB per agent per learner).

---

## 15. Azure Integration + Event-Driven Consolidation

### Why Chosen
<!-- Phase 9: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 9 -->

### Failure Modes
<!-- Phase 9 -->

### Trust / Explainability Impact
<!-- Phase 9 -->

### Computational Tradeoffs
<!-- Phase 9 -->
