"""Tests for Features 1-5: explainability, expected impact, weekly summary.

Covers:
- Explainability block presence and structure in NextBestAction
- Expected impact computation boundaries
- Weekly summary unavailable mode (no Azure OpenAI)
- Weekly summary generation (mocked LLM client)
- Dynamic agent count (implemented_agents field)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_navigator.contracts.events import (
    Explainability,
    ExpectedImpact,
    ExplainabilityFactor,
    DecisionTrace,
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
)
from learning_navigator.engine.event_bus import InMemoryEventBus
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.storage.local_store import (
    LocalJsonMemoryStore,
    LocalJsonPortfolioLogger,
)


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture()
def memory_store(tmp_path) -> LocalJsonMemoryStore:
    return LocalJsonMemoryStore(data_dir=tmp_path)


@pytest.fixture()
def portfolio_logger(tmp_path) -> LocalJsonPortfolioLogger:
    return LocalJsonPortfolioLogger(data_dir=tmp_path)


@pytest.fixture()
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture()
def engine(memory_store, portfolio_logger, event_bus) -> LearningGPSEngine:
    return LearningGPSEngine(
        memory_store=memory_store,
        portfolio_logger=portfolio_logger,
        event_bus=event_bus,
    )


def _quiz_event(
    learner_id: str = "test-learner",
    concept_id: str = "algebra",
    score: float = 0.8,
) -> LearnerEvent:
    return LearnerEvent(
        event_id="evt-test-1",
        learner_id=learner_id,
        event_type=LearnerEventType.QUIZ_RESULT,
        concept_id=concept_id,
        data={"score": score, "max_score": 1.0},
    )


# ═══════════════════════════════════════════════════════════════════
# Feature 1: Dynamic Agent Count
# ═══════════════════════════════════════════════════════════════════

class TestDynamicAgentCount:
    """Tests for implemented_agents count in agent status."""

    def test_agent_diagnostics_returns_implemented_count(self) -> None:
        from learning_navigator.api.agent_diagnostics import (
            get_agents_status,
            get_system_summary,
        )

        agents = get_agents_status()
        summary = get_system_summary(agents)

        assert "implemented" in summary
        assert "total" in summary
        assert isinstance(summary["implemented"], int)
        assert isinstance(summary["total"], int)
        assert summary["implemented"] >= 0
        assert summary["total"] >= summary["implemented"]
        assert summary["total"] == len(agents)

    def test_implemented_count_matches_status_filter(self) -> None:
        from learning_navigator.api.agent_diagnostics import (
            get_agents_status,
            get_system_summary,
        )

        agents = get_agents_status()
        summary = get_system_summary(agents)

        manual_count = sum(1 for a in agents if a["status"] == "implemented")
        assert summary["implemented"] == manual_count


# ═══════════════════════════════════════════════════════════════════
# Feature 2: Explainability Block
# ═══════════════════════════════════════════════════════════════════

class TestExplainabilityBlock:
    """Tests that NextBestAction includes explainability derived from real signals."""

    @pytest.mark.asyncio()
    async def test_nba_has_explainability(self, engine) -> None:
        """process_event returns a NextBestAction with an explainability field."""
        event = _quiz_event()
        result = await engine.process_event(event)
        assert isinstance(result, NextBestAction)
        assert hasattr(result, "explainability")
        assert isinstance(result.explainability, Explainability)

    @pytest.mark.asyncio()
    async def test_explainability_has_decision_trace(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        trace = result.explainability.decision_trace
        assert isinstance(trace, DecisionTrace)
        assert isinstance(trace.ran_agents, list)
        assert isinstance(trace.skipped_agents, list)

    @pytest.mark.asyncio()
    async def test_explainability_top_factors_bounded(self, engine) -> None:
        """Top factors should have at most 6 items."""
        event = _quiz_event()
        result = await engine.process_event(event)
        assert len(result.explainability.top_factors) <= 6

    @pytest.mark.asyncio()
    async def test_explainability_factor_structure(self, engine) -> None:
        """Each factor should have agent_id, agent_name, signal, evidence."""
        event = _quiz_event()
        result = await engine.process_event(event)
        for factor in result.explainability.top_factors:
            assert factor.agent_id
            assert factor.agent_name
            assert factor.signal
            assert factor.evidence

    @pytest.mark.asyncio()
    async def test_diagnoser_factor_present_for_quiz(self, engine) -> None:
        """Quiz events should produce a diagnoser factor."""
        event = _quiz_event()
        result = await engine.process_event(event)
        agent_ids = [f.agent_id for f in result.explainability.top_factors]
        assert "diagnoser" in agent_ids

    def test_explainability_model_serialization(self) -> None:
        """Explainability model serializes to JSON correctly."""
        exp = Explainability(
            top_factors=[
                ExplainabilityFactor(
                    agent_id="diagnoser",
                    agent_name="Diagnoser",
                    signal="mastery_gap_detected",
                    evidence="Found gap in algebra",
                    confidence=0.8,
                ),
            ],
            decision_trace=DecisionTrace(
                ran_agents=["diagnoser", "planner"],
                skipped_agents=["rag-agent"],
            ),
        )
        data = exp.model_dump(mode="json")
        assert len(data["top_factors"]) == 1
        assert data["top_factors"][0]["agent_id"] == "diagnoser"
        assert len(data["decision_trace"]["ran_agents"]) == 2


# ═══════════════════════════════════════════════════════════════════
# Feature 3: Expected Impact Boundaries
# ═══════════════════════════════════════════════════════════════════

class TestExpectedImpact:
    """Tests for expected impact computation."""

    @pytest.mark.asyncio()
    async def test_nba_has_expected_impact(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        assert hasattr(result, "expected_impact")
        assert isinstance(result.expected_impact, ExpectedImpact)

    @pytest.mark.asyncio()
    async def test_expected_impact_has_assumptions(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        assert isinstance(result.expected_impact.assumptions, list)
        assert len(result.expected_impact.assumptions) >= 1

    @pytest.mark.asyncio()
    async def test_mastery_gain_bounded(self, engine, memory_store) -> None:
        """Mastery gain should be between 0 and 0.15 (conservative)."""
        # Pre-populate with a concept
        state = LearnerState(learner_id="bounded-test")
        state.upsert_concept(
            ConceptState(concept_id="algebra", bkt=BKTParams(p_know=0.3))
        )
        await memory_store.save_learner_state(state)

        event = _quiz_event(learner_id="bounded-test", concept_id="algebra", score=0.7)
        result = await engine.process_event(event)

        gain = result.expected_impact.mastery_gain_estimate
        if gain is not None:
            assert 0.0 <= gain <= 0.15

    @pytest.mark.asyncio()
    async def test_time_horizon_default(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        if result.expected_impact.time_horizon_days is not None:
            assert result.expected_impact.time_horizon_days == 7

    def test_expected_impact_model_with_no_data(self) -> None:
        """ExpectedImpact with no numeric data should have assumptions."""
        impact = ExpectedImpact(
            assumptions=["Insufficient history for numeric estimate"],
        )
        data = impact.model_dump(mode="json")
        assert data["mastery_gain_estimate"] is None
        assert len(data["assumptions"]) == 1


# ═══════════════════════════════════════════════════════════════════
# Feature 5: Weekly Summary — Unavailable Mode
# ═══════════════════════════════════════════════════════════════════

class TestWeeklySummaryUnavailable:
    """Tests for weekly summary when Azure OpenAI is NOT configured."""

    @pytest.mark.asyncio()
    async def test_generate_returns_unavailable_when_no_llm(self) -> None:
        """When LLM is disabled, generate_weekly_summary returns status=unavailable."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary

        # Mock a db (we won't actually hit it for unavailable mode)
        mock_db = AsyncMock()
        mock_db.executescript = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.enabled = False
            mock_get.return_value = mock_client

            result = await generate_weekly_summary(
                mock_db,
                user_id="test-user",
                events=[],
                portfolio_entries=[],
            )

        assert result["status"] == "unavailable"
        assert "Azure OpenAI" in result.get("message", "")
        assert result["summary_text"] == ""


# ═══════════════════════════════════════════════════════════════════
# Feature 5: Weekly Summary — Generation with Mock LLM
# ═══════════════════════════════════════════════════════════════════

class TestWeeklySummaryGeneration:
    """Tests for weekly summary generation with a mocked LLM client."""

    @pytest.mark.asyncio()
    async def test_generate_with_mock_llm(self) -> None:
        """When LLM is available, generate_weekly_summary returns a proper summary."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary
        from learning_navigator.llm.azure_client import LLMResponse

        mock_db = AsyncMock()
        mock_db.executescript = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock()

        llm_response_content = json.dumps({
            "summary_text": "This week you made great progress in Algebra.",
            "highlights": ["Improved algebra mastery", "Consistent study sessions"],
            "focus_items": ["Review geometry basics"],
            "burnout_flag": False,
            "evidence_bullets": ["Practiced Algebra 3 times", "Mastery went from 50% to 65%"],
        })

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.enabled = True
            mock_client.chat = AsyncMock(return_value=LLMResponse(
                content=llm_response_content,
                model="gpt-4o",
                usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
            ))
            mock_get.return_value = mock_client

            result = await generate_weekly_summary(
                mock_db,
                user_id="test-user",
                events=[
                    {"concept": "algebra", "event_type": "quiz_result", "score": 0.8},
                ],
                portfolio_entries=[],
                learner_state={
                    "concepts": {
                        "algebra": {
                            "concept_id": "algebra",
                            "display_name": "Algebra",
                            "bkt": {"p_know": 0.65},
                            "forgetting_score": 0.2,
                        }
                    },
                    "motivation": {"level": "MEDIUM", "score": 0.6, "trend": 0.05},
                    "session_count": 12,
                },
            )

        assert result["status"] == "generated"
        assert "great progress" in result["summary_text"]
        assert len(result["highlights"]) == 2
        assert len(result["focus_items"]) == 1
        assert result["burnout_flag"] is False
        assert result["disclaimer"]  # Must have a disclaimer
        assert result["model_used"] == "gpt-4o"

    @pytest.mark.asyncio()
    async def test_generate_with_llm_failure(self) -> None:
        """When LLM call fails, returns status=error."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary

        mock_db = AsyncMock()
        mock_db.executescript = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock()

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.enabled = True
            mock_client.chat = AsyncMock(return_value=None)  # LLM call failed
            mock_get.return_value = mock_client

            result = await generate_weekly_summary(
                mock_db,
                user_id="test-user",
                events=[],
                portfolio_entries=[],
            )

        assert result["status"] == "error"
        assert result["summary_text"]  # Should have a fallback message

    @pytest.mark.asyncio()
    async def test_storage_persistence(self) -> None:
        """Summary should be saved to DB."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary
        from learning_navigator.llm.azure_client import LLMResponse

        mock_db = AsyncMock()
        mock_db.executescript = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock()

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.enabled = True
            mock_client.chat = AsyncMock(return_value=LLMResponse(
                content=json.dumps({
                    "summary_text": "Test summary",
                    "highlights": [],
                    "focus_items": [],
                    "burnout_flag": False,
                    "evidence_bullets": [],
                }),
                model="gpt-4o",
                usage={"total_tokens": 50},
            ))
            mock_get.return_value = mock_client

            await generate_weekly_summary(mock_db, "test-user", [], [])

        # Verify DB execute was called for INSERT
        calls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("INSERT" in c for c in calls)
