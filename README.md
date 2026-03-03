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
6. [Frontend Web UI](#frontend-web-ui)
7. [Tier-1 Features](#tier-1-features)
8. [Evaluation Harness](#evaluation-harness)
9. [Azure Deployment Notes](#azure-deployment-notes)
10. [AI Pattern Justification](#ai-pattern-justification)
11. [Competitive Differentiators](#competitive-differentiators)
12. [Current System Capabilities](#current-system-capabilities)
13. [Known Limitations](#known-limitations)
14. [Roadmap / TODO](#roadmap--todo)

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

## Frontend Web UI

A production-ready web application built with **Next.js 15 + TypeScript + Tailwind CSS 4**, featuring user authentication, onboarding, data management, and full integration with the multi-agent backend.

### Quick Start (Frontend + Backend)

```bash
# Terminal 1: Start backend
pip install -e ".[dev]"
learning-nav serve          # http://127.0.0.1:8000 (Swagger at /docs)

# Terminal 2: Start frontend
cd frontend
npm install
cp .env.example .env.local  # Edit if backend is not on :8000
npm run dev                  # http://localhost:3000
```

### Authentication

The app includes a full auth system with bcrypt password hashing, JWT tokens in HttpOnly cookies, and protected routes:

- **Register** → Create account with email + password
- **Login** → Session cookie set automatically
- **Onboarding** → 4-step wizard (subjects, goals, schedule, confirmation)
- **Protected routes** → All app pages require authentication; unauthenticated users redirect to `/login`

### Frontend Pages

| Page | URL | Auth | Description |
|---|---|---|---|
| Login | `/login` | Public | Email/password sign-in |
| Register | `/register` | Public | Account creation with display name |
| Onboarding | `/onboarding` | Auth | 4-step wizard: subjects → goals → schedule → start |
| Dashboard | `/` | Auth | Student stats, next-best-action, agent activity, concept mastery |
| Session | `/session` | Auth | Log learning events, run AI analysis, view results timeline |
| Plan & Forecast | `/plan` | Auth | Kanban study plan, counterfactual simulation charts |
| Portfolio | `/portfolio` | Auth | Learning portfolio with search/filter + local entries |
| My Data | `/my-data` | Auth | Log events, upload files (CSV/JSON/PDF), manage learning data |
| Settings | `/settings` | Auth | Account info, learning profile, security details |
| Dev Tools | `/dev-tools` | Auth | Backend health, endpoint ping, agent diagnostics, request log |

### Backend Auth Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/auth/register` | POST | Create account |
| `/auth/login` | POST | Login (sets HttpOnly cookie) |
| `/auth/logout` | POST | Clear session |
| `/auth/me` | GET | Current user |
| `/profile` | GET/PUT | User learning profile |
| `/profile/onboarding/complete` | POST | Save onboarding data |
| `/events` | GET/POST | Learning events (per user) |
| `/uploads` | GET/POST | File uploads (per user, max 10 MB) |
| `/api/v1/system/agents/status` | GET | Agent diagnostics (all 16 agents + `implemented_agents` count) |
| `/api/v1/summary/weekly` | GET | Retrieve weekly AI summary for current user |
| `/api/v1/summary/weekly/generate` | POST | Generate a new weekly AI summary via Azure OpenAI |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | Backend API base URL |
| `LN_JWT_SECRET` | `dev-secret-...` | JWT signing secret (change in production) |
| `LN_AUTH_DB_PATH` | `data/users.db` | SQLite database path for user data |
| `LN_AZURE_OPENAI_ENDPOINT` | *(none)* | Azure OpenAI endpoint URL (for weekly summary) |
| `LN_AZURE_OPENAI_API_KEY` | *(none)* | Azure OpenAI API key |
| `LN_AZURE_OPENAI_DEPLOYMENT` | `gpt-4o` | Azure OpenAI deployment/model name |

See [frontend/README.md](frontend/README.md) for detailed architecture notes.

### Demo Walkthrough

1. Start both backend and frontend (see Quick Start above)
2. Open http://localhost:3000 → redirected to Login
3. Click "Create one" → Register with email/password
4. Complete the 4-step **Onboarding** wizard (subjects, goals, schedule)
5. Land on **Dashboard** → see stats and agent activity
6. Go to **Session** → submit a quiz result event → see AI recommendation
7. Go to **My Data** → log events manually, upload CSV/JSON files
8. Go to **Dev Tools** → see all 16 agents marked as "implemented", ping endpoints
9. Go to **Settings** → view your profile and account details

---

## Tier-1 Features

Five high-ROI features implemented end-to-end (backend models → engine logic → API → frontend UI):

### 1. Dynamic Agent Count

The dashboard now queries the backend for the real `implemented_agents` count instead of displaying a hardcoded number. The `/api/v1/system/agents/status` endpoint returns this count based on live source-code scanning via `agent_diagnostics.py`.

### 2. "Why This Recommendation?" Panel

Every `NextBestAction` now carries an `explainability` field containing:
- **Top factors** — ranked list of `ExplainabilityFactor` objects, each with `agent_id`, `agent_name`, `signal`, `evidence`, and optional `confidence`
- **Decision trace** — which agents ran, which were skipped, debate outcome, and maker-checker result

On the frontend, clicking the **"Why this?"** button on any recommendation expands an animated panel showing the top contributing factors with color-coded confidence badges and a collapsible "Behind the Scenes" section with the full decision trace.

### 3. Expected Impact Field

Each `NextBestAction` now includes an `expected_impact` field with:
- `mastery_gain_estimate` — projected mastery improvement (computed from BKT gaps)
- `confidence_gain_estimate` — projected confidence improvement
- `risk_reduction` — narrative description of risk mitigation
- `time_horizon_days` — timeframe for expected gains
- `assumptions` — list of assumptions underlying the estimates

The frontend renders an **Expected Impact** card with a mastery-gain progress arc, risk-reduction text, and an expandable assumptions tooltip.

### 4. Agent Activity Moment

When the AI pipeline is running after a user submits a learning event, the dashboard shows an animated loading state with:
- A pulsing "AI agents are analyzing..." message
- Animated chips showing each agent that participated in the pipeline run
- Smooth entry/exit animations via Framer Motion

### 5. Weekly AI Summary

A personalized weekly summary generated by **Azure OpenAI** (with graceful fallback when not configured):
- Backend service (`weekly_summary.py`) aggregates portfolio events, computes metrics (events logged, concepts touched, avg score, streak), and calls Azure OpenAI to produce a 150-word narrative summary
- Summaries are cached in SQLite (`user_weekly_summaries` table) to avoid repeated LLM calls
- Frontend shows a **Weekly Summary** card with the AI-generated narrative, key metrics, and a "Generate Summary" button
- When Azure OpenAI is not configured, the card shows an informational message explaining the feature requires Azure credentials

**Required environment variables for Weekly Summary:**

| Variable | Description |
|---|---|
| `LN_AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `LN_AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `LN_AZURE_OPENAI_DEPLOYMENT` | Deployment name (default: `gpt-4o`) |

---

## Evaluation Harness

The evaluation harness provides **scenario-driven quality assessment** of the full GPS Engine pipeline. It replays realistic learner journeys and checks output properties.

### Running Evaluations

```bash
# Run all 8 built-in scenarios
learning-nav evaluate

# Filter by tag
learning-nav evaluate --tag safety

# JSON output for CI integration
learning-nav evaluate --json

# With adaptive routing enabled
learning-nav evaluate --adaptive-routing
```

### Built-in Scenarios

| Scenario | Steps | Description | Tags |
|---|---|---|---|
| happy-path-progression | 3 | Steady quiz score improvement | core, regression |
| struggling-learner | 4 | Repeated failures + frustration signal | core, safety |
| inactivity-drift | 3 | Long gap then return with score drop | core, continual-learning |
| high-achiever-acceleration | 3 | Consistently excellent scores | core |
| motivation-crisis | 3 | Motivation collapse requiring gentle recs | core, safety |
| prerequisite-chain | 3 | Multi-concept dependency enforcement | core, planning |
| exam-deadline-pressure | 3 | Near-deadline high-stress cramming | core, debate |
| cold-start | 1 | Brand-new learner, zero history | core, regression |

### Metrics Computed

- **Recommendation quality**: confidence calibration, gain plausibility, action-type coverage
- **Safety**: risk flag presence/absence, overload detection
- **Pipeline coverage**: agent participation per step (active vs. skipped)
- **Latency**: wall-clock time per pipeline run
- **Consistency**: confidence variance across repeated events

### Custom Scenarios

```python
from learning_navigator.evaluation.scenarios import EvalScenario, ScenarioStep, StepExpectation
from learning_navigator.contracts.events import LearnerEventType

custom = EvalScenario(
    name="my-scenario",
    description="Custom evaluation",
    learner_id="my-learner",
    steps=[
        ScenarioStep(
            event_type=LearnerEventType.QUIZ_RESULT,
            concept_id="my-concept",
            data={"score": 0.7, "max_score": 1.0},
            expectation=StepExpectation(min_confidence=0.3),
        ),
    ],
)
```

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

### Phase 10 — Evaluation Harness + Documentation Completion ✅
- [x] **EvalScenario / ScenarioStep / StepExpectation** — Dataclass-based scenario definitions with typed event sequences and declarative expectation constraints (confidence bounds, action types, risk keys, pipeline coverage)
- [x] **8 built-in scenarios** — Happy-path, struggling learner, inactivity drift, high achiever, motivation crisis, prerequisite chain, exam deadline, cold start
- [x] **MetricSuite / QualityMetrics** — Per-step and aggregate metrics: confidence calibration, gain plausibility, pipeline coverage, latency tracking, consistency
- [x] **EvaluationHarness** — Scenario-driven integration runner: isolated engine per scenario, sequential event feeding, wall-clock latency, structured reporting
- [x] **EvaluationResult** — Human-readable `summary()` + JSON-serialisable `to_dict()` for CI integration
- [x] **CLI `evaluate` command** — `learning-nav evaluate [--tag TAG] [--json] [--adaptive-routing]`
- [x] **Pattern justification** — Section 16: Evaluation Harness design rationale, failure modes, tradeoffs
- [x] 463+ passing tests

### Phase 11 — Tier-1 Features (End-to-End) ✅
- [x] **Dynamic Agent Count** — Dashboard sources real `implemented_agents` count from backend diagnostics instead of hardcoded value
- [x] **Explainability Panel** — `NextBestAction.explainability` with top factors + decision trace; frontend "Why this?" expandable panel
- [x] **Expected Impact** — `NextBestAction.expected_impact` with mastery gain estimate, risk reduction, assumptions; frontend impact card
- [x] **Agent Activity Moment** — Animated loading state with agent chips during pipeline execution
- [x] **Weekly AI Summary** — Azure OpenAI-powered weekly narrative summaries with SQLite caching, graceful fallback
- [x] **New User Welcome** — Authenticated users with no learner state see a friendly welcome banner instead of misleading "Sample UI Data" notice
- [x] 529 passing tests (33 new tier-1 feature tests)

---

## Known Limitations

- Agents are rule-based / deterministic (by design for v1 local-first); optional Azure OpenAI integration for weekly summary only
- EventBus is in-process only (no distributed messaging)
- Azure adapters require SDK + credentials to function (degrade gracefully to no-ops otherwise)
- Azure Functions consolidation is best-effort (no distributed locking)
- Evaluation harness scenarios are synthetic — real learner data replay planned for future phase

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
- [x] **Phase 10:** Evaluation harness + documentation completion
- [x] **Phase 11:** Tier-1 features — explainability, expected impact, weekly summary, agent activity, dynamic agent count (529 tests)
