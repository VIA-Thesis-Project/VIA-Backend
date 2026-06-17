"""Unit tests for synchronous relay worker behavior."""

from __future__ import annotations

from uuid import uuid4

from via.shared.event_bus.message import Message
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus
from via.shared.outbox.relay_worker import RelayWorker


class RecordingBus:
    """Event bus double that records published messages."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[Message] = []

    def publish(self, message: Message) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.published.append(message)


def test_publish_one_marks_dispatched_and_preserves_correlation_id() -> None:
    correlation_id = uuid4()
    bus = RecordingBus()
    worker = RelayWorker(session_factory=lambda: None, event_bus=bus, poll_interval_seconds=1)
    model = OutboxMessageModel.from_message(
        Message.event("VectorAgroambientalGenerado", {}, correlation_id=correlation_id),
        "AgroenvVector",
        uuid4(),
    )

    worker._publish_one(model)

    assert model.status == OutboxStatus.DISPATCHED.value
    assert model.dispatched_at is not None
    assert bus.published[0].correlation_id == correlation_id


def test_publish_one_marks_permanent_failure_after_max_retries() -> None:
    worker = RelayWorker(session_factory=lambda: None, event_bus=RecordingBus(fail=True), poll_interval_seconds=1, max_retries=5)
    model = OutboxMessageModel.from_message(Message.command("EjecutarEvaluacionViabilidad", {}), "EvaluationSaga", uuid4())
    model.retry_count = 4

    worker._publish_one(model)

    assert model.status == OutboxStatus.PERMANENT_FAILURE.value
    assert model.retry_count == 5
    assert model.last_error == "boom"
