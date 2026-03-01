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
│  │               │       ▼ Arbiter ▼             │        │    │
│  │               └──────────────────────────────┘        │    │
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
| **Diagnoser** | 🔲 Planned | Assess learner state from events | 3 |
| **Drift Detector** | 🔲 Planned | Detect learning drift / off-track signals | 3 |
| **Motivation Agent** | 🔲 Planned | Infer motivation level + trend | 3 |
| **Planner Agent** | 🔲 Planned | Generate study plan recommendations | 3 |
| **Evaluator Agent** | 🔲 Planned | Evaluate plan quality + learning outcomes | 3 |
| **Skill State Agent** | 🔲 Planned | BKT mastery tracking + knowledge graph | 4 |
| **Behavior Agent** | 🔲 Planned | Pattern anomaly detection | 4 |
| **Time Optimizer** | 🔲 Planned | Constrained time allocation optimization | 4 |
| **Reflection Agent** | 🔲 Planned | Explainable narrative generation | 4 |
| **Decay Agent** | 🔲 Planned | Ebbinghaus forgetting + refresh scheduling | 5 |
| **Generative Replay** | 🔲 Planned | Re-entry stories + memory consolidation | 5 |
| **Mastery Maximizer** | 🔲 Planned | Debate: maximize deep understanding | 6 |
| **Exam Strategist** | 🔲 Planned | Debate: maximize exam performance | 6 |
| **Burnout Minimizer** | 🔲 Planned | Debate: minimize overload risk | 6 |
| **Maker–Checker** | 🔲 Planned | Validate recommendations + adversarial audit | 3 |

---

## Setup Instructions

### Prerequisites

- Python 3.11+
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

- **Blob Storage** → `MemoryStore` interface (portfolio logs, replay artifacts)
- **Azure AI Search** → `RetrievalIndex` interface (RAG vector store)
- **Azure Functions** → Event-driven memory consolidation pipeline

All Azure code is isolated behind interfaces in `src/learning_navigator/storage/` with local fallbacks. See `infra/azure/` for deployment scaffolding (Phase 9).

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

*Implementation: Phase 8. Status: 🔲 Planned.*

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

---

## Known Limitations

- No actual LLM integration yet — agents are rule-based / stubbed (by design for v1 local-first)
- EventBus is in-process only (no distributed messaging)
- No persistence layer yet (Phase 2)
- No FastAPI server yet (Phase 3)
- RAG subsystem not yet implemented (Phase 7)

---

## Roadmap / TODO

- [x] **Phase 1:** Repo bootstrap + architecture skeleton
- [ ] **Phase 2:** Learner state core + storage abstractions
- [ ] **Phase 3:** Core agents v1 (Diagnoser, Drift, Motivation, Planner, Evaluator, Maker-Checker)
- [ ] **Phase 4:** Specialized agents (Skill State, Behavior, Time Optimizer, Reflection)
- [ ] **Phase 5:** Continual learning (Decay Agent, Generative Replay)
- [ ] **Phase 6:** Strategic debate system
- [ ] **Phase 7:** Learner-aware RAG with grounding
- [ ] **Phase 8:** Competitive differentiators (Adaptive Routing, Confidence Weighting)
- [ ] **Phase 9:** Azure deployment scaffolding
- [ ] **Phase 10:** Evaluation harness + documentation completion
