"""Debate Advocate Agents -- three strategic perspectives on learning plans.

The strategic debate system puts every study plan through a three-way lens:

1. **Mastery Maximizer** -- optimises for deep, durable understanding.
   Prefers thorough coverage, prerequisite mastery, spaced repetition.

2. **Exam Strategist** -- optimises for exam/assessment performance.
   Prefers high-yield topics, practice tests, time-efficient review.

3. **Burnout Minimizer** -- optimises for sustainable engagement.
   Prefers shorter sessions, easier wins, rest periods, variety.

Each advocate receives the current plan proposal and learner state, then
produces a *critique* with scored objections and concrete amendments.
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


# ══════════════════════════════════════════════════════════════════
#  Base Advocate
# ══════════════════════════════════════════════════════════════════


class _BaseAdvocate(BaseAgent):
    """Shared logic for all debate advocates."""

    perspective: str = "base"

    def _parse_payload(self, message: MessageEnvelope) -> tuple[LearnerState, dict[str, Any]]:
        payload = message.payload
        state = LearnerState.model_validate(payload.get("learner_state", {}))
        plan = payload.get("plan", {})
        return state, plan

    def _build_response(
        self,
        objections: list[dict[str, Any]],
        amendments: list[dict[str, Any]],
        score: float,
        rationale: str,
    ) -> AgentResponse:
        confidence = min(0.9, 0.4 + 0.1 * (len(objections) + len(amendments)))
        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload={
                "perspective": self.perspective,
                "objections": objections,
                "amendments": amendments,
                "alignment_score": round(score, 3),
                "objection_count": len(objections),
                "amendment_count": len(amendments),
            },
            rationale=rationale,
        )


# ══════════════════════════════════════════════════════════════════
#  Mastery Maximizer
# ══════════════════════════════════════════════════════════════════


class MasteryMaximizer(_BaseAdvocate):
    """Advocates for deep, durable learning over superficial coverage."""

    perspective = "mastery"

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="mastery-maximizer",
                display_name="Mastery Maximizer",
                capabilities=[AgentCapability.DEBATE_PROPOSE, AgentCapability.DEBATE_CRITIQUE],
                cost_tier=2,
                description="Advocates for deep understanding and prerequisite mastery.",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state, plan = self._parse_payload(message)
        recommendations = plan.get("recommendations", [])

        objections: list[dict[str, Any]] = []
        amendments: list[dict[str, Any]] = []

        # 1. Check for prerequisite violations
        for rec in recommendations:
            cid = rec.get("concept_id", "")
            prereqs = state.prerequisites_for(cid)
            unmet = [
                p for p in prereqs
                if (c := state.get_concept(p)) is not None and c.mastery < 0.6
            ]
            if unmet:
                objections.append({
                    "type": "prerequisite_violation",
                    "severity": 0.8,
                    "concept_id": cid,
                    "detail": f"Prerequisites not met: {', '.join(unmet)}",
                })
                amendments.append({
                    "type": "add_prerequisite",
                    "concept_ids": unmet,
                    "reason": f"Master prerequisites before advancing to {cid}",
                })

        # 2. Check for insufficient time per concept (shallow learning)
        for rec in recommendations:
            minutes = rec.get("minutes", 0)
            action = rec.get("action", "")
            if action in ("learn_new", "practice") and minutes < 10:
                objections.append({
                    "type": "insufficient_depth",
                    "severity": 0.6,
                    "concept_id": rec.get("concept_id", ""),
                    "detail": f"Only {minutes}min for {action} -- too shallow",
                })
                amendments.append({
                    "type": "increase_time",
                    "concept_id": rec.get("concept_id", ""),
                    "suggested_minutes": 15,
                    "reason": "Deep learning requires more focused time",
                })

        # 3. Check for skipping high-forgetting concepts
        high_forget = state.high_forgetting_concepts(threshold=0.5)
        planned_ids = {r.get("concept_id") for r in recommendations}
        for concept in high_forget[:3]:
            if concept.concept_id not in planned_ids:
                objections.append({
                    "type": "forgetting_ignored",
                    "severity": 0.7,
                    "concept_id": concept.concept_id,
                    "detail": f"Forgetting score {concept.forgetting_score:.0%} but not in plan",
                })
                amendments.append({
                    "type": "add_review",
                    "concept_id": concept.concept_id,
                    "reason": "Spaced review needed to prevent knowledge loss",
                })

        # 4. Too many concepts = surface-level coverage
        if len(recommendations) > 4:
            objections.append({
                "type": "too_many_topics",
                "severity": 0.5,
                "detail": f"{len(recommendations)} topics -- consider deeper focus on fewer",
            })

        # Alignment score: lower if many objections
        alignment = max(0.0, 1.0 - 0.15 * len(objections))

        logger.info(
            "mastery_maximizer.critique",
            objections=len(objections),
            amendments=len(amendments),
        )

        return self._build_response(
            objections, amendments, alignment,
            f"Mastery perspective: {len(objections)} objections, {len(amendments)} amendments",
        )


# ══════════════════════════════════════════════════════════════════
#  Exam Strategist
# ══════════════════════════════════════════════════════════════════


class ExamStrategist(_BaseAdvocate):
    """Advocates for exam-optimal study strategy."""

    perspective = "exam"

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="exam-strategist",
                display_name="Exam Strategist",
                capabilities=[AgentCapability.DEBATE_PROPOSE, AgentCapability.DEBATE_CRITIQUE],
                cost_tier=2,
                description="Advocates for exam performance and assessment readiness.",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state, plan = self._parse_payload(message)
        recommendations = plan.get("recommendations", [])

        objections: list[dict[str, Any]] = []
        amendments: list[dict[str, Any]] = []

        priority_ids = set(state.time_budget.priority_concept_ids)
        planned_ids = {r.get("concept_id") for r in recommendations}

        # 1. Priority concepts not in plan
        missing_priority = priority_ids - planned_ids
        for pid in missing_priority:
            concept = state.get_concept(pid)
            if concept and concept.mastery < 0.85:
                objections.append({
                    "type": "priority_missing",
                    "severity": 0.9,
                    "concept_id": pid,
                    "detail": f"Priority concept {pid} (mastery {concept.mastery:.0%}) not planned",
                })
                amendments.append({
                    "type": "add_priority",
                    "concept_id": pid,
                    "reason": "High-yield concept for upcoming assessment",
                })

        # 2. Deadline pressure: if deadline is close, focus on high-yield
        deadline = state.time_budget.deadline
        if deadline:
            from datetime import datetime, timezone
            hours_left = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours_left < 48:
                # Under deadline pressure -- object to low-priority concepts
                for rec in recommendations:
                    cid = rec.get("concept_id", "")
                    if cid not in priority_ids:
                        concept = state.get_concept(cid)
                        if concept and concept.mastery >= 0.6:
                            objections.append({
                                "type": "deadline_waste",
                                "severity": 0.7,
                                "concept_id": cid,
                                "detail": f"Deadline in {hours_left:.0f}h -- skip non-priority {cid}",
                            })

        # 3. Too much time on maintain actions (already mastered)
        maintain_minutes = sum(
            r.get("minutes", 0) for r in recommendations
            if r.get("action") == "maintain"
        )
        total_minutes = sum(r.get("minutes", 0) for r in recommendations)
        if total_minutes > 0 and maintain_minutes / total_minutes > 0.3:
            objections.append({
                "type": "over_maintenance",
                "severity": 0.5,
                "detail": f"{maintain_minutes}min on already-mastered -- shift to weak areas",
            })
            amendments.append({
                "type": "reduce_maintenance",
                "reason": "Reallocate maintenance time to unmastered priority concepts",
            })

        # 4. Recommend practice tests for mid-mastery concepts
        mid_mastery = [
            c for c in state.concepts.values()
            if 0.5 <= c.mastery < 0.85 and c.concept_id in priority_ids
        ]
        for concept in mid_mastery[:2]:
            if concept.concept_id in planned_ids:
                amendments.append({
                    "type": "add_practice_test",
                    "concept_id": concept.concept_id,
                    "reason": f"Practice test for {concept.concept_id} (mastery {concept.mastery:.0%}) builds exam readiness",
                })

        alignment = max(0.0, 1.0 - 0.15 * len(objections))

        logger.info(
            "exam_strategist.critique",
            objections=len(objections),
            amendments=len(amendments),
        )

        return self._build_response(
            objections, amendments, alignment,
            f"Exam perspective: {len(objections)} objections, {len(amendments)} amendments",
        )


# ══════════════════════════════════════════════════════════════════
#  Burnout Minimizer
# ══════════════════════════════════════════════════════════════════


class BurnoutMinimizer(_BaseAdvocate):
    """Advocates for sustainable learning and overload prevention."""

    perspective = "burnout"

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="burnout-minimizer",
                display_name="Burnout Minimizer",
                capabilities=[AgentCapability.DEBATE_PROPOSE, AgentCapability.DEBATE_CRITIQUE],
                cost_tier=2,
                description="Advocates for sustainable engagement and overload prevention.",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state, plan = self._parse_payload(message)
        recommendations = plan.get("recommendations", [])
        session_minutes = plan.get("session_minutes", 45)

        objections: list[dict[str, Any]] = []
        amendments: list[dict[str, Any]] = []

        # 1. Session too long for current motivation
        motivation = state.motivation
        max_minutes = {
            MotivationLevel.HIGH: 60,
            MotivationLevel.MEDIUM: 45,
            MotivationLevel.LOW: 30,
            MotivationLevel.CRITICAL: 20,
        }
        limit = max_minutes.get(motivation.level, 45)
        if session_minutes > limit:
            objections.append({
                "type": "session_too_long",
                "severity": 0.7,
                "detail": (
                    f"{session_minutes}min session with {motivation.level.value} "
                    f"motivation -- cap at {limit}min"
                ),
            })
            amendments.append({
                "type": "shorten_session",
                "suggested_minutes": limit,
                "reason": f"Motivation is {motivation.level.value} -- shorter sessions prevent burnout",
            })

        # 2. Too many difficult concepts in one session
        hard_count = 0
        for rec in recommendations:
            concept = state.get_concept(rec.get("concept_id", ""))
            if concept and concept.difficulty > 0.7:
                hard_count += 1
        if hard_count >= 3:
            objections.append({
                "type": "cognitive_overload",
                "severity": 0.8,
                "detail": f"{hard_count} hard concepts in one session -- risk of overwhelm",
            })
            amendments.append({
                "type": "mix_difficulty",
                "reason": "Interleave hard concepts with easier ones for variety",
            })

        # 3. All learn_new actions -- no reinforcement
        new_count = sum(1 for r in recommendations if r.get("action") == "learn_new")
        if new_count == len(recommendations) and len(recommendations) > 1:
            objections.append({
                "type": "all_new_content",
                "severity": 0.6,
                "detail": "Entire session is new content -- include some review for confidence",
            })
            amendments.append({
                "type": "add_review_break",
                "reason": "Mix new learning with familiar review to sustain momentum",
            })

        # 4. Behavioural anomalies suggest existing overload
        anomalies = state.behavioral_anomalies
        cramming = any(a.anomaly_type == "cramming" for a in anomalies)
        late_night = any(a.anomaly_type == "late_night_study" for a in anomalies)
        if cramming or late_night:
            severity = 0.8 if cramming else 0.6
            objections.append({
                "type": "existing_overload_signals",
                "severity": severity,
                "detail": "Behavioral signals suggest learner is already stressed",
            })
            amendments.append({
                "type": "reduce_intensity",
                "reason": "Existing stress signals -- lighten the load this session",
            })

        # 5. Declining motivation trend
        if motivation.trend < -0.2:
            objections.append({
                "type": "declining_motivation",
                "severity": 0.6,
                "detail": f"Motivation trend={motivation.trend:.2f} -- include easy wins",
            })
            amendments.append({
                "type": "add_easy_wins",
                "reason": "Include nearly-mastered concepts to boost confidence",
            })

        alignment = max(0.0, 1.0 - 0.15 * len(objections))

        logger.info(
            "burnout_minimizer.critique",
            objections=len(objections),
            amendments=len(amendments),
        )

        return self._build_response(
            objections, amendments, alignment,
            f"Burnout perspective: {len(objections)} objections, {len(amendments)} amendments",
        )
