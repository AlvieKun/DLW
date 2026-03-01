"""Tests for Phase 4 specialized agents: SkillState, Behavior, TimeOptimizer, Reflection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning_navigator.agents.behavior import BehaviorAgent
from learning_navigator.agents.reflection import ReflectionAgent
from learning_navigator.agents.skill_state import SkillStateAgent
from learning_navigator.agents.time_optimizer import TimeOptimizerAgent
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptRelation,
    ConceptRelationType,
    ConceptState,
    LearnerState,
    MotivationLevel,
    TimeBudget,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType

# ── Helpers ────────────────────────────────────────────────────────


def _make_state(**overrides) -> LearnerState:
    defaults = {"learner_id": "test-learner"}
    defaults.update(overrides)
    return LearnerState(**defaults)


def _concept(cid: str, mastery: float = 0.5, **kw) -> ConceptState:
    return ConceptState(
        concept_id=cid,
        bkt=BKTParams(p_know=mastery),
        **kw,
    )


def _prereq(src: str, tgt: str) -> ConceptRelation:
    return ConceptRelation(
        source_concept_id=src,
        target_concept_id=tgt,
        relation_type=ConceptRelationType.PREREQUISITE,
    )


def _msg(msg_type: MessageType, payload: dict) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=msg_type,
        source_agent_id="engine",
        target_agent_id="test",
        payload=payload,
    )


# ══════════════════════════════════════════════════════════════════
#  Skill State Agent
# ══════════════════════════════════════════════════════════════════


class TestSkillStateAgent:
    @pytest.fixture()
    def agent(self) -> SkillStateAgent:
        return SkillStateAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: SkillStateAgent) -> None:
        assert agent.agent_id == "skill-state"
        assert agent.metadata.cost_tier == 1

    @pytest.mark.asyncio()
    async def test_empty_state(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["summary"]["total_concepts"] == 0
        assert resp.payload["readiness"] == {}

    @pytest.mark.asyncio()
    async def test_single_concept_no_prereqs(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("algebra", 0.7))
        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        readiness = resp.payload["readiness"]
        assert readiness["algebra"]["readiness"] == 1.0
        assert readiness["algebra"]["prerequisites_met"] is True

    @pytest.mark.asyncio()
    async def test_prerequisite_gap_detected(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("algebra", 0.3))  # below threshold
        state.upsert_concept(_concept("calculus", 0.2))
        state.concept_relations.append(_prereq("algebra", "calculus"))

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        gaps = resp.payload["prerequisite_gaps"]
        assert len(gaps) == 1
        assert gaps[0]["concept_id"] == "calculus"
        assert "algebra" in gaps[0]["blocking_prerequisites"]

    @pytest.mark.asyncio()
    async def test_prerequisites_met_high_mastery(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("algebra", 0.9))
        state.upsert_concept(_concept("calculus", 0.4))
        state.concept_relations.append(_prereq("algebra", "calculus"))

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        assert resp.payload["readiness"]["calculus"]["prerequisites_met"] is True
        assert len(resp.payload["prerequisite_gaps"]) == 0

    @pytest.mark.asyncio()
    async def test_clusters_connected(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("a", 0.5))
        state.upsert_concept(_concept("b", 0.6))
        state.upsert_concept(_concept("c", 0.7))
        state.concept_relations.append(_prereq("a", "b"))
        # c is isolated

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        clusters = resp.payload["clusters"]
        assert len(clusters) == 2  # {a,b} and {c}

    @pytest.mark.asyncio()
    async def test_learning_order_prioritises_ready_low_mastery(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("easy", 0.8))
        state.upsert_concept(_concept("hard", 0.2))
        # Both have no prereqs → readiness=1.0
        # hard has lower mastery → higher learning priority

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        order = resp.payload["learning_order"]
        assert len(order) == 2
        assert order[0]["concept_id"] == "hard"

    @pytest.mark.asyncio()
    async def test_mastered_excluded_from_learning_order(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("done", 0.9))
        state.upsert_concept(_concept("todo", 0.3))

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        order = resp.payload["learning_order"]
        ids = [o["concept_id"] for o in order]
        assert "done" not in ids
        assert "todo" in ids

    @pytest.mark.asyncio()
    async def test_summary_counts(self, agent: SkillStateAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("mastered", 0.9))
        state.upsert_concept(_concept("progress", 0.5))
        state.upsert_concept(_concept("new", 0.1))

        msg = _msg(MessageType.SKILL_STATE_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        summary = resp.payload["summary"]
        assert summary["mastered_count"] == 1
        assert summary["in_progress_count"] == 1
        assert summary["not_started_count"] == 1


# ══════════════════════════════════════════════════════════════════
#  Behavior Agent
# ══════════════════════════════════════════════════════════════════


class TestBehaviorAgent:
    @pytest.fixture()
    def agent(self) -> BehaviorAgent:
        return BehaviorAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: BehaviorAgent) -> None:
        assert agent.agent_id == "behavior"
        assert agent.metadata.cost_tier == 1

    @pytest.mark.asyncio()
    async def test_no_anomalies_clean_state(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)
        assert resp.payload["anomaly_detected"] is False
        assert resp.payload["anomaly_count"] == 0

    @pytest.mark.asyncio()
    async def test_detect_cramming(self, agent: BehaviorAgent) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=6)
        state = _make_state(
            session_count=8,
            time_budget=TimeBudget(deadline=deadline),
        )
        state.upsert_concept(_concept("a", practice_count=10))
        state.upsert_concept(_concept("b", practice_count=2))

        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)

        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "cramming" in types

    @pytest.mark.asyncio()
    async def test_detect_rapid_guessing(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("math", 0.2))

        event = {
            "concept_id": "math",
            "data": {"response_time_seconds": 1.0},
        }
        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": event,
        })
        resp = await agent.handle(msg)

        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "rapid_guessing" in types

    @pytest.mark.asyncio()
    async def test_no_rapid_guessing_when_slow(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        event = {"data": {"response_time_seconds": 10.0}}
        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": event,
        })
        resp = await agent.handle(msg)
        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "rapid_guessing" not in types

    @pytest.mark.asyncio()
    async def test_detect_avoidance(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("a", practice_count=20))
        state.upsert_concept(_concept("b", practice_count=20))
        state.upsert_concept(_concept("c", practice_count=0))  # avoided

        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)

        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "avoidance" in types
        avoidance = next(a for a in resp.payload["anomalies"] if a["anomaly_type"] == "avoidance")
        assert "c" in avoidance["evidence"]["avoided_concepts"]

    @pytest.mark.asyncio()
    async def test_detect_irregular_sessions(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        # Create highly variable spacing history
        state.upsert_concept(_concept("a", spacing_history=[1.0, 48.0, 2.0, 72.0, 1.5, 96.0]))

        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)

        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "irregular_sessions" in types

    @pytest.mark.asyncio()
    async def test_detect_late_night(self, agent: BehaviorAgent) -> None:
        state = _make_state(
            last_active=datetime(2026, 3, 1, 2, 30, tzinfo=timezone.utc),
        )
        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)

        types = [a["anomaly_type"] for a in resp.payload["anomalies"]]
        assert "late_night_study" in types

    @pytest.mark.asyncio()
    async def test_signals_checked_always_reported(self, agent: BehaviorAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.BEHAVIOR_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "event": {},
        })
        resp = await agent.handle(msg)
        assert "cramming" in resp.payload["signals_checked"]
        assert "rapid_guessing" in resp.payload["signals_checked"]
        assert "avoidance" in resp.payload["signals_checked"]
        assert "irregular_sessions" in resp.payload["signals_checked"]
        assert "late_night_study" in resp.payload["signals_checked"]


# ══════════════════════════════════════════════════════════════════
#  Time Optimizer Agent
# ══════════════════════════════════════════════════════════════════


class TestTimeOptimizerAgent:
    @pytest.fixture()
    def agent(self) -> TimeOptimizerAgent:
        return TimeOptimizerAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: TimeOptimizerAgent) -> None:
        assert agent.agent_id == "time-optimizer"
        assert agent.metadata.cost_tier == 2

    @pytest.mark.asyncio()
    async def test_empty_state_no_allocations(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["allocations"] == []
        assert resp.payload["total_allocated_minutes"] == 0

    @pytest.mark.asyncio()
    async def test_single_concept_gets_time(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("algebra", 0.4))
        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        allocs = resp.payload["allocations"]
        assert len(allocs) == 1
        assert allocs[0]["concept_id"] == "algebra"
        assert allocs[0]["minutes"] > 0

    @pytest.mark.asyncio()
    async def test_mastered_concept_excluded(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("done", 0.96))
        state.upsert_concept(_concept("todo", 0.3))
        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        alloc_ids = [a["concept_id"] for a in resp.payload["allocations"]]
        assert "done" not in alloc_ids
        assert "todo" in alloc_ids

    @pytest.mark.asyncio()
    async def test_priority_concept_boosted(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state(
            time_budget=TimeBudget(priority_concept_ids=["important"]),
        )
        state.upsert_concept(_concept("important", 0.4))
        state.upsert_concept(_concept("normal", 0.4))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        scores = resp.payload["concept_scores"]
        assert scores["important"] > scores["normal"]

    @pytest.mark.asyncio()
    async def test_low_motivation_shortens_session(self, agent: TimeOptimizerAgent) -> None:
        from learning_navigator.contracts.learner_state import MotivationState

        state = _make_state()
        state.motivation = MotivationState(level=MotivationLevel.LOW, score=0.2)
        state.upsert_concept(_concept("a", 0.4))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        # Default 45min * 0.7 = 31min
        assert resp.payload["session_minutes"] < 45
        assert resp.payload["motivation_adjustment"] == "session_shortened_30pct"

    @pytest.mark.asyncio()
    async def test_critical_motivation_shortens_more(self, agent: TimeOptimizerAgent) -> None:
        from learning_navigator.contracts.learner_state import MotivationState

        state = _make_state()
        state.motivation = MotivationState(level=MotivationLevel.CRITICAL, score=0.1)
        state.upsert_concept(_concept("a", 0.4))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        assert resp.payload["session_minutes"] < 30
        assert resp.payload["motivation_adjustment"] == "session_shortened_50pct"

    @pytest.mark.asyncio()
    async def test_deadline_analysis_present(self, agent: TimeOptimizerAgent) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=12)
        state = _make_state(
            time_budget=TimeBudget(deadline=deadline),
        )
        state.upsert_concept(_concept("a", 0.4))
        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        da = resp.payload["deadline_analysis"]
        assert da is not None
        assert da["hours_to_deadline"] > 0
        assert 0.0 <= da["deadline_urgency"] <= 1.0

    @pytest.mark.asyncio()
    async def test_no_deadline_analysis_when_none(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("a", 0.4))
        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert resp.payload["deadline_analysis"] is None

    @pytest.mark.asyncio()
    async def test_max_six_allocations(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        for i in range(10):
            state.upsert_concept(_concept(f"c{i}", mastery=0.1 * i))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)
        assert len(resp.payload["allocations"]) <= 6

    @pytest.mark.asyncio()
    async def test_action_types(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("new", 0.1))
        state.upsert_concept(_concept("practice", 0.45))
        state.upsert_concept(_concept("deepen", 0.7))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        actions = {a["concept_id"]: a["action"] for a in resp.payload["allocations"]}
        assert actions["new"] == "learn_new"
        assert actions["practice"] == "practice"
        assert actions["deepen"] == "deepen"

    @pytest.mark.asyncio()
    async def test_forgetting_triggers_spaced_review(self, agent: TimeOptimizerAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("forgotten", 0.4, forgetting_score=0.8))

        msg = _msg(MessageType.TIME_ALLOCATION_REQUEST, {"learner_state": state.model_dump(mode="json")})
        resp = await agent.handle(msg)

        allocs = resp.payload["allocations"]
        assert allocs[0]["action"] == "spaced_review"


# ══════════════════════════════════════════════════════════════════
#  Reflection Agent
# ══════════════════════════════════════════════════════════════════


class TestReflectionAgent:
    @pytest.fixture()
    def agent(self) -> ReflectionAgent:
        return ReflectionAgent()

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: ReflectionAgent) -> None:
        assert agent.agent_id == "reflection"
        assert agent.metadata.cost_tier == 2

    @pytest.mark.asyncio()
    async def test_empty_state_produces_narrative(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
        })
        resp = await agent.handle(msg)

        assert "narrative" in resp.payload
        assert len(resp.payload["narrative"]) > 0
        assert resp.payload["section_count"] >= 1

    @pytest.mark.asyncio()
    async def test_progress_section_with_concepts(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("algebra", 0.9))
        state.upsert_concept(_concept("calculus", 0.3))

        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
        })
        resp = await agent.handle(msg)

        narrative = resp.payload["narrative"]
        assert "2 concepts" in narrative
        assert "mastered" in narrative.lower()

    @pytest.mark.asyncio()
    async def test_session_section_with_diagnosis(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("math", 0.6))

        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "diagnosis": {
                "updates": [
                    {"concept_id": "math", "new_mastery": 0.7, "correct": True},
                ],
            },
        })
        resp = await agent.handle(msg)
        narrative = resp.payload["narrative"]
        assert "math" in narrative.lower()

    @pytest.mark.asyncio()
    async def test_motivation_section_low(self, agent: ReflectionAgent) -> None:
        from learning_navigator.contracts.learner_state import MotivationState

        state = _make_state()
        state.motivation = MotivationState(level=MotivationLevel.LOW, score=0.2, trend=-0.2)

        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
        })
        resp = await agent.handle(msg)
        narrative = resp.payload["narrative"]
        assert "low" in narrative.lower()

    @pytest.mark.asyncio()
    async def test_drift_section_with_signals(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "drift_response": {
                "drift_signals": [
                    {"drift_type": "inactivity", "severity": 0.7},
                ],
            },
        })
        resp = await agent.handle(msg)
        narrative = resp.payload["narrative"]
        assert "inactivity" in narrative.lower()

    @pytest.mark.asyncio()
    async def test_behavior_section_with_anomalies(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "behavior_response": {
                "anomalies": [
                    {"anomaly_type": "cramming", "severity": 0.6},
                ],
            },
        })
        resp = await agent.handle(msg)
        narrative = resp.payload["narrative"]
        assert "cramming" in narrative.lower()

    @pytest.mark.asyncio()
    async def test_citations_include_contributing_agents(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "diagnosis": {"updates": [{"concept_id": "x", "correct": True}]},
            "motivation_response": {"motivation_state": {"level": "medium"}},
        })
        resp = await agent.handle(msg)
        citations = resp.payload["citations"]
        assert "diagnoser" in citations
        assert "motivation" in citations

    @pytest.mark.asyncio()
    async def test_outlook_section_exists(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        state.upsert_concept(_concept("a", 0.5))
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
        })
        resp = await agent.handle(msg)
        # Should have a "Looking Ahead" section
        titles = [s["title"] for s in resp.payload["sections"]]
        assert "Looking Ahead" in titles

    @pytest.mark.asyncio()
    async def test_plan_section_with_recommendations(self, agent: ReflectionAgent) -> None:
        state = _make_state()
        msg = _msg(MessageType.REFLECTION_REQUEST, {
            "learner_state": state.model_dump(mode="json"),
            "plan_response": {
                "recommendations": [
                    {"concept_id": "algebra", "action": "practice"},
                ],
            },
        })
        resp = await agent.handle(msg)
        narrative = resp.payload["narrative"]
        assert "algebra" in narrative.lower()
