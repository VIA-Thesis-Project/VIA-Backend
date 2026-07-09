"""Transactional outbox ORM model."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA
from via.shared.event_bus.message import Message, MessageKind

_created_at_lock = threading.Lock()
_last_created_at: datetime | None = None


def _next_created_at() -> datetime:
    """Return a strictly increasing timestamp for outbox ordering.

    The relay dispatches by (created_at, id). A database-side now() default is
    frozen per transaction, so rows written together would tie and dispatch in
    random UUID order; this per-process monotonic clock keeps write order.
    """

    global _last_created_at
    with _created_at_lock:
        now = datetime.now(timezone.utc)
        if _last_created_at is not None and now <= _last_created_at:
            now = _last_created_at + timedelta(microseconds=1)
        _last_created_at = now
        return now


class OutboxStatus(StrEnum):
    """Lifecycle state of an outbox message."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DISPATCHED = "DISPATCHED"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


class OutboxMessageModel(Base):
    """Stored command/event envelope pending relay to the in-memory bus."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("message_kind IN ('COMMAND', 'EVENT')", name="ck_outbox_message_kind"),
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'DISPATCHED', 'PERMANENT_FAILURE')",
            name="ck_outbox_status",
        ),
        {"schema": TRANSACTIONAL_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_type: Mapped[str] = mapped_column(String(150), nullable=False)
    message_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OutboxStatus.PENDING.value)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @classmethod
    def from_message(
        cls,
        message: Message,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
    ) -> "OutboxMessageModel":
        """Create an outbox row preserving the semantic message id."""

        return cls(
            id=message.id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            message_type=message.type,
            message_kind=message.kind.value,
            payload_json=message.payload,
            correlation_id=message.correlation_id,
            status=OutboxStatus.PENDING.value,
            created_at=_next_created_at(),
        )

    def to_message(self) -> Message:
        """Rebuild the message envelope for publication."""

        return Message(
            id=self.id,
            type=self.message_type,
            kind=MessageKind(self.message_kind),
            payload=self.payload_json,
            created_at=self.created_at,
            correlation_id=self.correlation_id,
        )
