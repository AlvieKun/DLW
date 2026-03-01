"""RAG Agent — retrieval-augmented grounding for recommendations.

The RAG Agent enriches the pipeline with *grounded* supporting material
retrieved from the knowledge base.  Given the learner's current state,
the plan, and the diagnosis, it constructs learner-aware queries and
returns ranked, citation-keyed passages.

Learner-awareness
─────────────────
Queries are **not** just the raw concept names.  The agent builds
contextual queries that incorporate:

• The learner's mastery level (beginner/intermediate/advanced framing).
• The recommended action (learn_new → introductory material,
  practice → exercises, deepen → advanced explanations,
  spaced_review → summaries and mnemonics).
• Prerequisite gaps (include prerequisite material when gaps exist).

This ensures retrieved content matches *where the learner is*, not just
*what the topic is*.

Grounding contract
──────────────────
Each citation is returned as a dict with:
  - ``doc_id``: unique key into the retrieval index
  - ``score``: relevance score from the index
  - ``content``: snippet of the retrieved passage
  - ``metadata``: any index-side metadata (source, topic, difficulty)
  - ``query``: the learner-aware query that produced this result
  - ``concept_id``: which plan concept this supports

These citations flow into ``NextBestAction.citations`` and into the
Reflection Agent's RAG Grounding section.
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
from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.contracts.messages import MessageEnvelope
from learning_navigator.storage.interfaces import RetrievalIndex

logger = structlog.get_logger(__name__)


class RAGAgent(BaseAgent):
    """Retrieves grounded supporting material for plan recommendations.

    Parameters
    ----------
    retrieval_index : RetrievalIndex
        The search backend (LocalTfidfIndex or AzureAISearchIndex).
    top_k_per_concept : int
        Maximum documents retrieved per concept query.
    min_score : float
        Minimum relevance score to include a result.
    """

    def __init__(
        self,
        retrieval_index: RetrievalIndex,
        top_k_per_concept: int = 3,
        min_score: float = 0.1,
    ) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="rag-agent",
                display_name="RAG Agent",
                capabilities=[AgentCapability.RAG_RETRIEVE],
                cost_tier=2,
                description=(
                    "Retrieves grounded supporting material from the knowledge "
                    "base using learner-aware contextual queries."
                ),
            )
        )
        self._index = retrieval_index
        self._top_k = top_k_per_concept
        self._min_score = min_score

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Retrieve grounded citations for plan recommendations."""
        payload = message.payload
        state = LearnerState.model_validate(payload.get("learner_state", {}))
        plan = payload.get("plan", {})
        diagnosis = payload.get("diagnosis", {})

        recommendations = plan.get("recommendations", [])

        log = logger.bind(agent=self.agent_id, learner_id=state.learner_id)
        log.info("rag.start", concepts=len(recommendations))

        all_citations: list[dict[str, Any]] = []
        queries_executed: list[dict[str, str]] = []

        for rec in recommendations:
            concept_id = rec.get("concept_id", "")
            action = rec.get("action", "study")

            if not concept_id:
                continue

            # Build learner-aware query
            query = self._build_query(state, concept_id, action, diagnosis)
            queries_executed.append({
                "concept_id": concept_id,
                "query": query,
            })

            # Search the index
            results = await self._index.search(
                query, top_k=self._top_k
            )

            for result in results:
                score = result.get("score", 0.0)
                if score < self._min_score:
                    continue

                citation = {
                    "doc_id": result.get("doc_id", ""),
                    "score": score,
                    "content": result.get("content", ""),
                    "metadata": result.get("metadata", {}),
                    "query": query,
                    "concept_id": concept_id,
                    "action": action,
                }
                all_citations.append(citation)

        # Deduplicate by doc_id, keeping highest score
        deduped = self._deduplicate(all_citations)

        # Sort by score descending
        deduped.sort(key=lambda c: c["score"], reverse=True)

        confidence = min(0.9, 0.3 + 0.1 * len(deduped)) if deduped else 0.2

        log.info(
            "rag.complete",
            citations=len(deduped),
            queries=len(queries_executed),
        )

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload={
                "citations": deduped,
                "citation_count": len(deduped),
                "queries": queries_executed,
                "query_count": len(queries_executed),
            },
            rationale=(
                f"Retrieved {len(deduped)} grounded citations "
                f"from {len(queries_executed)} learner-aware queries."
            ),
        )

    # ── Query construction ─────────────────────────────────────────

    def _build_query(
        self,
        state: LearnerState,
        concept_id: str,
        action: str,
        diagnosis: dict[str, Any],
    ) -> str:
        """Build a learner-aware search query.

        Strategy:
        - Base: concept name
        - Level modifier: based on mastery
        - Action modifier: based on recommended action
        - Prerequisite enrichment: if gaps exist
        """
        parts: list[str] = [concept_id]

        # Level awareness
        concept = state.get_concept(concept_id)
        if concept:
            mastery = concept.mastery
            if mastery < 0.3:
                parts.append("introduction basics beginner")
            elif mastery < 0.6:
                parts.append("intermediate explanation examples")
            elif mastery < 0.85:
                parts.append("advanced practice application")
            else:
                parts.append("mastery review summary")

            # Difficulty awareness
            if concept.difficulty > 0.7:
                parts.append("simplified step by step")

        # Action awareness
        action_queries = {
            "learn_new": "tutorial introduction concepts",
            "practice": "exercises problems worked examples",
            "deepen": "advanced theory deep dive",
            "spaced_review": "summary key points review flashcard",
            "maintain": "quick review refresher",
        }
        if action in action_queries:
            parts.append(action_queries[action])

        # Prerequisite gap enrichment
        prereqs = state.prerequisites_for(concept_id)
        weak_prereqs = [
            p for p in prereqs
            if (c := state.get_concept(p)) is not None and c.mastery < 0.5
        ]
        if weak_prereqs:
            parts.append(f"prerequisite {' '.join(weak_prereqs[:2])}")

        return " ".join(parts)

    @staticmethod
    def _deduplicate(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the highest-scoring citation per doc_id."""
        best: dict[str, dict[str, Any]] = {}
        for c in citations:
            doc_id = c["doc_id"]
            if doc_id not in best or c["score"] > best[doc_id]["score"]:
                best[doc_id] = c
        return list(best.values())
