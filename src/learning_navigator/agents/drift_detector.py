"""Drift Detector Agent — detects learning drift and off-track signals.

Drift detection monitors for patterns indicating the learner is
diverging from their goals:
• Topic drift — studying unrelated material.
• Difficulty mismatch — content too easy or too hard.
• Disengagement — declining interaction quality.
• Goal misalignment — actions not matching stated priorities.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from learning_navigator.agents.base import (
    AgentCapability,
    AgentMetadata,
    AgentResponse,
    BaseAgent,
)
from learning_navigator.contracts.learner_state import (
    DriftSignal,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)


class DriftDetectorAgent(BaseAgent):
    """Detects learning drift by analysing state patterns and recent events."""

    def __init__(self, inactivity_threshold_hours: float = 48.0) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="drift-detector",
                display_name="Drift Detector Agent",
                capabilities=[AgentCapability.DETECT_DRIFT],
                cost_tier=1,
                description="Detects learning drift and off-track signals",
            )
        )
        self._inactivity_threshold = inactivity_threshold_hours

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        payload = message.payload
        learner_state_raw = payload.get("learner_state")

        if not learner_state_raw:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=["Missing learner_state in payload"],
            )

        try:
            state = LearnerState.model_validate(learner_state_raw)
            signals = self._detect_drift(state)

            severity_max = max((s.severity for s in signals), default=0.0)
            confidence = 0.7 if signals else 0.8

            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=confidence,
                payload={
                    "drift_signals": [s.model_dump() for s in signals],
                    "drift_detected": len(signals) > 0,
                    "max_severity": severity_max,
                },
                rationale=(
                    f"Detected {len(signals)} drift signal(s), "
                    f"max severity={severity_max:.2f}"
                    if signals
                    else "No drift detected"
                ),
            )
        except Exception as e:
            logger.exception("drift_detector.handle_error")
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=[str(e)],
            )

    def _detect_drift(self, state: LearnerState) -> list[DriftSignal]:
        signals: list[DriftSignal] = []
        now = datetime.now(timezone.utc)

        # 1. Inactivity drift
        inactivity = state.inactivity_hours()
        if inactivity is not None and inactivity > self._inactivity_threshold:
            severity = min(1.0, inactivity / (self._inactivity_threshold * 3))
            signals.append(
                DriftSignal(
                    drift_type="inactivity",
                    severity=severity,
                    detected_at=now,
                    details={"hours_inactive": inactivity},
                )
            )

        # 2. Mastery plateau — concepts practiced many times but mastery < 0.4
        for concept in state.concepts.values():
            if concept.practice_count >= 5 and concept.mastery < 0.4:
                signals.append(
                    DriftSignal(
                        drift_type="mastery_plateau",
                        severity=0.6,
                        detected_at=now,
                        details={
                            "concept_id": concept.concept_id,
                            "mastery": concept.mastery,
                            "practice_count": concept.practice_count,
                        },
                    )
                )

        # 3. Difficulty mismatch — too easy (mastery > 0.95, still practicing)
        for concept in state.concepts.values():
            if concept.mastery > 0.95 and concept.practice_count > 10:
                signals.append(
                    DriftSignal(
                        drift_type="difficulty_mismatch_easy",
                        severity=0.3,
                        detected_at=now,
                        details={
                            "concept_id": concept.concept_id,
                            "mastery": concept.mastery,
                        },
                    )
                )

        # 4. Motivation decline as drift proxy
        if state.motivation.score < 0.3 and state.motivation.trend < -0.1:
            signals.append(
                DriftSignal(
                    drift_type="disengagement",
                    severity=0.7,
                    detected_at=now,
                    details={
                        "motivation_score": state.motivation.score,
                        "motivation_trend": state.motivation.trend,
                    },
                )
            )

        # 5. Priority concept neglect
        priority_ids = state.time_budget.priority_concept_ids
        if priority_ids:
            for pid in priority_ids:
                c = state.get_concept(pid)
                if c and c.last_practiced:
                    hours_since = (now - c.last_practiced).total_seconds() / 3600
                    if hours_since > self._inactivity_threshold and c.mastery < 0.7:
                        signals.append(
                            DriftSignal(
                                drift_type="priority_neglect",
                                severity=0.5,
                                detected_at=now,
                                details={
                                    "concept_id": pid,
                                    "hours_since_practice": hours_since,
                                },
                            )
                        )

        return signals
