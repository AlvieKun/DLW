"""Tests for the Learning GPS Engine — full pipeline integration."""

from __future__ import annotations

import pytest

from learning_navigator.contracts.events import (
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
    MotivationLevel,
)
from learning_navigator.engine.event_bus import InMemoryEventBus
from learning_navigator.engine.gps_engine import LearningGPSEngine
from learning_navigator.engine.hitl import DefaultHITLHook
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
    learner_id: str = "learner-1",
    concept_id: str = "algebra",
    score: float = 0.8,
) -> LearnerEvent:
    return LearnerEvent(
        event_id="evt-1",
        learner_id=learner_id,
        event_type=LearnerEventType.QUIZ_RESULT,
        concept_id=concept_id,
        data={"score": score, "max_score": 1.0},
    )


# ═══════════════════════════════════════════════════════════════════
# Full Pipeline Tests
# ═══════════════════════════════════════════════════════════════════

class TestLearningGPSEngine:
    """Integration tests for the full engine pipeline."""

    @pytest.mark.asyncio()
    async def test_process_event_returns_next_best_action(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        assert isinstance(result, NextBestAction)
        assert result.learner_id == "learner-1"
        assert result.recommended_action
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio()
    async def test_new_learner_state_created(self, engine, memory_store) -> None:
        """Processing an event for an unknown learner creates state."""
        event = _quiz_event(learner_id="new-learner")
        await engine.process_event(event)
        state = await memory_store.get_learner_state("new-learner")
        assert state is not None
        assert state.learner_id == "new-learner"

    @pytest.mark.asyncio()
    async def test_state_saved_after_processing(self, engine, memory_store) -> None:
        event = _quiz_event()
        await engine.process_event(event)
        state = await memory_store.get_learner_state("learner-1")
        assert state is not None

    @pytest.mark.asyncio()
    async def test_portfolio_logged(self, engine, portfolio_logger) -> None:
        event = _quiz_event()
        await engine.process_event(event)
        entries = await portfolio_logger.get_entries("learner-1")
        assert len(entries) >= 1
        assert entries[0].entry_type == "recommendation"

    @pytest.mark.asyncio()
    async def test_event_bus_receives_message(self, engine, event_bus) -> None:
        event = _quiz_event()
        await engine.process_event(event)
        assert len(event_bus._history) >= 1
        last = event_bus._history[-1]
        assert last.payload.get("learner_id") == "learner-1"

    @pytest.mark.asyncio()
    async def test_existing_state_used(self, engine, memory_store) -> None:
        """Pre-populated state is loaded and updated."""
        state = LearnerState(learner_id="existing")
        concept = ConceptState(concept_id="algebra", bkt=BKTParams(p_know=0.6))
        state.upsert_concept(concept)
        await memory_store.save_learner_state(state)

        event = _quiz_event(learner_id="existing", concept_id="algebra", score=1.0)
        result = await engine.process_event(event)
        assert isinstance(result, NextBestAction)

    @pytest.mark.asyncio()
    async def test_debug_trace_present(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        assert "trace_id" in result.debug_trace
        assert "pipeline_steps" in result.debug_trace
        steps = result.debug_trace["pipeline_steps"]
        agent_names = [s["agent"] for s in steps]
        assert "diagnoser" in agent_names
        assert "drift_detector" in agent_names
        assert "motivation" in agent_names
        assert "maker_checker" in agent_names

    @pytest.mark.asyncio()
    async def test_hitl_decision_recorded(self, engine) -> None:
        event = _quiz_event()
        result = await engine.process_event(event)
        assert "hitl_decision" in result.debug_trace

    @pytest.mark.asyncio()
    async def test_multiple_events_accumulate_state(
        self, engine, memory_store
    ) -> None:
        """Processing multiple events for the same learner accumulates state."""
        for i in range(3):
            event = LearnerEvent(
                event_id=f"evt-{i}",
                learner_id="multi",
                event_type=LearnerEventType.QUIZ_RESULT,
                concept_id="algebra",
                data={"score": 0.7 + i * 0.1, "max_score": 1.0},
            )
            await engine.process_event(event)

        state = await memory_store.get_learner_state("multi")
        assert state is not None
        # Concept should exist with updated BKT
        concept = state.get_concept("algebra")
        assert concept is not None

    @pytest.mark.asyncio()
    async def test_custom_hitl_hook(self, memory_store, portfolio_logger, event_bus) -> None:
        """Engine with strict HITL triggers review path on reviewed items."""
        strict_hook = DefaultHITLHook(
            auto_approve_threshold=0.99,  # almost nothing auto-approves
            require_review_on_errors=True,
        )
        engine = LearningGPSEngine(
            memory_store=memory_store,
            portfolio_logger=portfolio_logger,
            event_bus=event_bus,
            hitl_hook=strict_hook,
        )
        event = _quiz_event()
        result = await engine.process_event(event)
        # With strict threshold, HITL path is exercised
        assert isinstance(result, NextBestAction)
        # Result should still be produced regardless of HITL outcome
        assert result.learner_id == "learner-1"


# ── Engine State Mutation Helpers ──────────────────────────────────

class TestEngineHelpers:
    """Unit tests for the static state mutation helpers."""

    def test_apply_diagnosis(self) -> None:
        state = LearnerState(learner_id="test")
        state.upsert_concept(
            ConceptState(concept_id="c1", bkt=BKTParams(p_know=0.3))
        )
        diagnosis = {
            "updates": [
                {"concept_id": "c1", "new_mastery": 0.6},
            ],
        }
        updated = LearningGPSEngine._apply_diagnosis(state, diagnosis)
        assert updated.get_concept("c1").bkt.p_know == 0.6

    def test_apply_diagnosis_creates_new_concept(self) -> None:
        state = LearnerState(learner_id="test")
        diagnosis = {
            "updates": [
                {"concept_id": "new_concept", "new_mastery": 0.6},
            ],
        }
        updated = LearningGPSEngine._apply_diagnosis(state, diagnosis)
        concept = updated.get_concept("new_concept")
        assert concept is not None
        assert concept.bkt.p_know == 0.6

    def test_apply_drift(self) -> None:
        state = LearnerState(learner_id="test")
        drift_response = {
            "drift_signals": [
                {"drift_type": "inactivity", "severity": 0.7},
                {"drift_type": "mastery_plateau", "severity": 0.5},
            ],
        }
        updated = LearningGPSEngine._apply_drift(state, drift_response)
        assert len(updated.active_drift_signals) == 2
        assert updated.active_drift_signals[0].drift_type == "inactivity"

    def test_apply_motivation(self) -> None:
        state = LearnerState(learner_id="test")
        motivation_response = {
            "motivation_state": {
                "level": "high",
                "score": 0.85,
                "trend": 0.1,
            },
        }
        updated = LearningGPSEngine._apply_motivation(state, motivation_response)
        assert updated.motivation.level == MotivationLevel.HIGH
        assert updated.motivation.score == 0.85
        assert updated.motivation.trend == 0.1

    def test_apply_motivation_invalid_level_ignored(self) -> None:
        state = LearnerState(learner_id="test")
        motivation_response = {
            "motivation_state": {
                "level": "invalid_level",
                "score": 0.5,
            },
        }
        updated = LearningGPSEngine._apply_motivation(state, motivation_response)
        # Should not crash, level stays at default
        assert updated.motivation.score == 0.5
