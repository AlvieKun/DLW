"""Reflection Agent — explainable narrative generation.

Generates human-readable narratives summarising:
• What happened this session (events processed, state changes).
• Why recommendations were made (citing agent outputs).
• What progress looks like over time (mastery trajectory).
• What to expect next (forward-looking guidance).

The Reflection Agent reads the *full pipeline context* (diagnosis, drift,
motivation, plan, and evaluation outputs) and synthesises a coherent
learning narrative.  It does NOT change state — it only reads and reports.
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


class ReflectionAgent(BaseAgent):
    """Produces explainable narrative summaries of learner progress."""

    def __init__(self) -> None:
        super().__init__(
            AgentMetadata(
                agent_id="reflection",
                display_name="Reflection Agent",
                capabilities=[AgentCapability.REFLECTION],
                cost_tier=2,
                description=(
                    "Generates natural-language learning narratives "
                    "from pipeline context for explainability."
                ),
            )
        )

    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        state_raw = message.payload.get("learner_state", {})
        state = LearnerState.model_validate(state_raw)

        # Gather context from earlier pipeline stages
        diagnosis = message.payload.get("diagnosis", {})
        drift_response = message.payload.get("drift_response", {})
        motivation_response = message.payload.get("motivation_response", {})
        plan_response = message.payload.get("plan_response", {})
        skill_state_response = message.payload.get("skill_state_response", {})
        behavior_response = message.payload.get("behavior_response", {})
        time_response = message.payload.get("time_response", {})
        decay_response = message.payload.get("decay_response", {})
        replay_response = message.payload.get("replay_response", {})
        debate_response = message.payload.get("debate_response", {})
        rag_response = message.payload.get("rag_response", {})

        log = logger.bind(agent=self.agent_id, learner_id=state.learner_id)
        log.info("reflection.start")

        # Build narrative sections
        sections: list[dict[str, str]] = []

        sections.append(self._progress_section(state))
        sections.append(self._session_section(state, diagnosis))
        sections.append(self._motivation_section(state, motivation_response))
        sections.append(self._drift_section(drift_response))
        sections.append(self._behavior_section(behavior_response))
        sections.append(self._decay_section(decay_response))
        sections.append(self._replay_section(replay_response))
        sections.append(self._plan_section(plan_response, time_response))
        sections.append(self._skill_graph_section(skill_state_response))
        sections.append(self._debate_section(debate_response))
        sections.append(self._rag_grounding_section(rag_response))
        sections.append(self._outlook_section(state))

        # Filter empty sections
        sections = [s for s in sections if s["content"]]

        # Full narrative
        narrative = "\n\n".join(
            f"**{s['title']}**\n{s['content']}" for s in sections
        )

        # Citations: list of agents that contributed data
        citations = self._gather_citations(
            diagnosis, drift_response, motivation_response,
            plan_response, skill_state_response, behavior_response,
            time_response, decay_response, replay_response,
        )

        confidence = min(1.0, 0.4 + 0.1 * len(citations))

        payload: dict[str, Any] = {
            "narrative": narrative,
            "sections": sections,
            "section_count": len(sections),
            "citations": citations,
            "confidence": round(confidence, 3),
        }

        log.info("reflection.complete", sections=len(sections))

        return AgentResponse(
            source_agent_id=self.agent_id,
            confidence=confidence,
            payload=payload,
            rationale=f"Generated {len(sections)}-section narrative from {len(citations)} agent inputs.",
        )

    # ── Section builders ────────────────────────────────────────────

    @staticmethod
    def _progress_section(state: LearnerState) -> dict[str, str]:
        """Overall mastery progress summary."""
        if not state.concepts:
            return {
                "title": "Progress Overview",
                "content": "No concepts tracked yet. Start practicing to see your progress!",
            }

        avg = state.average_mastery()
        total = len(state.concepts)
        mastered = sum(1 for c in state.concepts.values() if c.mastery >= 0.85)
        weak = sum(1 for c in state.concepts.values() if c.mastery < 0.5)

        lines = [
            f"You're tracking {total} concept{'s' if total != 1 else ''}.",
            f"Average mastery: {avg:.0%}.",
        ]
        if mastered:
            lines.append(f"{mastered} concept{'s' if mastered != 1 else ''} mastered (≥85%).")
        if weak:
            lines.append(f"{weak} concept{'s' if weak != 1 else ''} need{'s' if weak == 1 else ''} more work (<50%).")

        return {"title": "Progress Overview", "content": " ".join(lines)}

    @staticmethod
    def _session_section(
        state: LearnerState, diagnosis: dict[str, Any]
    ) -> dict[str, str]:
        """What happened in this session."""
        updates = diagnosis.get("updates", [])
        if not updates:
            return {"title": "This Session", "content": ""}

        improved = [u for u in updates if u.get("correct", False)]
        struggled = [u for u in updates if not u.get("correct", True)]

        lines = [f"Processed {len(updates)} concept update{'s' if len(updates) != 1 else ''} this session."]
        if improved:
            ids = [u["concept_id"] for u in improved[:3]]
            lines.append(f"Improved on: {', '.join(ids)}.")
        if struggled:
            ids = [u["concept_id"] for u in struggled[:3]]
            lines.append(f"Struggled with: {', '.join(ids)}.")

        return {"title": "This Session", "content": " ".join(lines)}

    @staticmethod
    def _motivation_section(
        state: LearnerState, motivation_response: dict[str, Any]
    ) -> dict[str, str]:
        """Motivation-related narrative."""
        mot = state.motivation
        level = mot.level

        if level == MotivationLevel.HIGH:
            msg = "Your motivation is strong! Keep up the momentum."
        elif level == MotivationLevel.MEDIUM:
            msg = "Motivation is steady. Consistent practice will maintain it."
        elif level == MotivationLevel.LOW:
            msg = "Motivation appears low. Consider shorter sessions and easier concepts to rebuild confidence."
        else:
            msg = "Motivation is critically low. Focus on small wins and take breaks as needed."

        trend = mot.trend
        if trend > 0.1:
            msg += " Trend is improving."
        elif trend < -0.1:
            msg += " Trend is declining — pay attention to what's causing frustration."

        return {"title": "Motivation", "content": msg}

    @staticmethod
    def _drift_section(drift_response: dict[str, Any]) -> dict[str, str]:
        """Drift signals summary."""
        signals = drift_response.get("drift_signals", [])
        if not signals:
            return {"title": "Learning Drift", "content": ""}

        lines = [f"Detected {len(signals)} drift signal{'s' if len(signals) != 1 else ''}:"]
        for sig in signals[:3]:
            dtype = sig.get("drift_type", "unknown")
            sev = sig.get("severity", 0.0)
            lines.append(f"  • {dtype} (severity {sev:.0%})")

        return {"title": "Learning Drift", "content": "\n".join(lines)}

    @staticmethod
    def _behavior_section(behavior_response: dict[str, Any]) -> dict[str, str]:
        """Behavioural anomalies summary."""
        anomalies = behavior_response.get("anomalies", [])
        if not anomalies:
            return {"title": "Behavioral Patterns", "content": ""}

        lines = [f"Noticed {len(anomalies)} pattern{'s' if len(anomalies) != 1 else ''} to watch:"]
        messages = {
            "cramming": "It looks like you're cramming. Try to spread study sessions more evenly.",
            "rapid_guessing": "Some responses were very fast — make sure you're reading carefully.",
            "avoidance": "Some concepts are being avoided. Tackling them early prevents bigger gaps.",
            "irregular_sessions": "Your study schedule is irregular. Consistent timing helps retention.",
            "late_night_study": "Late-night studying may hurt retention. Try to study when well-rested.",
        }
        for anomaly in anomalies[:3]:
            atype = anomaly.get("anomaly_type", "unknown")
            lines.append(f"  • {messages.get(atype, atype)}")

        return {"title": "Behavioral Patterns", "content": "\n".join(lines)}

    @staticmethod
    def _plan_section(
        plan_response: dict[str, Any],
        time_response: dict[str, Any],
    ) -> dict[str, str]:
        """Plan and time allocation summary."""
        recommendations = plan_response.get("recommendations", [])
        allocations = time_response.get("allocations", [])

        if not recommendations and not allocations:
            return {"title": "Recommendations", "content": ""}

        lines: list[str] = []
        if recommendations:
            lines.append(f"Recommended {len(recommendations)} learning action{'s' if len(recommendations) != 1 else ''}:")
            for rec in recommendations[:3]:
                cid = rec.get("concept_id", "?")
                action = rec.get("action", "study")
                lines.append(f"  • {action.replace('_', ' ').title()}: {cid}")

        if allocations:
            total_min = sum(a.get("minutes", 0) for a in allocations)
            lines.append(f"Time budget: {total_min} minutes across {len(allocations)} concepts.")

        return {"title": "Recommendations", "content": "\n".join(lines)}

    @staticmethod
    def _skill_graph_section(skill_state_response: dict[str, Any]) -> dict[str, str]:
        """Knowledge graph analysis summary."""
        gaps = skill_state_response.get("prerequisite_gaps", [])
        learning_order = skill_state_response.get("learning_order", [])

        if not gaps and not learning_order:
            return {"title": "Knowledge Graph", "content": ""}

        lines: list[str] = []
        if gaps:
            lines.append(f"{len(gaps)} prerequisite gap{'s' if len(gaps) != 1 else ''} found:")
            for gap in gaps[:2]:
                cid = gap.get("concept_id", "?")
                blockers = gap.get("blocking_prerequisites", [])
                lines.append(f"  • {cid} — blocked by: {', '.join(blockers)}")

        if learning_order:
            top = learning_order[:3]
            lines.append("Suggested study order: " + " → ".join(t["concept_id"] for t in top))

        return {"title": "Knowledge Graph", "content": "\n".join(lines)}

    @staticmethod
    def _decay_section(decay_response: dict[str, Any]) -> dict[str, str]:
        """Memory decay / forgetting summary."""
        at_risk = decay_response.get("at_risk", [])
        summary = decay_response.get("summary", {})

        if not at_risk:
            return {"title": "Memory & Retention", "content": ""}

        avg_f = summary.get("average_forgetting", 0)
        lines = [
            f"{len(at_risk)} concept{'s' if len(at_risk) != 1 else ''} "
            f"at risk of being forgotten (avg forgetting {avg_f:.0%}):"
        ]
        for item in at_risk[:3]:
            cid = item.get("concept_id", "?")
            score = item.get("forgetting_score", 0)
            lines.append(f"  - {cid} (forgetting {score:.0%})")

        lines.append("Review these soon to prevent memory loss.")
        return {"title": "Memory & Retention", "content": "\n".join(lines)}

    @staticmethod
    def _replay_section(replay_response: dict[str, Any]) -> dict[str, str]:
        """Generative replay exercises summary."""
        replay_plan = replay_response.get("replay_plan", [])
        total = replay_response.get("total_exercises", 0)
        interleaved = replay_response.get("interleaved_sets", [])

        if not replay_plan:
            return {"title": "Practice Exercises", "content": ""}

        lines = [
            f"Generated {total} practice exercise{'s' if total != 1 else ''} "
            f"across {len(replay_plan)} concept{'s' if len(replay_plan) != 1 else ''}."
        ]
        for plan in replay_plan[:3]:
            cid = plan.get("concept_id", "?")
            n_ex = len(plan.get("exercises", []))
            lines.append(f"  - {cid}: {n_ex} exercise{'s' if n_ex != 1 else ''}")

        if interleaved:
            lines.append(f"{len(interleaved)} interleaved set{'s' if len(interleaved) != 1 else ''} for deeper retention.")

        return {"title": "Practice Exercises", "content": "\n".join(lines)}

    @staticmethod
    def _debate_section(debate_response: dict[str, Any]) -> dict[str, str]:
        """Strategic debate summary."""
        if not debate_response:
            return {"title": "Strategic Debate", "content": ""}

        outcome = debate_response.get("outcome", "debate_skipped")
        if outcome == "debate_skipped":
            return {"title": "Strategic Debate", "content": ""}

        lines: list[str] = []
        rounds = debate_response.get("rounds_used", 0)
        alignment = debate_response.get("overall_alignment", 1.0)
        amendments = debate_response.get("accepted_amendments", [])
        weights = debate_response.get("perspective_weights", {})

        outcome_labels = {
            "plan_approved": "Plan approved by all perspectives",
            "minor_revision": "Minor revisions accepted",
            "major_revision": "Major revisions required",
        }
        lines.append(f"Outcome: {outcome_labels.get(outcome, outcome)} (rounds: {rounds}).")
        lines.append(f"Overall alignment: {alignment:.0%}.")

        if weights:
            weight_parts = [f"{k}: {v:.0%}" for k, v in sorted(weights.items())]
            lines.append(f"Perspective weights: {', '.join(weight_parts)}.")

        if amendments:
            lines.append(f"{len(amendments)} amendment{'s' if len(amendments) != 1 else ''} applied to the plan.")

        return {"title": "Strategic Debate", "content": "\n".join(lines)}

    @staticmethod
    def _rag_grounding_section(rag_response: dict[str, Any]) -> dict[str, str]:
        """Summarise RAG citations grounding the recommendations."""
        citations = rag_response.get("citations", [])
        query_count = rag_response.get("query_count", 0)
        if not citations:
            return {"title": "Supporting Material", "content": ""}

        lines: list[str] = [
            f"Found {len(citations)} supporting reference{'s' if len(citations) != 1 else ''} "
            f"from {query_count} learner-aware {'queries' if query_count != 1 else 'query'}.",
        ]

        for cite in citations[:5]:  # cap display at 5
            doc_id = cite.get("doc_id", "unknown")
            score = cite.get("score", 0.0)
            concept = cite.get("concept_id", "")
            snippet = cite.get("content", "")[:120]
            label = f"[{doc_id}] (score {score:.2f})"
            if concept:
                label += f" for {concept}"
            lines.append(f"- {label}: {snippet}{'...' if len(cite.get('content', '')) > 120 else ''}")

        if len(citations) > 5:
            lines.append(f"  ...and {len(citations) - 5} more.")

        return {"title": "Supporting Material", "content": "\n".join(lines)}

    @staticmethod
    def _outlook_section(state: LearnerState) -> dict[str, str]:
        """Forward-looking guidance."""
        avg = state.average_mastery()
        lines: list[str] = []

        if avg >= 0.85:
            lines.append("Excellent progress! Focus on maintaining through periodic review.")
        elif avg >= 0.6:
            lines.append("Good progress. Push to master the remaining concepts.")
        elif avg >= 0.3:
            lines.append("Building foundation. Focus on fundamentals before advancing.")
        else:
            lines.append("Early stage — start with the basics and build consistently.")

        deadline = state.time_budget.deadline
        if deadline:
            from datetime import datetime, timezone
            hours = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours > 0:
                lines.append(f"Deadline in {hours:.0f} hours — stay on track!")
            else:
                lines.append("Deadline has passed. Review what you've learned.")

        return {"title": "Looking Ahead", "content": " ".join(lines)}

    @staticmethod
    def _gather_citations(*responses: dict[str, Any]) -> list[str]:
        """List agents that contributed non-empty data."""
        agent_map = [
            "diagnoser", "drift_detector", "motivation",
            "planner", "skill_state", "behavior", "time_optimizer",
            "decay", "generative_replay",
        ]
        citations: list[str] = []
        for i, resp in enumerate(responses):
            if resp and any(resp.values()) and i < len(agent_map):
                citations.append(agent_map[i])
        return citations
