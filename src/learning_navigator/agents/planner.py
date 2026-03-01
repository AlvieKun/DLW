"""Planner Agent — generates study plan recommendations.

The Planner takes the diagnosed learner state and produces a concrete
next-step recommendation: what to study, how long, and why.

Planning heuristics (v1, rule-based):
1. Prioritise weak concepts with unmet prerequisites.
2. Respect time budget constraints.
3. Factor in forgetting scores (prefer concepts about to be forgotten).
4. Adjust intensity based on motivation level.
"""

from __future__ import annotations

from typing import Any

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
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)


class PlannerAgent(BaseAgent):
    """Generates a study plan recommendation based on learner state."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="planner",
                display_name="Planner Agent",
                capabilities=[AgentCapability.PLAN],
                cost_tier=2,
                description="Generates study plan recommendations",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        payload = message.payload
        learner_state_raw = payload.get("learner_state")
        diagnosis = payload.get("diagnosis", {})

        if not learner_state_raw:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=["Missing learner_state in payload"],
            )

        try:
            state = LearnerState.model_validate(learner_state_raw)
            plan = self._create_plan(state, diagnosis)

            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=plan["confidence"],
                payload=plan,
                rationale=plan["rationale"],
            )
        except Exception as e:
            logger.exception("planner.handle_error")
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=[str(e)],
            )

    def _create_plan(
        self, state: LearnerState, diagnosis: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a study plan using rule-based prioritisation."""
        recommendations: list[dict[str, Any]] = []

        # Collect candidate concepts
        candidates = self._rank_concepts(state)

        # Determine session parameters from motivation
        session_minutes = state.time_budget.preferred_session_minutes
        if state.motivation.level == MotivationLevel.CRITICAL:
            session_minutes = min(session_minutes, 20)  # short sessions
        elif state.motivation.level == MotivationLevel.LOW:
            session_minutes = min(session_minutes, 30)

        # Build recommendations from top candidates
        remaining_minutes = session_minutes
        for concept_id, priority_score, reason in candidates[:5]:
            if remaining_minutes <= 0:
                break

            concept = state.get_concept(concept_id)
            if concept is None:
                continue

            alloc_minutes = min(remaining_minutes, 15)
            recommendations.append({
                "concept_id": concept_id,
                "action": self._suggest_action(concept.mastery, concept.forgetting_score),
                "minutes": alloc_minutes,
                "priority_score": round(priority_score, 3),
                "reason": reason,
            })
            remaining_minutes -= alloc_minutes

        if not recommendations and state.concepts:
            # Fallback: review the weakest concept
            weakest = state.weak_concepts(threshold=1.0)
            if weakest:
                recommendations.append({
                    "concept_id": weakest[0].concept_id,
                    "action": "review",
                    "minutes": session_minutes,
                    "priority_score": 0.5,
                    "reason": "fallback_weakest_concept",
                })

        confidence = min(0.85, 0.4 + 0.1 * len(recommendations))
        rationale = (
            f"Plan: {len(recommendations)} activities, "
            f"{session_minutes}min session, "
            f"motivation={state.motivation.level.value}"
        )

        return {
            "recommendations": recommendations,
            "session_minutes": session_minutes,
            "motivation_adjustment": state.motivation.level.value,
            "confidence": confidence,
            "rationale": rationale,
        }

    def _rank_concepts(
        self, state: LearnerState
    ) -> list[tuple[str, float, str]]:
        """Rank concepts by study priority. Returns (concept_id, score, reason)."""
        scored: list[tuple[str, float, str]] = []

        for concept in state.concepts.values():
            score = 0.0
            reason = "general_review"

            # Factor 1: Low mastery = high priority
            mastery_gap = 1.0 - concept.mastery
            score += mastery_gap * 3.0

            # Factor 2: High forgetting = urgent
            score += concept.forgetting_score * 2.5

            # Factor 3: Priority concepts get a boost
            if concept.concept_id in state.time_budget.priority_concept_ids:
                score += 2.0
                reason = "priority_concept"

            # Factor 4: Prerequisites first — if this concept blocks others
            dependents = state.dependents_of(concept.concept_id)
            if dependents and concept.mastery < 0.6:
                score += 1.5 * len(dependents)
                reason = "prerequisite_for_others"

            # Factor 5: High uncertainty = needs more data
            score += concept.uncertainty * 1.0

            # Determine most important reason
            if concept.forgetting_score > 0.5:
                reason = "high_forgetting"
            elif mastery_gap > 0.6:
                reason = "low_mastery"

            scored.append((concept.concept_id, score, reason))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    @staticmethod
    def _suggest_action(mastery: float, forgetting_score: float) -> str:
        """Suggest the type of activity based on mastery and forgetting."""
        if forgetting_score > 0.5:
            return "spaced_review"
        if mastery < 0.3:
            return "learn_new"
        if mastery < 0.6:
            return "practice"
        if mastery < 0.85:
            return "deepen"
        return "maintain"
