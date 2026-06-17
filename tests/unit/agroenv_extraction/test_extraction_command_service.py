"""Unit tests for Agroenvironmental Extraction command service and consumer."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from via.bounded_contexts.agroenv_extraction.application.command_service import (
    AGROENV_EXTRACTION_CONSUMER,
    AgroenvExtractionCommandService,
)
from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionClientResult, ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import INICIAR_EXTRACCION_AGROAMBIENTAL
from via.shared.orchestration.evaluation_process_manager.events import EXTRACCION_FALLIDA, VECTOR_AGROAMBIENTAL_GENERADO
from via.shared.outbox.models import OutboxMessageModel


def test_service_persists_vector_marks_idempotency_and_emits_success_event_in_one_transaction() -> None:
    session = FakeSession()
    service = _service(session, FakeExtractionClient(ExtractionClientResult(0.8, "stub", date(2026, 1, 15))))
    message = _message(fallback_allowed=True)

    service.handle_start_command(message)

    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.saved_vectors) == 1
    assert (message.id, AGROENV_EXTRACTION_CONSUMER) in session.processed
    outbox = _single_outbox(session)
    assert outbox.message_type == VECTOR_AGROAMBIENTAL_GENERADO
    assert outbox.correlation_id == UUID(message.payload["evaluation_id"])
    assert outbox.payload_json["variables"][0]["dataset_key"] == "sentinel-2"
    assert outbox.payload_json["variables"][0]["band"] == "B08"
    assert outbox.payload_json["variables"][0]["unit"] == "index"
    assert outbox.payload_json["variables"][0]["quality_mask"] == {"cloud": "masked"}
    assert outbox.payload_json["variables"][0]["fallback_allowed"] is True


def test_duplicate_message_is_discarded_without_repeating_effects() -> None:
    session = FakeSession()
    message = _message(fallback_allowed=True)
    session.processed.add((message.id, AGROENV_EXTRACTION_CONSUMER))
    service = _service(session, FakeExtractionClient(ExtractionClientResult(0.8, "stub", date(2026, 1, 15))))

    service.handle_start_command(message)

    assert session.saved_vectors == []
    assert not any(isinstance(model, OutboxMessageModel) for model in session.added)


def test_missing_variable_with_fallback_is_persisted_as_missing_and_still_emits_success() -> None:
    session = FakeSession()
    service = _service(session, FakeExtractionClient(None))
    message = _message(fallback_allowed=True)

    service.handle_start_command(message)

    outbox = _single_outbox(session)
    assert outbox.message_type == VECTOR_AGROAMBIENTAL_GENERADO
    assert outbox.payload_json["variables"][0]["status"] == "CRITERIO_FALTANTE"
    assert outbox.payload_json["variables"][0]["value"] is None


def test_missing_variable_without_fallback_emits_failure_and_does_not_save_vector() -> None:
    session = FakeSession()
    service = _service(session, FakeExtractionClient(None))
    message = _message(fallback_allowed=False)

    service.handle_start_command(message)

    outbox = _single_outbox(session)
    assert session.saved_vectors == []
    assert outbox.message_type == EXTRACCION_FALLIDA
    assert outbox.aggregate_type == "EvaluationSaga"
    assert outbox.correlation_id == UUID(message.payload["evaluation_id"])
    assert (message.id, AGROENV_EXTRACTION_CONSUMER) in session.processed


def test_consumer_only_handles_start_extraction_command() -> None:
    service = FakeCommandService()
    consumer = AgroenvExtractionConsumer(service)  # type: ignore[arg-type]
    start_message = _message(fallback_allowed=True)
    ignored_message = Message.command("OtroComando", {})

    consumer.handle(ignored_message)
    consumer.handle(start_message)

    assert service.messages == [start_message]


class FakeExtractionClient:
    """External extraction client test double."""

    def __init__(self, result: ExtractionClientResult | None) -> None:
        self.result = result
        self.requests: list[ExtractionRequest] = []

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        self.requests.append(request)
        return self.result


class FakeRepository:
    """Repository test double saving vectors into the fake session."""

    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    def save(self, vector: object) -> None:
        self._session.saved_vectors.append(vector)


class FakeSession:
    """Session double used to verify atomic side effects."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.processed: set[tuple[object, str]] = set()
        self.saved_vectors: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        self.added.append(model)
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))

    def get(self, model_type: type, key: tuple[object, str]) -> object | None:
        if model_type is ProcessedMessageIdModel and key in self.processed:
            return object()
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeCommandService:
    """Command service double for consumer tests."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def handle_start_command(self, message: Message) -> None:
        self.messages.append(message)


def _service(session: FakeSession, client: FakeExtractionClient) -> AgroenvExtractionCommandService:
    return AgroenvExtractionCommandService(
        session_factory=lambda: session,
        extraction_client=client,
        acl=ExtractionAcl(),
        repository_factory=FakeRepository,
    )


def _message(fallback_allowed: bool) -> Message:
    evaluation_id = uuid4()
    return Message.command(
        INICIAR_EXTRACCION_AGROAMBIENTAL,
        {
            "evaluation_id": str(evaluation_id),
            "parcel_id": str(uuid4()),
            "parcel_geometry": _polygon(),
            "crop_candidates": ["cacao"],
            "temporal_window": {"start": "2026-01-01", "end": "2026-01-31"},
            "required_extraction_spec": {
                "variables": [
                    {
                        "variable_name": "ndvi",
                        "criterion_id": "vigor",
                        "crop_id": "cacao",
                        "phase_id": "floracion",
                        "dataset_key": "sentinel-2",
                        "band": "B08",
                        "unit": "index",
                        "temporal_resolution": "monthly",
                        "spatial_resolution": "10m",
                        "scale": 10,
                        "reducer": "median",
                        "aggregation_method": "mean",
                        "quality_mask": {"cloud": "masked"},
                        "fallback_allowed": fallback_allowed,
                        "temporal_periods": [{"period_key": "2026-01", "temporal_weight": 1.0}],
                    }
                ]
            },
        },
        correlation_id=evaluation_id,
    )


def _single_outbox(session: FakeSession) -> OutboxMessageModel:
    matches = [model for model in session.added if isinstance(model, OutboxMessageModel)]
    assert len(matches) == 1
    return matches[0]


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }
