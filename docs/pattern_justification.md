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
<!-- Phase 6: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 6 -->

### Failure Modes
<!-- Phase 6 -->

### Trust / Explainability Impact
<!-- Phase 6 -->

### Computational Tradeoffs
<!-- Phase 6 -->

---

## 5. Skill State (BKT + Knowledge Graph)

### Why Chosen
<!-- Phase 4: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 4 -->

### Failure Modes
<!-- Phase 4 -->

### Trust / Explainability Impact
<!-- Phase 4 -->

### Computational Tradeoffs
<!-- Phase 4 -->

---

## 6. Behavior Anomaly Detection

### Why Chosen
<!-- Phase 4: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 4 -->

### Failure Modes
<!-- Phase 4 -->

### Trust / Explainability Impact
<!-- Phase 4 -->

### Computational Tradeoffs
<!-- Phase 4 -->

---

## 7. Time Optimization

### Why Chosen
<!-- Phase 4: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 4 -->

### Failure Modes
<!-- Phase 4 -->

### Trust / Explainability Impact
<!-- Phase 4 -->

### Computational Tradeoffs
<!-- Phase 4 -->

---

## 8. Reflection Narrative

### Why Chosen
<!-- Phase 4: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 4 -->

### Failure Modes
<!-- Phase 4 -->

### Trust / Explainability Impact
<!-- Phase 4 -->

### Computational Tradeoffs
<!-- Phase 4 -->

---

## 9. RAG Subsystem

### Why Chosen
<!-- Phase 7: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 7 -->

### Failure Modes
<!-- Phase 7 -->

### Trust / Explainability Impact
<!-- Phase 7 -->

### Computational Tradeoffs
<!-- Phase 7 -->

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
<!-- Phase 5: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 5 -->

### Failure Modes
<!-- Phase 5 -->

### Trust / Explainability Impact
<!-- Phase 5 -->

### Computational Tradeoffs
<!-- Phase 5 -->

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
<!-- Phase 8: Fill in fully when implemented -->
Agents self-report confidence, but self-assessment can be systematically biased. Dynamic weighting tracks actual prediction accuracy against outcomes and adjusts influence weights, creating a self-correcting ensemble without retraining individual agents.

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
