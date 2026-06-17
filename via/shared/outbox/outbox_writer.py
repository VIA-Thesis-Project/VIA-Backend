"""Transactional outbox writer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from via.shared.event_bus.message import Message
from via.shared.outbox.models import OutboxMessageModel


class OutboxWriter:
    """Persist messages in the caller-owned SQLAlchemy transaction."""

    def write(self, session: Session, message: Message, aggregate_type: str, aggregate_id: UUID) -> None:
        """Add a message row without committing the active transaction."""

        session.add(OutboxMessageModel.from_message(message, aggregate_type, aggregate_id))
