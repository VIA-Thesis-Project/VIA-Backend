"""Base command and event message contracts for VIA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class MessageKind(StrEnum):
    """Supported message kinds routed by the internal bus."""

    COMMAND = "COMMAND"
    EVENT = "EVENT"


@dataclass(frozen=True)
class Message:
    """Immutable command/event envelope used by bus, outbox and consumers."""

    type: str
    kind: MessageKind
    payload: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: UUID | None = None

    @classmethod
    def command(cls, message_type: str, payload: dict[str, Any], correlation_id: UUID | None = None) -> "Message":
        """Create a command message envelope."""

        return cls(type=message_type, kind=MessageKind.COMMAND, payload=payload, correlation_id=correlation_id)

    @classmethod
    def event(cls, message_type: str, payload: dict[str, Any], correlation_id: UUID | None = None) -> "Message":
        """Create an event message envelope."""

        return cls(type=message_type, kind=MessageKind.EVENT, payload=payload, correlation_id=correlation_id)
