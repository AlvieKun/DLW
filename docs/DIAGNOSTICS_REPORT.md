# Learning Navigator AI — Comprehensive Diagnostics Report

> **Generated**: 2026-03-02 (machine-assisted audit)  
> **Scope**: Full-stack application state — backend, frontend, infra, tests  
> **Evidence rule**: Every claim below is backed by file path + symbol name, endpoint + handler, or runtime result.

---

## Table of Contents

- [A. Repository Overview](#a-repository-overview)
- [B. Backend API Reality Check](#b-backend-api-reality-check)
- [C. Agent & Orchestration Diagnostics](#c-agent--orchestration-diagnostics)
- [D. Data / Memory / RAG](#d-data--memory--rag)
- [E. Evaluation / Maker-Checker / Auditor](#e-evaluation--maker-checker--auditor)
- [F. Azure / Cloud Integration](#f-azure--cloud-integration)
- [G. Frontend](#g-frontend)
- [H. Tests & Quality](#h-tests--quality)
- [I. Truth Table Summary](#i-truth-table-summary)

---

## A. Repository Overview

### File inventory

| Layer      | Location                        | Files | Key technology                 |
|------------|---------------------------------|------:|--------------------------------|
| Backend    | `src/learning_navigator/`       |    51 | Python 3.10, FastAPI, Pydantic v2, structlog |
| Frontend   | `frontend/src/`                 |    21 | Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Framer Motion |
| Tests      | `tests/`                        |    16 | pytest, pytest-asyncio          |
| Infra      | `infra/azure/`                  |     7 | Dockerfile, Bicep IaC, PowerShell |
| Docs       | `docs/`                         |     2 | Markdown                        |
| Data (dev) | `data/`                         |   ~12 | JSON states, JSONL portfolios, SQLite users.db |

### Package structure (backend)

```
src/learning_navigator/
├── agents/          15 agent modules + base.py + __init__.py
├── api/              6 modules (server, auth, auth_db, auth_routes, agent_diagnostics, azure_functions)
├── contracts/        3 modules (events, learner_state, messages) + __init__.py
├── engine/           7 modules (gps_engine, adaptive_router, confidence_calibrator, debate, event_bus, hitl, maker_checker)
├── evaluation/       3 modules (harness, metrics, scenarios) + __init__.py
├── infra/            2 modules (config, logging) + __init__.py
├── rag/              1 module  (__init__.py — thin, delegates to storage/local_tfidf)
├── storage/          5 modules (interfaces, local_store, local_tfidf, azure_store, azure_search) + __init__.py
├── __init__.py       version = "0.1.0"
└── cli.py            Typer CLI entrypoint
```

### Dependencies (`pyproject.toml`)

| Category | Packages |
|----------|----------|
| Core     | `pydantic>=2.5`, `pydantic-settings>=2.1`, `fastapi>=0.109`, `uvicorn[standard]>=0.25`, `typer>=0.9`, `structlog>=23.2`, `rich>=13.0` |
| Auth (runtime) | `bcrypt`, `PyJWT`, `aiosqlite` — **NOT declared in pyproject.toml** |
| Dev      | `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `httpx` |
| Azure    | `azure-storage-blob`, `azure-search-documents`, `azure-functions`, `azure-identity` |

> **Issue**: `bcrypt`, `PyJWT`, and `aiosqlite` are imported by `api/auth.py` and `api/auth_db.py` but are **missing from pyproject.toml `[project.dependencies]`**. This causes 13 test failures (see Section H). Status: **Broken (dependency declaration)**.

---

## B. Backend API Reality Check

### Server entrypoint

- **File**: `src/learning_navigator/api/server.py` (323 lines)
- **App factory**: `FastAPI(title="Learning Navigator AI", lifespan=lifespan)` at module level
- **Run command**: `uvicorn learning_navigator.api.server:app --reload`

### Lifespan initialization sequence (`server.py` `lifespan()`, lines 70–100)

1. Load `Settings` from env / `.env`
2. Create `MemoryStore` (local JSON or Azure Blob)
3. Create `PortfolioLogger` (local JSONL or Azure Blob)
4. Create `InMemoryEventBus`
5. Create `RetrievalIndex` (local TF-IDF or Azure AI Search)
6. Instantiate `LearningGPSEngine` with all above
7. Call `init_auth_db()` → creates SQLite tables

### Endpoint inventory

| Method | Path | Handler | Auth | Status |
|--------|------|---------|------|--------|
| GET | `/` | `root()` → server.py | None | **Implemented** — redirects to `/docs` |
| GET | `/health` | `health()` → server.py | None | **Implemented** — returns `{status, version, environment}` |
| POST | `/api/v1/events` | `process_event()` → server.py | Optional (`get_optional_user`) | **Implemented** — full pipeline run → `NextBestAction` |
| GET | `/api/v1/learners` | `list_learners()` → server.py | None | **Implemented** — returns all learner IDs from MemoryStore |
| GET | `/api/v1/learners/{id}/state` | `get_learner_state()` → server.py | None | **Implemented** — returns JSON learner state |
| DELETE | `/api/v1/learners/{id}/state` | `delete_learner_state()` → server.py | None | **Implemented** — deletes state file |
| GET | `/api/v1/learners/{id}/portfolio` | `get_portfolio()` → server.py | None | **Implemented** — filters by entry_type, limit |
| GET | `/api/v1/calibration` | `get_calibration()` → server.py | None | **Implemented** — confidence calibrator telemetry |
| GET | `/api/v1/system/agents/status` | `agents_status()` → server.py | None | **Implemented** — introspects all 16 agent modules |
| POST | `/auth/register` | `register()` → auth_routes.py | None | **Implemented** — creates user, sets HttpOnly cookie |
| POST | `/auth/login` | `login()` → auth_routes.py | None | **Implemented** — verifies bcrypt hash, returns JWT |
| POST | `/auth/logout` | `logout()` → auth_routes.py | None | **Implemented** — clears session cookie |
| GET | `/auth/me` | `me()` → auth_routes.py | Required (`get_current_user`) | **Implemented** — returns current user from JWT |
| GET | `/profile` | `get_user_profile()` → auth_routes.py | Required | **Implemented** — returns onboarding/preferences |
| PUT | `/profile` | `update_user_profile()` → auth_routes.py | Required | **Implemented** — updates profile fields |
| POST | `/profile/onboarding/complete` | `complete_onboarding()` → auth_routes.py | Required | **Implemented** — marks onboarded=true |
| GET | `/events` | `get_user_events()` → auth_routes.py | Required | **Implemented** — lists manually-logged events |
| POST | `/events` | `create_user_event()` → auth_routes.py | Required | **Implemented** — logs a learning event |
| GET | `/uploads` | `get_user_uploads()` → auth_routes.py | Required | **Implemented** — lists file uploads |
| POST | `/uploads` | `upload_file()` → auth_routes.py | Required | **Implemented** — saves file to disk, records metadata |

**Total**: 20 endpoints. **0 stubs**. All have real handler logic.

### CORS configuration (`server.py`, lines 112–118)

```python
allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
allow_credentials=True,
```

Status: **Implemented** — hardcoded to local dev origins. No production URL configured.

### Auth architecture

| Component | File | Mechanism | Status |
|-----------|------|-----------|--------|
| Password hashing | `api/auth.py` → `hash_password()` | bcrypt | **Implemented** |
| JWT creation | `api/auth.py` → `create_access_token()` | HS256, 72h expiry | **Implemented** |
| JWT verification | `api/auth.py` → `decode_token()` | PyJWT decode | **Implemented** |
| Session delivery | `api/auth_routes.py` (line ~103) | HttpOnly cookie `ln_session`, samesite=lax | **Implemented** |
| Fallback auth | `api/auth.py` → `get_current_user()` | Also checks `Authorization: Bearer` header | **Implemented** |
| User store | `api/auth_db.py` | aiosqlite, WAL mode, 4 tables | **Implemented** |

> **Security note**: JWT secret defaults to `"dev-secret-change-in-production-!!!!"` when `LN_JWT_SECRET` env var is unset. The non-auth endpoints (`/api/v1/*`) lack authentication — any caller can read/write learner states.

---

## C. Agent & Orchestration Diagnostics

### Agent inventory (16 agents)

Every agent below extends `BaseAgent` (`agents/base.py`), implements `async handle(MessageEnvelope) → AgentResponse`, and is instantiated in `LearningGPSEngine.__init__()` (`engine/gps_engine.py`, lines 100–150).

| # | Agent | File | agent_id | cost_tier | Logic type | Lines | Status |
|---|-------|------|----------|-----------|------------|------:|--------|
| 1 | DiagnoserAgent | `agents/diagnoser.py` | `diagnoser` | 1 | BKT update, quiz/time processing, inactivity detection | ~200 | **Implemented** |
| 2 | DriftDetectorAgent | `agents/drift_detector.py` | `drift-detector` | 1 | 5 signal types: inactivity, mastery plateau, difficulty mismatch, disengagement, priority neglect | ~180 | **Implemented** |
| 3 | MotivationAgent | `agents/motivation.py` | `motivation` | 1 | 4-signal weighted average: session freq, inactivity, mastery trend, sentiment | ~160 | **Implemented** |
| 4 | PlannerAgent | `agents/planner.py` | `planner` | 2 | Multi-factor ranking (mastery gap, forgetting, priority, prerequisites, uncertainty), action suggestion | ~200 | **Implemented** |
| 5 | EvaluatorAgent | `agents/evaluator.py` | `evaluator` | 2 | 6-check quality audit: prerequisites, overload, cognitive load, empty plan, time budget, priorities | ~200 | **Implemented** |
| 6 | SkillStateAgent | `agents/skill_state.py` | `skill-state` | 1 | Readiness scoring, prerequisite gap detection, cluster analysis, topological learning order | ~286 | **Implemented** |
| 7 | BehaviorAgent | `agents/behavior.py` | `behavior` | 1 | 5 anomaly detectors: cramming, rapid guessing, avoidance, irregular sessions, late-night study | ~309 | **Implemented** |
| 8 | DecayAgent | `agents/decay.py` | `decay` | 1 | Ebbinghaus exponential decay, stability estimation (reps, spacing quality, difficulty, mastery), review scheduling | ~268 | **Implemented** |
| 9 | GenerativeReplayAgent | `agents/generative_replay.py` | `generative-replay` | 2 | Candidate selection by fragility, per-concept exercise generation, interleaved set construction | ~379 | **Implemented** |
| 10 | TimeOptimizerAgent | `agents/time_optimizer.py` | `time-optimizer` | 2 | Urgency×importance scoring, proportional time allocation (greedy knapsack, max 6 concepts), deadline analysis | ~283 | **Implemented** |
| 11 | ReflectionAgent | `agents/reflection.py` | `reflection` | 2 | 12-section narrative generation from full pipeline context, citation gathering | ~427 | **Implemented** |
| 12 | RAGAgent | `agents/rag_agent.py` | `rag-agent` | 2 | Learner-aware query construction, TF-IDF/Azure Search retrieval, deduplication, citation formatting | ~236 | **Implemented** |
| 13 | MasteryMaximizer | `agents/debate_advocates.py` | `mastery-maximizer` | 2 | Prerequisite, depth, forgetting, coverage objections + amendments | ~419 (shared) | **Implemented** |
| 14 | ExamStrategist | `agents/debate_advocates.py` | `exam-strategist` | 2 | Priority focus, deadline pressure, practice test, time efficiency analysis | (shared) | **Implemented** |
| 15 | BurnoutMinimizer | `agents/debate_advocates.py` | `burnout-minimizer` | 2 | Session-length, motivation, variety, rest period, cramming detection | (shared) | **Implemented** |
| 16 | DebateArbitrator | `agents/debate_arbitrator.py` | `debate-arbitrator` | 2 | Context-adaptive weighting (deadline→exam boost, low motivation→burnout boost), objection threshold filtering | ~224 | **Implemented** |

**Result**: 16/16 agents are **fully implemented** with real rule-based logic. **Zero stubs**. **Zero LLM calls**.

### Orchestration pipeline (`engine/gps_engine.py` → `process_event()`, line 175)

The full pipeline executes in this order for each `LearnerEvent`:

```
1.  Load state         → MemoryStore.get_learner_state()
1b. Adaptive routing   → AdaptiveRouter.route() → decides which agents run
2.  Diagnose           → DiagnoserAgent (always runs)
3.  Drift detection    → DriftDetectorAgent (conditional)
4.  Motivation         → MotivationAgent (always runs)
4b. Skill state        → SkillStateAgent (conditional)
4c. Behavior           → BehaviorAgent (conditional)
4d. Decay              → DecayAgent (conditional)
4e. Generative replay  → GenerativeReplayAgent (conditional)
4f. Time optimization  → TimeOptimizerAgent (conditional)
5.  Plan + Check       → MakerChecker.run() [Planner makes, Evaluator checks, up to 2 rounds]
5b. Debate             → DebateEngine.run() [3 advocates → arbitrator, up to 2 rounds]
5c. RAG retrieval      → RAGAgent (conditional, needs retrieval index)
6.  HITL check         → DefaultHITLHook.should_require_review() → auto-approve/reject
7.  Save state         → MemoryStore.save_learner_state()
7b. Reflection         → ReflectionAgent (conditional, post-pipeline narrative)
8.  Publish event      → EventBus.publish()
9.  Build NBA          → _build_next_best_action() with calibrated confidence
10. Log to portfolio   → PortfolioLogger.append()
```

Status: **Fully implemented**. All pipeline steps have real logic with state mutations, conditional routing, and structured telemetry.

### Adaptive Router (`engine/adaptive_router.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Core agents (always run) | `diagnoser`, `motivation` | **Implemented** |
| Need scoring | Uncertainty + drift + anomaly + decay signals → per-agent score | **Implemented** |
| Greedy knapsack | Sorted by value density (need/cost), selected within budget | **Implemented** |
| Full-pipeline interval | Every Nth turn forces all agents | **Implemented** |
| Toggle | `adaptive_routing_enabled` setting (default: `True`) | **Implemented** |

### Confidence Calibrator (`engine/confidence_calibrator.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Per-agent tracking | `record_outcome(agent_id, reported, actual)` | **Implemented** |
| Exponential decay weighting | `decay_factor=0.9`, ~10-obs effective window | **Implemented** |
| Trust weight computation | `actual/reported` ratio, clamped [0.3, 1.5] | **Implemented** |
| Calibration API | `calibrate(agent_id, raw_confidence) → adjusted` | **Implemented** |
| Cold start | Returns raw confidence when < 3 observations | **Implemented** |

> **Note**: `record_outcome()` is never called in the current codebase — the calibrator only adjusts via `calibrate()` in `_build_next_best_action()`. Without outcome data, all trust weights stay at 1.0. Status: **Implemented but inert** (no feedback loop wired).

---

## D. Data / Memory / RAG

### Storage interfaces (`storage/interfaces.py`)

Three abstract base classes define the persistence contract:

| Interface | Methods | Purpose |
|-----------|---------|---------|
| `MemoryStore` | `get_learner_state()`, `save_learner_state()`, `delete_learner_state()`, `list_learner_ids()` | Current learner state snapshot |
| `PortfolioLogger` | `append()`, `get_entries()`, `count()` | Append-only audit log |
| `RetrievalIndex` | `index_document()`, `search()`, `delete_document()` | RAG vector/keyword index |

### Storage factory (`storage/__init__.py`)

Backend selection is config-driven via `Settings.storage_backend` and `Settings.search_backend`:

| Setting | Value | Implementation | Status |
|---------|-------|----------------|--------|
| `storage_backend` | `local_json` (default) | `LocalJsonMemoryStore` + `LocalJsonPortfolioLogger` | **Implemented** |
| `storage_backend` | `azure_blob` | `AzureBlobMemoryStore` + `AzureBlobPortfolioLogger` | **Implemented** (degrades to no-op stub without SDK/credentials) |
| `search_backend` | `local_tfidf` (default) | `LocalTfidfIndex` | **Implemented** |
| `search_backend` | `azure_ai_search` | `AzureAISearchIndex` | **Implemented** (degrades to no-op stub without SDK/credentials) |

### Local file store (`storage/local_store.py`)

| Component | Path pattern | Format | Status |
|-----------|-------------|--------|--------|
| `LocalJsonMemoryStore` | `data/states/{learner_id}.json` | Pydantic JSON | **Implemented** |
| `LocalJsonPortfolioLogger` | `data/portfolio/{learner_id}.jsonl` | Newline-delimited JSON | **Implemented** |

### Local TF-IDF index (`storage/local_tfidf.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Tokenizer | Regex split, stop-word removal | **Implemented** |
| TF-IDF engine | From-scratch (no sklearn), IDF computation, cosine similarity | **Implemented** |
| Persistence | Optional JSON dump to `data/rag_index/index.json` | **Implemented** |
| Metadata filtering | Post-ranking filter | **Implemented** |

**Result**: Full RAG pipeline works end-to-end locally: `RAGAgent` → `LocalTfidfIndex.search()` → citations returned in `NextBestAction.citations`.

### Auth database (`api/auth_db.py`)

| Table | Columns | Status |
|-------|---------|--------|
| `users` | `id, email, password_hash, display_name, created_at, updated_at` | **Implemented** |
| `user_profiles` | `user_id, onboarded, learning_goals, subjects, weekly_schedule, preferences, baseline_assessment` | **Implemented** |
| `user_uploads` | `id, user_id, file_name, file_type, file_size, storage_path, processed_status, created_at` | **Implemented** |
| `user_events` | `id, user_id, concept, score, time_spent_minutes, event_type, notes, source, timestamp` | **Implemented** |

Database: SQLite at `data/users.db`, WAL mode, foreign keys enabled.

### Data files on disk

| Path | Learner IDs | Contents |
|------|-------------|----------|
| `data/states/` | `string`, `student-1`, `student-2`, `student-alice`, `student-az` | Full LearnerState JSON (concepts, BKT, relations, motivation, drift signals) |
| `data/portfolio/` | Same 5 + `student-del` | JSONL portfolio entries (recommendations, state snapshots) |
| `data/rag_index/` | (empty) | No pre-indexed documents — index starts cold |
| `data/users.db` | (created at startup) | User accounts and profiles |

---

## E. Evaluation / Maker-Checker / Auditor

### Maker-Checker loop (`engine/maker_checker.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Make phase | `PlannerAgent.handle()` → study plan | **Implemented** |
| Check phase | `EvaluatorAgent.handle()` → quality audit (6 checks) | **Implemented** |
| Retry with feedback | Checker issues injected into maker payload for round 2 | **Implemented** |
| Max rounds | Default 2 | **Implemented** |
| Quality threshold | `min_quality_score=0.5` | **Implemented** |
| Verdicts | `APPROVED`, `REJECTED`, `NEEDS_REVISION` | **Implemented** |

### Strategic Debate (`engine/debate.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Advocate fan-out | 3 advocates receive plan in parallel | **Implemented** |
| Early alignment exit | If all advocates align, skip arbitration | **Implemented** |
| Arbitration | Context-adaptive weighting → objection threshold filtering | **Implemented** |
| Multi-round debate | Up to `max_debate_rounds` (default 2); loops on `major_revision` | **Implemented** |
| Debate outcomes | `PLAN_APPROVED`, `MINOR_REVISION`, `MAJOR_REVISION`, `DEBATE_SKIPPED` | **Implemented** |
| Toggle | `debate_enabled` config setting | **Implemented** |

### Evaluation harness (`evaluation/harness.py`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Scenario-based testing | `EvalScenario` with ordered `ScenarioStep` entries | **Implemented** |
| Isolated engine per scenario | Fresh `LocalJsonMemoryStore` + engine | **Implemented** |
| Step expectations | Confidence bounds, gain bounds, action substring, risk keys, pipeline coverage | **Implemented** |
| Metrics aggregation | Per-scenario and suite-level: pass rate, mean confidence, latency, coverage | **Implemented** |
| Report output | `.summary()` text + `.to_dict()` JSON | **Implemented** |

### Evaluation metrics (`evaluation/metrics.py`)

Seven metric dimensions checked per step:
1. Confidence bounds (`min_confidence`, `max_confidence`)
2. Learning gain bounds (`min_gain`, `max_gain`)
3. Action substring matching
4. Rationale non-empty
5. Required risk keys present
6. Forbidden risk keys absent
7. Minimum pipeline step count

### HITL hook (`engine/hitl.py`)

| Component | Implementation | Status |
|-----------|---------------|--------|
| `HITLHook` (abstract) | `request_review()`, `should_require_review()` | **Implemented** (interface) |
| `DefaultHITLHook` | Auto-approve above threshold (0.5), auto-reject below, log all requests | **Implemented** |
| `HITLDecision` enum | `APPROVE`, `REJECT`, `MODIFY`, `ESCALATE`, `AUTO_APPROVED` | **Implemented** |

> **Note**: No real HITL integration exists (no teacher dashboard, no Slack bot). The `DefaultHITLHook` always runs — human override requires a custom `HITLHook` subclass injection. Status: **Implemented (framework)**, **Missing (real integration)**.

---

## F. Azure / Cloud Integration

### Infrastructure as Code

| File | Purpose | Status |
|------|---------|--------|
| `infra/azure/main.bicep` | 195-line Bicep template: Storage Account, App Insights, Consumption App Service Plan, Function App, Azure AI Search (Basic SKU) | **Implemented** |
| `infra/azure/deploy.ps1` | PowerShell deployment script | **Implemented** |
| `infra/azure/Dockerfile` | Python 3.10-slim, `pip install .[azure]`, non-root user, healthcheck, uvicorn 2 workers | **Implemented** |
| `infra/azure/host.json` | Azure Functions host config | **Implemented** |
| `infra/azure/requirements-azure.txt` | Azure Functions requirements | **Implemented** |

### Azure storage adapters

| Adapter | File | SDK guard | Stub mode | Status |
|---------|------|-----------|-----------|--------|
| `AzureBlobMemoryStore` | `storage/azure_store.py` | `import azure.storage.blob` | Returns `None`/no-op when SDK missing | **Implemented** (real code behind SDK guard) |
| `AzureBlobPortfolioLogger` | `storage/azure_store.py` | Same | Returns empty/no-op | **Implemented** |
| `AzureAISearchIndex` | `storage/azure_search.py` | `import azure.search.documents` | Returns empty results | **Implemented** |

All three adapters:
- Attempt SDK import at construction time
- Create container/index if it doesn't exist
- Log warnings when degrading to stub mode
- Have full CRUD implementations behind the SDK guard

### Azure Functions adapter (`api/azure_functions.py`)

Wraps the FastAPI `app` for Azure Functions consumption plan deployment. Status: **Implemented**.

### Configuration (`infra/config.py`)

| Setting | Env var prefix | Default | Purpose |
|---------|---------------|---------|---------|
| `environment` | `LN_ENVIRONMENT` | `local` | dev/staging/production |
| `storage_backend` | `LN_STORAGE_BACKEND` | `local_json` | `local_json` or `azure_blob` |
| `search_backend` | `LN_SEARCH_BACKEND` | `local_tfidf` | `local_tfidf` or `azure_ai_search` |
| `azure_storage_connection_string` | `LN_AZURE_STORAGE_CONNECTION_STRING` | `""` | Azure Blob conn string |
| `azure_search_endpoint` | `LN_AZURE_SEARCH_ENDPOINT` | `""` | Azure Search URL |
| `azure_search_key` | `LN_AZURE_SEARCH_KEY` | `""` | Azure Search API key |
| `debate_enabled` | `LN_DEBATE_ENABLED` | `True` | Toggle debate subsystem |
| `adaptive_routing_enabled` | `LN_ADAPTIVE_ROUTING_ENABLED` | `True` | Toggle adaptive routing |
| `cost_budget_per_turn` | `LN_COST_BUDGET_PER_TURN` | `10.0` | Abstract cost budget |

> **Not deployed**: No evidence of actual Azure deployment. The Bicep template and Dockerfile exist but no deployment logs, resource URIs, or connection strings are committed. Status: **Implemented (IaC ready), Not deployed**.

---

## G. Frontend

### Tech stack

- **Framework**: Next.js 15 (App Router) — `frontend/package.json`
- **Language**: TypeScript (strict)
- **Styling**: Tailwind CSS 4, CSS variables for theming
- **Animation**: Framer Motion
- **Charts**: Recharts
- **Icons**: Lucide React
- **State**: React Context (`useAuth()`)

### Route inventory

| Route | File | Purpose | Auth required |
|-------|------|---------|---------------|
| `/` | `app/page.tsx` | GPS Home — hero card, "Get Today's Guidance" CTA, AI team cards, strengths/gaps | Yes (via AuthGate) |
| `/login` | `app/login/page.tsx` | Email/password login | No |
| `/register` | `app/register/page.tsx` | Account registration | No |
| `/onboarding` | `app/onboarding/page.tsx` | Multi-step onboarding wizard | Yes |
| `/session` | `app/session/page.tsx` | Study session — event submission, AI feedback timeline | Yes |
| `/plan` | `app/plan/page.tsx` | Study plan — kanban/timeline, what-if scenarios | Yes |
| `/portfolio` | `app/portfolio/page.tsx` | Learning journal — AI + local entries | Yes |
| `/my-data` | `app/my-data/page.tsx` | Activity logging + file upload | Yes |
| `/settings` | `app/settings/page.tsx` | User settings & preferences | Yes |
| `/dev-tools` | `app/dev-tools/page.tsx` | Developer diagnostics (API logs, agent status, raw state) | Yes |

**Total**: 10 pages, all with real UI logic. **Zero placeholder pages**.

### API client (`frontend/src/lib/api/client.ts`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Base URL | `NEXT_PUBLIC_API_BASE_URL` or `http://127.0.0.1:8000` | **Implemented** |
| Proxy routing | `/api/proxy/:path*` → backend (Next.js rewrites) | **Implemented** |
| Credential handling | `credentials: "include"` on all fetches | **Implemented** |
| Dev logging | Request/response timing, status codes, stored in-memory | **Implemented** |
| Typed functions | 20+ functions matching all backend endpoints | **Implemented** |
| Error handling | Returns `{data, error, status}` tuple | **Implemented** |

### Auth context (`frontend/src/lib/auth-context.tsx`)

| Feature | Implementation | Status |
|---------|---------------|--------|
| AuthProvider | React Context wrapping the app | **Implemented** |
| Auto-check | Calls `/auth/me` on mount to restore session | **Implemented** |
| AuthGate | `<ClientShell>` component redirects to `/login` if unauthenticated | **Implemented** |
| State | `user`, `loading`, `login()`, `logout()`, `register()` | **Implemented** |

### Frontend → Backend endpoint mapping

| Frontend action | API call | Backend endpoint |
|----------------|----------|-----------------|
| "Get Today's Guidance" button | `postEvent()` | `POST /api/v1/events` |
| Load learner state | `getLearnerState()` | `GET /api/v1/learners/{id}/state` |
| View portfolio | `getPortfolio()` | `GET /api/v1/learners/{id}/portfolio` |
| Submit quiz result (Session page) | `postEvent()` | `POST /api/v1/events` |
| Register account | `register()` | `POST /auth/register` |
| Login | `login()` | `POST /auth/login` |
| View AI team status (Dev Tools) | `getAgentStatus()` | `GET /api/v1/system/agents/status` |
| Upload file (My Data page) | `uploadFile()` | `POST /uploads` |
| Log learning event (My Data page) | `createEvent()` | `POST /events` |
| Update profile (Settings/Onboarding) | `updateProfile()` | `PUT /profile` |

### UX features

- **Dark/light mode**: CSS variable theming, toggle in top bar
- **Mobile responsive**: Sidebar collapses, mobile nav in top bar
- **Sample data fallback**: When backend is unavailable, UI shows sample data with a banner
- **Empty states**: All pages have guided first-run experiences with CTAs
- **AI Team visibility**: 14 agents shown with friendly names and colored icons on Home page
- **Human-centered language**: No technical jargon exposed to users (GPS framing, "AI team", "Study Session")

---

## H. Tests & Quality

### Test suite results (pytest, run 2026-03-02)

```
pytest tests/ -v --tb=short
450 passed, 13 failed, 12 warnings — 4.51s
```

| Test file | Tests | Status | Notes |
|-----------|------:|--------|-------|
| `test_agents.py` | ~40 | **All pass** | Diagnoser, Drift, Motivation, Planner, Evaluator |
| `test_azure_deployment.py` | ~35 | **13 fail** | `ModuleNotFoundError: No module named 'bcrypt'` — auth imports break server import |
| `test_config_and_agent.py` | ~20 | **All pass** | Settings, agent metadata, capabilities |
| `test_continual_learning.py` | ~30 | **All pass** | Decay, Generative Replay, forgetting curves |
| `test_contracts.py` | ~25 | **All pass** | Events, LearnerState, MessageEnvelope, BKT |
| `test_debate.py` | ~30 | **All pass** | Advocates, Arbitrator, DebateEngine |
| `test_differentiators.py` | ~40 | **All pass** | All differentiator features |
| `test_evaluation.py` | ~25 | **All pass** | Harness, metrics, scenarios |
| `test_event_bus.py` | ~15 | **All pass** | Pub/sub, wildcard, error handling |
| `test_gps_engine.py` | ~30 | **All pass** | Full pipeline integration tests |
| `test_learner_state.py` | ~25 | **All pass** | State model, BKT update, knowledge graph |
| `test_maker_checker.py` | ~15 | **All pass** | Make-check loop, retry, verdicts |
| `test_rag.py` | ~20 | **All pass** | TF-IDF index, RAG agent, learner-aware queries |
| `test_specialized_agents.py` | ~35 | **All pass** | SkillState, Behavior, TimeOptimizer, Reflection |
| `test_storage.py` | ~25 | **All pass** | LocalJsonMemoryStore, LocalJsonPortfolioLogger |
| `test_storage_factory.py` | ~10 | **All pass** | Backend selection via config |

### Root cause of 13 failures

All 13 failures are in `test_azure_deployment.py`. They occur because `from learning_navigator.api.server import ...` triggers `import bcrypt` (via `api/auth.py`), and `bcrypt` is not in `pyproject.toml` dependencies. The fix is to add `bcrypt`, `PyJWT`, and `aiosqlite` to `[project.dependencies]`.

### Quality tooling declared in `pyproject.toml`

| Tool | Configured | Status |
|------|-----------|--------|
| ruff (lint + format) | `target-version = "py310"`, 9 rule sets | **Configured** |
| mypy (strict mode) | `strict = true`, pydantic plugin | **Configured** |
| pytest | `testpaths = ["tests"]`, `pythonpath = ["src"]` | **Configured** |
| pytest-cov | In optional deps | **Declared, not run in CI** |

> **No CI/CD pipeline** is checked in. No GitHub Actions, Azure DevOps, or other CI configuration exists.

---

## I. Truth Table Summary

| Component | Status | Evidence |
|-----------|--------|----------|
| **Backend API (20 endpoints)** | **Implemented** | All handlers in `server.py` + `auth_routes.py` have real logic |
| **DiagnoserAgent** | **Implemented** | BKT update + quiz/time processing in `diagnoser.py` → `_diagnose()`, `_process_quiz()` |
| **DriftDetectorAgent** | **Implemented** | 5 signal detectors in `drift_detector.py` → `_detect_drift()` |
| **MotivationAgent** | **Implemented** | 4-signal weighted average in `motivation.py` → `_assess_motivation()` |
| **PlannerAgent** | **Implemented** | Multi-factor ranking in `planner.py` → `_rank_concepts()`, `_create_plan()` |
| **EvaluatorAgent** | **Implemented** | 6-check audit in `evaluator.py` → `_evaluate_plan()` |
| **SkillStateAgent** | **Implemented** | Graph analysis in `skill_state.py` → `_compute_readiness()`, `_find_prerequisite_gaps()` |
| **BehaviorAgent** | **Implemented** | 5 anomaly detectors in `behavior.py` → `_detect_cramming()` etc. |
| **DecayAgent** | **Implemented** | Ebbinghaus model in `decay.py` → `_forgetting_score()`, `_compute_stability()` |
| **GenerativeReplayAgent** | **Implemented** | Fragility selection + exercise gen in `generative_replay.py` |
| **TimeOptimizerAgent** | **Implemented** | Urgency×importance allocation in `time_optimizer.py` → `_score_concepts()` |
| **ReflectionAgent** | **Implemented** | 12-section narrative in `reflection.py` |
| **RAGAgent** | **Implemented** | Learner-aware queries + retrieval in `rag_agent.py` |
| **MasteryMaximizer** | **Implemented** | Prerequisite/depth/forgetting objections in `debate_advocates.py` |
| **ExamStrategist** | **Implemented** | Priority/deadline analysis in `debate_advocates.py` |
| **BurnoutMinimizer** | **Implemented** | Session-length/motivation/variety checks in `debate_advocates.py` |
| **DebateArbitrator** | **Implemented** | Context-adaptive weighting in `debate_arbitrator.py` → `_compute_weights()` |
| **GPS Engine (orchestrator)** | **Implemented** | 14-step pipeline in `gps_engine.py` → `process_event()` |
| **Maker-Checker loop** | **Implemented** | Make→check→retry in `maker_checker.py` → `run()` |
| **Debate Engine** | **Implemented** | Fan-out→arbitrate→loop in `debate.py` → `run()` |
| **Adaptive Router** | **Implemented** | Greedy knapsack in `adaptive_router.py` → `route()` |
| **Confidence Calibrator** | **Implemented (inert)** | Logic exists in `confidence_calibrator.py` but `record_outcome()` is never called → trust weights stay 1.0 |
| **EventBus** | **Implemented** | In-memory pub/sub in `event_bus.py` |
| **HITL framework** | **Implemented (auto-only)** | `DefaultHITLHook` auto-approves in `hitl.py`; no real human integration |
| **Local JSON storage** | **Implemented** | `local_store.py` — read/write JSON + JSONL |
| **Local TF-IDF index** | **Implemented** | From-scratch TF-IDF in `local_tfidf.py` |
| **Azure Blob storage** | **Implemented (SDK-guarded)** | Real CRUD behind SDK import guard in `azure_store.py` |
| **Azure AI Search** | **Implemented (SDK-guarded)** | Real search/index behind SDK guard in `azure_search.py` |
| **Auth (bcrypt + JWT)** | **Implemented** | `auth.py` + `auth_db.py` — 4 SQLite tables, cookie-based sessions |
| **Evaluation harness** | **Implemented** | Scenario runner in `harness.py` with 7-dimension metric check |
| **Azure IaC (Bicep)** | **Implemented (not deployed)** | `main.bicep` — Storage, App Insights, Function App, Search |
| **Docker** | **Implemented** | `Dockerfile` — multi-stage, healthcheck, non-root |
| **Frontend (10 pages)** | **Implemented** | All pages in `frontend/src/app/` have real UI + backend calls |
| **Frontend auth flow** | **Implemented** | Register → login → cookie → AuthGate in `auth-context.tsx` |
| **Test suite (450/463)** | **Mostly passing** | 450 pass, 13 fail due to missing `bcrypt` in deps |
| **CI/CD** | **Missing** | No GitHub Actions, Azure Pipelines, or other CI config found |
| **pyproject.toml deps** | **Broken** | `bcrypt`, `PyJWT`, `aiosqlite` used but not declared |

### Summary counts

| Metric | Value |
|--------|-------|
| Total backend Python files | 51 |
| Total frontend TS/TSX files | 21 |
| Total test files | 16 |
| Total test cases | 463 |
| Tests passing | 450 (97.2%) |
| Tests failing | 13 (all same root cause: missing `bcrypt` dep) |
| API endpoints | 20 |
| Agents (all implemented) | 16 |
| Stub agents | 0 |
| LLM calls | 0 (fully rule-based) |
| Storage backends | 4 (local JSON, local TF-IDF, Azure Blob, Azure AI Search) |
| Infrastructure files | 7 |
| CI/CD pipelines | 0 |

### Action items

1. **P0**: Add `bcrypt`, `PyJWT`, and `aiosqlite` to `pyproject.toml` `[project.dependencies]` → fixes 13 test failures
2. **P1**: Add authentication to core API endpoints (`/api/v1/*`) — currently unprotected
3. **P1**: Set up a CI/CD pipeline (GitHub Actions or Azure DevOps)
4. **P2**: Wire `ConfidenceCalibrator.record_outcome()` with actual learning outcomes for feedback loop
5. **P2**: Implement a real HITL integration (teacher dashboard or notification system)
6. **P2**: Add production CORS origins to server configuration
7. **P3**: Pre-populate `data/rag_index/` with starter learning materials
8. **P3**: Deploy to Azure and validate Bicep template end-to-end
