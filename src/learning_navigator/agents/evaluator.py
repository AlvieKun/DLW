"""Evaluator Agent — assesses plan quality and predicts outcomes.

The Evaluator performs two duties:
1. **Pre-execution**: Reviews a plan from the Planner and scores its quality,
   checking for prerequisite violations, overload risk, and alignment with
   learner goals.
2. **Post-execution**: After a learning session, evaluates actual outcomes
   against predicted gains.

This is a key component of the Maker-Checker loop: the Planner *makes* and
the Evaluator *checks*.
"""

from __future__ import annotations

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


class EvaluatorAgent(BaseAgent):
    """Evaluates plan quality and checks for safety / effectiveness."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="evaluator",
                display_name="Evaluator Agent",
                capabilities=[AgentCapability.EVALUATE],
                cost_tier=2,
                description="Evaluates plan quality and learning outcomes",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        payload = message.payload
        learner_state_raw = payload.get("learner_state")
        plan = payload.get("plan")

        if not learner_state_raw or not plan:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=["Missing learner_state or plan in payload"],
            )

        try:
            state = LearnerState.model_validate(learner_state_raw)
            evaluation = self._evaluate_plan(state, plan)

            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=evaluation["confidence"],
                payload=evaluation,
                rationale=evaluation["rationale"],
            )
        except Exception as e:
            logger.exception("evaluator.handle_error")
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=[str(e)],
            )

    def _evaluate_plan(
        self,
        state: LearnerState,
        plan: dict,
    ) -> dict:
        """Evaluate a study plan for quality, safety, and alignment."""
        recommendations = plan.get("recommendations", [])
        issues: list[dict] = []
        score = 1.0  # start at perfect, deduct for issues

        # Check 1: Prerequisite violations
        for rec in recommendations:
            concept_id = rec.get("concept_id", "")
            prereqs = state.prerequisites_for(concept_id)
            for prereq_id in prereqs:
                prereq_concept = state.get_concept(prereq_id)
                if prereq_concept and prereq_concept.mastery < 0.5:
                    issues.append({
                        "type": "prerequisite_violation",
                        "concept_id": concept_id,
                        "prerequisite_id": prereq_id,
                        "prerequisite_mastery": prereq_concept.mastery,
                        "severity": "warning",
                    })
                    score -= 0.15

        # Check 2: Overload risk
        session_minutes = plan.get("session_minutes", 0)
        if state.motivation.level in (MotivationLevel.LOW, MotivationLevel.CRITICAL) and session_minutes > 30:
                issues.append({
                    "type": "overload_risk",
                    "reason": "long_session_low_motivation",
                    "session_minutes": session_minutes,
                    "motivation_level": state.motivation.level.value,
                    "severity": "warning",
                })
                score -= 0.2

        # Check 3: Too many new concepts at once
        new_concepts = [
            r for r in recommendations
            if r.get("action") == "learn_new"
        ]
        if len(new_concepts) > 2:
            issues.append({
                "type": "cognitive_overload",
                "reason": "too_many_new_concepts",
                "count": len(new_concepts),
                "severity": "warning",
            })
            score -= 0.15

        # Check 4: Empty plan
        if not recommendations:
            issues.append({
                "type": "empty_plan",
                "reason": "no_recommendations_generated",
                "severity": "error",
            })
            score -= 0.5

        # Check 5: Time budget exceeded
        total_minutes = sum(r.get("minutes", 0) for r in recommendations)
        budget_minutes = state.time_budget.preferred_session_minutes
        if total_minutes > budget_minutes * 1.2:
            issues.append({
                "type": "time_budget_exceeded",
                "planned_minutes": total_minutes,
                "budget_minutes": budget_minutes,
                "severity": "warning",
            })
            score -= 0.1

        # Check 6: Priority concepts neglected
        priority_ids = set(state.time_budget.priority_concept_ids)
        planned_ids = {r.get("concept_id", "") for r in recommendations}
        missed_priorities = priority_ids - planned_ids
        if missed_priorities and recommendations:
            issues.append({
                "type": "priority_neglect",
                "missed_concept_ids": sorted(missed_priorities),
                "severity": "info",
            })
            score -= 0.05 * len(missed_priorities)

        score = max(0.0, min(1.0, score))
        approved = score >= 0.5 and not any(
            i["severity"] == "error" for i in issues
        )

        rationale = (
            f"Evaluation: score={score:.2f}, "
            f"{len(issues)} issues, "
            f"approved={approved}"
        )

        return {
            "approved": approved,
            "quality_score": round(score, 3),
            "issues": issues,
            "issue_count": len(issues),
            "recommendations_count": len(recommendations),
            "confidence": min(0.9, 0.5 + 0.1 * len(recommendations)),
            "rationale": rationale,
        }
