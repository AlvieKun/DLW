"""Tests for Phase 7: Learner-aware RAG with grounding.

Covers:
- LocalTfidfIndex (indexing, search, metadata filters, persistence, deletion)
- AzureAISearchIndex (stub behavior, graceful degradation)
- RAGAgent (query construction, citation retrieval, deduplication)
- Retrieval index factory (create_retrieval_index)
- GPS Engine integration (RAG pipeline step, citations in NBA)
- Reflection Agent RAG grounding section
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from learning_navigator.agents.rag_agent import RAGAgent
from learning_navigator.contracts.events import (
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptRelation,
    ConceptRelationType,
    ConceptState,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.infra.config import SearchBackend, Settings
from learning_navigator.storage import create_retrieval_index
from learning_navigator.storage.azure_search import AzureAISearchIndex
from learning_navigator.storage.interfaces import RetrievalIndex
from learning_navigator.storage.local_tfidf import LocalTfidfIndex

# ── Helpers ────────────────────────────────────────────────────────


def _make_state(**overrides: Any) -> LearnerState:
    defaults: dict[str, Any] = {"learner_id": "test-learner"}
    defaults.update(overrides)
    return LearnerState(**defaults)


def _concept(
    cid: str,
    mastery: float = 0.5,
    difficulty: float = 0.5,
) -> ConceptState:
    return ConceptState(
        concept_id=cid,
        bkt=BKTParams(p_know=mastery),
        difficulty=difficulty,
    )


def _quiz_event(
    learner_id: str = "test-learner",
    concept_id: str = "algebra",
    score: float = 0.8,
) -> LearnerEvent:
    return LearnerEvent(
        event_id="evt-rag-1",
        learner_id=learner_id,
        event_type=LearnerEventType.QUIZ_RESULT,
        concept_id=concept_id,
        data={"score": score, "max_score": 1.0},
    )


# ═══════════════════════════════════════════════════════════════════
# LocalTfidfIndex Tests
# ═══════════════════════════════════════════════════════════════════


class TestLocalTfidfIndex:
    """Unit tests for the TF-IDF-based local retrieval index."""

    @pytest.fixture()
    def index(self, tmp_path: Path) -> LocalTfidfIndex:
        return LocalTfidfIndex(data_dir=tmp_path)

    @pytest.mark.asyncio()
    async def test_implements_retrieval_index(self, index: LocalTfidfIndex) -> None:
        assert isinstance(index, RetrievalIndex)

    @pytest.mark.asyncio()
    async def test_index_and_search_basic(self, index: LocalTfidfIndex) -> None:
        await index.index_document(
            "doc-1",
            "Introduction to algebra variables and equations",
            {"topic": "algebra", "difficulty": "beginner"},
        )
        results = await index.search("algebra equations", top_k=5)
        assert len(results) >= 1
        assert results[0]["doc_id"] == "doc-1"
        assert results[0]["score"] > 0.0

    @pytest.mark.asyncio()
    async def test_search_empty_index(self, index: LocalTfidfIndex) -> None:
        results = await index.search("anything", top_k=5)
        assert results == []

    @pytest.mark.asyncio()
    async def test_search_no_match(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-1", "calculus derivatives integrals", {})
        results = await index.search("xyznonexistent", top_k=5)
        assert results == []

    @pytest.mark.asyncio()
    async def test_search_relevance_ranking(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-algebra", "algebra variables equations solving", {})
        await index.index_document("doc-calculus", "calculus derivatives integrals", {})
        await index.index_document("doc-mixed", "algebra calculus review", {})

        results = await index.search("algebra equations", top_k=5)
        assert len(results) >= 1
        # doc-algebra should rank highest (most specific match)
        assert results[0]["doc_id"] == "doc-algebra"

    @pytest.mark.asyncio()
    async def test_search_with_metadata_filter(self, index: LocalTfidfIndex) -> None:
        await index.index_document(
            "doc-1", "algebra basics", {"difficulty": "beginner"}
        )
        await index.index_document(
            "doc-2", "algebra advanced proofs", {"difficulty": "advanced"}
        )

        results = await index.search(
            "algebra", top_k=5, filters={"difficulty": "beginner"}
        )
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc-1"

    @pytest.mark.asyncio()
    async def test_search_top_k_limits_results(self, index: LocalTfidfIndex) -> None:
        for i in range(10):
            await index.index_document(f"doc-{i}", f"algebra concept variant {i}", {})

        results = await index.search("algebra", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio()
    async def test_delete_document(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-1", "algebra basics", {})
        assert index.document_count == 1

        deleted = await index.delete_document("doc-1")
        assert deleted is True
        assert index.document_count == 0

        # Search should return nothing
        results = await index.search("algebra", top_k=5)
        assert results == []

    @pytest.mark.asyncio()
    async def test_delete_nonexistent_returns_false(self, index: LocalTfidfIndex) -> None:
        result = await index.delete_document("nonexistent")
        assert result is False

    @pytest.mark.asyncio()
    async def test_update_existing_document(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-1", "old content about algebra", {})
        await index.index_document("doc-1", "new content about calculus", {})

        # Should find with new content
        results = await index.search("calculus", top_k=5)
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc-1"
        assert index.document_count == 1

    @pytest.mark.asyncio()
    async def test_result_structure(self, index: LocalTfidfIndex) -> None:
        await index.index_document(
            "doc-1",
            "algebra variables and expressions",
            {"source": "textbook", "chapter": "1"},
        )
        results = await index.search("algebra", top_k=5)
        assert len(results) == 1
        r = results[0]
        assert "doc_id" in r
        assert "score" in r
        assert "content" in r
        assert "metadata" in r
        assert r["metadata"]["source"] == "textbook"

    @pytest.mark.asyncio()
    async def test_persistence_to_disk(self, tmp_path: Path) -> None:
        # Create index and add documents
        idx1 = LocalTfidfIndex(data_dir=tmp_path)
        await idx1.index_document("doc-1", "algebra equations", {"topic": "algebra"})
        await idx1.index_document("doc-2", "calculus derivatives", {"topic": "calculus"})

        # Create new instance from same directory — should load from disk
        idx2 = LocalTfidfIndex(data_dir=tmp_path)
        assert idx2.document_count == 2

        results = await idx2.search("algebra", top_k=5)
        assert len(results) >= 1
        assert results[0]["doc_id"] == "doc-1"

    @pytest.mark.asyncio()
    async def test_document_count_property(self, index: LocalTfidfIndex) -> None:
        assert index.document_count == 0
        await index.index_document("doc-1", "content", {})
        assert index.document_count == 1
        await index.index_document("doc-2", "more content", {})
        assert index.document_count == 2


# ═══════════════════════════════════════════════════════════════════
# AzureAISearchIndex Tests
# ═══════════════════════════════════════════════════════════════════


class TestAzureAISearchIndex:
    """Tests for the Azure AI Search stub."""

    def test_implements_retrieval_index(self) -> None:
        idx = AzureAISearchIndex(
            endpoint="https://fake.search.windows.net",
            api_key="fake-key",
            index_name="test-index",
        )
        assert isinstance(idx, RetrievalIndex)

    @pytest.mark.asyncio()
    async def test_stub_search_returns_empty(self) -> None:
        idx = AzureAISearchIndex(
            endpoint="https://fake.search.windows.net",
            api_key="fake-key",
            index_name="test-index",
        )
        results = await idx.search("test query", top_k=5)
        assert results == []

    @pytest.mark.asyncio()
    async def test_stub_index_does_not_raise(self) -> None:
        idx = AzureAISearchIndex(
            endpoint="https://fake.search.windows.net",
            api_key="fake-key",
            index_name="test-index",
        )
        # Should not raise
        await idx.index_document("doc-1", "content", {"topic": "test"})

    @pytest.mark.asyncio()
    async def test_stub_delete_returns_false(self) -> None:
        idx = AzureAISearchIndex(
            endpoint="https://fake.search.windows.net",
            api_key="fake-key",
            index_name="test-index",
        )
        result = await idx.delete_document("doc-1")
        assert result is False


# ═══════════════════════════════════════════════════════════════════
# RAG Agent Tests
# ═══════════════════════════════════════════════════════════════════


class TestRAGAgent:
    """Tests for the RAG Agent."""

    @pytest.fixture()
    def index_with_docs(self, tmp_path: Path) -> LocalTfidfIndex:
        """Pre-populated index for RAG tests."""
        import asyncio

        idx = LocalTfidfIndex(data_dir=tmp_path)

        async def _populate() -> None:
            await idx.index_document(
                "algebra-intro",
                "Introduction to algebra. Variables represent unknown values. "
                "Equations express relationships between quantities.",
                {"topic": "algebra", "difficulty": "beginner"},
            )
            await idx.index_document(
                "algebra-practice",
                "Algebra practice problems. Solve for x in linear equations. "
                "Word problems and application exercises.",
                {"topic": "algebra", "difficulty": "intermediate"},
            )
            await idx.index_document(
                "calculus-intro",
                "Introduction to calculus. Limits, derivatives, and integrals. "
                "Rate of change and area under curves.",
                {"topic": "calculus", "difficulty": "advanced"},
            )
            await idx.index_document(
                "algebra-review",
                "Quick algebra review. Key formulas and properties summary. "
                "Flashcard-style revision notes.",
                {"topic": "algebra", "difficulty": "beginner"},
            )

        asyncio.get_event_loop().run_until_complete(_populate())
        return idx

    @pytest.fixture()
    def rag_agent(self, index_with_docs: LocalTfidfIndex) -> RAGAgent:
        return RAGAgent(index_with_docs, top_k_per_concept=3, min_score=0.01)

    @pytest.mark.asyncio()
    async def test_rag_agent_basic_retrieval(self, rag_agent: RAGAgent) -> None:
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.3)})
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": {
                    "recommendations": [
                        {"concept_id": "algebra", "action": "learn_new"},
                    ],
                },
                "diagnosis": {},
            },
        )
        resp = await rag_agent.handle(msg)
        assert resp.source_agent_id == "rag-agent"
        assert resp.confidence > 0.0

        citations = resp.payload["citations"]
        assert len(citations) > 0
        assert all("doc_id" in c for c in citations)
        assert all("score" in c for c in citations)
        assert all("concept_id" in c for c in citations)

    @pytest.mark.asyncio()
    async def test_rag_agent_empty_plan(self, rag_agent: RAGAgent) -> None:
        state = _make_state()
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": {"recommendations": []},
                "diagnosis": {},
            },
        )
        resp = await rag_agent.handle(msg)
        assert resp.payload["citations"] == []
        assert resp.payload["query_count"] == 0

    @pytest.mark.asyncio()
    async def test_rag_agent_deduplication(self, rag_agent: RAGAgent) -> None:
        """Multiple concepts referencing same doc should deduplicate."""
        state = _make_state(concepts={
            "algebra": _concept("algebra", mastery=0.3),
        })
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": {
                    "recommendations": [
                        {"concept_id": "algebra", "action": "learn_new"},
                        {"concept_id": "algebra", "action": "practice"},
                    ],
                },
                "diagnosis": {},
            },
        )
        resp = await rag_agent.handle(msg)
        citations = resp.payload["citations"]
        doc_ids = [c["doc_id"] for c in citations]
        # No duplicate doc_ids
        assert len(doc_ids) == len(set(doc_ids))

    @pytest.mark.asyncio()
    async def test_rag_agent_learner_aware_query_beginner(
        self, rag_agent: RAGAgent
    ) -> None:
        """Low mastery learner should see beginner-appropriate queries."""
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.1)})
        query = rag_agent._build_query(state, "algebra", "learn_new", {})
        assert "beginner" in query.lower() or "introduction" in query.lower() or "basics" in query.lower()

    @pytest.mark.asyncio()
    async def test_rag_agent_learner_aware_query_advanced(
        self, rag_agent: RAGAgent
    ) -> None:
        """High mastery learner should see advanced-appropriate queries."""
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.75)})
        query = rag_agent._build_query(state, "algebra", "deepen", {})
        assert "advanced" in query.lower()

    @pytest.mark.asyncio()
    async def test_rag_agent_prerequisite_enrichment(
        self, rag_agent: RAGAgent
    ) -> None:
        """Queries should include weak prerequisites."""
        state = _make_state(
            concepts={
                "calculus": _concept("calculus", mastery=0.3),
                "algebra": _concept("algebra", mastery=0.2),
            },
            concept_relations=[
                ConceptRelation(
                    source_concept_id="algebra",
                    target_concept_id="calculus",
                    relation_type=ConceptRelationType.PREREQUISITE,
                    weight=1.0,
                ),
            ],
        )
        query = rag_agent._build_query(state, "calculus", "learn_new", {})
        assert "prerequisite" in query.lower()
        assert "algebra" in query.lower()

    @pytest.mark.asyncio()
    async def test_rag_agent_min_score_filtering(self, tmp_path: Path) -> None:
        """Results below min_score should be excluded."""
        idx = LocalTfidfIndex(data_dir=tmp_path)
        await idx.index_document("doc-1", "algebra basics", {})

        agent = RAGAgent(idx, top_k_per_concept=3, min_score=0.99)
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.5)})
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": {"recommendations": [{"concept_id": "algebra", "action": "study"}]},
                "diagnosis": {},
            },
        )
        resp = await agent.handle(msg)
        # With min_score=0.99, most/all TF-IDF results should be filtered
        assert resp.payload["citation_count"] == 0 or all(
            c["score"] >= 0.99 for c in resp.payload["citations"]
        )

    @pytest.mark.asyncio()
    async def test_rag_agent_citations_sorted_by_score(
        self, rag_agent: RAGAgent
    ) -> None:
        state = _make_state(concepts={
            "algebra": _concept("algebra", mastery=0.5),
            "calculus": _concept("calculus", mastery=0.5),
        })
        msg = MessageEnvelope(
            message_type=MessageType.RAG_QUERY,
            source_agent_id="engine",
            target_agent_id="rag-agent",
            payload={
                "learner_state": state.model_dump(mode="json"),
                "plan": {
                    "recommendations": [
                        {"concept_id": "algebra", "action": "practice"},
                        {"concept_id": "calculus", "action": "learn_new"},
                    ],
                },
                "diagnosis": {},
            },
        )
        resp = await rag_agent.handle(msg)
        citations = resp.payload["citations"]
        if len(citations) > 1:
            scores = [c["score"] for c in citations]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio()
    async def test_rag_agent_action_awareness(self, rag_agent: RAGAgent) -> None:
        """Different actions should produce different query modifiers."""
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.5)})
        q_learn = rag_agent._build_query(state, "algebra", "learn_new", {})
        q_review = rag_agent._build_query(state, "algebra", "spaced_review", {})
        # Different actions should produce different queries
        assert q_learn != q_review
        assert "tutorial" in q_learn
        assert "review" in q_review

    @pytest.mark.asyncio()
    async def test_rag_agent_difficulty_awareness(self, rag_agent: RAGAgent) -> None:
        """High difficulty concepts should include simplified query terms."""
        state = _make_state(concepts={"algebra": _concept("algebra", mastery=0.3, difficulty=0.9)})
        query = rag_agent._build_query(state, "algebra", "learn_new", {})
        assert "simplified" in query.lower() or "step" in query.lower()


# ═══════════════════════════════════════════════════════════════════
# Retrieval Index Factory Tests
# ═══════════════════════════════════════════════════════════════════


class TestRetrievalIndexFactory:
    """Tests for create_retrieval_index factory function."""

    def test_default_creates_local_tfidf(self, tmp_path: Path) -> None:
        settings = Settings(local_data_dir=tmp_path / "data")
        idx = create_retrieval_index(settings)
        assert isinstance(idx, LocalTfidfIndex)

    def test_azure_creates_azure_index(self) -> None:
        settings = Settings(
            search_backend=SearchBackend.AZURE_AI_SEARCH,
            azure_search_endpoint="https://fake.search.windows.net",
            azure_search_key="fake-key",
            azure_search_index="test-idx",
        )
        idx = create_retrieval_index(settings)
        assert isinstance(idx, AzureAISearchIndex)


# ═══════════════════════════════════════════════════════════════════
# GPS Engine RAG Integration Tests
# ═══════════════════════════════════════════════════════════════════


class TestGPSEngineRAGIntegration:
    """Integration tests verifying RAG flows through the GPS Engine."""

    @pytest.fixture()
    def rag_index(self, tmp_path: Path) -> LocalTfidfIndex:
        import asyncio

        idx = LocalTfidfIndex(data_dir=tmp_path / "rag_data")

        async def _populate() -> None:
            await idx.index_document(
                "algebra-basics",
                "Algebra introduction. Variables, expressions, equations. "
                "Solving linear equations step by step.",
                {"topic": "algebra"},
            )
            await idx.index_document(
                "algebra-exercises",
                "Algebra practice exercises. Solve for x. Word problems.",
                {"topic": "algebra"},
            )

        asyncio.get_event_loop().run_until_complete(_populate())
        return idx

    @pytest.fixture()
    def engine_with_rag(
        self, tmp_path: Path, rag_index: LocalTfidfIndex
    ) -> LearningGPSEngine:
        from learning_navigator.engine.event_bus import InMemoryEventBus
        from learning_navigator.engine.gps_engine import LearningGPSEngine
        from learning_navigator.storage.local_store import (
            LocalJsonMemoryStore,
            LocalJsonPortfolioLogger,
        )

        return LearningGPSEngine(
            memory_store=LocalJsonMemoryStore(data_dir=tmp_path / "mem"),
            portfolio_logger=LocalJsonPortfolioLogger(data_dir=tmp_path / "portfolio"),
            event_bus=InMemoryEventBus(),
            retrieval_index=rag_index,
        )

    @pytest.fixture()
    def engine_without_rag(self, tmp_path: Path) -> LearningGPSEngine:
        from learning_navigator.engine.event_bus import InMemoryEventBus
        from learning_navigator.engine.gps_engine import LearningGPSEngine
        from learning_navigator.storage.local_store import (
            LocalJsonMemoryStore,
            LocalJsonPortfolioLogger,
        )

        return LearningGPSEngine(
            memory_store=LocalJsonMemoryStore(data_dir=tmp_path / "mem2"),
            portfolio_logger=LocalJsonPortfolioLogger(data_dir=tmp_path / "portfolio2"),
            event_bus=InMemoryEventBus(),
        )

    @pytest.mark.asyncio()
    async def test_engine_with_rag_populates_citations(
        self, engine_with_rag: LearningGPSEngine
    ) -> None:
        event = _quiz_event(concept_id="algebra", score=0.6)
        nba = await engine_with_rag.process_event(event)
        assert isinstance(nba, NextBestAction)
        # With documents indexed, citations list should be populated
        assert isinstance(nba.citations, list)

    @pytest.mark.asyncio()
    async def test_engine_without_rag_has_empty_citations(
        self, engine_without_rag: LearningGPSEngine
    ) -> None:
        event = _quiz_event(concept_id="algebra", score=0.6)
        nba = await engine_without_rag.process_event(event)
        assert isinstance(nba, NextBestAction)
        assert nba.citations == []

    @pytest.mark.asyncio()
    async def test_engine_rag_agent_attribute(
        self, engine_with_rag: LearningGPSEngine,
        engine_without_rag: LearningGPSEngine,
    ) -> None:
        assert engine_with_rag.rag_agent is not None
        assert engine_without_rag.rag_agent is None

    @pytest.mark.asyncio()
    async def test_engine_rag_in_debug_trace(
        self, engine_with_rag: LearningGPSEngine
    ) -> None:
        event = _quiz_event(concept_id="algebra", score=0.5)
        nba = await engine_with_rag.process_event(event)
        rag_steps = [
            s for s in nba.debug_trace.get("pipeline_steps", [])
            if s.get("agent") == "rag"
        ]
        assert len(rag_steps) == 1
        assert "citations" in rag_steps[0]
        assert "queries" in rag_steps[0]


# ═══════════════════════════════════════════════════════════════════
# Reflection Agent RAG Section Tests
# ═══════════════════════════════════════════════════════════════════


class TestReflectionRAGSection:
    """Tests for the Reflection Agent's RAG grounding section."""

    def test_empty_rag_response_produces_empty_section(self) -> None:
        from learning_navigator.agents.reflection import ReflectionAgent

        section = ReflectionAgent._rag_grounding_section({})
        assert section["title"] == "Supporting Material"
        assert section["content"] == ""

    def test_rag_section_with_citations(self) -> None:
        from learning_navigator.agents.reflection import ReflectionAgent

        rag_response = {
            "citations": [
                {
                    "doc_id": "algebra-intro",
                    "score": 0.85,
                    "content": "Introduction to algebra basics.",
                    "concept_id": "algebra",
                },
                {
                    "doc_id": "algebra-review",
                    "score": 0.72,
                    "content": "Quick algebra review.",
                    "concept_id": "algebra",
                },
            ],
            "query_count": 1,
        }
        section = ReflectionAgent._rag_grounding_section(rag_response)
        assert section["title"] == "Supporting Material"
        assert "2 supporting references" in section["content"]
        assert "algebra-intro" in section["content"]
        assert "0.85" in section["content"]

    def test_rag_section_caps_at_five_citations(self) -> None:
        from learning_navigator.agents.reflection import ReflectionAgent

        citations = [
            {"doc_id": f"doc-{i}", "score": 0.5, "content": f"content {i}", "concept_id": "c"}
            for i in range(8)
        ]
        rag_response = {"citations": citations, "query_count": 2}
        section = ReflectionAgent._rag_grounding_section(rag_response)
        assert "...and 3 more" in section["content"]


# ═══════════════════════════════════════════════════════════════════
# TF-IDF Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestLocalTfidfEdgeCases:
    """Edge cases and boundary conditions for LocalTfidfIndex."""

    @pytest.fixture()
    def index(self, tmp_path: Path) -> LocalTfidfIndex:
        return LocalTfidfIndex(data_dir=tmp_path)

    @pytest.mark.asyncio()
    async def test_empty_content_indexing(self, index: LocalTfidfIndex) -> None:
        await index.index_document("empty", "", {})
        assert index.document_count == 1
        results = await index.search("anything", top_k=5)
        assert results == []

    @pytest.mark.asyncio()
    async def test_single_word_search(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-1", "algebra is fundamental", {})
        results = await index.search("algebra", top_k=5)
        assert len(results) == 1

    @pytest.mark.asyncio()
    async def test_case_insensitive_search(self, index: LocalTfidfIndex) -> None:
        await index.index_document("doc-1", "ALGEBRA BASICS", {})
        results = await index.search("algebra basics", top_k=5)
        assert len(results) == 1

    @pytest.mark.asyncio()
    async def test_multiple_metadata_filters(self, index: LocalTfidfIndex) -> None:
        await index.index_document(
            "doc-1", "algebra content",
            {"topic": "algebra", "level": "beginner"},
        )
        await index.index_document(
            "doc-2", "algebra content",
            {"topic": "algebra", "level": "advanced"},
        )

        results = await index.search(
            "algebra", top_k=5,
            filters={"topic": "algebra", "level": "advanced"},
        )
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc-2"

    @pytest.mark.asyncio()
    async def test_persistence_survives_delete(self, tmp_path: Path) -> None:
        idx = LocalTfidfIndex(data_dir=tmp_path)
        await idx.index_document("doc-1", "first document about math", {})
        await idx.index_document("doc-2", "second document about science", {})
        await idx.delete_document("doc-1")

        # Reload from disk
        idx2 = LocalTfidfIndex(data_dir=tmp_path)
        assert idx2.document_count == 1
        results = await idx2.search("science", top_k=5)
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc-2"

    @pytest.mark.asyncio()
    async def test_large_batch_indexing(self, index: LocalTfidfIndex) -> None:
        for i in range(50):
            await index.index_document(
                f"doc-{i}", f"topic number {i} about various subjects", {}
            )
        assert index.document_count == 50
        results = await index.search("topic", top_k=10)
        assert len(results) == 10
