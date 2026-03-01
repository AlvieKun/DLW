"""Diagnoser Agent — assesses learner state from incoming events.

The Diagnoser is the first agent in the pipeline.  It takes raw learner
events (quiz results, time-on-task, etc.) and updates the LearnerState
accordingly.  It does NOT plan — it only observes and updates.

Responsibilities:
• Update BKT mastery based on quiz results.
• Update practice timestamps and spacing history.
• Flag concepts that need attention.
• Compute a diagnostic summary for downstream agents.
"""

from __future__ import annotations

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


class DiagnoserAgent(BaseAgent):
    """Processes learner events and updates state with diagnostic findings."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="diagnoser",
                display_name="Diagnoser Agent",
                capabilities=[AgentCapability.DIAGNOSE],
                cost_tier=1,
                description="Assesses learner state from incoming events",
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Process a diagnosis request containing a learner event + state."""
        payload = message.payload
        learner_state_raw = payload.get("learner_state")
        event_data = payload.get("event")

        if not learner_state_raw or not event_data:
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=["Missing learner_state or event in payload"],
            )

        try:
            state = LearnerState.model_validate(learner_state_raw)
            diagnosis = self._diagnose(state, event_data)

            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=diagnosis["confidence"],
                payload=diagnosis,
                rationale=diagnosis.get("summary", "Diagnosis complete"),
            )
        except Exception as e:
            logger.exception("diagnoser.handle_error")
            return AgentResponse(
                source_agent_id=self.agent_id,
                confidence=0.0,
                errors=[str(e)],
            )

    def _diagnose(self, state: LearnerState, event: dict[str, Any]) -> dict[str, Any]:
        """Run diagnostic analysis on the learner state given a new event."""
        event_type = event.get("event_type", "")
        concept_id = event.get("concept_id")
        now = datetime.now(timezone.utc)

        updates: list[dict[str, Any]] = []
        flags: list[str] = []

        if event_type == "quiz_result" and concept_id:
            updates.extend(self._process_quiz(state, concept_id, event, now))

        if event_type == "time_on_task" and concept_id:
            updates.extend(self._process_time_on_task(state, concept_id, event, now))

        # Compute weak concepts
        weak = state.weak_concepts(threshold=0.5)
        if len(weak) > len(state.concepts) * 0.5 and len(state.concepts) > 0:
            flags.append("majority_concepts_below_mastery")

        # Check inactivity
        inactivity = state.inactivity_hours()
        if inactivity is not None and inactivity > 48:
            flags.append(f"inactivity_gap_{inactivity:.0f}h")

        confidence = min(0.9, 0.5 + 0.1 * len(updates))

        return {
            "updates": updates,
            "flags": flags,
            "weak_concept_ids": [c.concept_id for c in weak],
            "average_mastery": state.average_mastery(),
            "average_uncertainty": state.average_uncertainty(),
            "confidence": confidence,
            "summary": (
                f"Diagnosed {len(updates)} updates, {len(flags)} flags. "
                f"Avg mastery={state.average_mastery():.2f}, "
                f"Avg uncertainty={state.average_uncertainty():.2f}"
            ),
        }

    def _process_quiz(
        self, state: LearnerState, concept_id: str, event: dict[str, Any], now: datetime
    ) -> list[dict[str, Any]]:
        """Update BKT from quiz result."""
        updates = []
        score = event.get("data", {}).get("score", 0.0)
        max_score = event.get("data", {}).get("max_score", 1.0)
        correct = score >= (max_score * 0.5) if max_score > 0 else False

        concept = state.get_concept(concept_id)
        if concept is None:
            concept = ConceptState(concept_id=concept_id)
            state.upsert_concept(concept)

        old_mastery = concept.mastery
        new_bkt = concept.bkt.update(correct=correct)

        # Update spacing history
        new_spacing = list(concept.spacing_history)
        if concept.last_practiced:
            hours_since = (now - concept.last_practiced).total_seconds() / 3600
            new_spacing.append(hours_since)

        updated = concept.model_copy(
            update={
                "bkt": new_bkt,
                "last_practiced": now,
                "practice_count": concept.practice_count + 1,
                "spacing_history": new_spacing[-20:],  # keep last 20
            }
        )
        state.upsert_concept(updated)

        updates.append({
            "type": "bkt_update",
            "concept_id": concept_id,
            "old_mastery": old_mastery,
            "new_mastery": new_bkt.mastery,
            "correct": correct,
        })

        return updates

    def _process_time_on_task(
        self, state: LearnerState, concept_id: str, event: dict[str, Any], now: datetime
    ) -> list[dict[str, Any]]:
        """Record time-on-task data."""
        minutes = event.get("data", {}).get("minutes", 0)
        concept = state.get_concept(concept_id)
        if concept is None:
            concept = ConceptState(concept_id=concept_id)
            state.upsert_concept(concept)

        updated = concept.model_copy(update={"last_practiced": now})
        state.upsert_concept(updated)

        return [{
            "type": "time_on_task",
            "concept_id": concept_id,
            "minutes": minutes,
        }]
