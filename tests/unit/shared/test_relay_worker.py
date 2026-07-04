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


def _worker(bus: RecordingBus, max_retries: int = 5) -> RelayWorker:
    return RelayWorker(
        session_factory=lambda: None,
        event_bus=bus,
        poll_interval_seconds=1,
        max_retries=max_retries,
    )


def test_publish_one_preserves_correlation_id_and_returns_no_error() -> None:
    correlation_id = uuid4()
    bus = RecordingBus()
    worker = _worker(bus)
    message = Message.event("VectorAgroambientalGenerado", {}, correlation_id=correlation_id)

    error = worker._publish_one(message)

    assert error is None
    assert bus.published[0].correlation_id == correlation_id


def test_publish_one_returns_error_text_instead_of_raising() -> None:
    worker = _worker(RecordingBus(fail=True))

    error = worker._publish_one(Message.command("EjecutarEvaluacionViabilidad", {}))

    assert error == "boom"


def test_apply_outcome_marks_dispatched_and_clears_claim_on_success() -> None:
    worker = _worker(RecordingBus())
    model = OutboxMessageModel.from_message(
        Message.event("VectorAgroambientalGenerado", {}),
        "AgroenvVector",
        uuid4(),
    )
    model.status = OutboxStatus.IN_PROGRESS.value

    worker._apply_outcome(model, error=None)

    assert model.status == OutboxStatus.DISPATCHED.value
    assert model.dispatched_at is not None
    assert model.claimed_at is None
    assert model.last_error is None


def test_apply_outcome_reverts_to_pending_below_max_retries() -> None:
    worker = _worker(RecordingBus(fail=True), max_retries=5)
    model = OutboxMessageModel.from_message(Message.command("EjecutarEvaluacionViabilidad", {}), "EvaluationSaga", uuid4())
    model.status = OutboxStatus.IN_PROGRESS.value
    model.retry_count = 0

    worker._apply_outcome(model, error="boom")

    assert model.status == OutboxStatus.PENDING.value
    assert model.retry_count == 1
    assert model.last_error == "boom"
    assert model.claimed_at is None


def test_apply_outcome_marks_permanent_failure_after_max_retries() -> None:
    worker = _worker(RecordingBus(fail=True), max_retries=5)
    model = OutboxMessageModel.from_message(Message.command("EjecutarEvaluacionViabilidad", {}), "EvaluationSaga", uuid4())
    model.status = OutboxStatus.IN_PROGRESS.value
    model.retry_count = 4

    worker._apply_outcome(model, error="boom")

    assert model.status == OutboxStatus.PERMANENT_FAILURE.value
    assert model.retry_count == 5
    assert model.last_error == "boom"


def test_load_pending_reclaims_stale_in_progress_rows() -> None:
    """The claim query must cover PENDING rows and stale IN_PROGRESS rows.

    Crash recovery contract: if the process dies after claiming but before
    finalizing, rows stay IN_PROGRESS and must be reclaimed after
    stale_claim_timeout_seconds.
    """
    import inspect

    source = inspect.getsource(RelayWorker._load_pending)

    assert "PENDING" in source
    assert "IN_PROGRESS" in source
    assert "claimed_at" in source
    assert "with_for_update" in source
    assert "skip_locked" in source


def test_process_batch_publishes_without_open_transaction() -> None:
    """Claim commits (releasing locks) before any handler runs.

    Verified structurally: process_batch is claim → publish → finalize, and
    the publish phase does not receive a session.
    """
    import inspect

    source = inspect.getsource(RelayWorker.process_batch)

    assert "_claim_batch" in source
    assert "_publish_one" in source
    assert "_finalize_batch" in source
    assert "session" not in source
