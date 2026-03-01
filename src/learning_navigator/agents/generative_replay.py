"""Generative Replay Agent -- synthetic practice generation for retention.

Generates structured replay exercises for concepts at risk of being forgotten.
Unlike the Planner (which decides *what* to study next), the Generative Replay
Agent creates *how* to study -- producing calibrated exercise specifications
that reinforce fading memories.

Key strategies:
* **Retrieval practice**: Recall exercises for concepts with decent mastery
  but rising forgetting scores (fragile knowledge).
* **Interleaving**: Mixes related concepts in a single replay set to
  strengthen discriminative learning.
* **Spacing calibration**: Times replay exercises to the optimal review
  window from the Decay Agent's schedule.
* **Difficulty calibration**: Adjusts exercise difficulty to the learner's
  current mastery, keeping the challenge in the zone of proximal development.

This agent is rule-based for v1.  A future version may use an LLM to generate
actual exercise content (problem text, hints, etc.).  For now it outputs
*exercise specifications* that a downstream content service can hydrate.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from learning_navigator.agents.base import (
    AgentCapability,
    AgentMetadata,
    AgentResponse,
    BaseAgent,
)
from learning_navigator.contracts.learner_state import (
    ConceptRelationType,
    LearnerState,
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)

# ── Defaults ───────────────────────────────────────────────────────────────

_FORGETTING_THRESHOLD = 0.35  # include concept in replay if forgetting >= this
_MAX_REPLAY_CONCEPTS = 8  # cap concepts per replay set
_MIN_MASTERY_FOR_REPLAY = 0.15  # too-low mastery -> learn_new, not replay
_MAX_EXERCISES_PER_CONCEPT = 4
_INTERLEAVE_RATIO = 0.3  # fraction of exercises that are interleaved


class GenerativeReplayAgent(BaseAgent):
    """Generates structured replay exercise plans for retention."""

    def __init__(
        self,
        forgetting_threshold: float = _FORGETTING_THRESHOLD,
        max_replay_concepts: int = _MAX_REPLAY_CONCEPTS,
        min_mastery_for_replay: float = _MIN_MASTERY_FOR_REPLAY,
        max_exercises_per_concept: int = _MAX_EXERCISES_PER_CONCEPT,
        interleave_ratio: float = _INTERLEAVE_RATIO,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="generative-replay",
                display_name="Generative Replay Agent",
                capabilities=[AgentCapability.GENERATIVE_REPLAY],
                cost_tier=2,
                description=(
                    "Creates calibrated replay exercises for concepts "
                    "at risk of being forgotten, using interleaving "
                    "and difficulty-calibrated retrieval practice."
                ),
            )
        )
        self.forgetting_threshold = forgetting_threshold
        self.max_replay_concepts = max_replay_concepts
        self.min_mastery_for_replay = min_mastery_for_replay
        self.max_exercises_per_concept = max_exercises_per_concept
        self.interleave_ratio = interleave_ratio

    # ── BaseAgent contract ─────────────────────────────────────────────

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Generate a replay plan from learner state + decay analysis."""
        payload = message.payload
        state_raw = payload.get("learner_state", {})
        decay_report = payload.get("decay_report", {})
        state = LearnerState.model_validate(state_raw)

        # Select concepts eligible for replay
        candidates = self._select_candidates(state, decay_report)

        if not candidates:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.8,
                payload={
                    "replay_plan": [],
                    "interleaved_sets": [],
                    "total_exercises": 0,
                    "concepts_targeted": 0,
                    "summary": "No concepts require replay at this time.",
                },
                rationale="All concepts are above the retention threshold.",
            )

        # Generate per-concept exercises
        exercises = self._generate_exercises(candidates, state)

        # Build interleaved sets from related concepts
        interleaved = self._build_interleaved_sets(candidates, state)

        total_exercises = sum(len(ex["exercises"]) for ex in exercises)
        concepts_targeted = len(exercises)

        confidence = min(0.9, 0.5 + 0.05 * concepts_targeted)

        result_payload: dict[str, Any] = {
            "replay_plan": exercises,
            "interleaved_sets": interleaved,
            "total_exercises": total_exercises,
            "concepts_targeted": concepts_targeted,
            "summary": (
                f"Generated {total_exercises} exercises across "
                f"{concepts_targeted} concepts "
                f"({len(interleaved)} interleaved sets)."
            ),
        }

        logger.info(
            "replay.plan_generated",
            concepts=concepts_targeted,
            exercises=total_exercises,
            interleaved_sets=len(interleaved),
        )

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=result_payload,
            rationale=(
                f"Replay plan targets {concepts_targeted} concepts with "
                f"{total_exercises} exercises to reinforce fading memories."
            ),
        )

    # ── Candidate selection ────────────────────────────────────────────

    def _select_candidates(
        self,
        state: LearnerState,
        decay_report: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Select concepts eligible for replay.

        A concept is a replay candidate when:
        1. It has been learned (mastery >= min_mastery_for_replay).
        2. It is at risk of forgetting (score >= forgetting_threshold).
        3. It is not fully mastered-and-stable (avoids wasted effort).

        Uses decay_report if available, otherwise falls back to
        concept.forgetting_score from learner state.
        """
        concept_reports = decay_report.get("concept_reports", {})
        candidates: list[dict[str, Any]] = []

        for cid, concept in state.concepts.items():
            # Prefer fresh decay data; fall back to stored forgetting_score
            if cid in concept_reports:
                forgetting = concept_reports[cid].get(
                    "forgetting_score", concept.forgetting_score
                )
            else:
                forgetting = concept.forgetting_score

            mastery = concept.mastery

            # Skip if mastery is too low (hasn't learned yet)
            if mastery < self.min_mastery_for_replay:
                continue

            # Skip if not at risk
            if forgetting < self.forgetting_threshold:
                continue

            # Priority: higher forgetting + higher mastery = more fragile knowledge
            # Fragile knowledge benefits most from replay
            fragility = forgetting * mastery
            candidates.append({
                "concept_id": cid,
                "mastery": mastery,
                "forgetting": forgetting,
                "fragility": round(fragility, 4),
                "difficulty": concept.difficulty,
                "practice_count": concept.practice_count,
            })

        # Sort by fragility descending, cap at max
        candidates.sort(key=lambda c: c["fragility"], reverse=True)
        return candidates[: self.max_replay_concepts]

    # ── Exercise generation ────────────────────────────────────────────

    def _generate_exercises(
        self,
        candidates: list[dict[str, Any]],
        state: LearnerState,
    ) -> list[dict[str, Any]]:
        """Generate exercise specifications for each candidate concept."""
        result: list[dict[str, Any]] = []

        for cand in candidates:
            cid = cand["concept_id"]
            mastery = cand["mastery"]
            forgetting = cand["forgetting"]
            difficulty = cand["difficulty"]

            # Number of exercises scales with forgetting severity
            n_exercises = self._exercise_count(forgetting)

            exercises: list[dict[str, Any]] = []
            for i in range(n_exercises):
                ex_type = self._exercise_type(mastery, i)
                ex_difficulty = self._calibrate_difficulty(mastery, difficulty, i)
                exercises.append({
                    "exercise_index": i,
                    "type": ex_type,
                    "target_concept": cid,
                    "difficulty": round(ex_difficulty, 3),
                    "estimated_minutes": self._estimated_minutes(ex_type),
                    "hints_available": mastery < 0.5,
                })

            result.append({
                "concept_id": cid,
                "mastery": round(mastery, 4),
                "forgetting": round(forgetting, 4),
                "fragility": cand["fragility"],
                "exercises": exercises,
            })

        return result

    def _exercise_count(self, forgetting: float) -> int:
        """Compute number of exercises based on forgetting severity."""
        # Higher forgetting -> more exercises (2-max_exercises)
        raw = 2 + int(forgetting * (self.max_exercises_per_concept - 1))
        return min(raw, self.max_exercises_per_concept)

    @staticmethod
    def _exercise_type(mastery: float, index: int) -> str:
        """Choose exercise type based on mastery and sequence position.

        Types (progressive difficulty within a set):
        - recognition: Multiple-choice / matching (low effort)
        - recall: Free recall / fill-in-the-blank
        - application: Apply concept to a new scenario
        - synthesis: Combine with related concepts
        """
        if mastery < 0.4:
            # Lower mastery -> more recognition and recall
            types = ["recognition", "recall", "recall", "application"]
        elif mastery < 0.7:
            types = ["recall", "recall", "application", "synthesis"]
        else:
            types = ["recall", "application", "synthesis", "synthesis"]

        return types[min(index, len(types) - 1)]

    @staticmethod
    def _calibrate_difficulty(
        mastery: float, base_difficulty: float, exercise_index: int
    ) -> float:
        """Calibrate exercise difficulty to the zone of proximal development.

        Target: slightly above current mastery to challenge without frustrating.
        Each successive exercise in a set is slightly harder.
        """
        # Base target: between mastery and mastery+0.15
        target = mastery + 0.05 + exercise_index * 0.03
        # Blend with curriculum difficulty
        blended = 0.6 * target + 0.4 * base_difficulty
        return max(0.05, min(0.95, blended))

    @staticmethod
    def _estimated_minutes(exercise_type: str) -> int:
        """Estimated completion time per exercise type."""
        estimates = {
            "recognition": 2,
            "recall": 3,
            "application": 5,
            "synthesis": 7,
        }
        return estimates.get(exercise_type, 3)

    # ── Interleaving ───────────────────────────────────────────────────

    def _build_interleaved_sets(
        self,
        candidates: list[dict[str, Any]],
        state: LearnerState,
    ) -> list[dict[str, Any]]:
        """Group related concepts into interleaved practice sets.

        Interleaving related concepts (e.g., algebra + calculus) forces
        discriminative learning, which improves long-term retention more
        than blocked practice.
        """
        if len(candidates) < 2:
            return []

        cid_set = {c["concept_id"] for c in candidates}
        interleaved: list[dict[str, Any]] = []
        used: set[str] = set()

        for cand in candidates:
            cid = cand["concept_id"]
            if cid in used:
                continue

            # Find related candidates via knowledge graph edges
            related = self._find_related(cid, cid_set, state)
            group = [cid] + [r for r in related if r not in used]

            if len(group) >= 2:
                # Compute interleaved exercise count
                n_interleaved = max(
                    1,
                    math.ceil(
                        self.interleave_ratio
                        * sum(
                            self._exercise_count(
                                next(
                                    (
                                        c["forgetting"]
                                        for c in candidates
                                        if c["concept_id"] == g
                                    ),
                                    0.5,
                                )
                            )
                            for g in group
                        )
                    ),
                )
                interleaved.append({
                    "concepts": group,
                    "interleaved_exercises": n_interleaved,
                    "strategy": "alternating",
                })
                used.update(group)

        return interleaved

    @staticmethod
    def _find_related(
        concept_id: str,
        candidate_ids: set[str],
        state: LearnerState,
    ) -> list[str]:
        """Find candidate concepts related to concept_id via the knowledge graph."""
        related: list[str] = []
        for rel in state.concept_relations:
            if rel.source_concept_id == concept_id and rel.target_concept_id in candidate_ids:
                related.append(rel.target_concept_id)
            elif (
                rel.target_concept_id == concept_id
                and rel.source_concept_id in candidate_ids
                and rel.relation_type in (
                    ConceptRelationType.PREREQUISITE,
                    ConceptRelationType.COREQUISITE,
                    ConceptRelationType.RELATED,
                )
            ):
                related.append(rel.source_concept_id)
        return related
