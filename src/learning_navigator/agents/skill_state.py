"""Skill State Agent — advanced knowledge graph analysis and readiness scoring.

The Skill State Agent builds on the Diagnoser's per-concept BKT updates by
analysing the *relationships* between concepts.  It answers questions like:

• "Is the learner ready for calculus?"  (prerequisite mastery check)
• "Which knowledge clusters are strong / weak?"
• "What's the optimal next concept to study?"

Responsibilities:
• Compute concept-readiness scores (prerequisite mastery gate).
• Identify knowledge graph clusters (connected components of mastery).
• Find prerequisite gaps — concepts blocked by under-mastered prerequisites.
• Suggest an ordering of concepts from most to least ready-to-learn.
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
)
from learning_navigator.contracts.messages import MessageEnvelope

logger = structlog.get_logger(__name__)

# Minimum prerequisite mastery before a concept is considered "ready"
_DEFAULT_READINESS_THRESHOLD = 0.6


class SkillStateAgent(BaseAgent):
    """Analyses the knowledge graph to produce readiness and cluster reports."""

    def __init__(
        self,
        readiness_threshold: float = _DEFAULT_READINESS_THRESHOLD,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="skill-state",
                display_name="Skill State Agent",
                capabilities=[AgentCapability.SKILL_STATE],
                cost_tier=1,
                description=(
                    "Analyses knowledge graph for readiness, prerequisite gaps, "
                    "and learning-path ordering."
                ),
            )
        )
        self.readiness_threshold = readiness_threshold

    # ── public API ──────────────────────────────────────────────────

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state_raw = message.payload.get("learner_state", {})
        state = LearnerState.model_validate(state_raw)

        log = logger.bind(
            agent=self.agent_id,
            learner_id=state.learner_id,
            concept_count=len(state.concepts),
            relation_count=len(state.concept_relations),
        )
        log.info("skill_state.start")

        # 1. Compute readiness for every concept
        readiness_map = self._compute_readiness(state)

        # 2. Find prerequisite gaps
        prereq_gaps = self._find_prerequisite_gaps(state, readiness_map)

        # 3. Cluster analysis - group concepts by connected component
        clusters = self._cluster_concepts(state)

        # 4. Suggested learning order (topological-ish, filtered by readiness)
        learning_order = self._suggest_learning_order(state, readiness_map)

        # 5. Summary statistics
        mastered = [
            cid for cid, cs in state.concepts.items() if cs.mastery >= 0.85
        ]
        in_progress = [
            cid
            for cid, cs in state.concepts.items()
            if 0.3 <= cs.mastery < 0.85
        ]
        not_started = [
            cid for cid, cs in state.concepts.items() if cs.mastery < 0.3
        ]

        confidence = min(
            1.0,
            0.5 + 0.1 * len(state.concept_relations) + 0.05 * len(state.concepts),
        )

        payload: dict[str, Any] = {
            "readiness": readiness_map,
            "prerequisite_gaps": prereq_gaps,
            "clusters": clusters,
            "learning_order": learning_order,
            "summary": {
                "mastered_count": len(mastered),
                "in_progress_count": len(in_progress),
                "not_started_count": len(not_started),
                "mastered": mastered,
                "in_progress": in_progress,
                "not_started": not_started,
                "total_concepts": len(state.concepts),
            },
            "confidence": round(confidence, 3),
        }

        rationale = self._build_rationale(
            readiness_map, prereq_gaps, mastered, not_started
        )
        log.info("skill_state.complete", gaps=len(prereq_gaps))

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=payload,
            rationale=rationale,
        )

    # ── internal helpers ────────────────────────────────────────────

    def _compute_readiness(
        self, state: LearnerState
    ) -> dict[str, dict[str, Any]]:
        """For each concept, compute a readiness score in [0, 1].

        Readiness = 1.0  if the concept has no prerequisites.
        Otherwise readiness = min(prerequisite masteries) clamped to [0, 1].
        """
        result: dict[str, dict[str, Any]] = {}
        for cid in state.concepts:
            prereq_ids = state.prerequisites_for(cid)
            if not prereq_ids:
                result[cid] = {
                    "readiness": 1.0,
                    "prerequisites_met": True,
                    "blocking_prerequisites": [],
                }
                continue

            prereq_masteries: list[tuple[str, float]] = []
            for pid in prereq_ids:
                pc = state.get_concept(pid)
                mastery = pc.mastery if pc else 0.0
                prereq_masteries.append((pid, mastery))

            min_mastery = min(m for _, m in prereq_masteries)
            blocking = [
                pid
                for pid, m in prereq_masteries
                if m < self.readiness_threshold
            ]
            result[cid] = {
                "readiness": round(min_mastery, 3),
                "prerequisites_met": len(blocking) == 0,
                "blocking_prerequisites": blocking,
            }
        return result

    @staticmethod
    def _find_prerequisite_gaps(
        state: LearnerState,
        readiness_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return concepts whose prerequisites are unsatisfied."""
        gaps: list[dict[str, Any]] = []
        for cid, info in readiness_map.items():
            if info["blocking_prerequisites"]:
                concept = state.get_concept(cid)
                gaps.append({
                    "concept_id": cid,
                    "mastery": round(concept.mastery, 3) if concept else 0.0,
                    "blocking_prerequisites": info["blocking_prerequisites"],
                    "readiness": info["readiness"],
                })
        return sorted(gaps, key=lambda g: g["readiness"])

    @staticmethod
    def _cluster_concepts(state: LearnerState) -> list[dict[str, Any]]:
        """Group concepts into connected components via relations."""
        if not state.concepts:
            return []

        # Build undirected adjacency from all relation types
        adj: dict[str, set[str]] = {cid: set() for cid in state.concepts}
        for rel in state.concept_relations:
            src, tgt = rel.source_concept_id, rel.target_concept_id
            if src in adj:
                adj[src].add(tgt)
            if tgt in adj:
                adj[tgt].add(src)

        visited: set[str] = set()
        clusters: list[dict[str, Any]] = []

        for cid in state.concepts:
            if cid in visited:
                continue
            # BFS
            component: list[str] = []
            queue = [cid]
            while queue:
                node = queue.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for neighbor in adj.get(node, set()):
                    if neighbor not in visited and neighbor in state.concepts:
                        queue.append(neighbor)

            masteries = [
                state.concepts[c].mastery for c in component if c in state.concepts
            ]
            avg = sum(masteries) / len(masteries) if masteries else 0.0
            clusters.append({
                "concepts": sorted(component),
                "size": len(component),
                "average_mastery": round(avg, 3),
            })

        return sorted(clusters, key=lambda c: c["average_mastery"])

    @staticmethod
    def _suggest_learning_order(
        state: LearnerState,
        readiness_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Suggest a learning order: ready + low-mastery concepts first.

        Score = readiness x (1 - mastery).  Higher score = should study sooner.
        """
        scored: list[dict[str, Any]] = []
        for cid, info in readiness_map.items():
            concept = state.get_concept(cid)
            mastery = concept.mastery if concept else 0.0
            readiness = info["readiness"]
            # Skip already-mastered concepts
            if mastery >= 0.85:
                continue
            score = readiness * (1.0 - mastery)
            scored.append({
                "concept_id": cid,
                "readiness": readiness,
                "mastery": round(mastery, 3),
                "learning_priority": round(score, 3),
            })
        return sorted(scored, key=lambda s: s["learning_priority"], reverse=True)

    @staticmethod
    def _build_rationale(
        readiness_map: dict[str, dict[str, Any]],
        prereq_gaps: list[dict[str, Any]],
        mastered: list[str],
        not_started: list[str],
    ) -> str:
        ready_count = sum(
            1 for r in readiness_map.values() if r["prerequisites_met"]
        )
        total = len(readiness_map)
        parts = [
            f"{ready_count}/{total} concepts have prerequisites satisfied.",
            f"{len(mastered)} mastered, {len(not_started)} not started.",
        ]
        if prereq_gaps:
            top_gap = prereq_gaps[0]
            parts.append(
                f"Top gap: {top_gap['concept_id']} blocked by "
                f"{', '.join(top_gap['blocking_prerequisites'])}."
            )
        return " ".join(parts)
