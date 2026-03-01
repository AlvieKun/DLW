"""Tests for storage factory functions and Azure stub behavior."""

from __future__ import annotations

import pytest

from learning_navigator.infra.config import Settings, StorageBackend
from learning_navigator.storage import create_memory_store, create_portfolio_logger
from learning_navigator.storage.azure_store import (
    AzureBlobMemoryStore,
    AzureBlobPortfolioLogger,
)
from learning_navigator.storage.local_store import (
    LocalJsonMemoryStore,
    LocalJsonPortfolioLogger,
)


class TestStorageFactory:
    def test_default_creates_local(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        settings = Settings(local_data_dir=tmp_path / "data")
        store = create_memory_store(settings)
        assert isinstance(store, LocalJsonMemoryStore)

    def test_azure_creates_azure_store(self) -> None:
        settings = Settings(storage_backend=StorageBackend.AZURE_BLOB)
        store = create_memory_store(settings)
        assert isinstance(store, AzureBlobMemoryStore)

    def test_default_creates_local_portfolio(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        settings = Settings(local_data_dir=tmp_path / "data")
        logger = create_portfolio_logger(settings)
        assert isinstance(logger, LocalJsonPortfolioLogger)

    def test_azure_creates_azure_portfolio(self) -> None:
        settings = Settings(storage_backend=StorageBackend.AZURE_BLOB)
        logger = create_portfolio_logger(settings)
        assert isinstance(logger, AzureBlobPortfolioLogger)


class TestAzureStubBehavior:
    """Verify Azure stubs degrade gracefully when SDK is not installed."""

    @pytest.mark.asyncio
    async def test_get_returns_none(self) -> None:
        store = AzureBlobMemoryStore()
        result = await store.get_learner_state("any")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_is_noop(self) -> None:
        from learning_navigator.contracts.learner_state import LearnerState

        store = AzureBlobMemoryStore()
        # Should not raise
        await store.save_learner_state(LearnerState(learner_id="test"))

    @pytest.mark.asyncio
    async def test_delete_returns_false(self) -> None:
        store = AzureBlobMemoryStore()
        assert await store.delete_learner_state("any") is False

    @pytest.mark.asyncio
    async def test_list_returns_empty(self) -> None:
        store = AzureBlobMemoryStore()
        assert await store.list_learner_ids() == []

    @pytest.mark.asyncio
    async def test_portfolio_append_noop(self) -> None:
        from datetime import datetime, timezone

        from learning_navigator.storage.interfaces import PortfolioEntry

        logger = AzureBlobPortfolioLogger()
        entry = PortfolioEntry(
            entry_id="e1",
            learner_id="s1",
            entry_type="test",
            timestamp=datetime.now(timezone.utc),
        )
        await logger.append(entry)  # Should not raise

    @pytest.mark.asyncio
    async def test_portfolio_get_empty(self) -> None:
        logger = AzureBlobPortfolioLogger()
        assert await logger.get_entries("any") == []
        assert await logger.count("any") == 0
