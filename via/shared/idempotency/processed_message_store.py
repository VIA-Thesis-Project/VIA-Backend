"""Processed message tracking for idempotent consumers."""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from via.shared.database.base import Base, TRANSACTIONAL_SCHEMA


class ProcessedMessageIdModel(Base):
    """Message processed marker scoped by consumer name."""

    __tablename__ = "processed_message_ids"
    __table_args__ = (PrimaryKeyConstraint("message_id", "consumer"), {"schema": TRANSACTIONAL_SCHEMA})

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    consumer: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IdempotentConsumerMixin:
    """Reusable checks for at-least-once message consumers."""

    def is_already_processed(self, session: object, message_id: uuid.UUID, consumer_name: str) -> bool:
        """Return True when a consumer has already processed a message."""

        return session.get(ProcessedMessageIdModel, (message_id, consumer_name)) is not None

    def mark_as_processed(self, session: object, message_id: uuid.UUID, consumer_name: str) -> None:
        """Record a processed message without committing the caller transaction."""

        session.add(ProcessedMessageIdModel(message_id=message_id, consumer=consumer_name))
