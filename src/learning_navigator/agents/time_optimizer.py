"""Time Optimizer Agent — constrained time allocation across concepts.

Given the learner's time budget (hours remaining, session length, deadline)
and current concept states, this agent produces an optimal allocation of
study time.

Strategy:
1. Score each concept by urgency x importance.
2. Allocate time proportionally within the session budget.
3. Respect the deadline by front-loading high-urgency topics.
4. Honour priority concepts from the time budget.

Result: a list of (concept_id, minutes, action_type) allocations that
sum to ≤ the session budget.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
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

# ── constants ───────────────────────────────────────────────────────

_MIN_BLOCK_MINUTES = 5
_MINIMUM_SESSION_MINUTES = 10


class TimeOptimizerAgent(BaseAgent):
    """Produces an optimal time allocation plan within the learner's budget."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="time-optimizer",
                display_name="Time Optimizer Agent",
                capabilities=[AgentCapability.TIME_OPTIMIZATION],
                cost_tier=2,
                description="Constrained time allocation across concepts using urgency/importance weighting.",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state_raw = message.payload.get("learner_state", {})
        state = LearnerState.model_validate(state_raw)

        log = logger.bind(agent=self.agent_id, learner_id=state.learner_id)
        log.info("time_optimizer.start")

        # Determine session budget
        session_minutes = state.time_budget.preferred_session_minutes
        session_minutes = self._adjust_for_motivation(session_minutes, state)
        session_minutes = max(_MINIMUM_SESSION_MINUTES, session_minutes)

        # Score and allocate
        scored_concepts = self._score_concepts(state)
        allocations = self._allocate_time(scored_concepts, session_minutes)

        # Compute deadline urgency if applicable
        deadline_info = self._deadline_analysis(state)

        total_allocated = sum(a["minutes"] for a in allocations)
        confidence = min(1.0, 0.5 + 0.05 * len(state.concepts))

        payload: dict[str, Any] = {
            "allocations": allocations,
            "session_minutes": session_minutes,
            "total_allocated_minutes": total_allocated,
            "unallocated_minutes": session_minutes - total_allocated,
            "deadline_analysis": deadline_info,
            "concept_scores": {s["concept_id"]: s["score"] for s in scored_concepts},
            "motivation_adjustment": self._motivation_label(state),
            "confidence": round(confidence, 3),
        }

        rationale = self._build_rationale(allocations, session_minutes, deadline_info)
        log.info("time_optimizer.complete", allocations=len(allocations))

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=payload,
            rationale=rationale,
        )

    # ── scoring ─────────────────────────────────────────────────────

    def _score_concepts(
        self, state: LearnerState
    ) -> list[dict[str, Any]]:
        """Score each concept by urgency x importance.

        Urgency drivers:
        - Low mastery (below 0.5)
        - High forgetting score
        - Deadline proximity (priority concepts get boost)

        Importance drivers:
        - Number of dependents (downstream concepts that need this)
        - Explicit priority flag from time budget
        """
        priority_ids = set(state.time_budget.priority_concept_ids)
        scored: list[dict[str, Any]] = []

        for cid, concept in state.concepts.items():
            # Skip fully mastered
            if concept.mastery >= 0.95:
                continue

            # Urgency
            mastery_gap = 1.0 - concept.mastery
            forgetting = concept.forgetting_score
            urgency = mastery_gap * 2.0 + forgetting * 1.5

            # Importance
            dependent_count = len(state.dependents_of(cid))
            priority_boost = 2.0 if cid in priority_ids else 0.0
            importance = 1.0 + dependent_count * 0.5 + priority_boost

            score = urgency * importance
            action = self._choose_action(concept.mastery, forgetting)

            scored.append({
                "concept_id": cid,
                "score": round(score, 3),
                "urgency": round(urgency, 3),
                "importance": round(importance, 3),
                "mastery": round(concept.mastery, 3),
                "forgetting": round(forgetting, 3),
                "action": action,
                "is_priority": cid in priority_ids,
            })

        return sorted(scored, key=lambda s: s["score"], reverse=True)

    @staticmethod
    def _choose_action(mastery: float, forgetting: float) -> str:
        if forgetting > 0.5:
            return "spaced_review"
        if mastery < 0.3:
            return "learn_new"
        if mastery < 0.6:
            return "practice"
        if mastery < 0.85:
            return "deepen"
        return "maintain"

    # ── allocation ──────────────────────────────────────────────────

    @staticmethod
    def _allocate_time(
        scored: list[dict[str, Any]], budget_minutes: int
    ) -> list[dict[str, Any]]:
        """Proportionally allocate time based on scores.

        Ensures:
        - Each concept gets at least _MIN_BLOCK_MINUTES.
        - Total ≤ budget_minutes.
        - Maximum ~6 concepts per session to avoid fragmentation.
        """
        if not scored:
            return []

        # Take top concepts (max 6 per session)
        top = scored[:6]
        total_score = sum(s["score"] for s in top)
        if total_score <= 0:
            return []

        allocations: list[dict[str, Any]] = []
        remaining = budget_minutes

        for item in top:
            if remaining < _MIN_BLOCK_MINUTES:
                break

            proportion = item["score"] / total_score
            minutes = max(_MIN_BLOCK_MINUTES, round(proportion * budget_minutes))
            minutes = min(minutes, remaining)

            allocations.append({
                "concept_id": item["concept_id"],
                "minutes": minutes,
                "action": item["action"],
                "score": item["score"],
                "is_priority": item.get("is_priority", False),
            })
            remaining -= minutes

        return allocations

    # ── motivation adjustment ───────────────────────────────────────

    @staticmethod
    def _adjust_for_motivation(base_minutes: int, state: LearnerState) -> int:
        """Shorten sessions for low-motivation learners."""
        level = state.motivation.level
        if level == MotivationLevel.CRITICAL:
            return max(_MINIMUM_SESSION_MINUTES, int(base_minutes * 0.5))
        if level == MotivationLevel.LOW:
            return max(_MINIMUM_SESSION_MINUTES, int(base_minutes * 0.7))
        return base_minutes

    @staticmethod
    def _motivation_label(state: LearnerState) -> str:
        level = state.motivation.level
        if level == MotivationLevel.CRITICAL:
            return "session_shortened_50pct"
        if level == MotivationLevel.LOW:
            return "session_shortened_30pct"
        return "no_adjustment"

    # ── deadline ────────────────────────────────────────────────────

    @staticmethod
    def _deadline_analysis(state: LearnerState) -> dict[str, Any] | None:
        """Compute deadline-related urgency if a deadline is set."""
        deadline = state.time_budget.deadline
        if deadline is None:
            return None

        now = datetime.now(timezone.utc)
        hours_remaining = (deadline - now).total_seconds() / 3600.0
        hours_budget = state.time_budget.hours_remaining_this_week

        # Urgency increases exponentially as deadline approaches
        urgency = 1.0 if hours_remaining <= 0 else min(1.0, math.exp(-hours_remaining / 48.0))

        # Check if budget is sufficient
        concepts_below_target = len(state.weak_concepts(threshold=0.6))
        estimated_hours_needed = concepts_below_target * 0.5  # rough estimate

        return {
            "hours_to_deadline": round(hours_remaining, 1),
            "hours_budget_remaining": round(hours_budget, 1),
            "deadline_urgency": round(urgency, 3),
            "estimated_hours_needed": round(estimated_hours_needed, 1),
            "budget_sufficient": hours_budget >= estimated_hours_needed,
        }

    # ── rationale ───────────────────────────────────────────────────

    @staticmethod
    def _build_rationale(
        allocations: list[dict[str, Any]],
        session_minutes: int,
        deadline_info: dict[str, Any] | None,
    ) -> str:
        if not allocations:
            return "No concepts need study time — all mastered or no concepts tracked."

        parts = [
            f"Allocated {sum(a['minutes'] for a in allocations)}min across "
            f"{len(allocations)} concepts in a {session_minutes}min session.",
        ]
        top = allocations[0]
        parts.append(f"Top priority: {top['concept_id']} ({top['action']}, {top['minutes']}min).")

        if deadline_info:
            hrs = deadline_info["hours_to_deadline"]
            if hrs > 0:
                parts.append(f"Deadline in {hrs:.0f}h — urgency {deadline_info['deadline_urgency']:.0%}.")
            else:
                parts.append("Deadline has passed!")

        return " ".join(parts)
