"""Motivation Agent — infers learner motivation level and trend.

Uses heuristic signals from the learner state (engagement patterns,
quiz performance trends, session frequency) to estimate motivation.

Future: could integrate sentiment analysis from learner messages
or physiological signals.
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
    LearnerState,
    MotivationLevel,
    MotivationState,
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)


class MotivationAgent(BaseAgent):
    """Estimates motivation level from behavioral signals in learner state."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="motivation",
                display_name="Motivation Agent",
                capabilities=[AgentCapability.MOTIVATE],
                cost_tier=1,
                description="Infers motivation level + trend from learner signals",
            )
        )

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
            result = self._assess_motivation(state)

            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=result["confidence"],
                payload=result,
                rationale=result["rationale"],
            )
        except Exception as e:
            logger.exception("motivation.handle_error")
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=[str(e)],
            )

    def _assess_motivation(self, state: LearnerState) -> dict:
        """Compute motivation score from multiple signals."""
        signals: list[tuple[float, float]] = []  # (score_contribution, weight)

        # Signal 1: Session frequency — more sessions = higher motivation
        if state.session_count > 0:
            # Normalize: 10+ sessions/week mapped to score ~1.0
            freq_score = min(1.0, state.session_count / 10.0)
            signals.append((freq_score, 1.0))

        # Signal 2: Practice consistency — low inactivity = motivated
        inactivity = state.inactivity_hours()
        if inactivity is not None:
            if inactivity < 12:
                signals.append((0.9, 1.5))
            elif inactivity < 24:
                signals.append((0.7, 1.0))
            elif inactivity < 72:
                signals.append((0.4, 1.0))
            else:
                signals.append((0.15, 1.5))

        # Signal 3: Mastery trend — improving mastery = motivated
        avg_mastery = state.average_mastery()
        if avg_mastery > 0:
            signals.append((min(1.0, avg_mastery * 1.2), 0.8))

        # Signal 4: Explicit sentiment (if present in metadata)
        explicit_sentiment = state.metadata.get("last_sentiment_score")
        if explicit_sentiment is not None:
            signals.append((float(explicit_sentiment), 2.0))

        # Weighted average
        if signals:
            total_weight = sum(w for _, w in signals)
            motivation_score = sum(s * w for s, w in signals) / total_weight
        else:
            motivation_score = 0.5  # default uncertainty

        # Compute trend relative to previous
        old_score = state.motivation.score
        trend = motivation_score - old_score

        # Map score to level
        if motivation_score >= 0.7:
            level = MotivationLevel.HIGH
        elif motivation_score >= 0.4:
            level = MotivationLevel.MEDIUM
        elif motivation_score >= 0.2:
            level = MotivationLevel.LOW
        else:
            level = MotivationLevel.CRITICAL

        # Confidence based on signal count
        confidence = min(0.9, 0.4 + 0.1 * len(signals))

        new_state = MotivationState(
            level=level,
            score=round(motivation_score, 3),
            trend=round(max(-1.0, min(1.0, trend)), 3),
            confidence=confidence,
            last_updated=datetime.now(timezone.utc),
        )

        rationale_parts = [f"score={motivation_score:.2f}", f"level={level.value}"]
        if trend > 0.05:
            rationale_parts.append("trending up")
        elif trend < -0.05:
            rationale_parts.append("trending down")
        else:
            rationale_parts.append("stable")

        return {
            "motivation_state": new_state.model_dump(mode="json"),
            "confidence": confidence,
            "signals_used": len(signals),
            "rationale": f"Motivation assessment: {', '.join(rationale_parts)}",
        }
