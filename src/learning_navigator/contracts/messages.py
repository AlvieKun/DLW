"""Message envelope contracts for multi-agent communication.

Every inter-agent message is wrapped in a MessageEnvelope that carries
schema versioning, correlation/causality tracking, provenance metadata,
and a validated payload.  This is the *only* way agents communicate
through the EventBus.

Design decisions
────────────────
• Pydantic v2 for runtime validation + JSON schema generation.
• Generic payload via discriminated union or free-form dict — we start with
  typed payloads per message_type and fall back to ``dict`` for extensibility.
• ``schema_version`` enables forward-compatible migrations.
• ``correlation_id`` + ``causality_chain`` enable full distributed tracing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Message types ──────────────────────────────────────────────────────────

class MessageType(str, Enum):
    """Well-known message types flowing through the system."""

    # Orchestrator lifecycle
    LEARNER_EVENT = "learner_event"
    NEXT_BEST_ACTION = "next_best_action"
    AGENT_REQUEST = "agent_request"
    AGENT_RESPONSE = "agent_response"

    # Diagnostic / state
    DIAGNOSIS_REQUEST = "diagnosis_request"
    DIAGNOSIS_RESULT = "diagnosis_result"
    DRIFT_ALERT = "drift_alert"
    MOTIVATION_SIGNAL = "motivation_signal"
    MOTIVATION_UPDATE = "motivation_update"

    # Planning & debate
    PLAN_PROPOSAL = "plan_proposal"
    PLAN_READY = "plan_ready"
    PLAN_REVIEW = "plan_review"
    PLAN_CRITIQUE = "plan_critique"
    ARBITRATION_RESULT = "arbitration_result"
    EVALUATION_RESULT = "evaluation_result"

    # Continual learning
    DECAY_REQUEST = "decay_request"
    DECAY_REPORT = "decay_report"
    REPLAY_REQUEST = "replay_request"
    REPLAY_ARTIFACT = "replay_artifact"

    # RAG
    RAG_QUERY = "rag_query"
    RAG_RESULT = "rag_result"

    # Maker-Checker
    CHECK_REQUEST = "check_request"
    CHECK_RESULT = "check_result"

    # Phase 4 specialized agents
    SKILL_STATE_REQUEST = "skill_state_request"
    SKILL_STATE_RESULT = "skill_state_result"
    BEHAVIOR_REQUEST = "behavior_request"
    BEHAVIOR_RESULT = "behavior_result"
    TIME_ALLOCATION_REQUEST = "time_allocation_request"
    TIME_ALLOCATION_RESULT = "time_allocation_result"
    REFLECTION_REQUEST = "reflection_request"
    REFLECTION_RESULT = "reflection_result"

    # Human-in-the-loop
    HITL_OVERRIDE = "hitl_override"
    HITL_EXPLANATION = "hitl_explanation"

    # Engine output
    ACTION_RECOMMENDED = "action_recommended"

    # Generic extensibility
    CUSTOM = "custom"


class Severity(str, Enum):
    """Urgency/severity tag for messages."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Provenance ─────────────────────────────────────────────────────────────

class Provenance(BaseModel):
    """Trace metadata attached to every message for observability."""

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


# ── The Envelope ───────────────────────────────────────────────────────────

class MessageEnvelope(BaseModel):
    """Canonical message envelope for all inter-agent communication.

    Every field is explicit so that:
    • Messages are self-describing and can be logged/stored as-is.
    • Any consumer can validate without out-of-band knowledge.
    • Migration is straightforward via ``schema_version``.
    """

    # Identity & versioning
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: str = Field(default="1.0.0")
    message_type: MessageType
    severity: Severity = Severity.MEDIUM

    # Correlation / causality
    correlation_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Groups messages belonging to the same user interaction / session turn.",
    )
    causality_chain: list[str] = Field(
        default_factory=list,
        description="Ordered list of parent message_ids that led to this message.",
    )

    # Addressing
    source_agent_id: str
    target_agent_id: str | None = None  # None = broadcast

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Payload — typed per message_type; dict for flexibility at v1
    payload: dict[str, Any] = Field(default_factory=dict)

    # Observability
    provenance: Provenance = Field(default_factory=Provenance)

    # ── helpers ────────────────────────────────────────────────────────

    def derive(
        self,
        *,
        message_type: MessageType,
        source_agent_id: str,
        target_agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
        severity: Severity | None = None,
    ) -> MessageEnvelope:
        """Create a causally-linked child message preserving correlation context."""
        return MessageEnvelope(
            schema_version=self.schema_version,
            message_type=message_type,
            severity=severity or self.severity,
            correlation_id=self.correlation_id,
            causality_chain=[*self.causality_chain, self.message_id],
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            payload=payload or {},
            provenance=Provenance(
                trace_id=self.provenance.trace_id,
                parent_span_id=self.provenance.span_id,
                tags=self.provenance.tags.copy(),
            ),
        )
