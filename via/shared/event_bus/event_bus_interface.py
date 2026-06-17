"""Abstract internal event bus contract."""

from __future__ import annotations

from typing import Protocol

from via.shared.event_bus.message import Message


class MessageHandler(Protocol):
    """Callable object that handles one message synchronously."""

    def __call__(self, message: Message) -> None:
        """Handle a single command or event message."""


class EventBus(Protocol):
    """Synchronous in-process bus interface."""

    def register(self, message_type: str, handler: MessageHandler) -> None:
        """Register a handler for one message type."""

    def publish(self, message: Message) -> None:
        """Publish one message to all registered handlers."""
