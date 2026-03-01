"""Tests for message contracts — MessageEnvelope, LearnerEvent, NextBestAction."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from learning_navigator.contracts.events import (
    LearnerEvent,
    LearnerEventType,
    NextBestAction,
)
from learning_navigator.contracts.messages import (
    MessageEnvelope,
    MessageType,
    Provenance,
    Severity,
)


class TestMessageEnvelope:
    """Validate envelope creation, serialization, and causal derivation."""

    def test_create_minimal(self) -> None:
        msg = MessageEnvelope(
            message_type=MessageType.LEARNER_EVENT,
            source_agent_id="orchestrator",
        )
        assert msg.schema_version == "1.0.0"
        assert msg.message_type == MessageType.LEARNER_EVENT
        assert msg.source_agent_id == "orchestrator"
        assert msg.target_agent_id is None
        assert msg.severity == Severity.MEDIUM
        assert isinstance(msg.message_id, str) and len(msg.message_id) == 32
        assert isinstance(msg.created_at, datetime)
        assert msg.provenance.trace_id

    def test_roundtrip_json(self) -> None:
        msg = MessageEnvelope(
            message_type=MessageType.AGENT_REQUEST,
            source_agent_id="planner",
            target_agent_id="evaluator",
            payload={"concept": "algebra", "score": 0.72},
        )
        json_str = msg.model_dump_json()
        restored = MessageEnvelope.model_validate_json(json_str)
        assert restored.message_id == msg.message_id
        assert restored.payload["concept"] == "algebra"
        assert restored.payload["score"] == 0.72

    def test_derive_preserves_correlation(self) -> None:
        parent = MessageEnvelope(
            message_type=MessageType.LEARNER_EVENT,
            source_agent_id="orchestrator",
            correlation_id="session-42",
        )
        child = parent.derive(
            message_type=MessageType.AGENT_REQUEST,
            source_agent_id="orchestrator",
            target_agent_id="diagnoser",
            payload={"foo": "bar"},
        )
        assert child.correlation_id == "session-42"
        assert child.causality_chain == [parent.message_id]
        assert child.provenance.trace_id == parent.provenance.trace_id
        assert child.provenance.parent_span_id == parent.provenance.span_id

    def test_derive_chain_grows(self) -> None:
        m1 = MessageEnvelope(
            message_type=MessageType.LEARNER_EVENT,
            source_agent_id="a",
        )
        m2 = m1.derive(
            message_type=MessageType.AGENT_REQUEST,
            source_agent_id="b",
        )
        m3 = m2.derive(
            message_type=MessageType.AGENT_RESPONSE,
            source_agent_id="c",
        )
        assert m3.causality_chain == [m1.message_id, m2.message_id]

    def test_all_message_types_are_strings(self) -> None:
        for mt in MessageType:
            assert isinstance(mt.value, str)


class TestProvenance:
    def test_defaults(self) -> None:
        p = Provenance()
        assert len(p.trace_id) == 32
        assert len(p.span_id) == 16
        assert p.parent_span_id is None

    def test_custom_tags(self) -> None:
        p = Provenance(tags={"env": "test"})
        assert p.tags["env"] == "test"


class TestLearnerEvent:
    def test_create(self) -> None:
        evt = LearnerEvent(
            event_id="e1",
            learner_id="learner-001",
            event_type=LearnerEventType.QUIZ_RESULT,
            concept_id="algebra-101",
            data={"score": 0.8, "max_score": 1.0},
        )
        assert evt.learner_id == "learner-001"
        assert evt.event_type == LearnerEventType.QUIZ_RESULT
        assert evt.data["score"] == 0.8

    def test_optional_concept(self) -> None:
        evt = LearnerEvent(
            event_id="e2",
            learner_id="learner-001",
            event_type=LearnerEventType.SENTIMENT_SIGNAL,
        )
        assert evt.concept_id is None


class TestNextBestAction:
    def test_valid(self) -> None:
        nba = NextBestAction(
            action_id="a1",
            learner_id="learner-001",
            recommended_action="Review algebra fundamentals",
            rationale="Quiz score dropped below threshold",
            confidence=0.85,
            expected_learning_gain=0.15,
            risk_assessment={"burnout": 0.1, "drift": 0.3},
            citations=["doc:algebra-101:chunk-3"],
        )
        assert nba.confidence == 0.85
        assert "burnout" in nba.risk_assessment

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            NextBestAction(
                action_id="a2",
                learner_id="l",
                recommended_action="x",
                rationale="y",
                confidence=1.5,  # out of range
                expected_learning_gain=0.1,
            )

    def test_gain_bounds(self) -> None:
        with pytest.raises(ValidationError):
            NextBestAction(
                action_id="a3",
                learner_id="l",
                recommended_action="x",
                rationale="y",
                confidence=0.5,
                expected_learning_gain=-0.1,  # out of range
            )
