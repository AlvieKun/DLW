# Learning Navigator AI — Multi-Agent Learning GPS

> An adaptive, explainable, multi-agent system that acts as a **GPS for learning**: continuously diagnosing learner state, predicting drift and forgetting, orchestrating strategic debate between planning philosophies, and producing grounded next-best-action recommendations with confidence scores and risk assessments.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)]()

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Agent Catalog](#agent-catalog)
4. [Setup Instructions](#setup-instructions)
5. [Local Development Guide](#local-development-guide)
6. [Azure Deployment Notes](#azure-deployment-notes)
7. [AI Pattern Justification](#ai-pattern-justification)
8. [Competitive Differentiators](#competitive-differentiators)
9. [Current System Capabilities](#current-system-capabilities)
10. [Known Limitations](#known-limitations)
11. [Roadmap / TODO](#roadmap--todo)

---

## Project Overview

Learning Navigator is a **production-grade multi-agent AI system** designed to guide individual learners through personalized study plans. Unlike single-agent tutoring systems, it separates concerns across specialized agents — each with explicit input/output contracts, confidence scoring, and telemetry hooks — orchestrated by a central **Learning GPS Engine**.

### Why multi-agent?

| Concern | Single-Agent | Learning Navigator |
|---|---|---|
| Diagnosis vs Planning | Conflated | Separate agents with clear contracts |
| Strategic tradeoffs | Single policy | Three-way debate (mastery / exam / burnout) |
| Forgetting modelling | Ad-hoc or absent | Dedicated Decay Agent + Generative Replay |
| Explainability | Black box | Reflection Agent + citation grounding |
| Extensibility | Monolithic rewrite | Register a new agent, subscribe to events |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Learning GPS Engine                           │
│                  (Orchestrator + Router)                         │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐    │
│  │ Adaptive  │  │   EventBus   │  │  Cost-Aware Inference  │    │
│  │  Router   │──│  (Pub/Sub)   │──│      Router            │    │
│  │  [D1]     │  │              │  │      [D4]              │    │
│  └──────────┘  └──────┬───────┘  └────────────────────────┘    │
│                       │                                         │
├───────────────────────┼─────────────────────────────────────────┤
│                       ▼                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Agent Layer (Pub/Sub Consumers)             │    │
│  │                                                         │    │
│  │  ┌──────────┐ ┌───────────┐ ┌────────────┐            │    │
│  │  │Diagnoser │ │  Drift    │ │ Motivation │            │    │
│  │  │  Agent   │ │ Detector  │ │   Agent    │            │    │
│  │  └──────────┘ └───────────┘ └────────────┘            │    │
│  │  ┌──────────┐ ┌───────────┐ ┌────────────┐            │    │
│  │  │ Planner  │ │ Evaluator │ │  Decay     │            │    │
│  │  │  Agent   │ │   Agent   │ │  Agent     │            │    │
│  │  └──────────┘ └───────────┘ └────────────┘            │    │
│  │  ┌──────────┐ ┌───────────┐ ┌────────────┐            │    │
│  │  │  Skill   │ │ Behavior  │ │   Time     │            │    │
│  │  │  State   │ │  Agent    │ │ Optimizer  │            │    │
│  │  └──────────┘ └───────────┘ └────────────┘            │    │
│  │  ┌──────────┐ ┌──────────────────────────────┐        │    │
│  │  │Reflection│ │  Strategic Debate System      │        │    │
│  │  │  Agent   │ │  ┌────────┐┌─────┐┌────────┐ │        │    │
│  │  │          │ │  │Mastery ││Exam ││Burnout │ │        │    │
│  │  │          │ │  │Maximizr││Strat││Minimzr │ │        │    │
│  │  └──────────┘ │  └────────┘└─────┘└────────┘ │        │    │
│  │  ┌──────────┐ │       ▼ Arbiter ▼             │        │    │
│  │  │RAG Agent │ └──────────────────────────────┘        │    │
│  │  └──────────┘                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐     │
│  │ RAG Subsystem│  │ Maker–Checker │  │  HITL Hooks      │     │
│  │ (Grounded)   │  │  (Validator)  │  │  (Overrides)     │     │
│  └──────────────┘  └───────────────┘  └──────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐     │
│  │MemoryStore   │  │ PortfolioLog  │  │ RetrievalIndex   │     │
│  │(Local/Azure) │  │ (Local/Azure) │  │ (TF-IDF/AzSearch)│     │
│  └──────────────┘  └───────────────┘  └──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

**Key design properties:**
- **Loose coupling** via EventBus (pub/sub with typed envelopes)
- **Explicit contracts** — every message is a Pydantic-validated `MessageEnvelope`
- **Observability** — structured logging, trace/span IDs, telemetry hooks
- **Azure-ready, local-first** — all storage/search behind interfaces with local fallbacks
- **Extensible** — add agents by implementing `BaseAgent` and subscribing to event types

---

## Agent Catalog

| Agent | Status | Capabilities | Phase |
|---|---|---|---|
| **Diagnoser** | ✅ Done | BKT updates from quiz/time events, spacing history, weak-concept flagging | 3 |
| **Drift Detector** | ✅ Done | 5 drift types: inactivity, plateau, easy-mismatch, disengagement, priority-neglect | 3 |
| **Motivation Agent** | ✅ Done | 4-signal motivation inference (frequency, consistency, mastery trend, sentiment) | 3 |
| **Planner Agent** | ✅ Done | Priority-ranked study plans with motivation-adaptive session lengths | 3 |
| **Evaluator Agent** | ✅ Done | 6-check plan quality: prereq violation, overload, cognitive load, empty plan, time, priority | 3 |
| **Maker–Checker** | ✅ Done | Maker→Checker loop with configurable rounds and min quality score | 3 |
| **HITL Hooks** | ✅ Done | Pluggable human-in-the-loop review with auto-approve threshold | 3 |
| **Learning GPS Engine** | ✅ Done | Full pipeline: Event → Diagnose → Drift → Motivate → SkillState → Behavior → Decay → Replay → TimeOpt → Plan → Check → Debate → RAG → HITL → Reflect → Action | 3-7 |
| **Skill State Agent** | ✅ Done | Knowledge graph analysis, prerequisite-gap detection, concept-readiness scoring, cluster analysis, learning-order suggestions | 4 |
| **Behavior Agent** | ✅ Done | 5 anomaly types: cramming, rapid guessing, concept avoidance, irregular sessions, late-night study | 4 |
| **Time Optimizer** | ✅ Done | Urgency x importance scoring, proportional time allocation, deadline analysis, motivation-adaptive session lengths | 4 |
| **Reflection Agent** | ✅ Done | 11-section narrative generation: progress, session, motivation, drift, behavior, decay, exercises, plan, knowledge graph, debate, RAG grounding, outlook | 4-7 |
| **Decay Agent** | ✅ Done | Ebbinghaus forgetting curves, memory stability estimation, spaced-repetition review scheduling, at-risk concept flagging | 5 |
| **Generative Replay** | ✅ Done | Calibrated replay exercises, retrieval practice, interleaved concept sets, difficulty calibration | 5 |
| **Mastery Maximizer** | ✅ Done | Debate: prerequisite violations, depth checks, forgetting-gap detection, topic-count analysis | 6 |
| **Exam Strategist** | ✅ Done | Debate: priority-concept coverage, deadline pressure, maintenance ratio, practice-test suggestions | 6 |
| **Burnout Minimizer** | ✅ Done | Debate: session-length caps, cognitive overload, new-content ratio, stress signals, motivation trend | 6 |
| **Debate Arbitrator** | ✅ Done | Contextual perspective weighting (deadline/motivation/anomaly-aware), objection scoring, amendment acceptance | 6 |
| **RAG Agent** | ✅ Done | Learner-aware retrieval queries, citation grounding, deduplication, mastery/action/prerequisite-aware search | 7 |
| **Adaptive Router** | ✅ Done | Cost-aware uncertainty-driven agent selection, greedy knapsack, core-agent guarantee, value-density ranking, contextual need scoring | 8 |
| **Confidence Calibrator** | ✅ Done | Exponential-decay trust weighting, per-agent outcome tracking, cold-start passthrough, calibrated confidence output | 8 |

---

## Setup Instructions

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install

```bash
# Clone the repository
git clone <repo-url>
cd DLW

# Create virtual environment and install
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Run Lint

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

---

## Local Development Guide

```bash
# Run the CLI
learning-nav --version
learning-nav run --log-format console

# Run tests with coverage
pytest --cov=learning_navigator

# Type checking
mypy src/
```

### Environment Variables

All settings can be overridden via environment variables prefixed with `LN_`:

| Variable | Default | Description |
|---|---|---|
| `LN_ENVIRONMENT` | `local` | Runtime environment |
| `LN_DEBUG` | `false` | Enable debug mode |
| `LN_LOG_LEVEL` | `INFO` | Python log level |
| `LN_LOG_FORMAT` | `json` | `json` or `console` |
| `LN_STORAGE_BACKEND` | `local_json` | `local_json`, `local_sqlite`, `azure_blob` |
| `LN_SEARCH_BACKEND` | `local_tfidf` | `local_tfidf`, `azure_ai_search` |
| `LN_DEBATE_ENABLED` | `true` | Enable strategic debate system |
| `LN_ADAPTIVE_ROUTING_ENABLED` | `true` | Enable adaptive agent routing |

---

## Azure Deployment Notes

The system is designed **local-first with Azure-ready abstractions**:

- **Blob Storage** → `AzureBlobMemoryStore` + `AzureBlobPortfolioLogger` (states & portfolio in blob containers)
- **Azure AI Search** → `AzureAISearchIndex` (full-text retrieval with auto-schema creation)
- **Azure Functions** → HTTP triggers (`ProcessEvent`, `Health`) + timer trigger (`MemoryConsolidation` every 6h)
- **FastAPI Server** → Full REST API with 7 endpoints (`/health`, `/api/v1/events`, learner state CRUD, portfolio, calibration)

All Azure code is isolated behind interfaces in `src/learning_navigator/storage/` with local fallbacks.
When the Azure SDK is not installed or credentials are empty, adapters degrade gracefully to no-op stubs.

### Quick Start (Local)

```bash
# Install with Azure extras
pip install -e ".[azure]"

# Run the FastAPI server
learning-nav run --host 0.0.0.0 --port 8000

# Or via uvicorn directly
uvicorn learning_navigator.api.server:app --reload
```

### Azure Deployment

See `infra/azure/` for full deployment scaffolding:
- `main.bicep` — Infrastructure-as-Code (Function App, Storage, AI Search)
- `deploy.ps1` — One-command deployment script
- `Dockerfile` — Container deployment option for FastAPI
- `host.json` / `local.settings.json.template` — Azure Functions config

---

## AI Pattern Justification

Every architectural decision is justified with:
- **Why chosen** — rationale and evidence
- **Alternatives considered** — what we evaluated and rejected
- **Failure modes** — what can go wrong and mitigations
- **Trust/explainability impact** — how it affects user trust
- **Computational tradeoffs** — cost vs benefit

📄 **Full report:** [docs/pattern_justification.md](docs/pattern_justification.md)

---

## Competitive Differentiators

Beyond standard RAG, multi-agent pipelines, maker–checker, and HITL:

### D1: Adaptive Agent Routing
Uses learner state uncertainty + cost budget to dynamically select which agents run per turn. Low-uncertainty states skip expensive debate; high-drift states prioritize the drift pipeline. **Result:** lower latency and cost for routine turns, full power when needed.

### D2: Dynamic Agent Confidence Weighting
Each agent self-reports confidence with calibration metadata. The orchestrator tracks historical accuracy and weights agent contributions dynamically. Over-confident agents are dampened; well-calibrated agents gain influence. **Result:** system improves its own reliability over time without retraining.

*Implementation: Phase 8. Status: ✅ Done.*

---

## Current System Capabilities

### Phase 1 — Repository Bootstrap ✅
- [x] Project scaffold with modular package structure
- [x] Pydantic message contracts (`MessageEnvelope`, `LearnerEvent`, `NextBestAction`)
- [x] EventBus interface + in-memory implementation with observability
- [x] Base agent interface with capability metadata + confidence scoring
- [x] Configuration system (env vars + typed settings)
- [x] Structured logging (JSON + console modes)
- [x] CLI entry point
- [x] Test suite (contracts, event bus, config, agent interface)

### Phase 2 — Learner State Core + Storage ✅
- [x] `LearnerState` domain model with full uncertainty tracking
- [x] `BKTParams` — Bayesian Knowledge Tracing with posterior update + entropy-based uncertainty
- [x] `ConceptState` with mastery, forgetting score, difficulty, spacing history
- [x] Knowledge graph (adjacency list: prerequisite, corequisite, extends, related edges)
- [x] Motivation state with level, score, trend, confidence
- [x] Drift signals + behavioral anomaly flags
- [x] Time budget constraints (weekly hours, session length, deadlines, priorities)
- [x] `MemoryStore` interface + `LocalJsonMemoryStore` (JSON-on-disk)
- [x] `PortfolioLogger` interface + `LocalJsonPortfolioLogger` (JSONL append-only)
- [x] `RetrievalIndex` interface (RAG store abstraction)
- [x] Azure Blob Storage stub adapters (`AzureBlobMemoryStore`, `AzureBlobPortfolioLogger`)
- [x] Storage factory functions with config-driven backend selection
- [x] 78 passing tests

### Phase 3 — Core Agents v1 + Orchestrator ✅
- [x] **DiagnoserAgent** — BKT updates from quiz/time-on-task events, spacing history, weak-concept flags
- [x] **DriftDetectorAgent** — 5 drift types: inactivity, mastery plateau, difficulty mismatch, disengagement, priority neglect
- [x] **MotivationAgent** — 4-signal weighted motivation inference with level/score/trend/confidence
- [x] **PlannerAgent** — Priority-ranked recommendations with motivation-adaptive session lengths
- [x] **EvaluatorAgent** — 6-check plan quality validation (prerequisite, overload, cognitive, empty, time, priority)
- [x] **Maker-Checker subsystem** — Iterative make→check loop with configurable rounds and quality threshold
- [x] **HITL hooks** — Pluggable human-in-the-loop review with auto-approve threshold and audit log
- [x] **Learning GPS Engine** — Full pipeline orchestrator: Event → Diagnose → Drift → Motivate → Plan+Check → HITL → NextBestAction
- [x] State persistence across events with automatic learner creation
- [x] Portfolio audit logging for every recommendation
- [x] EventBus telemetry integration
- [x] Debug trace in NextBestAction output
- [x] 132 passing tests

### Phase 4 — Specialized Agents ✅
- [x] **SkillStateAgent** — Knowledge graph analysis: prerequisite-gap detection, concept-readiness scoring, cluster analysis, learning-order suggestions
- [x] **BehaviorAgent** — 5 anomaly types: cramming, rapid guessing, concept avoidance, irregular sessions, late-night study
- [x] **TimeOptimizerAgent** — Urgency x importance scoring, proportional time allocation (max 6 concepts/session), deadline analysis, motivation-adaptive session lengths
- [x] **ReflectionAgent** — 8-section narrative generation from full pipeline context with citation tracking
- [x] Integrated all 4 agents into GPS Engine pipeline (9-agent pipeline + maker-checker + HITL)
- [x] 8 new MessageType values for Phase 4 agent routing
- [x] Behavioral anomalies applied to LearnerState
- [x] 172 passing tests

### Phase 5 — Continual Learning ✅
- [x] **DecayAgent** — Ebbinghaus exponential decay with stability factors (repetition, spacing quality, difficulty, mastery)
- [x] **GenerativeReplayAgent** — Calibrated replay exercises with retrieval practice, interleaving, and difficulty calibration
- [x] Decay Agent computes per-concept forgetting scores, memory stability, review schedules, and at-risk flagging
- [x] Generative Replay selects fragile concepts (high mastery + high forgetting), generates typed exercises, builds interleaved sets
- [x] Engine integration: 11-agent pipeline with decay → replay → time optimization sequencing
- [x] Reflection Agent updated with Memory & Retention and Practice Exercises sections
- [x] Forgetting scores applied to LearnerState concept states via engine
- [x] 4 new MessageType values (DECAY_REQUEST, DECAY_REPORT, REPLAY_REQUEST, REPLAY_ARTIFACT)
- [x] 202 passing tests

### Phase 6 — Strategic Debate System ✅
- [x] **MasteryMaximizer** — Advocate for deep understanding: prerequisite violation detection, depth checks (min session time), forgetting-gap detection, topic-count analysis
- [x] **ExamStrategist** — Advocate for exam performance: priority-concept coverage enforcement, deadline-pressure analysis, maintenance-ratio limits, practice-test suggestions
- [x] **BurnoutMinimizer** — Advocate for sustainable engagement: motivation-based session caps, cognitive overload detection (hard-concept limits), new-content ratio, stress signal awareness, motivation trend analysis
- [x] **DebateArbitrator** — Resolves strategic disagreements: contextual perspective weighting (deadline→exam, low motivation→burnout, cramming→burnout), normalised weights, severity-based objection filtering, amendment acceptance
- [x] **DebateEngine subsystem** — Full debate orchestration: fan-out to 3 advocates → collect critiques → alignment check → arbitrate → DebateResult; configurable rounds, early-exit on alignment
- [x] GPS Engine integration: debate step between Maker-Checker and HITL (15-agent pipeline)
- [x] Reflection Agent updated with Strategic Debate section (10 narrative sections total)
- [x] 248 passing tests

### Phase 7 — Learner-Aware RAG with Grounding ✅
- [x] **LocalTfidfIndex** — Full TF-IDF retrieval engine: tokenisation, IDF computation, cosine similarity ranking, metadata filtering, JSON disk persistence
- [x] **AzureAISearchIndex** — Graceful Azure AI Search stub (no-op when SDK not installed, ready for Phase 9)
- [x] **RAGAgent** — Learner-aware retrieval: mastery-level query framing, action-type modifiers, difficulty awareness, prerequisite enrichment, deduplication, min-score filtering
- [x] `create_retrieval_index()` factory with config-driven backend selection (local TF-IDF / Azure AI Search)
- [x] GPS Engine integration: RAG step post-debate, citations flow into `NextBestAction.citations`
- [x] Reflection Agent updated with Supporting Material section (11 sections total)
- [x] 16-agent pipeline: Event → Diagnose → Drift → Motivate → SkillState → Behavior → Decay → Replay → TimeOpt → Plan+Check → Debate → RAG → HITL → Reflect → Action
- [x] 290 passing tests

### Phase 8 — Competitive Differentiators ✅
- [x] **AdaptiveRouter** — Cost-aware, uncertainty-driven agent selection: greedy knapsack over cost budgets, core-agent guarantee (diagnoser + motivation always run), value-density ranking, periodic full-pipeline refresh, contextual need scoring (drift, decay, anomalies)
- [x] **ConfidenceCalibrator** — Exponential-decay weighted outcome tracking per agent, trust_weight computation (actual/reported ratio), cold-start passthrough, clamped [0.3, 1.5] trust range, per-agent independence
- [x] GPS Engine integration: routing step after state load, conditional agent execution via `_should_run()` guards, routing decisions in debug trace, confidence calibration on final NBA
- [x] Pipeline steps record `skipped: true` for agents bypassed by routing
- [x] Config: `adaptive_routing_enabled`, `cost_budget_per_turn` settings
- [x] Engine exports: `AdaptiveRouter`, `RoutingDecision`, `ConfidenceCalibrator`, `CalibrationRecord`
- [x] 354 passing tests

### Phase 9 — Azure Deployment Scaffolding ✅
- [x] **AzureBlobMemoryStore** — Full Azure Blob Storage adapter: container auto-creation, `states/{learner_id}.json` layout, graceful SDK-absent degradation
- [x] **AzureBlobPortfolioLogger** — Append-only JSONL portfolio in Azure Blob: download-append-upload pattern, entry filtering, count support
- [x] **AzureAISearchIndex** — Full Azure AI Search adapter: auto-index creation with `SearchableField`/`SimpleField` schema, OData filter building, JSON-encoded metadata
- [x] **FastAPI REST Server** — 7 endpoints: health, process event (→ NextBestAction), learner state CRUD, portfolio queries, calibration telemetry, learner listing
- [x] **Azure Functions Scaffold** — HTTP triggers (`ProcessEvent`, `Health`) + timer trigger (`MemoryConsolidation` every 6h), lazy engine init, graceful degradation
- [x] **CLI `run` command** — Launches uvicorn server with configurable host/port/reload
- [x] **Infrastructure-as-Code** — Bicep template, deployment script, Dockerfile, host.json, local.settings template
- [x] All storage adapters degrade to no-op stubs when SDK not installed or credentials empty
- [x] Config-driven backend selection: `LN_STORAGE_BACKEND=azure_blob`, `LN_SEARCH_BACKEND=azure_ai_search`
- [x] 400 passing tests

---

## Known Limitations

- No actual LLM integration yet — agents are rule-based / deterministic (by design for v1 local-first)
- EventBus is in-process only (no distributed messaging)
- Azure adapters require SDK + credentials to function (degrade gracefully to no-ops otherwise)
- Azure Functions consolidation is best-effort (no distributed locking)

---

## Roadmap / TODO

- [x] **Phase 1:** Repo bootstrap + architecture skeleton
- [x] **Phase 2:** Learner state core + storage abstractions
- [x] **Phase 3:** Core agents v1 + Maker-Checker + HITL + GPS Engine orchestrator
- [x] **Phase 4:** Specialized agents (Skill State, Behavior, Time Optimizer, Reflection)
- [x] **Phase 5:** Continual learning (Decay Agent, Generative Replay)
- [x] **Phase 6:** Strategic debate system
- [x] **Phase 7:** Learner-aware RAG with grounding
- [x] **Phase 8:** Competitive differentiators (Adaptive Routing, Confidence Weighting)
- [x] **Phase 9:** Azure deployment scaffolding
- [ ] **Phase 10:** Evaluation harness + documentation completion
