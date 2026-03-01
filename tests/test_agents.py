"""Tests for Phase 3 core agents — Diagnoser, DriftDetector, Motivation, Planner, Evaluator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning_navigator.agents.diagnoser import DiagnoserAgent
from learning_navigator.agents.drift_detector import DriftDetectorAgent
from learning_navigator.agents.evaluator import EvaluatorAgent
from learning_navigator.agents.motivation import MotivationAgent
from learning_navigator.agents.planner import PlannerAgent
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptRelation,
    ConceptRelationType,
    ConceptState,
    LearnerState,
    MotivationLevel,
    MotivationState,
    TimeBudget,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType

# ── Helpers ────────────────────────────────────────────────────────

def _build_state(**overrides) -> LearnerState:
    """Build a LearnerState with sensible defaults."""
    defaults = {"learner_id": "test-learner"}
    defaults.update(overrides)
    return LearnerState(**defaults)


def _make_msg(
    msg_type: MessageType,
    payload: dict,
    source: str = "test",
    target: str | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=msg_type,
        source_agent_id=source,
        target_agent_id=target,
        payload=payload,
    )


def _state_with_concepts(*concepts: ConceptState) -> LearnerState:
    state = _build_state()
    for c in concepts:
        state.upsert_concept(c)
    return state


# ── DiagnoserAgent ─────────────────────────────────────────────────

class TestDiagnoserAgent:
    @pytest.fixture()
    def agent(self) -> DiagnoserAgent:
        return DiagnoserAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: DiagnoserAgent) -> None:
        assert agent.agent_id == "diagnoser"
        assert agent.metadata.cost_tier == 1

    @pytest.mark.asyncio()
    async def test_missing_payload(self, agent: DiagnoserAgent) -> None:
        msg = _make_msg(MessageType.DIAGNOSIS_REQUEST, {})
        resp = await agent.handle(msg)
        assert resp.errors
        assert resp.confidence == 0.0

    @pytest.mark.asyncio()
    async def test_quiz_result_updates_bkt(self, agent: DiagnoserAgent) -> None:
        concept = ConceptState(
            concept_id="algebra",
            bkt=BKTParams(p_know=0.3),
        )
        state = _state_with_concepts(concept)

        msg = _make_msg(
            MessageType.DIAGNOSIS_REQUEST,
            {
                "learner_state": state.model_dump(mode="json"),
                "event": {
                    "event_type": "quiz_result",
                    "concept_id": "algebra",
                    "data": {"score": 0.8, "max_score": 1.0},
                },
            },
        )
        resp = await agent.handle(msg)
        assert resp.confidence > 0
        assert len(resp.payload["updates"]) == 1
        update = resp.payload["updates"][0]
        assert update["type"] == "bkt_update"
        assert update["correct"] is True
        assert update["new_mastery"] > update["old_mastery"]

    @pytest.mark.asyncio()
    async def test_quiz_incorrect_lowers_mastery(self, agent: DiagnoserAgent) -> None:
        concept = ConceptState(
            concept_id="algebra",
            bkt=BKTParams(p_know=0.7),
        )
        state = _state_with_concepts(concept)
        msg = _make_msg(
            MessageType.DIAGNOSIS_REQUEST,
            {
                "learner_state": state.model_dump(mode="json"),
                "event": {
                    "event_type": "quiz_result",
                    "concept_id": "algebra",
                    "data": {"score": 0.1, "max_score": 1.0},
                },
            },
        )
        resp = await agent.handle(msg)
        update = resp.payload["updates"][0]
        assert update["correct"] is False
        assert update["new_mastery"] < update["old_mastery"]

    @pytest.mark.asyncio()
    async def test_time_on_task(self, agent: DiagnoserAgent) -> None:
        state = _state_with_concepts(ConceptState(concept_id="geom"))
        msg = _make_msg(
            MessageType.DIAGNOSIS_REQUEST,
            {
                "learner_state": state.model_dump(mode="json"),
                "event": {
                    "event_type": "time_on_task",
                    "concept_id": "geom",
                    "data": {"minutes": 15},
                },
            },
        )
        resp = await agent.handle(msg)
        assert resp.payload["updates"][0]["type"] == "time_on_task"

    @pytest.mark.asyncio()
    async def test_weak_concepts_flagged(self, agent: DiagnoserAgent) -> None:
        concepts = [
            ConceptState(concept_id=f"c{i}", bkt=BKTParams(p_know=0.2))
            for i in range(5)
        ]
        state = _state_with_concepts(*concepts)
        msg = _make_msg(
            MessageType.DIAGNOSIS_REQUEST,
            {
                "learner_state": state.model_dump(mode="json"),
                "event": {"event_type": "quiz_result", "concept_id": "c0",
                          "data": {"score": 0.1, "max_score": 1.0}},
            },
        )
        resp = await agent.handle(msg)
        assert len(resp.payload["weak_concept_ids"]) >= 4


# ── DriftDetectorAgent ─────────────────────────────────────────────

class TestDriftDetectorAgent:
    @pytest.fixture()
    def agent(self) -> DriftDetectorAgent:
        return DriftDetectorAgent(inactivity_threshold_hours=24.0)

    @pytest.mark.asyncio()
    async def test_no_drift_fresh_state(self, agent: DriftDetectorAgent) -> None:
        state = _build_state()
        msg = _make_msg(MessageType.DRIFT_ALERT, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["drift_detected"] is False

    @pytest.mark.asyncio()
    async def test_inactivity_drift(self, agent: DriftDetectorAgent) -> None:
        concept = ConceptState(
            concept_id="c1",
            last_practiced=datetime.now(timezone.utc) - timedelta(hours=72),
        )
        state = _state_with_concepts(concept)
        state.last_active = datetime.now(timezone.utc) - timedelta(hours=72)
        msg = _make_msg(MessageType.DRIFT_ALERT, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        signals = resp.payload["drift_signals"]
        types = [s["drift_type"] for s in signals]
        assert "inactivity" in types

    @pytest.mark.asyncio()
    async def test_mastery_plateau(self, agent: DriftDetectorAgent) -> None:
        concept = ConceptState(
            concept_id="stuck",
            bkt=BKTParams(p_know=0.3),
            practice_count=8,
            last_practiced=datetime.now(timezone.utc),
        )
        state = _state_with_concepts(concept)
        msg = _make_msg(MessageType.DRIFT_ALERT, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        signals = resp.payload["drift_signals"]
        types = [s["drift_type"] for s in signals]
        assert "mastery_plateau" in types

    @pytest.mark.asyncio()
    async def test_difficulty_mismatch(self, agent: DriftDetectorAgent) -> None:
        concept = ConceptState(
            concept_id="easy",
            bkt=BKTParams(p_know=0.97),
            practice_count=15,
            last_practiced=datetime.now(timezone.utc),
        )
        state = _state_with_concepts(concept)
        msg = _make_msg(MessageType.DRIFT_ALERT, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        types = [s["drift_type"] for s in resp.payload["drift_signals"]]
        assert "difficulty_mismatch_easy" in types

    @pytest.mark.asyncio()
    async def test_disengagement(self, agent: DriftDetectorAgent) -> None:
        state = _build_state()
        state.motivation = MotivationState(
            level=MotivationLevel.CRITICAL,
            score=0.15,
            trend=-0.2,
        )
        msg = _make_msg(MessageType.DRIFT_ALERT, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        types = [s["drift_type"] for s in resp.payload["drift_signals"]]
        assert "disengagement" in types

    @pytest.mark.asyncio()
    async def test_missing_state_returns_error(self, agent: DriftDetectorAgent) -> None:
        msg = _make_msg(MessageType.DRIFT_ALERT, {})
        resp = await agent.handle(msg)
        assert resp.errors


# ── MotivationAgent ────────────────────────────────────────────────

class TestMotivationAgent:
    @pytest.fixture()
    def agent(self) -> MotivationAgent:
        return MotivationAgent()

    @pytest.mark.asyncio()
    async def test_fresh_learner_defaults(self, agent: MotivationAgent) -> None:
        state = _build_state()
        msg = _make_msg(MessageType.MOTIVATION_SIGNAL, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.confidence > 0
        assert "motivation_state" in resp.payload

    @pytest.mark.asyncio()
    async def test_active_learner_high_motivation(self, agent: MotivationAgent) -> None:
        state = _build_state(session_count=12)
        concept = ConceptState(
            concept_id="c1",
            bkt=BKTParams(p_know=0.8),
            last_practiced=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        state.upsert_concept(concept)
        msg = _make_msg(MessageType.MOTIVATION_SIGNAL, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        mot = resp.payload["motivation_state"]
        assert mot["level"] in ("high", "medium")
        assert mot["score"] > 0.5

    @pytest.mark.asyncio()
    async def test_inactive_learner_low_motivation(self, agent: MotivationAgent) -> None:
        state = _build_state(session_count=1)
        concept = ConceptState(
            concept_id="c1",
            bkt=BKTParams(p_know=0.2),
            last_practiced=datetime.now(timezone.utc) - timedelta(hours=100),
        )
        state.upsert_concept(concept)
        msg = _make_msg(MessageType.MOTIVATION_SIGNAL, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        mot = resp.payload["motivation_state"]
        assert mot["level"] in ("low", "critical")
        assert mot["score"] < 0.5

    @pytest.mark.asyncio()
    async def test_explicit_sentiment_signal(self, agent: MotivationAgent) -> None:
        state = _build_state(metadata={"last_sentiment_score": 0.95})
        msg = _make_msg(MessageType.MOTIVATION_SIGNAL, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["signals_used"] >= 1

    @pytest.mark.asyncio()
    async def test_missing_state(self, agent: MotivationAgent) -> None:
        msg = _make_msg(MessageType.MOTIVATION_SIGNAL, {})
        resp = await agent.handle(msg)
        assert resp.errors


# ── PlannerAgent ───────────────────────────────────────────────────

class TestPlannerAgent:
    @pytest.fixture()
    def agent(self) -> PlannerAgent:
        return PlannerAgent()

    @pytest.mark.asyncio()
    async def test_generates_recommendations(self, agent: PlannerAgent) -> None:
        state = _state_with_concepts(
            ConceptState(concept_id="alg", bkt=BKTParams(p_know=0.3)),
            ConceptState(concept_id="geom", bkt=BKTParams(p_know=0.6)),
        )
        msg = _make_msg(
            MessageType.PLAN_READY,
            {"learner_state": state.model_dump(mode="json"), "diagnosis": {}},
        )
        resp = await agent.handle(msg)
        assert resp.confidence > 0
        recs = resp.payload["recommendations"]
        assert len(recs) >= 1
        assert recs[0]["concept_id"] in ("alg", "geom")

    @pytest.mark.asyncio()
    async def test_low_motivation_short_session(self, agent: PlannerAgent) -> None:
        state = _state_with_concepts(
            ConceptState(concept_id="c1", bkt=BKTParams(p_know=0.3)),
        )
        state.motivation = MotivationState(
            level=MotivationLevel.CRITICAL, score=0.1
        )
        state.time_budget = TimeBudget(preferred_session_minutes=60)
        msg = _make_msg(
            MessageType.PLAN_READY,
            {"learner_state": state.model_dump(mode="json"), "diagnosis": {}},
        )
        resp = await agent.handle(msg)
        assert resp.payload["session_minutes"] <= 20

    @pytest.mark.asyncio()
    async def test_priority_concepts_boosted(self, agent: PlannerAgent) -> None:
        state = _state_with_concepts(
            ConceptState(concept_id="priority", bkt=BKTParams(p_know=0.4)),
            ConceptState(concept_id="other", bkt=BKTParams(p_know=0.4)),
        )
        state.time_budget = TimeBudget(priority_concept_ids=["priority"])
        msg = _make_msg(
            MessageType.PLAN_READY,
            {"learner_state": state.model_dump(mode="json"), "diagnosis": {}},
        )
        resp = await agent.handle(msg)
        recs = resp.payload["recommendations"]
        assert recs[0]["concept_id"] == "priority"

    @pytest.mark.asyncio()
    async def test_empty_state_fallback(self, agent: PlannerAgent) -> None:
        state = _build_state()
        msg = _make_msg(
            MessageType.PLAN_READY,
            {"learner_state": state.model_dump(mode="json"), "diagnosis": {}},
        )
        resp = await agent.handle(msg)
        assert resp.confidence >= 0

    @pytest.mark.asyncio()
    async def test_missing_state_returns_error(self, agent: PlannerAgent) -> None:
        msg = _make_msg(MessageType.PLAN_READY, {})
        resp = await agent.handle(msg)
        assert resp.errors

    @pytest.mark.asyncio()
    async def test_suggest_action_types(self, agent: PlannerAgent) -> None:
        assert PlannerAgent._suggest_action(0.1, 0.1) == "learn_new"
        assert PlannerAgent._suggest_action(0.5, 0.1) == "practice"
        assert PlannerAgent._suggest_action(0.75, 0.1) == "deepen"
        assert PlannerAgent._suggest_action(0.95, 0.1) == "maintain"
        assert PlannerAgent._suggest_action(0.5, 0.8) == "spaced_review"


# ── EvaluatorAgent ─────────────────────────────────────────────────

class TestEvaluatorAgent:
    @pytest.fixture()
    def agent(self) -> EvaluatorAgent:
        return EvaluatorAgent()

    @pytest.mark.asyncio()
    async def test_approves_good_plan(self, agent: EvaluatorAgent) -> None:
        state = _state_with_concepts(
            ConceptState(concept_id="c1", bkt=BKTParams(p_know=0.5)),
        )
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "practice", "minutes": 15},
            ],
            "session_minutes": 30,
        }
        msg = _make_msg(
            MessageType.PLAN_REVIEW,
            {"learner_state": state.model_dump(mode="json"), "plan": plan},
        )
        resp = await agent.handle(msg)
        assert resp.payload["approved"] is True
        assert resp.payload["quality_score"] > 0.5

    @pytest.mark.asyncio()
    async def test_flags_prerequisite_violation(self, agent: EvaluatorAgent) -> None:
        state = _build_state()
        prereq = ConceptState(concept_id="prereq", bkt=BKTParams(p_know=0.2))
        target = ConceptState(concept_id="advanced", bkt=BKTParams(p_know=0.3))
        state.upsert_concept(prereq)
        state.upsert_concept(target)
        state.concept_relations.append(
            ConceptRelation(
                source_concept_id="prereq",
                target_concept_id="advanced",
                relation_type=ConceptRelationType.PREREQUISITE,
            )
        )
        plan = {
            "recommendations": [
                {"concept_id": "advanced", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 30,
        }
        msg = _make_msg(
            MessageType.PLAN_REVIEW,
            {"learner_state": state.model_dump(mode="json"), "plan": plan},
        )
        resp = await agent.handle(msg)
        issue_types = [i["type"] for i in resp.payload["issues"]]
        assert "prerequisite_violation" in issue_types

    @pytest.mark.asyncio()
    async def test_flags_overload_risk(self, agent: EvaluatorAgent) -> None:
        state = _build_state()
        state.motivation = MotivationState(level=MotivationLevel.LOW, score=0.25)
        plan = {
            "recommendations": [{"concept_id": "c1", "action": "study", "minutes": 40}],
            "session_minutes": 45,
        }
        msg = _make_msg(
            MessageType.PLAN_REVIEW,
            {"learner_state": state.model_dump(mode="json"), "plan": plan},
        )
        resp = await agent.handle(msg)
        issue_types = [i["type"] for i in resp.payload["issues"]]
        assert "overload_risk" in issue_types

    @pytest.mark.asyncio()
    async def test_flags_cognitive_overload(self, agent: EvaluatorAgent) -> None:
        state = _build_state()
        plan = {
            "recommendations": [
                {"concept_id": f"c{i}", "action": "learn_new", "minutes": 10}
                for i in range(4)
            ],
            "session_minutes": 60,
        }
        msg = _make_msg(
            MessageType.PLAN_REVIEW,
            {"learner_state": state.model_dump(mode="json"), "plan": plan},
        )
        resp = await agent.handle(msg)
        issue_types = [i["type"] for i in resp.payload["issues"]]
        assert "cognitive_overload" in issue_types

    @pytest.mark.asyncio()
    async def test_empty_plan_rejected(self, agent: EvaluatorAgent) -> None:
        state = _build_state()
        plan = {"recommendations": [], "session_minutes": 30}
        msg = _make_msg(
            MessageType.PLAN_REVIEW,
            {"learner_state": state.model_dump(mode="json"), "plan": plan},
        )
        resp = await agent.handle(msg)
        assert resp.payload["approved"] is False

    @pytest.mark.asyncio()
    async def test_missing_payload(self, agent: EvaluatorAgent) -> None:
        msg = _make_msg(MessageType.PLAN_REVIEW, {})
        resp = await agent.handle(msg)
        assert resp.errors
