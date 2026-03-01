"""Maker-Checker subsystem — validates agent outputs before delivery.

The Maker-Checker pattern ensures that no recommendation reaches the learner
without independent validation.  The *maker* (e.g. Planner) produces a
candidate, and the *checker* (e.g. Evaluator) audits it.

This module provides:
- ``MakerCheckerResult``: the outcome of a check round.
- ``MakerChecker``: orchestrates one round of make → check with optional retry.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from learning_navigator.agents.base import AgentResponse, BaseAgent
from learning_navigator.contracts.messages import MessageEnvelope, MessageType

logger = structlog.get_logger(__name__)


class CheckVerdict(str, Enum):
    """Outcome of a checker review."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class MakerCheckerResult(BaseModel):
    """Result of a maker-checker validation round."""

    verdict: CheckVerdict = CheckVerdict.REJECTED
    maker_response: dict[str, Any] = Field(default_factory=dict)
    checker_response: dict[str, Any] = Field(default_factory=dict)
    rounds: int = 1
    final_confidence: float = 0.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = ""


class MakerChecker:
    """Orchestrates a Maker-Checker loop between two agents.

    Parameters
    ----------
    maker : BaseAgent
        The agent that produces candidate outputs (e.g. Planner).
    checker : BaseAgent
        The agent that validates those outputs (e.g. Evaluator).
    max_rounds : int
        Maximum make-check iterations before forcing a decision.
    min_quality_score : float
        Minimum quality score from checker to approve.
    """

    def __init__(
        self,
        maker: BaseAgent,
        checker: BaseAgent,
        max_rounds: int = 2,
        min_quality_score: float = 0.5,
    ) -> None:
        self.maker = maker
        self.checker = checker
        self.max_rounds = max_rounds
        self.min_quality_score = min_quality_score

    async def run(
        self,
        maker_message: MessageEnvelope,
        learner_state_raw: dict[str, Any],
    ) -> MakerCheckerResult:
        """Execute the maker-checker loop.

        1. Maker produces a plan.
        2. Checker evaluates it.
        3. If approved or max rounds reached, return result.
        4. Otherwise, feed checker issues back into maker payload and retry.
        """
        current_message = maker_message
        last_maker: AgentResponse | None = None
        last_checker: AgentResponse | None = None

        for round_num in range(1, self.max_rounds + 1):
            logger.info(
                "maker_checker.round",
                round=round_num,
                maker=self.maker.agent_id,
                checker=self.checker.agent_id,
            )

            # --- MAKE ---
            last_maker = await self.maker.handle(current_message)

            if last_maker.errors:
                return MakerCheckerResult(
                    verdict=CheckVerdict.REJECTED,
                    maker_response=last_maker.payload,
                    rounds=round_num,
                    final_confidence=last_maker.confidence,
                    issues=[{"type": "maker_error", "errors": last_maker.errors}],
                    rationale="Maker produced errors",
                )

            # --- CHECK ---
            check_payload = {
                "learner_state": learner_state_raw,
                "plan": last_maker.payload,
            }
            check_message = MessageEnvelope(
                message_type=MessageType.PLAN_REVIEW,
                source_agent_id=self.maker.agent_id,
                target_agent_id=self.checker.agent_id,
                payload=check_payload,
            )

            last_checker = await self.checker.handle(check_message)

            if last_checker.errors:
                return MakerCheckerResult(
                    verdict=CheckVerdict.REJECTED,
                    maker_response=last_maker.payload,
                    checker_response=last_checker.payload,
                    rounds=round_num,
                    final_confidence=0.0,
                    issues=[{"type": "checker_error", "errors": last_checker.errors}],
                    rationale="Checker produced errors",
                )

            quality_score = last_checker.payload.get("quality_score", 0.0)
            approved = last_checker.payload.get("approved", False)

            if approved and quality_score >= self.min_quality_score:
                return MakerCheckerResult(
                    verdict=CheckVerdict.APPROVED,
                    maker_response=last_maker.payload,
                    checker_response=last_checker.payload,
                    rounds=round_num,
                    final_confidence=min(
                        last_maker.confidence, last_checker.confidence
                    ),
                    issues=last_checker.payload.get("issues", []),
                    rationale=f"Approved in round {round_num}: score={quality_score:.2f}",
                )

            # --- RETRY: inject checker feedback ---
            if round_num < self.max_rounds:
                revised_payload = dict(current_message.payload)
                revised_payload["checker_feedback"] = {
                    "issues": last_checker.payload.get("issues", []),
                    "quality_score": quality_score,
                }
                current_message = current_message.derive(
                    message_type=MessageType.PLAN_READY,
                    source_agent_id="maker_checker",
                    payload=revised_payload,
                )

        # Exhausted rounds
        final_quality = (
            last_checker.payload.get("quality_score", 0.0)
            if last_checker
            else 0.0
        )
        verdict = (
            CheckVerdict.APPROVED
            if final_quality >= self.min_quality_score
            else CheckVerdict.NEEDS_REVISION
        )

        return MakerCheckerResult(
            verdict=verdict,
            maker_response=last_maker.payload if last_maker else {},
            checker_response=last_checker.payload if last_checker else {},
            rounds=self.max_rounds,
            final_confidence=final_quality,
            issues=(
                last_checker.payload.get("issues", []) if last_checker else []
            ),
            rationale=f"Exhausted {self.max_rounds} rounds: score={final_quality:.2f}",
        )
