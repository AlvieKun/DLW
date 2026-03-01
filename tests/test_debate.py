"""Tests for Phase 6: Strategic Debate System.

Covers:
- MasteryMaximizer advocate
- ExamStrategist advocate
- BurnoutMinimizer advocate
- DebateArbitrator
- DebateEngine orchestration
- GPS Engine integration with debate
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning_navigator.agents.debate_advocates import (
    BurnoutMinimizer,
    ExamStrategist,
    MasteryMaximizer,
)
from learning_navigator.agents.debate_arbitrator import DebateArbitrator
from learning_navigator.contracts.learner_state import (
    BehavioralAnomaly,
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
from learning_navigator.engine.debate import (
    DebateEngine,
    DebateOutcome,
    DebateResult,
)

# ── Helpers ────────────────────────────────────────────────────────


def _make_state(**overrides) -> LearnerState:
    defaults = {"learner_id": "test-learner"}
    defaults.update(overrides)
    return LearnerState(**defaults)


def _concept(
    cid: str,
    mastery: float = 0.5,
    difficulty: float = 0.5,
    forgetting_score: float = 0.0,
    practice_count: int = 0,
) -> ConceptState:
    return ConceptState(
        concept_id=cid,
        bkt=BKTParams(p_know=mastery),
        difficulty=difficulty,
        forgetting_score=forgetting_score,
        practice_count=practice_count,
    )


def _prereq(src: str, tgt: str) -> ConceptRelation:
    return ConceptRelation(
        source_concept_id=src,
        target_concept_id=tgt,
        relation_type=ConceptRelationType.PREREQUISITE,
    )


def _critique_message(
    state: LearnerState,
    plan: dict,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=MessageType.PLAN_CRITIQUE,
        source_agent_id="test",
        target_agent_id="advocate",
        payload={
            "learner_state": state.model_dump(mode="json"),
            "plan": plan,
        },
    )


def _arb_message(
    state: LearnerState,
    critiques: list[dict],
) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=MessageType.ARBITRATION_RESULT,
        source_agent_id="test",
        target_agent_id="debate-arbitrator",
        payload={
            "learner_state": state.model_dump(mode="json"),
            "critiques": critiques,
        },
    )


# ══════════════════════════════════════════════════════════════════
#  Mastery Maximizer Tests
# ══════════════════════════════════════════════════════════════════


class TestMasteryMaximizer:
    @pytest.fixture()
    def agent(self) -> MasteryMaximizer:
        return MasteryMaximizer()

    @pytest.mark.asyncio()
    async def test_no_objections_for_good_plan(self, agent: MasteryMaximizer):
        """A well-structured plan should get high alignment."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.3))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 20},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert resp.payload["alignment_score"] >= 0.85
        assert resp.payload["objection_count"] == 0

    @pytest.mark.asyncio()
    async def test_prerequisite_violation(self, agent: MasteryMaximizer):
        """Detects unmet prerequisites."""
        state = _make_state(
            concept_relations=[_prereq("prereq1", "advanced1")],
        )
        state.upsert_concept(_concept("prereq1", mastery=0.3))
        state.upsert_concept(_concept("advanced1", mastery=0.2))
        plan = {
            "recommendations": [
                {"concept_id": "advanced1", "action": "learn_new", "minutes": 20},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        obj_types = [o["type"] for o in resp.payload["objections"]]
        assert "prerequisite_violation" in obj_types
        amend_types = [a["type"] for a in resp.payload["amendments"]]
        assert "add_prerequisite" in amend_types

    @pytest.mark.asyncio()
    async def test_insufficient_depth(self, agent: MasteryMaximizer):
        """Flags too-short learning sessions."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.3))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 5},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "insufficient_depth"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_forgetting_ignored(self, agent: MasteryMaximizer):
        """Flags high-forgetting concepts not in the plan."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.7, forgetting_score=0.8))
        state.upsert_concept(_concept("c2", mastery=0.3))
        plan = {
            "recommendations": [
                {"concept_id": "c2", "action": "learn_new", "minutes": 15},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "forgetting_ignored"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_too_many_topics(self, agent: MasteryMaximizer):
        """Flags surface-level coverage with too many topics."""
        state = _make_state()
        recs = []
        for i in range(6):
            cid = f"c{i}"
            state.upsert_concept(_concept(cid, mastery=0.3))
            recs.append({"concept_id": cid, "action": "learn_new", "minutes": 15})
        plan = {"recommendations": recs}
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "too_many_topics"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: MasteryMaximizer):
        assert agent.agent_id == "mastery-maximizer"
        assert agent.perspective == "mastery"


# ══════════════════════════════════════════════════════════════════
#  Exam Strategist Tests
# ══════════════════════════════════════════════════════════════════


class TestExamStrategist:
    @pytest.fixture()
    def agent(self) -> ExamStrategist:
        return ExamStrategist()

    @pytest.mark.asyncio()
    async def test_priority_missing(self, agent: ExamStrategist):
        """Flags priority concepts not included in plan."""
        state = _make_state(
            time_budget=TimeBudget(priority_concept_ids=["priority1"]),
        )
        state.upsert_concept(_concept("priority1", mastery=0.4))
        state.upsert_concept(_concept("other", mastery=0.4))
        plan = {
            "recommendations": [
                {"concept_id": "other", "action": "learn_new", "minutes": 20},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "priority_missing"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_over_maintenance(self, agent: ExamStrategist):
        """Flags too much time on already-mastered concepts."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.95))
        state.upsert_concept(_concept("c2", mastery=0.3))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "maintain", "minutes": 25},
                {"concept_id": "c2", "action": "learn_new", "minutes": 20},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "over_maintenance"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_no_objections_good_plan(self, agent: ExamStrategist):
        """Priority concepts included -> no objections."""
        state = _make_state(
            time_budget=TimeBudget(priority_concept_ids=["c1"]),
        )
        state.upsert_concept(_concept("c1", mastery=0.4))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 30},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert resp.payload["objection_count"] == 0

    @pytest.mark.asyncio()
    async def test_practice_test_amendment(self, agent: ExamStrategist):
        """Suggests practice tests for mid-mastery priority concepts."""
        state = _make_state(
            time_budget=TimeBudget(priority_concept_ids=["c1"]),
        )
        state.upsert_concept(_concept("c1", mastery=0.65))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "practice", "minutes": 20},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            a["type"] == "add_practice_test"
            for a in resp.payload["amendments"]
        )

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: ExamStrategist):
        assert agent.agent_id == "exam-strategist"
        assert agent.perspective == "exam"


# ══════════════════════════════════════════════════════════════════
#  Burnout Minimizer Tests
# ══════════════════════════════════════════════════════════════════


class TestBurnoutMinimizer:
    @pytest.fixture()
    def agent(self) -> BurnoutMinimizer:
        return BurnoutMinimizer()

    @pytest.mark.asyncio()
    async def test_session_too_long_low_motivation(self, agent: BurnoutMinimizer):
        """Flags long sessions with low motivation."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.LOW, score=0.3, trend=-0.1
            ),
        )
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 20},
            ],
            "session_minutes": 50,
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "session_too_long"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_cognitive_overload(self, agent: BurnoutMinimizer):
        """Flags too many hard concepts in one session."""
        state = _make_state()
        recs = []
        for i in range(4):
            cid = f"hard{i}"
            state.upsert_concept(_concept(cid, mastery=0.3, difficulty=0.9))
            recs.append({"concept_id": cid, "action": "learn_new", "minutes": 10})
        plan = {"recommendations": recs, "session_minutes": 40}
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "cognitive_overload"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_all_new_content(self, agent: BurnoutMinimizer):
        """Flags session with all new content and no review."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.2))
        state.upsert_concept(_concept("c2", mastery=0.15))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 15},
                {"concept_id": "c2", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 30,
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "all_new_content"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_existing_overload_signals(self, agent: BurnoutMinimizer):
        """Flags when behavioral anomalies show existing stress."""
        state = _make_state(
            behavioral_anomalies=[
                BehavioralAnomaly(
                    anomaly_type="cramming", severity=0.8, evidence={}
                )
            ],
        )
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 15,
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "existing_overload_signals"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_declining_motivation(self, agent: BurnoutMinimizer):
        """Flags declining motivation trend."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.MEDIUM, score=0.5, trend=-0.3
            ),
        )
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 20,
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert any(
            o["type"] == "declining_motivation"
            for o in resp.payload["objections"]
        )

    @pytest.mark.asyncio()
    async def test_no_objections_calm_session(self, agent: BurnoutMinimizer):
        """Short, low-difficulty session with good motivation -> no objections."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.HIGH, score=0.9, trend=0.1
            ),
        )
        state.upsert_concept(_concept("c1", mastery=0.5, difficulty=0.3))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "practice", "minutes": 15},
            ],
            "session_minutes": 15,
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert resp.payload["objection_count"] == 0
        assert resp.payload["alignment_score"] >= 0.85

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: BurnoutMinimizer):
        assert agent.agent_id == "burnout-minimizer"
        assert agent.perspective == "burnout"


# ══════════════════════════════════════════════════════════════════
#  Debate Arbitrator Tests
# ══════════════════════════════════════════════════════════════════


class TestDebateArbitrator:
    @pytest.fixture()
    def agent(self) -> DebateArbitrator:
        return DebateArbitrator()

    @pytest.mark.asyncio()
    async def test_no_critiques_passes(self, agent: DebateArbitrator):
        """No critiques -> plan passes without debate."""
        state = _make_state()
        msg = _arb_message(state, critiques=[])
        resp = await agent.handle(msg)
        assert resp.payload["resolution"] == "no_debate"
        assert resp.payload["overall_alignment"] == 1.0

    @pytest.mark.asyncio()
    async def test_high_severity_major_revision(self, agent: DebateArbitrator):
        """High-severity objections from multiple perspectives -> major revision."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.LOW, score=0.2, trend=-0.3
            ),
        )
        critiques = [
            {
                "perspective": "mastery",
                "objections": [
                    {"type": "prerequisite_violation", "severity": 0.95},
                ],
                "amendments": [{"type": "add_prerequisite"}],
                "alignment_score": 0.2,
            },
            {
                "perspective": "burnout",
                "objections": [
                    {"type": "cognitive_overload", "severity": 0.95},
                ],
                "amendments": [{"type": "mix_difficulty"}],
                "alignment_score": 0.2,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await agent.handle(msg)
        assert resp.payload["resolution"] == "major_revision"
        assert resp.payload["accepted_objection_count"] >= 1
        assert resp.payload["accepted_amendment_count"] >= 1

    @pytest.mark.asyncio()
    async def test_low_severity_minor_revision(self, agent: DebateArbitrator):
        """Low-severity objections -> minor revision."""
        state = _make_state()
        critiques = [
            {
                "perspective": "mastery",
                "objections": [
                    {"type": "too_many_topics", "severity": 0.3},
                ],
                "amendments": [],
                "alignment_score": 0.75,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await agent.handle(msg)
        # Low severity * moderate weight may be below threshold
        assert resp.payload["resolution"] in ("plan_approved", "minor_revision")

    @pytest.mark.asyncio()
    async def test_weight_adjustment_low_motivation(self, agent: DebateArbitrator):
        """Low motivation boosts burnout weight."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.LOW, score=0.2, trend=-0.3
            ),
        )
        critiques = [
            {
                "perspective": "burnout",
                "objections": [
                    {"type": "session_too_long", "severity": 0.7},
                ],
                "amendments": [{"type": "shorten_session"}],
                "alignment_score": 0.5,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await agent.handle(msg)
        weights = resp.payload["perspective_weights"]
        assert weights["burnout"] > weights["mastery"]

    @pytest.mark.asyncio()
    async def test_weight_adjustment_cramming(self, agent: DebateArbitrator):
        """Cramming anomaly boosts burnout weight."""
        state = _make_state(
            behavioral_anomalies=[
                BehavioralAnomaly(
                    anomaly_type="cramming", severity=0.8, evidence={}
                )
            ],
        )
        critiques = [
            {
                "perspective": "mastery",
                "objections": [{"type": "test", "severity": 0.5}],
                "amendments": [],
                "alignment_score": 0.6,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await agent.handle(msg)
        weights = resp.payload["perspective_weights"]
        # burnout should be boosted
        assert weights["burnout"] > 0.3

    @pytest.mark.asyncio()
    async def test_deadline_boosts_exam_weight(self, agent: DebateArbitrator):
        """Near deadline boosts exam weight."""
        soon = datetime.now(timezone.utc) + timedelta(hours=12)
        state = _make_state(
            time_budget=TimeBudget(deadline=soon),
        )
        critiques = [
            {
                "perspective": "exam",
                "objections": [{"type": "priority_missing", "severity": 0.9}],
                "amendments": [{"type": "add_priority"}],
                "alignment_score": 0.3,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await agent.handle(msg)
        weights = resp.payload["perspective_weights"]
        assert weights["exam"] > weights["mastery"]

    @pytest.mark.asyncio()
    async def test_metadata(self, agent: DebateArbitrator):
        assert agent.agent_id == "debate-arbitrator"


# ══════════════════════════════════════════════════════════════════
#  Debate Engine Tests
# ══════════════════════════════════════════════════════════════════


class TestDebateEngine:
    @pytest.fixture()
    def advocates(self) -> list:
        return [MasteryMaximizer(), ExamStrategist(), BurnoutMinimizer()]

    @pytest.fixture()
    def arbitrator(self) -> DebateArbitrator:
        return DebateArbitrator()

    @pytest.fixture()
    def engine(self, advocates, arbitrator) -> DebateEngine:
        return DebateEngine(
            advocates=advocates,
            arbitrator=arbitrator,
            max_rounds=2,
            enabled=True,
        )

    @pytest.mark.asyncio()
    async def test_debate_skipped_when_disabled(self, advocates, arbitrator):
        engine = DebateEngine(
            advocates=advocates,
            arbitrator=arbitrator,
            enabled=False,
        )
        result = await engine.run(plan={}, learner_state_raw={})
        assert result.outcome == DebateOutcome.DEBATE_SKIPPED
        assert result.rounds_used == 0

    @pytest.mark.asyncio()
    async def test_debate_skipped_no_advocates(self, arbitrator):
        engine = DebateEngine(
            advocates=[],
            arbitrator=arbitrator,
            enabled=True,
        )
        result = await engine.run(plan={}, learner_state_raw={})
        assert result.outcome == DebateOutcome.DEBATE_SKIPPED

    @pytest.mark.asyncio()
    async def test_aligned_plan_approved(self, engine: DebateEngine):
        """Plan with no issues -> all aligned -> approved."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.4))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "practice", "minutes": 20},
            ],
            "session_minutes": 20,
        }
        result = await engine.run(
            plan=plan,
            learner_state_raw=state.model_dump(mode="json"),
        )
        assert result.outcome == DebateOutcome.PLAN_APPROVED
        assert result.rounds_used == 1
        assert result.overall_alignment >= 0.85

    @pytest.mark.asyncio()
    async def test_problematic_plan_gets_revision(self, engine: DebateEngine):
        """Plan with many issues -> minor or major revision."""
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.LOW, score=0.2, trend=-0.3
            ),
            concept_relations=[_prereq("prereq1", "adv1")],
        )
        state.upsert_concept(_concept("prereq1", mastery=0.2))
        state.upsert_concept(_concept("adv1", mastery=0.1, difficulty=0.9))
        state.upsert_concept(_concept("hard2", mastery=0.1, difficulty=0.9))
        state.upsert_concept(_concept("hard3", mastery=0.1, difficulty=0.9))
        plan = {
            "recommendations": [
                {"concept_id": "adv1", "action": "learn_new", "minutes": 5},
                {"concept_id": "hard2", "action": "learn_new", "minutes": 5},
                {"concept_id": "hard3", "action": "learn_new", "minutes": 5},
            ],
            "session_minutes": 60,
        }
        result = await engine.run(
            plan=plan,
            learner_state_raw=state.model_dump(mode="json"),
        )
        assert result.outcome in (
            DebateOutcome.MINOR_REVISION,
            DebateOutcome.MAJOR_REVISION,
        )
        assert len(result.advocate_critiques) == 3
        assert result.arbitration  # non-empty

    @pytest.mark.asyncio()
    async def test_debate_returns_perspective_weights(self, engine: DebateEngine):
        """Debate result includes perspective weights from arbitrator."""
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.4, forgetting_score=0.7))
        plan = {
            "recommendations": [
                {"concept_id": "c2", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 30,
        }
        result = await engine.run(
            plan=plan,
            learner_state_raw=state.model_dump(mode="json"),
        )
        # If there were objections, we get arbitration
        if result.outcome != DebateOutcome.PLAN_APPROVED:
            assert "mastery" in result.perspective_weights
            assert "exam" in result.perspective_weights
            assert "burnout" in result.perspective_weights

    @pytest.mark.asyncio()
    async def test_debate_result_model(self):
        """DebateResult model defaults."""
        result = DebateResult()
        assert result.outcome == DebateOutcome.DEBATE_SKIPPED
        assert result.rounds_used == 0
        assert result.advocate_critiques == []

    @pytest.mark.asyncio()
    async def test_max_rounds_respected(self, advocates, arbitrator):
        """Engine does not exceed max_rounds."""
        engine = DebateEngine(
            advocates=advocates,
            arbitrator=arbitrator,
            max_rounds=1,
            enabled=True,
        )
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.CRITICAL, score=0.1, trend=-0.5
            ),
        )
        state.upsert_concept(_concept("c1", mastery=0.1, difficulty=0.9))
        state.upsert_concept(_concept("c2", mastery=0.1, difficulty=0.9))
        state.upsert_concept(_concept("c3", mastery=0.1, difficulty=0.9))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 5},
                {"concept_id": "c2", "action": "learn_new", "minutes": 5},
                {"concept_id": "c3", "action": "learn_new", "minutes": 5},
            ],
            "session_minutes": 90,
        }
        result = await engine.run(
            plan=plan,
            learner_state_raw=state.model_dump(mode="json"),
        )
        assert result.rounds_used <= 1


# ══════════════════════════════════════════════════════════════════
#  Advocate Response Structure Tests
# ══════════════════════════════════════════════════════════════════


class TestAdvocateResponseStructure:
    """Verify all advocates return well-formed response payloads."""

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("agent_cls", [MasteryMaximizer, ExamStrategist, BurnoutMinimizer])
    async def test_response_has_required_fields(self, agent_cls):
        agent = agent_cls()
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.4))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 15},
            ],
            "session_minutes": 15,
        }
        resp = await agent.handle(_critique_message(state, plan))
        payload = resp.payload
        assert "perspective" in payload
        assert "objections" in payload
        assert "amendments" in payload
        assert "alignment_score" in payload
        assert "objection_count" in payload
        assert "amendment_count" in payload
        assert isinstance(payload["objections"], list)
        assert isinstance(payload["amendments"], list)
        assert 0.0 <= payload["alignment_score"] <= 1.0

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("agent_cls", [MasteryMaximizer, ExamStrategist, BurnoutMinimizer])
    async def test_empty_plan_no_crash(self, agent_cls):
        """Advocates handle empty plan without error."""
        agent = agent_cls()
        state = _make_state()
        plan = {"recommendations": []}
        resp = await agent.handle(_critique_message(state, plan))
        assert resp.payload["objection_count"] >= 0

    @pytest.mark.asyncio()
    @pytest.mark.parametrize("agent_cls", [MasteryMaximizer, ExamStrategist, BurnoutMinimizer])
    async def test_confidence_range(self, agent_cls):
        agent = agent_cls()
        state = _make_state()
        state.upsert_concept(_concept("c1", mastery=0.4))
        plan = {
            "recommendations": [
                {"concept_id": "c1", "action": "learn_new", "minutes": 15},
            ],
        }
        resp = await agent.handle(_critique_message(state, plan))
        assert 0.0 <= resp.confidence <= 1.0


# ══════════════════════════════════════════════════════════════════
#  Arbitrator Weight Computation Tests
# ══════════════════════════════════════════════════════════════════


class TestArbitratorWeights:
    """Focused tests on contextual weight computation."""

    def test_default_weights_sum_to_one(self):
        arb = DebateArbitrator()
        total = sum(arb.base_weights.values())
        assert abs(total - 1.0) < 1e-6

    @pytest.mark.asyncio()
    async def test_weights_normalise(self):
        """After adjustments, weights still normalise to 1.0."""
        arb = DebateArbitrator()
        state = _make_state(
            motivation=MotivationState(
                level=MotivationLevel.CRITICAL, score=0.1, trend=-0.5
            ),
            behavioral_anomalies=[
                BehavioralAnomaly(anomaly_type="cramming", severity=0.8, evidence={})
            ],
        )
        soon = datetime.now(timezone.utc) + timedelta(hours=6)
        state.time_budget = TimeBudget(deadline=soon)

        critiques = [
            {
                "perspective": "mastery",
                "objections": [{"type": "test", "severity": 0.5}],
                "amendments": [],
                "alignment_score": 0.5,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await arb.handle(msg)
        weights = resp.payload["perspective_weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-3

    @pytest.mark.asyncio()
    async def test_rejected_objections_tracked(self):
        """Low-severity objections can be rejected."""
        arb = DebateArbitrator(objection_threshold=0.5)
        state = _make_state()
        critiques = [
            {
                "perspective": "mastery",
                "objections": [{"type": "minor", "severity": 0.2}],
                "amendments": [{"type": "small_tweak"}],
                "alignment_score": 0.8,
            },
        ]
        msg = _arb_message(state, critiques)
        resp = await arb.handle(msg)
        # With severity 0.2 * weight ~0.4 = 0.08, below 0.5 threshold
        assert len(resp.payload["rejected_objections"]) >= 1


# ══════════════════════════════════════════════════════════════════
#  Import / Export Tests
# ══════════════════════════════════════════════════════════════════


class TestImports:
    def test_agents_init_exports(self):
        from learning_navigator.agents import (
            BurnoutMinimizer,
            DebateArbitrator,
            ExamStrategist,
            MasteryMaximizer,
        )
        assert MasteryMaximizer is not None
        assert ExamStrategist is not None
        assert BurnoutMinimizer is not None
        assert DebateArbitrator is not None

    def test_engine_init_exports(self):
        from learning_navigator.engine import (
            DebateEngine,
            DebateOutcome,
            DebateResult,
        )
        assert DebateEngine is not None
        assert DebateOutcome is not None
        assert DebateResult is not None
