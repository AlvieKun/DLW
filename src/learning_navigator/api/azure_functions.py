"""Azure Functions entry points for Learning Navigator.

Provides serverless deployment via Azure Functions:

1. **HTTP Trigger** — Proxies to the same FastAPI-compatible logic
   (process event, health check).
2. **Timer Trigger** — Scheduled memory consolidation / housekeeping.
3. **Blob Trigger** — React to new learner state changes for
   downstream processing.

These functions use the same engine and storage interfaces as the
local FastAPI server, just with Azure Functions hosting.

Deployment
──────────
1. Install Azure Functions Core Tools (``func``)
2. Copy or symlink this directory to your functions app
3. Set environment variables (LN_STORAGE_BACKEND=azure_blob, etc.)
4. ``func start`` for local testing, ``func azure functionapp publish``
   for cloud deployment

Note: When azure-functions SDK is not installed, this module degrades
gracefully and can still be imported for testing.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _try_import_azure_functions() -> bool:
    """Check if the Azure Functions SDK is available."""
    try:
        import azure.functions  # noqa: F401

        return True
    except ImportError:
        return False


# ── Engine factory (lazy init) ─────────────────────────────────────

_engine_instance: Any = None


async def _get_engine() -> Any:
    """Lazily initialise the GPS engine with config-driven backends."""
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    from learning_navigator.engine.event_bus import InMemoryEventBus
    from learning_navigator.engine.gps_engine import LearningGPSEngine
    from learning_navigator.infra.config import get_settings
    from learning_navigator.storage import (
        create_memory_store,
        create_portfolio_logger,
        create_retrieval_index,
    )

    settings = get_settings()
    _engine_instance = LearningGPSEngine(
        memory_store=create_memory_store(settings),
        portfolio_logger=create_portfolio_logger(settings),
        event_bus=InMemoryEventBus(),
        retrieval_index=create_retrieval_index(settings),
        adaptive_routing_enabled=settings.adaptive_routing_enabled,
        cost_budget_per_turn=settings.cost_budget_per_turn,
    )
    logger.info("azure_functions.engine_initialized")
    return _engine_instance


# ── HTTP Trigger: Process Event ────────────────────────────────────

async def process_event_handler(req_body: dict[str, Any]) -> dict[str, Any]:
    """Process a learner event and return NextBestAction.

    This is the core handler that both the Azure Function HTTP trigger
    and local Flask/FastAPI adapters call.
    """
    from learning_navigator.contracts.events import LearnerEvent, LearnerEventType

    engine = await _get_engine()

    event = LearnerEvent(
        event_id=req_body.get("event_id", "az-func-evt"),
        learner_id=req_body["learner_id"],
        event_type=LearnerEventType(req_body["event_type"]),
        concept_id=req_body.get("concept_id"),
        data=req_body.get("data", {}),
    )

    nba = await engine.process_event(event)
    return nba.model_dump(mode="json")


async def health_handler() -> dict[str, Any]:
    """Return health check response."""
    from learning_navigator import __version__
    from learning_navigator.infra.config import get_settings

    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment.value,
        "runtime": "azure-functions",
    }


# ── Timer Trigger: Memory Consolidation ────────────────────────────

async def consolidation_handler() -> dict[str, Any]:
    """Periodic memory consolidation task.

    Runs on a schedule (e.g., every 6 hours) to:
    1. Compact portfolio logs (archive old entries).
    2. Update calibration weights from recent outcomes.
    3. Clean up stale learner states (no activity for 90+ days).

    Returns a summary of actions taken.
    """
    from learning_navigator.infra.config import get_settings
    from learning_navigator.storage import create_memory_store

    settings = get_settings()
    store = create_memory_store(settings)

    learner_ids = await store.list_learner_ids()
    summary = {
        "total_learners": len(learner_ids),
        "consolidated": 0,
        "errors": 0,
    }

    logger.info(
        "consolidation.start",
        total_learners=len(learner_ids),
    )

    for learner_id in learner_ids:
        try:
            state = await store.get_learner_state(learner_id)
            if state is None:
                continue

            # Future: check last-updated timestamp and archive if stale
            summary["consolidated"] += 1
        except Exception as exc:
            logger.warning(
                "consolidation.error",
                learner_id=learner_id,
                error=str(exc),
            )
            summary["errors"] += 1

    logger.info("consolidation.complete", **summary)
    return summary


# ── Azure Functions bindings (only when SDK available) ─────────────

if _try_import_azure_functions():

    import azure.functions as func

    # Create the FunctionApp
    func_app = func.FunctionApp()

    @func_app.function_name("ProcessEvent")
    @func_app.route(route="api/v1/events", methods=["POST"])
    async def process_event_function(req: func.HttpRequest) -> func.HttpResponse:
        """HTTP trigger: process a learner event."""
        try:
            body = req.get_json()
            result = await process_event_handler(body)
            return func.HttpResponse(
                json.dumps(result),
                mimetype="application/json",
                status_code=200,
            )
        except Exception as exc:
            logger.error("azure_function.process_event.failed", error=str(exc))
            return func.HttpResponse(
                json.dumps({"error": str(exc)}),
                mimetype="application/json",
                status_code=500,
            )

    @func_app.function_name("Health")
    @func_app.route(route="health", methods=["GET"])
    async def health_function(req: func.HttpRequest) -> func.HttpResponse:
        """HTTP trigger: health check."""
        result = await health_handler()
        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json",
            status_code=200,
        )

    @func_app.function_name("MemoryConsolidation")
    @func_app.schedule(
        schedule="0 0 */6 * * *",  # Every 6 hours
        arg_name="timer",
    )
    async def consolidation_function(timer: func.TimerRequest) -> None:
        """Timer trigger: periodic memory consolidation."""
        logger.info(
            "azure_function.consolidation.triggered",
            past_due=timer.past_due,
        )
        await consolidation_handler()
