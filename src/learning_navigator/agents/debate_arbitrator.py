"""Debate Arbitrator Agent -- resolves strategic disagreements.

The Arbitrator receives critiques from all three debate advocates
(Mastery Maximizer, Exam Strategist, Burnout Minimizer) and produces
a *resolution* that balances their concerns via weighted scoring.

Resolution strategy:
1. Collect all objections and amendments from advocates.
2. Weight each perspective based on learner context:
   - Near deadline -> higher exam weight
   - Low motivation / burnout signals -> higher burnout weight
   - No deadline pressure -> higher mastery weight
3. Accept amendments above a threshold score.
4. Produce a merged amendment list and overall alignment score.
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

# Default perspective weights (sum to 1.0)
_DEFAULT_WEIGHTS = {
    "mastery": 0.4,
    "exam": 0.3,
    "burnout": 0.3,
}

# Minimum weighted severity for an objection to be accepted
_OBJECTION_ACCEPT_THRESHOLD = 0.3


class DebateArbitrator(BaseAgent):
    """Resolves debate by weighting advocate perspectives contextually."""

    def __init__(
        self,
        base_weights: dict[str, float] | None = None,
        objection_threshold: float = _OBJECTION_ACCEPT_THRESHOLD,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="debate-arbitrator",
                display_name="Debate Arbitrator",
                capabilities=[AgentCapability.DEBATE_ARBITRATE],
                cost_tier=2,
                description=(
                    "Resolves strategic debates between Mastery, Exam, "
                    "and Burnout advocates via contextual weighting."
                ),
            )
        )
        self.base_weights = dict(base_weights or _DEFAULT_WEIGHTS)
        self.objection_threshold = objection_threshold

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Arbitrate the debate from all advocate critiques."""
        payload = message.payload
        state = LearnerState.model_validate(payload.get("learner_state", {}))
        critiques = payload.get("critiques", [])

        if not critiques:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.5,
                payload={
                    "resolution": "no_debate",
                    "accepted_objections": [],
                    "accepted_amendments": [],
                    "perspective_weights": self.base_weights,
                    "overall_alignment": 1.0,
                },
                rationale="No critiques received -- plan passes without debate.",
            )

        # 1. Compute context-adaptive weights
        weights = self._compute_weights(state)

        # 2. Score and filter objections
        all_objections: list[dict[str, Any]] = []
        all_amendments: list[dict[str, Any]] = []

        for critique in critiques:
            perspective = critique.get("perspective", "unknown")
            w = weights.get(perspective, 0.2)

            for obj in critique.get("objections", []):
                weighted_severity = obj.get("severity", 0.5) * w
                enriched = {
                    **obj,
                    "source_perspective": perspective,
                    "weight": round(w, 3),
                    "weighted_severity": round(weighted_severity, 3),
                    "accepted": weighted_severity >= self.objection_threshold,
                }
                all_objections.append(enriched)

            for amend in critique.get("amendments", []):
                enriched = {
                    **amend,
                    "source_perspective": perspective,
                    "weight": round(w, 3),
                }
                all_amendments.append(enriched)

        accepted_objections = [o for o in all_objections if o["accepted"]]
        # Accept amendments only from perspectives whose objections were accepted
        accepted_perspectives = {o["source_perspective"] for o in accepted_objections}
        accepted_amendments = [
            a for a in all_amendments
            if a["source_perspective"] in accepted_perspectives
        ]

        # 3. Compute overall alignment
        if all_objections:
            avg_alignment = sum(
                c.get("alignment_score", 0.5) for c in critiques
            ) / len(critiques)
        else:
            avg_alignment = 1.0

        # 4. Resolution summary
        resolution = self._resolution_type(accepted_objections)

        confidence = min(0.9, 0.5 + 0.05 * len(critiques))

        result_payload: dict[str, Any] = {
            "resolution": resolution,
            "accepted_objections": accepted_objections,
            "rejected_objections": [o for o in all_objections if not o["accepted"]],
            "accepted_amendments": accepted_amendments,
            "perspective_weights": {k: round(v, 3) for k, v in weights.items()},
            "overall_alignment": round(avg_alignment, 3),
            "total_objections": len(all_objections),
            "accepted_objection_count": len(accepted_objections),
            "accepted_amendment_count": len(accepted_amendments),
        }

        logger.info(
            "arbitrator.resolution",
            resolution=resolution,
            total_objections=len(all_objections),
            accepted=len(accepted_objections),
            amendments=len(accepted_amendments),
        )

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=result_payload,
            rationale=(
                f"Debate resolved: {resolution}. "
                f"{len(accepted_objections)}/{len(all_objections)} objections accepted, "
                f"{len(accepted_amendments)} amendments applied."
            ),
        )

    def _compute_weights(self, state: LearnerState) -> dict[str, float]:
        """Adjust perspective weights based on learner context."""
        w = dict(self.base_weights)

        # Deadline pressure -> boost exam weight
        deadline = state.time_budget.deadline
        if deadline:
            from datetime import datetime, timezone
            hours_left = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours_left < 24:
                w["exam"] += 0.3
                w["mastery"] -= 0.15
                w["burnout"] -= 0.15
            elif hours_left < 72:
                w["exam"] += 0.15
                w["mastery"] -= 0.075
                w["burnout"] -= 0.075

        # Low motivation -> boost burnout weight
        if state.motivation.level in (MotivationLevel.LOW, MotivationLevel.CRITICAL):
            w["burnout"] += 0.2
            w["mastery"] -= 0.1
            w["exam"] -= 0.1

        # Behavioural anomalies -> boost burnout weight
        if any(a.anomaly_type == "cramming" for a in state.behavioral_anomalies):
            w["burnout"] += 0.1
            w["exam"] -= 0.05
            w["mastery"] -= 0.05

        # Normalise to sum to 1.0
        total = sum(w.values())
        if total > 0:
            w = {k: v / total for k, v in w.items()}

        return w

    @staticmethod
    def _resolution_type(accepted: list[dict[str, Any]]) -> str:
        """Classify the overall resolution outcome."""
        if not accepted:
            return "plan_approved"

        perspectives = {o["source_perspective"] for o in accepted}
        max_severity = max(o.get("weighted_severity", 0) for o in accepted)

        if max_severity > 0.4:
            return "major_revision"
        if len(perspectives) >= 2:
            return "minor_revision"
        return "minor_revision"
