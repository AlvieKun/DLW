"""Tests for the in-memory EventBus."""

from __future__ import annotations

import pytest

from learning_navigator.contracts.messages import MessageEnvelope, MessageType
from learning_navigator.engine.event_bus import InMemoryEventBus


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


def _make_msg(mt: MessageType = MessageType.LEARNER_EVENT) -> MessageEnvelope:
    return MessageEnvelope(
        message_type=mt,
        source_agent_id="test-source",
    )


class TestInMemoryEventBus:
    @pytest.mark.asyncio
    async def test_publish_calls_handler(self, bus: InMemoryEventBus) -> None:
        received: list[MessageEnvelope] = []

        async def handler(msg: MessageEnvelope) -> None:
            received.append(msg)

        bus.subscribe(MessageType.LEARNER_EVENT, handler)
        msg = _make_msg()
        await bus.publish(msg)

        assert len(received) == 1
        assert received[0].message_id == msg.message_id

    @pytest.mark.asyncio
    async def test_wildcard_handler(self, bus: InMemoryEventBus) -> None:
        received: list[MessageEnvelope] = []

        async def handler(msg: MessageEnvelope) -> None:
            received.append(msg)

        bus.subscribe(None, handler)  # wildcard
        await bus.publish(_make_msg(MessageType.LEARNER_EVENT))
        await bus.publish(_make_msg(MessageType.AGENT_REQUEST))

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_no_duplicate_subscribe(self, bus: InMemoryEventBus) -> None:
        received: list[MessageEnvelope] = []

        async def handler(msg: MessageEnvelope) -> None:
            received.append(msg)

        bus.subscribe(MessageType.LEARNER_EVENT, handler)
        bus.subscribe(MessageType.LEARNER_EVENT, handler)  # duplicate
        await bus.publish(_make_msg())

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus: InMemoryEventBus) -> None:
        received: list[MessageEnvelope] = []

        async def handler(msg: MessageEnvelope) -> None:
            received.append(msg)

        bus.subscribe(MessageType.LEARNER_EVENT, handler)
        bus.unsubscribe(MessageType.LEARNER_EVENT, handler)
        await bus.publish(_make_msg())

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash(self, bus: InMemoryEventBus) -> None:
        """A failing handler must not prevent other handlers from running."""
        ok_received: list[MessageEnvelope] = []

        async def bad_handler(msg: MessageEnvelope) -> None:
            raise RuntimeError("boom")

        async def ok_handler(msg: MessageEnvelope) -> None:
            ok_received.append(msg)

        bus.subscribe(MessageType.LEARNER_EVENT, bad_handler)
        bus.subscribe(MessageType.LEARNER_EVENT, ok_handler)
        await bus.publish(_make_msg())

        assert len(ok_received) == 1

    @pytest.mark.asyncio
    async def test_history_recording(self, bus: InMemoryEventBus) -> None:
        await bus.publish(_make_msg())
        await bus.publish(_make_msg(MessageType.AGENT_REQUEST))
        assert len(bus.history) == 2

    @pytest.mark.asyncio
    async def test_clear_history(self, bus: InMemoryEventBus) -> None:
        await bus.publish(_make_msg())
        bus.clear_history()
        assert len(bus.history) == 0

    @pytest.mark.asyncio
    async def test_type_routing_isolation(self, bus: InMemoryEventBus) -> None:
        """Handler for type A must not receive type B messages."""
        received_a: list[MessageEnvelope] = []
        received_b: list[MessageEnvelope] = []

        async def handler_a(msg: MessageEnvelope) -> None:
            received_a.append(msg)

        async def handler_b(msg: MessageEnvelope) -> None:
            received_b.append(msg)

        bus.subscribe(MessageType.LEARNER_EVENT, handler_a)
        bus.subscribe(MessageType.AGENT_REQUEST, handler_b)

        await bus.publish(_make_msg(MessageType.LEARNER_EVENT))
        await bus.publish(_make_msg(MessageType.AGENT_REQUEST))

        assert len(received_a) == 1
        assert received_a[0].message_type == MessageType.LEARNER_EVENT
        assert len(received_b) == 1
        assert received_b[0].message_type == MessageType.AGENT_REQUEST
