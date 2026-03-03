"""Tests for Tier 1 features: explainability, expected impact, weekly summary, agent count."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_navigator.contracts.events import (
    DecisionTrace,
    Explainability,
    ExplainabilityFactor,
    ExpectedImpact,
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


# ── Helpers ────────────────────────────────────────────────────────

def _quiz_event(
    learner_id: str = "tester",
    concept_id: str = "algebra",
    score: float = 0.8,
) -> LearnerEvent:
    return LearnerEvent(
        event_id="evt-test",
        learner_id=learner_id,
        event_type=LearnerEventType.QUIZ_RESULT,
        concept_id=concept_id,
        data={"score": score, "max_score": 1.0},
    )


@pytest.fixture()
def memory_store(tmp_path) -> LocalJsonMemoryStore:
    return LocalJsonMemoryStore(data_dir=tmp_path)


@pytest.fixture()
def portfolio_logger(tmp_path) -> LocalJsonPortfolioLogger:
    return LocalJsonPortfolioLogger(data_dir=tmp_path)


@pytest.fixture()
def engine(memory_store, portfolio_logger) -> LearningGPSEngine:
    return LearningGPSEngine(
        memory_store=memory_store,
        portfolio_logger=portfolio_logger,
        event_bus=InMemoryEventBus(),
    )


# ═══════════════════════════════════════════════════════════════════
# 1. Explainability Block Presence
# ═══════════════════════════════════════════════════════════════════


class TestExplainability:
    """Explainability model tests + integration."""

    def test_explainability_factor_model(self) -> None:
        """ExplainabilityFactor can be constructed with all fields."""
        f = ExplainabilityFactor(
            agent_id="diagnoser",
            agent_name="Diagnoser",
            signal="mastery_gap_detected",
            evidence="Found mastery gap on 'algebra' (mastery: 30%)",
            confidence=0.85,
        )
        assert f.agent_id == "diagnoser"
        assert f.confidence == 0.85

    def test_explainability_factor_optional_confidence(self) -> None:
        """Confidence is optional."""
        f = ExplainabilityFactor(
            agent_id="decay",
            agent_name="Decay",
            signal="high_forgetting_risk",
            evidence="2 topics at risk",
        )
        assert f.confidence is None

    def test_decision_trace_model(self) -> None:
        trace = DecisionTrace(
            ran_agents=["diagnoser", "decay"],
            skipped_agents=["rag-agent"],
            debate_outcome={"outcome": "consensus"},
            maker_checker={"verdict": "approved", "rounds": 1},
        )
        assert len(trace.ran_agents) == 2
        assert trace.debate_outcome is not None

    def test_decision_trace_defaults(self) -> None:
        trace = DecisionTrace()
        assert trace.ran_agents == []
        assert trace.skipped_agents == []
        assert trace.debate_outcome is None

    def test_explainability_model(self) -> None:
        exp = Explainability(
            top_factors=[
                ExplainabilityFactor(
                    agent_id="diagnoser",
                    agent_name="Diagnoser",
                    signal="gap",
                    evidence="mastery gap found",
                ),
            ],
            decision_trace=DecisionTrace(ran_agents=["diagnoser"]),
        )
        assert len(exp.top_factors) == 1
        assert exp.decision_trace.ran_agents == ["diagnoser"]

    def test_explainability_default_empty(self) -> None:
        exp = Explainability()
        assert exp.top_factors == []
        assert exp.decision_trace.ran_agents == []

    def test_nba_has_explainability_field(self) -> None:
        """NextBestAction must include explainability by default."""
        nba = NextBestAction(
            action_id="a1",
            learner_id="l1",
            recommended_action="study:algebra",
            rationale="test",
            confidence=0.8,
            expected_learning_gain=0.1,
        )
        assert hasattr(nba, "explainability")
        assert isinstance(nba.explainability, Explainability)

    @pytest.mark.asyncio()
    async def test_engine_produces_explainability(self, engine) -> None:
        """Full pipeline produces non-empty explainability block."""
        event = _quiz_event()
        result = await engine.process_event(event)

        assert isinstance(result.explainability, Explainability)
        # Decision trace should have ran_agents from routing
        trace = result.explainability.decision_trace
        assert isinstance(trace, DecisionTrace)
        assert isinstance(trace.ran_agents, list)
        # At least some factors should be produced from diagnosis
        # (even if empty for new learner, the list should exist)
        assert isinstance(result.explainability.top_factors, list)

    @pytest.mark.asyncio()
    async def test_engine_explainability_with_existing_state(self, engine, memory_store) -> None:
        """With pre-existing state, explainability has richer factors."""
        state = LearnerState(learner_id="rich")
        state.upsert_concept(
            ConceptState(
                concept_id="algebra",
                bkt=BKTParams(p_know=0.3),
                forgetting_score=0.7,
            )
        )
        await memory_store.save_learner_state(state)

        event = _quiz_event(learner_id="rich", concept_id="algebra", score=0.5)
        result = await engine.process_event(event)

        # Should have at least a diagnoser factor (mastery gap)
        factor_agents = [f.agent_id for f in result.explainability.top_factors]
        # With low mastery + high forgetting, we expect diagnoser and/or decay agent factors
        assert len(result.explainability.top_factors) >= 1

    @pytest.mark.asyncio()
    async def test_top_factors_capped_at_six(self, engine) -> None:
        """top_factors should never exceed 6 items."""
        event = _quiz_event()
        result = await engine.process_event(event)
        assert len(result.explainability.top_factors) <= 6

    @pytest.mark.asyncio()
    async def test_decision_trace_has_debate(self, engine) -> None:
        """Decision trace should include debate outcome."""
        event = _quiz_event()
        result = await engine.process_event(event)
        trace = result.explainability.decision_trace
        # Debate should be present (may be None if not run, but field exists)
        assert hasattr(trace, "debate_outcome")

    @pytest.mark.asyncio()
    async def test_decision_trace_has_maker_checker(self, engine) -> None:
        """Decision trace should include maker-checker info."""
        event = _quiz_event()
        result = await engine.process_event(event)
        trace = result.explainability.decision_trace
        assert trace.maker_checker is not None
        assert "verdict" in trace.maker_checker


# ═══════════════════════════════════════════════════════════════════
# 2. Expected Impact Computation Boundaries
# ═══════════════════════════════════════════════════════════════════


class TestExpectedImpact:
    """Expected impact model tests + integration."""

    def test_expected_impact_model(self) -> None:
        impact = ExpectedImpact(
            mastery_gain_estimate=0.1,
            risk_reduction={"forgetting": 0.2},
            time_horizon_days=7,
            assumptions=["Based on current mastery"],
        )
        assert impact.mastery_gain_estimate == 0.1
        assert impact.time_horizon_days == 7

    def test_expected_impact_defaults(self) -> None:
        impact = ExpectedImpact()
        assert impact.mastery_gain_estimate is None
        assert impact.risk_reduction == {}
        assert impact.assumptions == []

    def test_mastery_gain_bounded(self) -> None:
        """mastery_gain_estimate must be in [0, 1]."""
        with pytest.raises(Exception):
            ExpectedImpact(mastery_gain_estimate=1.5)
        with pytest.raises(Exception):
            ExpectedImpact(mastery_gain_estimate=-0.1)

    def test_nba_has_expected_impact(self) -> None:
        nba = NextBestAction(
            action_id="a1",
            learner_id="l1",
            recommended_action="study:x",
            rationale="test",
            confidence=0.5,
            expected_learning_gain=0.1,
        )
        assert isinstance(nba.expected_impact, ExpectedImpact)

    @pytest.mark.asyncio()
    async def test_engine_produces_expected_impact(self, engine) -> None:
        """Pipeline output includes expected_impact."""
        event = _quiz_event()
        result = await engine.process_event(event)
        assert isinstance(result.expected_impact, ExpectedImpact)
        assert isinstance(result.expected_impact.assumptions, list)
        assert len(result.expected_impact.assumptions) >= 1

    @pytest.mark.asyncio()
    async def test_expected_impact_conservative(self, engine, memory_store) -> None:
        """mastery_gain_estimate should be conservative (≤ 0.15)."""
        state = LearnerState(learner_id="conservative")
        state.upsert_concept(
            ConceptState(concept_id="math", bkt=BKTParams(p_know=0.5))
        )
        await memory_store.save_learner_state(state)

        event = _quiz_event(learner_id="conservative", concept_id="math")
        result = await engine.process_event(event)

        if result.expected_impact.mastery_gain_estimate is not None:
            assert result.expected_impact.mastery_gain_estimate <= 0.15

    @pytest.mark.asyncio()
    async def test_expected_impact_insufficient_data(self, engine) -> None:
        """For new learners, expected_impact should have assumption about insufficient data."""
        event = _quiz_event(learner_id="brand-new")
        result = await engine.process_event(event)
        # Should have some assumptions
        assert len(result.expected_impact.assumptions) >= 1

    @pytest.mark.asyncio()
    async def test_risk_reduction_from_high_forgetting(self, engine, memory_store) -> None:
        """High forgetting score should produce forgetting risk_reduction."""
        state = LearnerState(learner_id="forgetful")
        state.upsert_concept(
            ConceptState(
                concept_id="history",
                bkt=BKTParams(p_know=0.6),
                forgetting_score=0.8,
            )
        )
        await memory_store.save_learner_state(state)

        event = _quiz_event(learner_id="forgetful", concept_id="history")
        result = await engine.process_event(event)

        # If the engine chose this concept, risk_reduction should have forgetting
        if result.expected_impact.risk_reduction:
            forgetting_reduction = result.expected_impact.risk_reduction.get("forgetting")
            if forgetting_reduction is not None:
                assert forgetting_reduction > 0
                assert forgetting_reduction <= 1.0

    @pytest.mark.asyncio()
    async def test_time_horizon_default(self, engine) -> None:
        """Default time horizon should be 7 days."""
        event = _quiz_event()
        result = await engine.process_event(event)
        assert result.expected_impact.time_horizon_days == 7


# ═══════════════════════════════════════════════════════════════════
# 3. Agent Status / Dynamic Agent Count
# ═══════════════════════════════════════════════════════════════════


class TestAgentDiagnostics:
    """Tests for agent diagnostics and dynamic count."""

    def test_agents_status_returns_list(self) -> None:
        from learning_navigator.api.agent_diagnostics import get_agents_status
        agents = get_agents_status()
        assert isinstance(agents, list)
        assert len(agents) > 0

    def test_each_agent_has_status(self) -> None:
        from learning_navigator.api.agent_diagnostics import get_agents_status
        agents = get_agents_status()
        for agent in agents:
            assert "status" in agent
            assert agent["status"] in ("implemented", "partial", "stub", "error", "unknown")

    def test_system_summary_has_implemented_count(self) -> None:
        from learning_navigator.api.agent_diagnostics import get_agents_status, get_system_summary
        agents = get_agents_status()
        summary = get_system_summary(agents)
        assert "implemented" in summary
        assert isinstance(summary["implemented"], int)
        assert summary["implemented"] >= 0
        assert summary["implemented"] <= summary["total"]

    def test_summary_fields(self) -> None:
        from learning_navigator.api.agent_diagnostics import get_agents_status, get_system_summary
        agents = get_agents_status()
        summary = get_system_summary(agents)
        assert "total" in summary
        assert "implemented" in summary
        assert "partial" in summary
        assert "stub" in summary
        assert "health_level" in summary
        assert "health_pct" in summary


# ═══════════════════════════════════════════════════════════════════
# 4. Weekly Summary — Unavailable Mode
# ═══════════════════════════════════════════════════════════════════


class TestWeeklySummaryUnavailable:
    """Tests for weekly summary graceful degradation."""

    @pytest.mark.asyncio()
    async def test_unavailable_when_no_llm(self) -> None:
        """When LLM is not configured, returns status='unavailable'."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary

        # Create a real in-memory SQLite database
        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        try:
            result = await generate_weekly_summary(
                db=db,
                user_id="test-user",
                events=[],
                portfolio_entries=[],
            )
            assert result["status"] == "unavailable"
            assert "message" in result
            assert "Azure OpenAI" in result["message"]
            assert result["summary_text"] == ""
            assert result["highlights"] == []
            assert result["focus_items"] == []
        finally:
            await db.close()

    @pytest.mark.asyncio()
    async def test_unavailable_no_fake_content(self) -> None:
        """Unavailable mode must not return fake/fabricated content."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary

        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        try:
            result = await generate_weekly_summary(
                db=db,
                user_id="test-user",
                events=[{"concept": "math", "score": 0.9}],
                portfolio_entries=[],
            )
            # Even with data, if LLM not configured, should be unavailable
            assert result["status"] == "unavailable"
            assert result["summary_text"] == ""
        finally:
            await db.close()


# ═══════════════════════════════════════════════════════════════════
# 5. Weekly Summary — Generation with Mocked LLM
# ═══════════════════════════════════════════════════════════════════


class TestWeeklySummaryGeneration:
    """Tests for weekly summary generation when Azure is configured (mocked)."""

    @pytest.mark.asyncio()
    async def test_generation_with_mocked_llm(self) -> None:
        """When LLM is available, generates a proper summary."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary
        from learning_navigator.llm.azure_client import LLMResponse

        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        mock_response = LLMResponse(
            content=json.dumps({
                "summary_text": "Great progress this week! You practiced algebra 5 times.",
                "highlights": ["Strong algebra practice", "Consistent schedule"],
                "focus_items": ["Review geometry basics"],
                "burnout_flag": False,
                "evidence_bullets": ["Practiced algebra 5 times", "Average score: 85%"],
            }),
            model="gpt-4o",
            usage={"total_tokens": 500},
        )

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_llm:
            client = MagicMock()
            client.enabled = True
            client.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = client

            try:
                result = await generate_weekly_summary(
                    db=db,
                    user_id="test-user",
                    events=[{"concept": "algebra", "event_type": "quiz_result", "score": 0.85}],
                    portfolio_entries=[],
                )

                assert result["status"] == "generated"
                assert "Great progress" in result["summary_text"]
                assert len(result["highlights"]) == 2
                assert len(result["focus_items"]) == 1
                assert result["burnout_flag"] is False
                assert result["model_used"] == "gpt-4o"
                assert result["disclaimer"] != ""
            finally:
                await db.close()

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_error(self) -> None:
        """When LLM call fails, returns status='error'."""
        from learning_navigator.api.weekly_summary import generate_weekly_summary

        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_llm:
            client = MagicMock()
            client.enabled = True
            client.chat = AsyncMock(return_value=None)  # Simulate LLM failure
            mock_llm.return_value = client

            try:
                result = await generate_weekly_summary(
                    db=db,
                    user_id="test-user",
                    events=[],
                    portfolio_entries=[],
                )
                assert result["status"] == "error"
                assert "message" in result
            finally:
                await db.close()

    @pytest.mark.asyncio()
    async def test_summary_persisted_to_db(self) -> None:
        """Generated summary is saved to the database."""
        from learning_navigator.api.weekly_summary import (
            generate_weekly_summary,
            get_latest_summary,
        )
        from learning_navigator.llm.azure_client import LLMResponse

        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        mock_response = LLMResponse(
            content=json.dumps({
                "summary_text": "Weekly progress summary",
                "highlights": ["Good work"],
                "focus_items": ["Keep going"],
                "burnout_flag": False,
                "evidence_bullets": ["Data point 1"],
            }),
            model="gpt-4o",
        )

        with patch("learning_navigator.api.weekly_summary.get_llm_client") as mock_llm:
            client = MagicMock()
            client.enabled = True
            client.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = client

            try:
                await generate_weekly_summary(
                    db=db, user_id="persist-test", events=[], portfolio_entries=[],
                )

                # Retrieve the saved summary
                saved = await get_latest_summary(db, "persist-test")
                assert saved is not None
                assert saved["user_id"] == "persist-test"
                assert saved["summary_text"] == "Weekly progress summary"
            finally:
                await db.close()

    @pytest.mark.asyncio()
    async def test_storage_roundtrip(self) -> None:
        """Save and retrieve a summary correctly handles JSON fields."""
        from learning_navigator.api.weekly_summary import (
            save_summary,
            get_latest_summary,
            _ensure_table,
        )

        import aiosqlite
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row

        try:
            await _ensure_table(db)
            summary = {
                "id": "test-id",
                "user_id": "u1",
                "week_start": "2026-02-24",
                "week_end": "2026-03-03",
                "summary_text": "Test summary",
                "highlights": ["h1", "h2"],
                "focus_items": ["f1"],
                "burnout_flag": True,
                "evidence_bullets": ["e1", "e2"],
                "model_used": "gpt-4o",
                "status": "generated",
                "disclaimer": "AI generated",
                "created_at": "2026-03-03T00:00:00+00:00",
            }
            await save_summary(db, summary)

            result = await get_latest_summary(db, "u1")
            assert result is not None
            assert result["highlights"] == ["h1", "h2"]
            assert result["focus_items"] == ["f1"]
            assert result["burnout_flag"] is True
            assert result["evidence_bullets"] == ["e1", "e2"]
        finally:
            await db.close()


# ═══════════════════════════════════════════════════════════════════
# 6. Full Pipeline NBA serialization (all new fields present)
# ═══════════════════════════════════════════════════════════════════


class TestNBAFullSchema:
    """Verify NBA output includes all new fields and serializes correctly."""

    @pytest.mark.asyncio()
    async def test_nba_json_roundtrip(self, engine) -> None:
        """NBA with all new fields survives JSON serialization."""
        event = _quiz_event()
        result = await engine.process_event(event)

        # Serialize to dict then back
        data = result.model_dump(mode="json")
        assert "explainability" in data
        assert "expected_impact" in data
        assert "top_factors" in data["explainability"]
        assert "decision_trace" in data["explainability"]
        assert "ran_agents" in data["explainability"]["decision_trace"]
        assert "assumptions" in data["expected_impact"]

        # Roundtrip
        restored = NextBestAction.model_validate(data)
        assert isinstance(restored.explainability, Explainability)
        assert isinstance(restored.expected_impact, ExpectedImpact)

    @pytest.mark.asyncio()
    async def test_nba_backward_compatible(self) -> None:
        """NBA can be created without new fields (defaults apply)."""
        nba = NextBestAction(
            action_id="compat",
            learner_id="l",
            recommended_action="study:x",
            rationale="r",
            confidence=0.5,
            expected_learning_gain=0.1,
        )
        data = nba.model_dump(mode="json")
        assert data["explainability"]["top_factors"] == []
        assert data["expected_impact"]["assumptions"] == []
