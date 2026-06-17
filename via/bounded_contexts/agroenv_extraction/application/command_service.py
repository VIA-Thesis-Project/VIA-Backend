"""Command service for Agroenvironmental Extraction."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.agroenv_extraction.application.ports import IExtractionAcl, IExtractionClient, IExtractionRepository, StartExtractionCommand
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin
from via.shared.orchestration.evaluation_process_manager.events import (
    EXTRACCION_FALLIDA,
    VECTOR_AGROAMBIENTAL_GENERADO,
)
from via.shared.outbox.outbox_writer import OutboxWriter


AGROENV_EXTRACTION_CONSUMER = "agroenv-extraction-consumer"
AGGREGATE_TYPE = "AgroenvVector"


class AgroenvExtractionCommandService(IdempotentConsumerMixin):
    """Execute extraction commands with idempotency and transactional outbox."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        extraction_client: IExtractionClient,
        acl: IExtractionAcl,
        repository_factory: Callable[[Session], IExtractionRepository],
        outbox_writer: OutboxWriter | None = None,
    ) -> None:
        """Create the service with injected infrastructure ports."""

        self._session_factory = session_factory
        self._extraction_client = extraction_client
        self._acl = acl
        self._repository_factory = repository_factory
        self._outbox_writer = outbox_writer or OutboxWriter()

    def handle_start_command(self, message: Message, consumer_name: str = AGROENV_EXTRACTION_CONSUMER) -> None:
        """Consume one start extraction command idempotently."""

        command = StartExtractionCommand.from_payload(message.payload)
        with self._transaction() as session:
            if self.is_already_processed(session, message.id, consumer_name):
                return

            try:
                vector = self._acl.build_vector(command, self._extraction_client)
                self._repository_factory(session).save(vector)
                event = Message.event(
                    VECTOR_AGROAMBIENTAL_GENERADO,
                    vector.to_event_payload(),
                    correlation_id=command.evaluation_id,
                )
                self._outbox_writer.write(session, event, AGGREGATE_TYPE, vector.id)
            except Exception as exc:
                failure = _failure_message(command.evaluation_id, command.parcel_id, exc)
                self._outbox_writer.write(session, failure, "EvaluationSaga", command.evaluation_id)

            self.mark_as_processed(session, message.id, consumer_name)

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        """Open a synchronous session and commit or roll back as one unit."""

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _failure_message(evaluation_id: UUID, parcel_id: UUID, exc: Exception) -> Message:
    return Message.event(
        EXTRACCION_FALLIDA,
        {
            "evaluation_id": str(evaluation_id),
            "parcel_id": str(parcel_id),
            "failure_cause": str(exc),
        },
        correlation_id=evaluation_id,
    )
