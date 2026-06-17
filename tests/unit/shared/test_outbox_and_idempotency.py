"""Unit tests for outbox writer and idempotency helpers."""

from __future__ import annotations

from uuid import uuid4

from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin, ProcessedMessageIdModel
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus
from via.shared.outbox.outbox_writer import OutboxWriter


class FakeSession:
    """Small session double for transaction ownership tests."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.keys: set[tuple[object, tuple[object, ...]]] = set()
        self.commits = 0

    def add(self, model: object) -> None:
        self.added.append(model)

    def get(self, model: object, key: tuple[object, ...]) -> object | None:
        return object() if (model, key) in self.keys else None

    def commit(self) -> None:
        self.commits += 1


def test_outbox_model_preserves_message_id_and_correlation_id() -> None:
    correlation_id = uuid4()
    aggregate_id = uuid4()
    message = Message.event("EvaluacionCompletada", {"evaluation_id": str(correlation_id)}, correlation_id=correlation_id)

    model = OutboxMessageModel.from_message(message, "EvaluationSaga", aggregate_id)

    assert model.id == message.id
    assert model.aggregate_type == "EvaluationSaga"
    assert model.aggregate_id == aggregate_id
    assert model.message_type == "EvaluacionCompletada"
    assert model.message_kind == "EVENT"
    assert model.payload_json == {"evaluation_id": str(correlation_id)}
    assert model.correlation_id == correlation_id
    assert model.status == OutboxStatus.PENDING.value
    assert model.to_message().correlation_id == correlation_id


def test_outbox_writer_does_not_commit_caller_transaction() -> None:
    session = FakeSession()
    aggregate_id = uuid4()

    OutboxWriter().write(session, Message.command("IniciarExtraccionAgroambiental", {}), "EvaluationSaga", aggregate_id)

    assert len(session.added) == 1
    assert isinstance(session.added[0], OutboxMessageModel)
    assert session.added[0].aggregate_id == aggregate_id
    assert session.commits == 0


def test_idempotency_is_scoped_by_message_and_consumer() -> None:
    session = FakeSession()
    mixin = IdempotentConsumerMixin()
    message_id = uuid4()

    assert not mixin.is_already_processed(session, message_id, "consumer-a")
    session.keys.add((ProcessedMessageIdModel, (message_id, "consumer-a")))

    assert mixin.is_already_processed(session, message_id, "consumer-a")
    assert not mixin.is_already_processed(session, message_id, "consumer-b")

    mixin.mark_as_processed(session, message_id, "consumer-b")
    assert isinstance(session.added[-1], ProcessedMessageIdModel)
    assert session.commits == 0
