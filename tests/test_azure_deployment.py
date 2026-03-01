"""Tests for Phase 9 — Azure deployment scaffolding.

Covers:
1. Azure Blob MemoryStore & PortfolioLogger (stub-mode when no SDK)
2. Azure AI Search index (stub-mode)
3. FastAPI server endpoints (via httpx TestClient)
4. Azure Functions handler logic (pure-Python path)
5. CLI command existence
6. Infra file existence
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from learning_navigator.contracts.events import LearnerEventType
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
)
from learning_navigator.storage.azure_search import AzureAISearchIndex
from learning_navigator.storage.azure_store import (
    AzureBlobMemoryStore,
    AzureBlobPortfolioLogger,
)
from learning_navigator.storage.interfaces import PortfolioEntry

# ═══════════════════════════════════════════════════════════════════
# Section 1 — Azure Blob MemoryStore stub behaviour
# ═══════════════════════════════════════════════════════════════════


class TestAzureBlobMemoryStoreStub:
    """When Azure SDK is not installed / conn-string empty → stub mode."""

    def test_stub_when_no_connection_string(self) -> None:
        store = AzureBlobMemoryStore(connection_string="")
        assert store.available is False

    def test_stub_is_default(self) -> None:
        store = AzureBlobMemoryStore()
        assert store.available is False

    @pytest.mark.asyncio()
    async def test_get_returns_none_in_stub(self) -> None:
        store = AzureBlobMemoryStore()
        result = await store.get_learner_state("student-99")
        assert result is None

    @pytest.mark.asyncio()
    async def test_save_is_noop_in_stub(self) -> None:
        store = AzureBlobMemoryStore()
        state = LearnerState(learner_id="student-99")
        # Should not raise
        await store.save_learner_state(state)

    @pytest.mark.asyncio()
    async def test_delete_returns_false_in_stub(self) -> None:
        store = AzureBlobMemoryStore()
        result = await store.delete_learner_state("student-99")
        assert result is False

    @pytest.mark.asyncio()
    async def test_list_returns_empty_in_stub(self) -> None:
        store = AzureBlobMemoryStore()
        result = await store.list_learner_ids()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# Section 2 — Azure Blob PortfolioLogger stub behaviour
# ═══════════════════════════════════════════════════════════════════


class TestAzureBlobPortfolioLoggerStub:
    """Portfolio logger stub when no SDK / empty creds."""

    def test_stub_when_no_connection_string(self) -> None:
        logger = AzureBlobPortfolioLogger(connection_string="")
        assert logger.available is False

    def test_stub_is_default(self) -> None:
        logger = AzureBlobPortfolioLogger()
        assert logger.available is False

    @pytest.mark.asyncio()
    async def test_append_is_noop_in_stub(self) -> None:
        plog = AzureBlobPortfolioLogger()
        entry = PortfolioEntry(
            entry_id="e-1",
            learner_id="student-1",
            entry_type="recommendation",
            timestamp=datetime.now(timezone.utc),
            data={"note": "test"},
        )
        # Should not raise
        await plog.append(entry)

    @pytest.mark.asyncio()
    async def test_get_entries_empty_in_stub(self) -> None:
        plog = AzureBlobPortfolioLogger()
        entries = await plog.get_entries("student-1")
        assert entries == []

    @pytest.mark.asyncio()
    async def test_count_zero_in_stub(self) -> None:
        plog = AzureBlobPortfolioLogger()
        assert await plog.count("student-1") == 0


# ═══════════════════════════════════════════════════════════════════
# Section 3 — Azure AI Search stub behaviour
# ═══════════════════════════════════════════════════════════════════


class TestAzureAISearchStub:
    """Azure AI Search index stub when SDK unavailable / no creds."""

    def test_stub_default(self) -> None:
        index = AzureAISearchIndex()
        assert index.available is False

    def test_stub_empty_endpoint(self) -> None:
        index = AzureAISearchIndex(endpoint="", api_key="some-key")
        assert index.available is False

    def test_stub_empty_key(self) -> None:
        index = AzureAISearchIndex(endpoint="https://x.search.windows.net", api_key="")
        assert index.available is False

    @pytest.mark.asyncio()
    async def test_index_document_noop_in_stub(self) -> None:
        idx = AzureAISearchIndex()
        await idx.index_document("doc-1", "content here")

    @pytest.mark.asyncio()
    async def test_search_returns_empty_in_stub(self) -> None:
        idx = AzureAISearchIndex()
        results = await idx.search("anything", top_k=3)
        assert results == []

    @pytest.mark.asyncio()
    async def test_delete_returns_false_in_stub(self) -> None:
        idx = AzureAISearchIndex()
        result = await idx.delete_document("doc-1")
        assert result is False


# ═══════════════════════════════════════════════════════════════════
# Section 4 — FastAPI server endpoints
# ═══════════════════════════════════════════════════════════════════


def _make_state(learner_id: str = "student-1") -> LearnerState:
    """Helper to create a sample learner state."""
    s = LearnerState(learner_id=learner_id)
    s.upsert_concept(
        ConceptState(concept_id="algebra", bkt=BKTParams(p_know=0.6))
    )
    return s


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _init_server_globals() -> None:
    """Wire up server globals so endpoints don't return 503."""
    import learning_navigator.api.server as srv

    if srv._engine is not None:
        return  # Already initialised

    from learning_navigator.engine.event_bus import InMemoryEventBus
    from learning_navigator.engine.gps_engine import LearningGPSEngine
    from learning_navigator.infra.config import get_settings
    from learning_navigator.storage import (
        create_memory_store,
        create_portfolio_logger,
        create_retrieval_index,
    )

    settings = get_settings()
    srv._settings = settings
    srv._memory_store = create_memory_store(settings)
    srv._portfolio_logger = create_portfolio_logger(settings)
    event_bus = InMemoryEventBus()
    retrieval_index = create_retrieval_index(settings)
    srv._engine = LearningGPSEngine(
        memory_store=srv._memory_store,
        portfolio_logger=srv._portfolio_logger,
        event_bus=event_bus,
        retrieval_index=retrieval_index,
    )


def _reset_server_globals() -> None:
    import learning_navigator.api.server as srv

    srv._engine = None
    srv._memory_store = None
    srv._portfolio_logger = None
    srv._settings = None


class TestFastAPIServer:
    """Test the REST endpoints via httpx AsyncClient + ASGITransport."""

    @pytest.mark.asyncio()
    async def test_health_endpoint(self) -> None:
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    @pytest.mark.asyncio()
    async def test_process_event_returns_nba(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/events",
                json={
                    "event_id": "evt-1",
                    "learner_id": "student-1",
                    "event_type": "quiz_result",
                    "concept_id": "algebra",
                    "data": {"score": 0.85},
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "recommended_action" in body
        assert body["learner_id"] == "student-1"

    @pytest.mark.asyncio()
    async def test_get_learner_state_not_found(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/learners/nonexistent/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is False

    @pytest.mark.asyncio()
    async def test_get_learner_state_after_event(self) -> None:
        """After processing an event, the learner state should be stored."""
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First process an event to create state
            await client.post(
                "/api/v1/events",
                json={
                    "event_id": "e-2",
                    "learner_id": "student-2",
                    "event_type": "content_interaction",
                    "data": {},
                },
            )
            resp = await client.get("/api/v1/learners/student-2/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["learner_id"] == "student-2"
        assert body["found"] is True

    @pytest.mark.asyncio()
    async def test_delete_learner_state(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create + delete
            await client.post(
                "/api/v1/events",
                json={
                    "event_id": "e-del",
                    "learner_id": "student-del",
                    "event_type": "content_interaction",
                    "data": {},
                },
            )
            resp = await client.delete("/api/v1/learners/student-del/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["learner_id"] == "student-del"

    @pytest.mark.asyncio()
    async def test_get_portfolio_empty(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/learners/student-1/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        assert body["learner_id"] == "student-1"
        assert isinstance(body["entries"], list)

    @pytest.mark.asyncio()
    async def test_calibration_endpoint(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/calibration")
        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body

    @pytest.mark.asyncio()
    async def test_list_learners(self) -> None:
        _init_server_globals()
        from learning_navigator.api.server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/learners")
        assert resp.status_code == 200
        body = resp.json()
        assert "learner_ids" in body
        assert "count" in body


# ═══════════════════════════════════════════════════════════════════
# Section 5 — Azure Functions handler tests (pure-Python path)
# ═══════════════════════════════════════════════════════════════════


class TestAzureFunctionsHandlers:
    """Test the handler functions directly (no azure.functions SDK needed)."""

    @pytest.mark.asyncio()
    async def test_health_handler(self) -> None:
        from learning_navigator.api.azure_functions import health_handler

        result = await health_handler()
        assert result["status"] == "ok"
        assert "version" in result
        assert result["runtime"] == "azure-functions"

    @pytest.mark.asyncio()
    async def test_process_event_handler(self) -> None:
        # Reset engine for clean test
        import learning_navigator.api.azure_functions as af_mod
        from learning_navigator.api.azure_functions import (
            process_event_handler,
        )

        af_mod._engine_instance = None

        result = await process_event_handler({
            "event_id": "az-evt-1",
            "learner_id": "student-az",
            "event_type": "quiz_result",
            "concept_id": "algebra",
            "data": {"score": 0.9},
        })
        assert "recommended_action" in result
        assert result["learner_id"] == "student-az"

        # Cleanup
        af_mod._engine_instance = None

    @pytest.mark.asyncio()
    async def test_consolidation_handler(self) -> None:
        from learning_navigator.api.azure_functions import consolidation_handler

        result = await consolidation_handler()
        assert "total_learners" in result
        assert "consolidated" in result
        assert "errors" in result
        assert result["errors"] == 0

    @pytest.mark.asyncio()
    async def test_try_import_check(self) -> None:
        from learning_navigator.api.azure_functions import _try_import_azure_functions

        # Returns bool — no crash regardless of whether SDK installed
        result = _try_import_azure_functions()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════
# Section 6 — CLI command existence
# ═══════════════════════════════════════════════════════════════════


class TestCLI:
    """Verify CLI commands are registered."""

    def test_app_exists(self) -> None:
        from learning_navigator.cli import app

        assert app is not None

    def test_run_command_registered(self) -> None:
        """The 'run' command should be in the Typer app."""
        from learning_navigator.cli import app

        # Typer stores registered commands
        command_names = [cmd.name or cmd.callback.__name__ for cmd in app.registered_commands]
        assert "run" in command_names

    def test_version_flag(self) -> None:
        from typer.testing import CliRunner

        from learning_navigator.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "learning-navigator" in result.output


# ═══════════════════════════════════════════════════════════════════
# Section 7 — Infrastructure files
# ═══════════════════════════════════════════════════════════════════


class TestInfraFiles:
    """Verify deployment infra files exist."""

    def test_host_json_exists(self) -> None:
        from pathlib import Path

        assert (Path(__file__).parent.parent / "infra" / "azure" / "host.json").exists()

    def test_bicep_template_exists(self) -> None:
        from pathlib import Path

        assert (Path(__file__).parent.parent / "infra" / "azure" / "main.bicep").exists()

    def test_deploy_script_exists(self) -> None:
        from pathlib import Path

        assert (Path(__file__).parent.parent / "infra" / "azure" / "deploy.ps1").exists()

    def test_requirements_azure_exists(self) -> None:
        from pathlib import Path

        assert (
            Path(__file__).parent.parent / "infra" / "azure" / "requirements-azure.txt"
        ).exists()

    def test_dockerfile_exists(self) -> None:
        from pathlib import Path

        assert (Path(__file__).parent.parent / "infra" / "azure" / "Dockerfile").exists()

    def test_local_settings_template_exists(self) -> None:
        from pathlib import Path

        path = Path(__file__).parent.parent / "infra" / "azure" / "local.settings.json.template"
        assert path.exists()


# ═══════════════════════════════════════════════════════════════════
# Section 8 — Storage factory picks Azure backends from config
# ═══════════════════════════════════════════════════════════════════


class TestStorageFactoryAzure:
    """Config-driven backend selection wires Azure when requested."""

    def test_factory_creates_azure_memory_store(self) -> None:
        from learning_navigator.infra.config import Settings, StorageBackend, reset_settings
        from learning_navigator.storage import create_memory_store

        reset_settings()
        settings = Settings(
            storage_backend=StorageBackend.AZURE_BLOB,
            azure_storage_connection_string="",  # no real conn → stub mode
        )
        store = create_memory_store(settings)
        assert isinstance(store, AzureBlobMemoryStore)
        assert store.available is False

    def test_factory_creates_azure_portfolio_logger(self) -> None:
        from learning_navigator.infra.config import Settings, StorageBackend, reset_settings
        from learning_navigator.storage import create_portfolio_logger

        reset_settings()
        settings = Settings(
            storage_backend=StorageBackend.AZURE_BLOB,
            azure_storage_connection_string="",
        )
        plog = create_portfolio_logger(settings)
        assert isinstance(plog, AzureBlobPortfolioLogger)
        assert plog.available is False

    def test_factory_creates_azure_search_index(self) -> None:
        from learning_navigator.infra.config import (
            SearchBackend,
            Settings,
            reset_settings,
        )
        from learning_navigator.storage import create_retrieval_index

        reset_settings()
        settings = Settings(search_backend=SearchBackend.AZURE_AI_SEARCH)
        idx = create_retrieval_index(settings)
        assert isinstance(idx, AzureAISearchIndex)
        assert idx.available is False


# ═══════════════════════════════════════════════════════════════════
# Section 9 — API model validation
# ═══════════════════════════════════════════════════════════════════


class TestAPIModels:
    """Request / response Pydantic models validate correctly."""

    def test_event_request_model(self) -> None:
        from learning_navigator.api.server import EventRequest

        req = EventRequest(
            event_id="e-1",
            learner_id="s-1",
            event_type=LearnerEventType.QUIZ_RESULT,
            concept_id="algebra",
            data={"score": 0.9},
        )
        assert req.event_id == "e-1"
        assert req.event_type == LearnerEventType.QUIZ_RESULT

    def test_health_response_model(self) -> None:
        from learning_navigator.api.server import HealthResponse

        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version

    def test_learner_state_response_model(self) -> None:
        from learning_navigator.api.server import LearnerStateResponse

        resp = LearnerStateResponse(learner_id="s-1", found=False)
        assert resp.state is None
        assert resp.found is False

    def test_portfolio_response_model(self) -> None:
        from learning_navigator.api.server import PortfolioResponse

        resp = PortfolioResponse(learner_id="s-1", count=0, entries=[])
        assert resp.count == 0

    def test_calibration_response_model(self) -> None:
        from learning_navigator.api.server import CalibrationResponse

        resp = CalibrationResponse(agents={"diagnoser": {"trust": 1.0}})
        assert resp.agents["diagnoser"]["trust"] == 1.0
