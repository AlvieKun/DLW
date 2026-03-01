"""EventBus interface and in-memory implementation.

The EventBus is the *nervous system* of the Learning GPS Engine.
All inter-agent messages flow through it, enabling:
• Loose coupling (agents never import each other).
• Observability (every publish is a hook for structured logging / tracing).
• Extensibility (swap to Azure Service Bus, Redis Streams, etc.).

Architecture decision: in-process async for v1.
────────────────────────────────────────────
We use ``asyncio`` queues + callback dispatch.  This is correct for a
single-process FastAPI deployment.  For scale-out, the interface is the
same — only the adapter changes.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from learning_navigator.contracts.messages import MessageEnvelope, MessageType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Type alias for subscribers
MessageHandler = Callable[[MessageEnvelope], Awaitable[Any]]


class EventBus(ABC):
    """Abstract event bus interface.

    Concrete implementations must support:
    • Topic-based publish/subscribe keyed on ``MessageType``.
    • Wildcard subscription to *all* message types.
    • Async dispatch.
    """

    @abstractmethod
    async def publish(self, message: MessageEnvelope) -> None:
        """Publish a message to all subscribers of its ``message_type``."""
        ...

    @abstractmethod
    def subscribe(
        self,
        message_type: MessageType | None,
        handler: MessageHandler,
    ) -> None:
        """Register a handler for a specific message type.

        If ``message_type`` is ``None``, the handler receives *all* messages
        (useful for logging / telemetry middleware).
        """
        ...

    @abstractmethod
    def unsubscribe(
        self,
        message_type: MessageType | None,
        handler: MessageHandler,
    ) -> None:
        """Remove a previously registered handler."""
        ...


class InMemoryEventBus(EventBus):
    """Simple async in-process event bus for local / single-process use.

    Thread-safety note: intended for use within a single ``asyncio`` event
    loop.  For multi-threaded scenarios, add a lock or switch to a
    queue-based adapter.
    """

    def __init__(self) -> None:
        # message_type -> list of handlers
        self._handlers: dict[MessageType | None, list[MessageHandler]] = defaultdict(list)
        # audit log for testing / debugging
        self._history: list[MessageEnvelope] = []
        self._max_history: int = 10_000

    async def publish(self, message: MessageEnvelope) -> None:
        """Dispatch message to matching handlers + wildcard handlers."""
        # Record in history
        if len(self._history) < self._max_history:
            self._history.append(message)

        # Structured log (observability hook)
        logger.info(
            "event_bus.publish",
            message_id=message.message_id,
            message_type=message.message_type.value,
            source=message.source_agent_id,
            target=message.target_agent_id,
            correlation_id=message.correlation_id,
            trace_id=message.provenance.trace_id,
        )

        # Collect handlers: specific + wildcard
        handlers: list[MessageHandler] = [
            *self._handlers.get(message.message_type, []),
            *self._handlers.get(None, []),
        ]

        # Dispatch concurrently
        if handlers:
            results = await asyncio.gather(
                *(h(message) for h in handlers),
                return_exceptions=True,
            )
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        "event_bus.handler_error",
                        handler=handlers[i].__qualname__,
                        error=str(result),
                        message_id=message.message_id,
                    )

    def subscribe(
        self,
        message_type: MessageType | None,
        handler: MessageHandler,
    ) -> None:
        if handler not in self._handlers[message_type]:
            self._handlers[message_type].append(handler)
            logger.debug(
                "event_bus.subscribe",
                message_type=message_type.value if message_type else "*",
                handler=handler.__qualname__,
            )

    def unsubscribe(
        self,
        message_type: MessageType | None,
        handler: MessageHandler,
    ) -> None:
        import contextlib
        with contextlib.suppress(ValueError):
            self._handlers[message_type].remove(handler)

    @property
    def history(self) -> list[MessageEnvelope]:
        """Read-only access to published message history (for testing)."""
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
