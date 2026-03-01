"""Debate Engine — orchestrates a multi-advocate strategic debate.

Workflow
───────
1. Receive an approved plan from the Maker-Checker subsystem.
2. Fan-out: send the plan to all registered advocate agents in parallel.
3. Collect critiques (objections + amendments + alignment_score).
4. Forward critiques to the Arbitrator for resolution.
5. If the Arbitrator signals *major_revision* and rounds remain, loop.
6. Return a ``DebateResult`` summarising the final resolution.

The debate is optional — controlled by ``config.debate_enabled`` and
``config.max_debate_rounds``.  When disabled, the engine returns an
auto-approved result without invoking any advocate.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from learning_navigator.agents.base import AgentResponse, BaseAgent
from learning_navigator.contracts.messages import MessageEnvelope, MessageType

logger = structlog.get_logger(__name__)


# ── Data Types ──────────────────────────────────────────────────────────────


class DebateOutcome(str, Enum):
    """High-level result of the debate process."""

    PLAN_APPROVED = "plan_approved"
    MINOR_REVISION = "minor_revision"
    MAJOR_REVISION = "major_revision"
    DEBATE_SKIPPED = "debate_skipped"


class DebateResult(BaseModel):
    """Outcome of the full debate round(s)."""

    outcome: DebateOutcome = DebateOutcome.DEBATE_SKIPPED
    rounds_used: int = 0
    advocate_critiques: list[dict[str, Any]] = Field(default_factory=list)
    arbitration: dict[str, Any] = Field(default_factory=dict)
    accepted_amendments: list[dict[str, Any]] = Field(default_factory=list)
    perspective_weights: dict[str, float] = Field(default_factory=dict)
    overall_alignment: float = 1.0
    rationale: str = ""


# ── Debate Engine ──────────────────────────────────────────────────────────


class DebateEngine:
    """Orchestrates a multi-perspective debate on learning plans.

    Parameters
    ----------
    advocates : list[BaseAgent]
        The advocate agents (Mastery, Exam, Burnout).
    arbitrator : BaseAgent
        The arbitration agent that resolves disagreements.
    max_rounds : int
        Maximum debate iterations.
    enabled : bool
        When False, ``run()`` returns an auto-approved ``DebateResult``.
    """

    def __init__(
        self,
        advocates: list[BaseAgent],
        arbitrator: BaseAgent,
        max_rounds: int = 2,
        enabled: bool = True,
    ) -> None:
        self.advocates = list(advocates)
        self.arbitrator = arbitrator
        self.max_rounds = max_rounds
        self.enabled = enabled

    async def run(
        self,
        plan: dict[str, Any],
        learner_state_raw: dict[str, Any],
        correlation_id: str = "",
    ) -> DebateResult:
        """Execute the debate loop.

        Parameters
        ----------
        plan : dict
            The plan payload produced by the Maker-Checker.
        learner_state_raw : dict
            JSON-serialised ``LearnerState``.
        correlation_id : str
            Tracing ID from the outer pipeline.
        """
        if not self.enabled or not self.advocates:
            return DebateResult(
                outcome=DebateOutcome.DEBATE_SKIPPED,
                rationale="Debate disabled or no advocates registered.",
            )

        last_arbitration: dict[str, Any] = {}
        all_critiques: list[dict[str, Any]] = []

        for round_num in range(1, self.max_rounds + 1):
            logger.info(
                "debate.round.start",
                round=round_num,
                advocates=len(self.advocates),
            )

            # 1. Fan-out to advocates
            critiques = await self._collect_critiques(
                plan, learner_state_raw, correlation_id
            )
            all_critiques = critiques  # keep latest round

            # 2. Check if debate is even needed
            if self._all_aligned(critiques):
                logger.info("debate.all_aligned", round=round_num)
                return DebateResult(
                    outcome=DebateOutcome.PLAN_APPROVED,
                    rounds_used=round_num,
                    advocate_critiques=critiques,
                    arbitration={},
                    overall_alignment=self._avg_alignment(critiques),
                    rationale=f"All advocates aligned in round {round_num}.",
                )

            # 3. Arbitrate
            arb_response = await self._arbitrate(
                plan, critiques, learner_state_raw, correlation_id
            )
            last_arbitration = arb_response.payload

            resolution = last_arbitration.get("resolution", "plan_approved")

            if resolution != "major_revision":
                break  # no more rounds needed

            # Major revision — loop continues if rounds remain
            logger.info("debate.major_revision", round=round_num)

        # Build final result
        outcome = self._map_outcome(last_arbitration.get("resolution", "plan_approved"))
        accepted = last_arbitration.get("accepted_amendments", [])
        weights = last_arbitration.get("perspective_weights", {})
        alignment = last_arbitration.get("overall_alignment", 1.0)

        result = DebateResult(
            outcome=outcome,
            rounds_used=min(self.max_rounds, round_num),  # type: ignore[possibly-undefined]
            advocate_critiques=all_critiques,
            arbitration=last_arbitration,
            accepted_amendments=accepted,
            perspective_weights=weights,
            overall_alignment=alignment,
            rationale=(
                f"Debate resolved as {outcome.value} after "
                f"{min(self.max_rounds, round_num)} round(s)."  # type: ignore[possibly-undefined]
            ),
        )

        logger.info(
            "debate.complete",
            outcome=outcome.value,
            rounds=result.rounds_used,
            amendments=len(accepted),
        )

        return result

    # ── Internal helpers ─────────────────────────────────────────────

    async def _collect_critiques(
        self,
        plan: dict[str, Any],
        learner_state_raw: dict[str, Any],
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        """Send the plan to all advocates and collect their critiques."""
        critiques: list[dict[str, Any]] = []

        for advocate in self.advocates:
            msg = MessageEnvelope(
                message_type=MessageType.PLAN_CRITIQUE,
                source_agent_id="debate-engine",
                target_agent_id=advocate.agent_id,
                payload={
                    "learner_state": learner_state_raw,
                    "plan": plan,
                },
                correlation_id=correlation_id,
            )
            try:
                response: AgentResponse = await advocate.handle(msg)
                critiques.append(response.payload)
            except Exception:
                logger.exception(
                    "debate.advocate_error", advocate=advocate.agent_id
                )
                critiques.append({
                    "perspective": getattr(advocate, "perspective", "unknown"),
                    "objections": [],
                    "amendments": [],
                    "alignment_score": 1.0,
                    "error": True,
                })

        return critiques

    async def _arbitrate(
        self,
        plan: dict[str, Any],
        critiques: list[dict[str, Any]],
        learner_state_raw: dict[str, Any],
        correlation_id: str,
    ) -> AgentResponse:
        """Send critiques to the arbitrator for resolution."""
        msg = MessageEnvelope(
            message_type=MessageType.ARBITRATION_RESULT,
            source_agent_id="debate-engine",
            target_agent_id=self.arbitrator.agent_id,
            payload={
                "learner_state": learner_state_raw,
                "plan": plan,
                "critiques": critiques,
            },
            correlation_id=correlation_id,
        )
        return await self.arbitrator.handle(msg)

    @staticmethod
    def _all_aligned(critiques: list[dict[str, Any]], threshold: float = 0.85) -> bool:
        """Return True if every advocate considers the plan aligned."""
        if not critiques:
            return True
        return all(
            c.get("alignment_score", 0.0) >= threshold
            for c in critiques
            if not c.get("error")
        )

    @staticmethod
    def _avg_alignment(critiques: list[dict[str, Any]]) -> float:
        """Average alignment score across advocates."""
        scores = [
            c.get("alignment_score", 0.0)
            for c in critiques
            if not c.get("error")
        ]
        return round(sum(scores) / len(scores), 3) if scores else 1.0

    @staticmethod
    def _map_outcome(resolution: str) -> DebateOutcome:
        mapping = {
            "plan_approved": DebateOutcome.PLAN_APPROVED,
            "minor_revision": DebateOutcome.MINOR_REVISION,
            "major_revision": DebateOutcome.MAJOR_REVISION,
        }
        return mapping.get(resolution, DebateOutcome.MINOR_REVISION)
