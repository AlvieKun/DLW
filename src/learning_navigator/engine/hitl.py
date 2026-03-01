"""Human-in-the-Loop (HITL) hooks.

Provides interfaces for human oversight of agent recommendations:
- ``HITLDecision``: Possible human decisions.
- ``HITLRequest``: A structured request for human review.
- ``HITLHook``: Abstract interface that implementations can plug into.
- ``DefaultHITLHook``: Auto-approves (no human present) for automated flows.

Integrations (teacher dashboard, Slack, etc.) subclass ``HITLHook``
and override ``request_review`` with real async I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class HITLDecision(str, Enum):
    """Possible outcomes of human review."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    ESCALATE = "escalate"
    AUTO_APPROVED = "auto_approved"


class HITLRequest(BaseModel):
    """A structured request for human review."""

    request_id: str = Field(default_factory=lambda: "")
    learner_id: str
    recommendation: dict[str, Any] = Field(default_factory=dict)
    agent_rationale: str = ""
    quality_score: float = 0.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    urgency: str = "normal"  # normal, high, critical
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HITLResponse(BaseModel):
    """Response from a human reviewer or auto-approval."""

    decision: HITLDecision
    reviewer_id: str = "system"
    modifications: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    reviewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HITLHook(ABC):
    """Abstract interface for Human-in-the-Loop review.

    Subclass this to integrate with teacher dashboards, Slack bots,
    email workflows, etc.
    """

    @abstractmethod
    async def request_review(self, request: HITLRequest) -> HITLResponse:
        """Submit a recommendation for human review."""

    @abstractmethod
    async def should_require_review(
        self, quality_score: float, issues: list[dict[str, Any]]
    ) -> bool:
        """Determine whether this recommendation needs human review."""


class DefaultHITLHook(HITLHook):
    """Auto-approves all recommendations (no human in the loop).

    Used for automated testing and when no human reviewer is configured.
    Optionally logs requests to a list for inspection.
    """

    def __init__(
        self,
        auto_approve_threshold: float = 0.5,
        require_review_on_errors: bool = True,
    ) -> None:
        self.auto_approve_threshold = auto_approve_threshold
        self.require_review_on_errors = require_review_on_errors
        self.review_log: list[HITLRequest] = []

    async def request_review(self, request: HITLRequest) -> HITLResponse:
        """Auto-approve or auto-reject based on quality score."""
        self.review_log.append(request)

        if request.quality_score >= self.auto_approve_threshold:
            logger.info(
                "hitl.auto_approved",
                learner_id=request.learner_id,
                quality_score=request.quality_score,
            )
            return HITLResponse(
                decision=HITLDecision.AUTO_APPROVED,
                reviewer_id="auto",
                reason=f"Quality score {request.quality_score:.2f} >= threshold {self.auto_approve_threshold}",
            )

        logger.warning(
            "hitl.auto_rejected",
            learner_id=request.learner_id,
            quality_score=request.quality_score,
        )
        return HITLResponse(
            decision=HITLDecision.REJECT,
            reviewer_id="auto",
            reason=f"Quality score {request.quality_score:.2f} below threshold {self.auto_approve_threshold}",
        )

    async def should_require_review(
        self, quality_score: float, issues: list[dict[str, Any]]
    ) -> bool:
        """Require review if there are errors or low quality."""
        if self.require_review_on_errors:
            has_errors = any(
                i.get("severity") == "error" for i in issues
            )
            if has_errors:
                return True

        return quality_score < self.auto_approve_threshold
