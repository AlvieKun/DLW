"""Tests for storage implementations — LocalJsonMemoryStore, LocalJsonPortfolioLogger."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
)
from learning_navigator.storage.interfaces import PortfolioEntry
from learning_navigator.storage.local_store import (
    LocalJsonMemoryStore,
    LocalJsonPortfolioLogger,
)


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory for each test."""
    return tmp_path / "test_data"


@pytest.fixture
def memory_store(tmp_data_dir: Path) -> LocalJsonMemoryStore:
    return LocalJsonMemoryStore(data_dir=tmp_data_dir)


@pytest.fixture
def portfolio_logger(tmp_data_dir: Path) -> LocalJsonPortfolioLogger:
    return LocalJsonPortfolioLogger(data_dir=tmp_data_dir)


def _make_state(learner_id: str = "student-1") -> LearnerState:
    s = LearnerState(learner_id=learner_id)
    s.upsert_concept(
        ConceptState(
            concept_id="algebra",
            bkt=BKTParams(p_know=0.6),
        )
    )
    return s


class TestLocalJsonMemoryStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self, memory_store: LocalJsonMemoryStore) -> None:
        state = _make_state("s1")
        await memory_store.save_learner_state(state)
        loaded = await memory_store.get_learner_state("s1")
        assert loaded is not None
        assert loaded.learner_id == "s1"
        assert loaded.get_concept("algebra") is not None
        assert loaded.get_concept("algebra").mastery == pytest.approx(0.6)  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, memory_store: LocalJsonMemoryStore) -> None:
        result = await memory_store.get_learner_state("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self, memory_store: LocalJsonMemoryStore) -> None:
        state = _make_state("s1")
        await memory_store.save_learner_state(state)

        # Update mastery
        c = state.get_concept("algebra")
        assert c is not None
        state.upsert_concept(c.model_copy(update={"bkt": BKTParams(p_know=0.9)}))
        await memory_store.save_learner_state(state)

        loaded = await memory_store.get_learner_state("s1")
        assert loaded is not None
        assert loaded.get_concept("algebra").mastery == pytest.approx(0.9)  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_delete(self, memory_store: LocalJsonMemoryStore) -> None:
        state = _make_state("s1")
        await memory_store.save_learner_state(state)
        assert await memory_store.delete_learner_state("s1") is True
        assert await memory_store.get_learner_state("s1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, memory_store: LocalJsonMemoryStore) -> None:
        assert await memory_store.delete_learner_state("nobody") is False

    @pytest.mark.asyncio
    async def test_list_learner_ids(self, memory_store: LocalJsonMemoryStore) -> None:
        await memory_store.save_learner_state(_make_state("a"))
        await memory_store.save_learner_state(_make_state("b"))
        await memory_store.save_learner_state(_make_state("c"))
        ids = await memory_store.list_learner_ids()
        assert sorted(ids) == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_list_empty(self, memory_store: LocalJsonMemoryStore) -> None:
        ids = await memory_store.list_learner_ids()
        assert ids == []


def _make_entry(learner_id: str = "s1", entry_type: str = "recommendation") -> PortfolioEntry:
    return PortfolioEntry(
        entry_id="e1",
        learner_id=learner_id,
        entry_type=entry_type,
        timestamp=datetime.now(timezone.utc),
        data={"action": "review algebra"},
        source_agent_id="planner",
    )


class TestLocalJsonPortfolioLogger:
    @pytest.mark.asyncio
    async def test_append_and_get(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        entry = _make_entry("s1")
        await portfolio_logger.append(entry)
        entries = await portfolio_logger.get_entries("s1")
        assert len(entries) == 1
        assert entries[0].entry_id == "e1"
        assert entries[0].data["action"] == "review algebra"

    @pytest.mark.asyncio
    async def test_append_multiple(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        for i in range(5):
            entry = PortfolioEntry(
                entry_id=f"e{i}",
                learner_id="s1",
                entry_type="recommendation",
                timestamp=datetime.now(timezone.utc),
                data={"index": i},
            )
            await portfolio_logger.append(entry)
        entries = await portfolio_logger.get_entries("s1")
        assert len(entries) == 5

    @pytest.mark.asyncio
    async def test_filter_by_entry_type(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        await portfolio_logger.append(_make_entry("s1", "recommendation"))
        await portfolio_logger.append(_make_entry("s1", "override"))
        await portfolio_logger.append(_make_entry("s1", "recommendation"))

        recs = await portfolio_logger.get_entries("s1", entry_type="recommendation")
        assert len(recs) == 2
        overrides = await portfolio_logger.get_entries("s1", entry_type="override")
        assert len(overrides) == 1

    @pytest.mark.asyncio
    async def test_limit(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        for i in range(10):
            entry = PortfolioEntry(
                entry_id=f"e{i}",
                learner_id="s1",
                entry_type="recommendation",
                timestamp=datetime.now(timezone.utc),
            )
            await portfolio_logger.append(entry)
        entries = await portfolio_logger.get_entries("s1", limit=3)
        assert len(entries) == 3

    @pytest.mark.asyncio
    async def test_count(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        assert await portfolio_logger.count("s1") == 0
        await portfolio_logger.append(_make_entry("s1"))
        await portfolio_logger.append(_make_entry("s1"))
        assert await portfolio_logger.count("s1") == 2

    @pytest.mark.asyncio
    async def test_get_entries_empty(self, portfolio_logger: LocalJsonPortfolioLogger) -> None:
        entries = await portfolio_logger.get_entries("nonexistent")
        assert entries == []

    @pytest.mark.asyncio
    async def test_entries_isolated_per_learner(
        self, portfolio_logger: LocalJsonPortfolioLogger
    ) -> None:
        await portfolio_logger.append(_make_entry("s1"))
        await portfolio_logger.append(_make_entry("s2"))
        assert len(await portfolio_logger.get_entries("s1")) == 1
        assert len(await portfolio_logger.get_entries("s2")) == 1
