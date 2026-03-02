"""FastAPI REST server for Learning Navigator.

Provides HTTP endpoints for:
- Health check / readiness
- Processing learner events (→ NextBestAction)
- Retrieving and managing learner state
- Portfolio log queries
- Calibration telemetry

The server instantiates the full GPS Engine pipeline using
config-driven backend selection (local or Azure).

Usage::

    uvicorn learning_navigator.api.server:app --reload
    # or via CLI: learning-nav run
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from learning_navigator import __version__
from learning_navigator.contracts.events import (
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.engine.event_bus import InMemoryEventBus
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.infra.config import Settings, get_settings
from learning_navigator.infra.logging import setup_logging
from learning_navigator.storage import (
    create_memory_store,
    create_portfolio_logger,
    create_retrieval_index,
)
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioLogger,
)
from learning_navigator.api.auth import get_current_user, get_optional_user
from learning_navigator.api.auth_db import init_db as init_auth_db
from learning_navigator.api.auth_routes import router as auth_router
from learning_navigator.api.agent_diagnostics import get_agents_status, get_system_summary

logger = structlog.get_logger(__name__)

# ── Global state (initialised at startup) ──────────────────────────

_engine: LearningGPSEngine | None = None
_memory_store: MemoryStore | None = None
_portfolio_logger: PortfolioLogger | None = None
_settings: Settings | None = None


# ── Lifespan ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise engine and storage on startup, teardown on shutdown."""
    global _engine, _memory_store, _portfolio_logger, _settings

    _settings = get_settings()
    setup_logging(
        log_level=_settings.log_level,
        log_format=_settings.log_format,
    )

    _memory_store = create_memory_store(_settings)
    _portfolio_logger = create_portfolio_logger(_settings)
    event_bus = InMemoryEventBus()
    retrieval_index = create_retrieval_index(_settings)

    _engine = LearningGPSEngine(
        memory_store=_memory_store,
        portfolio_logger=_portfolio_logger,
        event_bus=event_bus,
        retrieval_index=retrieval_index,
        adaptive_routing_enabled=_settings.adaptive_routing_enabled,
        cost_budget_per_turn=_settings.cost_budget_per_turn,
    )

    # Initialise auth database
    await init_auth_db()

    logger.info(
        "api.startup",
        version=__version__,
        environment=_settings.environment.value,
        storage_backend=_settings.storage_backend.value,
        search_backend=_settings.search_backend.value,
    )
    yield

    logger.info("api.shutdown")


# ── App ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Learning Navigator AI",
    description="Multi-Agent Learning GPS — adaptive, explainable learning navigation",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth & user data routes
app.include_router(auth_router, tags=["auth"])


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect root to interactive API docs."""
    return RedirectResponse(url="/docs")


# ── Request / Response models ──────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    environment: str = "local"


class EventRequest(BaseModel):
    """Request body for the process-event endpoint."""

    event_id: str
    learner_id: str | None = None  # auto-filled from auth; ignored if provided
    event_type: LearnerEventType
    concept_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class LearnerStateResponse(BaseModel):
    """Wrapper for returning learner state."""

    learner_id: str
    found: bool
    state: dict[str, Any] | None = None


class PortfolioResponse(BaseModel):
    """Wrapper for portfolio entries."""

    learner_id: str
    count: int
    entries: list[dict[str, Any]]


class CalibrationResponse(BaseModel):
    """Calibration telemetry response."""

    agents: dict[str, Any]


# ── Endpoints ──────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check / readiness probe."""
    env = _settings.environment.value if _settings else "local"
    return HealthResponse(environment=env)


@app.post("/api/v1/events", response_model=NextBestAction)
async def process_event(
    request: EventRequest,
    user: dict = Depends(get_current_user),
) -> NextBestAction:
    """Process a learner event and return a NextBestAction recommendation.

    The learner_id is derived from the authenticated user.
    This is the primary endpoint — it runs the full GPS Engine pipeline:
    Event → Diagnose → Drift → Motivate → SkillState → Behavior → Decay →
    Replay → TimeOpt → Plan+Check → Debate → RAG → HITL → Reflect → Action
    """
    if _engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Engine not initialised",
        )

    # Always use authenticated user's ID as learner_id
    learner_id = user["user_id"]

    event = LearnerEvent(
        event_id=request.event_id,
        learner_id=learner_id,
        event_type=request.event_type,
        concept_id=request.concept_id,
        data=request.data,
    )

    try:
        nba = await _engine.process_event(event)
        return nba
    except Exception as exc:
        logger.error(
            "api.process_event.failed",
            learner_id=learner_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {exc}",
        ) from exc


@app.get("/api/v1/me/state", response_model=LearnerStateResponse)
async def get_my_state(
    user: dict = Depends(get_current_user),
) -> LearnerStateResponse:
    """Retrieve the authenticated user's learner state."""
    if _memory_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage not initialised",
        )

    learner_id = user["user_id"]
    state = await _memory_store.get_learner_state(learner_id)
    if state is None:
        return LearnerStateResponse(
            learner_id=learner_id,
            found=False,
        )
    return LearnerStateResponse(
        learner_id=learner_id,
        found=True,
        state=state.model_dump(mode="json"),
    )


@app.get("/api/v1/learners/{learner_id}/state", response_model=LearnerStateResponse)
async def get_learner_state(
    learner_id: str,
    user: dict = Depends(get_current_user),
) -> LearnerStateResponse:
    """Retrieve learner state — scoped to authenticated user."""
    if _memory_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage not initialised",
        )

    # Users can only access their own state
    if learner_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you can only view your own data.",
        )

    state = await _memory_store.get_learner_state(learner_id)
    if state is None:
        return LearnerStateResponse(
            learner_id=learner_id,
            found=False,
        )
    return LearnerStateResponse(
        learner_id=learner_id,
        found=True,
        state=state.model_dump(mode="json"),
    )


@app.delete("/api/v1/learners/{learner_id}/state")
async def delete_learner_state(
    learner_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a learner's state — scoped to authenticated user."""
    if _memory_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage not initialised",
        )

    if learner_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you can only delete your own data.",
        )

    deleted = await _memory_store.delete_learner_state(learner_id)
    return {"learner_id": learner_id, "deleted": deleted}


@app.get("/api/v1/me/portfolio", response_model=PortfolioResponse)
async def get_my_portfolio(
    entry_type: str | None = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
) -> PortfolioResponse:
    """Retrieve portfolio entries for the authenticated user."""
    if _portfolio_logger is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portfolio logger not initialised",
        )

    learner_id = user["user_id"]
    entries = await _portfolio_logger.get_entries(
        learner_id,
        entry_type=entry_type,
        limit=limit,
    )
    return PortfolioResponse(
        learner_id=learner_id,
        count=len(entries),
        entries=[e.model_dump(mode="json") for e in entries],
    )


@app.get("/api/v1/learners/{learner_id}/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
    learner_id: str,
    entry_type: str | None = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
) -> PortfolioResponse:
    """Retrieve portfolio entries — scoped to authenticated user."""
    if _portfolio_logger is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portfolio logger not initialised",
        )

    if learner_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you can only view your own portfolio.",
        )

    entries = await _portfolio_logger.get_entries(
        learner_id,
        entry_type=entry_type,
        limit=limit,
    )
    return PortfolioResponse(
        learner_id=learner_id,
        count=len(entries),
        entries=[e.model_dump(mode="json") for e in entries],
    )


@app.get("/api/v1/calibration", response_model=CalibrationResponse)
async def get_calibration(
    user: dict = Depends(get_current_user),
) -> CalibrationResponse:
    """Return current confidence-calibration telemetry."""
    if _engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Engine not initialised",
        )
    return CalibrationResponse(
        agents=_engine.confidence_calibrator.get_calibration_summary(),
    )


@app.get("/api/v1/learners")
async def list_learners(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List learner IDs — returns only the authenticated user's ID.

    Admin listing of all learners is disabled by default.
    Set LN_ADMIN_LISTING=true to enable full listing.
    """
    import os

    if _memory_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage not initialised",
        )

    admin_listing = os.environ.get("LN_ADMIN_LISTING", "false").lower() == "true"
    if admin_listing:
        ids = await _memory_store.list_learner_ids()
        return {"learner_ids": ids, "count": len(ids)}

    # Non-admin: only return the current user's own ID
    own_id = user["user_id"]
    return {"learner_ids": [own_id], "count": 1}


# ── System / Diagnostics ──────────────────────────────────────────


@app.get("/api/v1/system/agents/status")
async def agents_status() -> dict[str, Any]:
    """Return implementation status for every agent in the pipeline."""
    agents = get_agents_status()
    summary = get_system_summary(agents)
    agent_list = [a.model_dump() if hasattr(a, "model_dump") else a for a in agents]
    return {
        "agents": agent_list,
        "total_agents": len(agent_list),
        "implemented_agents": summary["implemented"],
        "summary": summary,
    }
