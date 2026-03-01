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
<!-- Phase 2: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 2 -->

### Failure Modes
<!-- Phase 2 -->

### Trust / Explainability Impact
<!-- Phase 2 -->

### Computational Tradeoffs
<!-- Phase 2 -->

---

## 3. Core Agents

### Why Chosen
<!-- Phase 3: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 3 -->

### Failure Modes
<!-- Phase 3 -->

### Trust / Explainability Impact
<!-- Phase 3 -->

### Computational Tradeoffs
<!-- Phase 3 -->

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
<!-- Phase 3: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 3 -->

### Failure Modes
<!-- Phase 3 -->

### Trust / Explainability Impact
<!-- Phase 3 -->

### Computational Tradeoffs
<!-- Phase 3 -->

---

## 11. Human-in-the-Loop Hooks

### Why Chosen
<!-- Phase 3: Fill in when implemented -->

### Alternatives Considered
<!-- Phase 3 -->

### Failure Modes
<!-- Phase 3 -->

### Trust / Explainability Impact
<!-- Phase 3 -->

### Computational Tradeoffs
<!-- Phase 3 -->

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
