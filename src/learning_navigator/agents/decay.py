"""Decay Agent -- forgetting-curve analysis and spaced-repetition scheduling.

Uses an Ebbinghaus-inspired exponential decay model augmented with
spaced-repetition stability factors to:

* Compute a per-concept **forgetting score** (0 = fully retained, 1 = forgotten).
* Estimate **memory stability** from spacing history, difficulty, and mastery.
* Produce an **optimal review schedule** with recommended next-review times.
* Flag **at-risk** concepts approaching the recall threshold.

The decay model:
    retention(t) = exp(-t / S)

where *t* is hours since last practice and *S* is a stability factor computed
from the learner's spacing history, difficulty, and mastery level.  Good
spacing (expanding intervals) increases stability; high difficulty decreases it.

Stability factors are inspired by SM-2 / FSRS but simplified for a
deterministic, rule-based v1 implementation.
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
    ConceptState,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

# Base stability in hours for a concept with no spacing history.
_BASE_STABILITY_HOURS = 24.0

# Above this forgetting score a concept is considered "at risk".
_AT_RISK_THRESHOLD = 0.5

# Target retention the review schedule aims to maintain.
_TARGET_RETENTION = 0.85


class DecayAgent(BaseAgent):
    """Analyses forgetting curves and produces review schedules."""

    def __init__(
        self,
        base_stability_hours: float = _BASE_STABILITY_HOURS,
        at_risk_threshold: float = _AT_RISK_THRESHOLD,
        target_retention: float = _TARGET_RETENTION,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="decay",
                display_name="Decay Agent",
                capabilities=[AgentCapability.DECAY_ANALYSIS],
                cost_tier=1,
                description=(
                    "Computes forgetting scores via Ebbinghaus decay "
                    "and recommends spaced-repetition review schedules."
                ),
            )
        )
        self.base_stability_hours = base_stability_hours
        self.at_risk_threshold = at_risk_threshold
        self.target_retention = target_retention

    # ── BaseAgent contract ─────────────────────────────────────────────

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Compute decay analysis for all concepts in learner state."""
        payload = message.payload
        state_raw = payload.get("learner_state", {})
        state = LearnerState.model_validate(state_raw)

        now = datetime.now(timezone.utc)

        concept_reports: dict[str, dict[str, Any]] = {}
        at_risk: list[dict[str, Any]] = []
        review_schedule: list[dict[str, Any]] = []

        for cid, concept in state.concepts.items():
            report = self._analyse_concept(concept, now)
            concept_reports[cid] = report

            if report["forgetting_score"] >= self.at_risk_threshold:
                at_risk.append({
                    "concept_id": cid,
                    "forgetting_score": report["forgetting_score"],
                    "stability_hours": report["stability_hours"],
                    "hours_since_practice": report["hours_since_practice"],
                })

            # Always include a review recommendation
            review_schedule.append({
                "concept_id": cid,
                "next_review_hours": report["next_review_hours"],
                "urgency": report["forgetting_score"],
                "action": self._review_action(concept.mastery, report["forgetting_score"]),
            })

        # Sort review schedule by urgency (most urgent first)
        review_schedule.sort(key=lambda r: r["urgency"], reverse=True)
        at_risk.sort(key=lambda r: r["forgetting_score"], reverse=True)

        total = len(state.concepts)
        at_risk_count = len(at_risk)
        avg_forgetting = (
            sum(r["forgetting_score"] for r in concept_reports.values()) / total
            if total > 0
            else 0.0
        )

        confidence = min(0.95, 0.5 + 0.05 * total) if total > 0 else 0.3

        result_payload: dict[str, Any] = {
            "concept_reports": concept_reports,
            "at_risk": at_risk,
            "at_risk_count": at_risk_count,
            "review_schedule": review_schedule,
            "summary": {
                "total_concepts": total,
                "at_risk_count": at_risk_count,
                "average_forgetting": round(avg_forgetting, 3),
            },
            "confidence": round(confidence, 3),
        }

        logger.info(
            "decay.analysis_complete",
            total=total,
            at_risk=at_risk_count,
            avg_forgetting=round(avg_forgetting, 3),
        )

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=result_payload,
            rationale=(
                f"Analysed {total} concepts: {at_risk_count} at risk of forgetting "
                f"(avg forgetting={avg_forgetting:.2f})."
            ),
        )

    # ── Core decay logic ───────────────────────────────────────────────

    def _analyse_concept(
        self, concept: ConceptState, now: datetime
    ) -> dict[str, Any]:
        """Compute forgetting analysis for a single concept."""
        hours_since = self._hours_since_practice(concept, now)
        stability = self._compute_stability(concept)
        forgetting_score = self._forgetting_score(hours_since, stability)
        next_review = self._next_review_hours(stability)

        return {
            "forgetting_score": round(forgetting_score, 4),
            "retention": round(1.0 - forgetting_score, 4),
            "stability_hours": round(stability, 2),
            "hours_since_practice": round(hours_since, 2),
            "next_review_hours": round(next_review, 2),
            "mastery": round(concept.mastery, 4),
            "difficulty": round(concept.difficulty, 4),
            "practice_count": concept.practice_count,
        }

    @staticmethod
    def _hours_since_practice(concept: ConceptState, now: datetime) -> float:
        """Hours elapsed since the concept was last practiced."""
        if concept.last_practiced is None:
            # Never practiced -- treat as very long ago
            return 720.0  # 30 days
        delta = (now - concept.last_practiced).total_seconds() / 3600.0
        return max(0.0, delta)

    def _compute_stability(self, concept: ConceptState) -> float:
        """Estimate memory stability in hours.

        Factors:
        1. Base stability scaled by practice count (repetitions increase
           stability: approx doubling every 5 reps, diminishing returns).
        2. Spacing quality bonus: expanding intervals boost stability.
        3. Difficulty penalty: harder concepts decay faster.
        4. Mastery bonus: higher mastery correlates with better encoding.
        """
        base = self.base_stability_hours

        # Repetition factor: log growth, capped at ~8x base
        rep_factor = 1.0 + math.log1p(concept.practice_count) * 0.8
        rep_factor = min(rep_factor, 8.0)

        # Spacing quality: ratio of expanding intervals in spacing history
        spacing_factor = self._spacing_quality(concept.spacing_history)

        # Difficulty penalty: d=0 -> 1.5x, d=0.5 -> 1.0x, d=1 -> 0.5x
        difficulty_factor = 1.5 - concept.difficulty

        # Mastery bonus: m=0 -> 0.5x, m=0.5 -> 0.75x, m=1 -> 1.0x
        mastery_factor = 0.5 + 0.5 * concept.mastery

        stability = base * rep_factor * spacing_factor * difficulty_factor * mastery_factor
        return max(1.0, stability)  # floor at 1 hour

    @staticmethod
    def _spacing_quality(intervals: list[float]) -> float:
        """Score the quality of spacing intervals.

        Perfect expanding schedule (each interval >= previous) gets 1.5x.
        Flat / contracting schedule gets 0.8x.
        No history gets 1.0x (neutral).

        Returns a multiplier in [0.8, 1.5].
        """
        if len(intervals) < 2:
            return 1.0

        expanding_count = sum(
            1 for i in range(1, len(intervals)) if intervals[i] >= intervals[i - 1]
        )
        ratio = expanding_count / (len(intervals) - 1)

        # Map ratio 0..1 -> 0.8..1.5
        return 0.8 + ratio * 0.7

    @staticmethod
    def _forgetting_score(hours_since: float, stability: float) -> float:
        """Ebbinghaus exponential decay: forgetting = 1 - exp(-t/S)."""
        retention = math.exp(-hours_since / stability)
        return min(1.0, max(0.0, 1.0 - retention))

    def _next_review_hours(self, stability: float) -> float:
        """Hours until retention drops to target_retention.

        Solve: target = exp(-t/S)  =>  t = -S * ln(target)
        """
        if self.target_retention <= 0.0 or self.target_retention >= 1.0:
            return stability  # fallback
        return -stability * math.log(self.target_retention)

    @staticmethod
    def _review_action(mastery: float, forgetting_score: float) -> str:
        """Choose appropriate review action based on mastery and decay."""
        if forgetting_score > 0.7:
            return "urgent_review"
        if forgetting_score > 0.5:
            return "spaced_review"
        if mastery < 0.3:
            return "learn_new"
        if mastery < 0.6:
            return "practice"
        if mastery < 0.85:
            return "deepen"
        return "maintain"
