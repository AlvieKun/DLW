"""Domain event types ingested by the Learning GPS Engine.

These represent *external* learner events (quiz, time-on-task, sentiment,
inactivity) that trigger orchestrator processing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LearnerEventType(str, Enum):
    """Categories of raw learner events."""

    QUIZ_RESULT = "quiz_result"
    TIME_ON_TASK = "time_on_task"
    SENTIMENT_SIGNAL = "sentiment_signal"
    MOTIVATION_SIGNAL = "motivation_signal"
    INACTIVITY_GAP = "inactivity_gap"
    CONTENT_INTERACTION = "content_interaction"
    SELF_REPORT = "self_report"
    TEACHER_ANNOTATION = "teacher_annotation"
    CUSTOM = "custom"


class LearnerEvent(BaseModel):
    """A single event produced by a learner's activity."""

    event_id: str
    learner_id: str
    event_type: LearnerEventType
    concept_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = "unknown"


class NextBestAction(BaseModel):
    """The orchestrator's output recommendation to the learner/frontend.

    Each recommendation is explainable: it carries rationale, confidence,
    expected gain, and risk flags produced by the agent ensemble.
    """

    action_id: str
    learner_id: str
    recommended_action: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    expected_learning_gain: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalized estimated gain if followed.",
    )
    risk_assessment: dict[str, float] = Field(
        default_factory=dict,
        description="Risk scores keyed by risk type (burnout, drift, forgetting).",
    )
    citations: list[str] = Field(
        default_factory=list,
        description="RAG citation keys grounding this recommendation.",
    )
    debug_trace: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque debug info for telemetry / HITL review.",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
