"""Base agent interface — the contract every agent must satisfy.

Design notes
────────────
• ``BaseAgent`` is abstract.  Concrete agents implement ``handle()``.
• Every agent exposes ``capabilities`` metadata so the orchestrator and
  adaptive router can make routing decisions without coupling to impl.
• ``confidence`` on responses enables dynamic weighting (Differentiator D3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from learning_navigator.contracts.messages import MessageEnvelope


class AgentCapability(str, Enum):
    """Tags describing what an agent can do — used by adaptive routing."""

    DIAGNOSE = "diagnose"
    PLAN = "plan"
    EVALUATE = "evaluate"
    MOTIVATE = "motivate"
    DETECT_DRIFT = "detect_drift"
    DECAY_ANALYSIS = "decay_analysis"
    GENERATIVE_REPLAY = "generative_replay"
    SKILL_STATE = "skill_state"
    BEHAVIOR_ANALYSIS = "behavior_analysis"
    TIME_OPTIMIZATION = "time_optimization"
    REFLECTION = "reflection"
    DEBATE_PROPOSE = "debate_propose"
    DEBATE_CRITIQUE = "debate_critique"
    DEBATE_ARBITRATE = "debate_arbitrate"
    RAG_RETRIEVE = "rag_retrieve"
    CHECK = "check"


class AgentMetadata(BaseModel):
    """Static metadata exposed by every agent for registry / routing."""

    agent_id: str
    display_name: str
    capabilities: list[AgentCapability]
    version: str = "0.1.0"
    cost_tier: int = Field(
        default=1,
        ge=1,
        le=5,
        description="1=cheap/fast, 5=expensive/slow — used by cost-aware routing.",
    )
    description: str = ""


class AgentResponse(BaseModel):
    """Standardised wrapper returned by ``BaseAgent.handle()``."""

    source_agent_id: str
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent self-assessed confidence; used for weighting.",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    errors: list[str] = Field(default_factory=list)
    telemetry: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary perf / tracing data emitted by the agent.",
    )


class BaseAgent(ABC):
    """Abstract base for all agents in the Learning Navigator system."""

    def __init__(self, metadata: AgentMetadata) -> None:
        self._metadata = metadata

    @property
    def agent_id(self) -> str:
        return self._metadata.agent_id

    @property
    def metadata(self) -> AgentMetadata:
        return self._metadata

    @abstractmethod
    async def handle(self, message: MessageEnvelope) -> AgentResponse:
        """Process an incoming message and return a structured response.

        Implementors MUST:
        • Validate the payload against their expected schema.
        • Set ``confidence`` honestly (calibration tracked by orchestrator).
        • Populate ``rationale`` for explainability.
        • Log telemetry via the structured logger.
        """
        ...

    def __repr__(self) -> str:
        caps = ", ".join(c.value for c in self._metadata.capabilities)
        return f"<{self.__class__.__name__} id={self.agent_id} caps=[{caps}]>"
