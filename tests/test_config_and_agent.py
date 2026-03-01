"""Tests for configuration and base agent interface."""

from __future__ import annotations

import pytest

from learning_navigator.agents.base import (
    AgentCapability,
    AgentMetadata,
    AgentResponse,
    BaseAgent,
)
from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.infra.config import Environment, Settings, get_settings, reset_settings


class TestSettings:
    def setup_method(self) -> None:
        reset_settings()

    def test_defaults(self) -> None:
        s = Settings()
        assert s.environment == Environment.LOCAL
        assert s.debug is False
        assert s.log_level == "INFO"
        assert s.confidence_threshold == 0.6

    def test_override(self) -> None:
        s = Settings(debug=True, log_level="DEBUG")
        assert s.debug is True
        assert s.log_level == "DEBUG"

    def test_get_settings_caching(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_settings_override(self) -> None:
        s1 = get_settings(debug=True)
        assert s1.debug is True
        reset_settings()


class TestBaseAgent:
    """Verify the agent interface contract via a minimal stub."""

    def _make_stub(self) -> BaseAgent:
        class StubAgent(BaseAgent):
            async def handle(self, message: MessageEnvelope) -> AgentResponse:
                return AgentResponse(
                    source_agent_id=self.agent_id,
                    confidence=0.9,
                    payload={"echo": message.payload},
                    rationale="Stub echo",
                )

        meta = AgentMetadata(
            agent_id="stub-agent",
            display_name="Stub Agent",
            capabilities=[AgentCapability.DIAGNOSE],
            cost_tier=1,
        )
        return StubAgent(metadata=meta)

    def test_metadata(self) -> None:
        agent = self._make_stub()
        assert agent.agent_id == "stub-agent"
        assert AgentCapability.DIAGNOSE in agent.metadata.capabilities

    @pytest.mark.asyncio
    async def test_handle(self) -> None:
        agent = self._make_stub()
        msg = MessageEnvelope(
            message_type=MessageType.AGENT_REQUEST,
            source_agent_id="orchestrator",
            target_agent_id="stub-agent",
            payload={"question": "test"},
        )
        resp = await agent.handle(msg)
        assert resp.confidence == 0.9
        assert resp.payload["echo"]["question"] == "test"

    def test_repr(self) -> None:
        agent = self._make_stub()
        r = repr(agent)
        assert "StubAgent" in r
        assert "stub-agent" in r
        assert "diagnose" in r
