"""Synchronous in-memory event bus implementation."""

from __future__ import annotations

from collections import defaultdict

from via.shared.event_bus.event_bus_interface import MessageHandler
from via.shared.event_bus.message import Message


class InMemoryEventBus:
    """Route messages to registered handlers in the current process."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)

    def register(self, message_type: str, handler: MessageHandler) -> None:
        """Register a synchronous handler for a message type."""

        self._handlers[message_type].append(handler)

    def publish(self, message: Message) -> None:
        """Publish a message synchronously to registered handlers."""

        for handler in list(self._handlers.get(message.type, [])):
            handler(message)
