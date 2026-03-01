"""Tests for Maker-Checker subsystem and HITL hooks."""

from __future__ import annotations

import pytest

from learning_navigator.agents.evaluator import EvaluatorAgent
from learning_navigator.agents.planner import PlannerAgent
from learning_navigator.contracts.learner_state import (
    BKTParams,
    ConceptState,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.hitl import (
    DefaultHITLHook,
    HITLDecision,
    HITLRequest,
)
from learning_navigator.engine.maker_checker import (
    CheckVerdict,
    MakerChecker,
    MakerCheckerResult,
)


def _state_with_concepts(*concepts: ConceptState) -> LearnerState:
    state = LearnerState(learner_id="test-learner")
    for c in concepts:
        state.upsert_concept(c)
    return state


def _plan_message(state: LearnerState) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=MessageType.PLAN_READY,
        source_agent_id="engine",
        target_agent_id="planner",
        payload={
            "learner_state": state.model_dump(mode="json"),
            "diagnosis": {},
        },
    )


# ── MakerChecker ───────────────────────────────────────────────────

class TestMakerChecker:
    @pytest.fixture()
    def mc(self) -> MakerChecker:
        return MakerChecker(
            maker=PlannerAgent(),
            checker=EvaluatorAgent(),
            max_rounds=2,
        )

    @pytest.mark.asyncio()
    async def test_approves_good_plan(self, mc: MakerChecker) -> None:
        state = _state_with_concepts(
            ConceptState(concept_id="c1", bkt=BKTParams(p_know=0.4)),
            ConceptState(concept_id="c2", bkt=BKTParams(p_know=0.6)),
        )
        result = await mc.run(
            maker_message=_plan_message(state),
            learner_state_raw=state.model_dump(mode="json"),
        )
        assert isinstance(result, MakerCheckerResult)
        assert result.verdict == CheckVerdict.APPROVED
        assert result.rounds >= 1
        assert result.final_confidence > 0

    @pytest.mark.asyncio()
    async def test_empty_state_may_not_produce_plan(self, mc: MakerChecker) -> None:
        state = LearnerState(learner_id="empty")
        result = await mc.run(
            maker_message=_plan_message(state),
            learner_state_raw=state.model_dump(mode="json"),
        )
        # With no concepts, planner produces empty recommendations -> evaluator rejects
        assert isinstance(result, MakerCheckerResult)
        assert result.rounds <= 2

    @pytest.mark.asyncio()
    async def test_maker_checker_result_model(self) -> None:
        r = MakerCheckerResult(
            verdict=CheckVerdict.APPROVED,
            rounds=1,
            final_confidence=0.8,
            rationale="test",
        )
        dumped = r.model_dump()
        assert dumped["verdict"] == "approved"
        assert dumped["rounds"] == 1

    @pytest.mark.asyncio()
    async def test_max_rounds_respected(self) -> None:
        """Maker-checker with strict quality threshold exhausts max rounds."""
        mc = MakerChecker(
            maker=PlannerAgent(),
            checker=EvaluatorAgent(),
            max_rounds=1,
            min_quality_score=0.99,  # unreachable
        )
        state = _state_with_concepts(
            ConceptState(concept_id="c1", bkt=BKTParams(p_know=0.5)),
        )
        result = await mc.run(
            maker_message=_plan_message(state),
            learner_state_raw=state.model_dump(mode="json"),
        )
        assert result.rounds == 1


# ── HITL Hooks ─────────────────────────────────────────────────────

class TestDefaultHITLHook:
    @pytest.fixture()
    def hook(self) -> DefaultHITLHook:
        return DefaultHITLHook(auto_approve_threshold=0.5)

    @pytest.mark.asyncio()
    async def test_auto_approves_above_threshold(self, hook: DefaultHITLHook) -> None:
        request = HITLRequest(
            learner_id="l1",
            recommendation={"action": "study"},
            quality_score=0.8,
        )
        resp = await hook.request_review(request)
        assert resp.decision == HITLDecision.AUTO_APPROVED
        assert len(hook.review_log) == 1

    @pytest.mark.asyncio()
    async def test_auto_rejects_below_threshold(self, hook: DefaultHITLHook) -> None:
        request = HITLRequest(
            learner_id="l1",
            recommendation={"action": "study"},
            quality_score=0.2,
        )
        resp = await hook.request_review(request)
        assert resp.decision == HITLDecision.REJECT

    @pytest.mark.asyncio()
    async def test_should_require_review_with_errors(self, hook: DefaultHITLHook) -> None:
        needs = await hook.should_require_review(
            quality_score=0.8,
            issues=[{"severity": "error", "type": "test"}],
        )
        assert needs is True

    @pytest.mark.asyncio()
    async def test_should_not_require_review_clean(self, hook: DefaultHITLHook) -> None:
        needs = await hook.should_require_review(
            quality_score=0.8,
            issues=[],
        )
        assert needs is False

    @pytest.mark.asyncio()
    async def test_should_require_review_low_quality(self, hook: DefaultHITLHook) -> None:
        needs = await hook.should_require_review(
            quality_score=0.3,
            issues=[],
        )
        assert needs is True

    @pytest.mark.asyncio()
    async def test_review_log_accumulates(self, hook: DefaultHITLHook) -> None:
        for i in range(3):
            await hook.request_review(
                HITLRequest(learner_id=f"l{i}", quality_score=0.5 + i * 0.1)
            )
        assert len(hook.review_log) == 3
