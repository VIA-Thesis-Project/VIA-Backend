"""Synchronous Process Manager coordinating the evaluation saga."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Iterator
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin
from via.shared.orchestration.evaluation_process_manager.commands import (
    EJECUTAR_EVALUACION_VIABILIDAD,
    GENERAR_RECOMENDACION_SOLICITADA,
    INICIAR_EXTRACCION_AGROAMBIENTAL,
    EjecutarEvaluacionViabilidad,
    GenerarRecomendacionSolicitada,
    IniciarExtraccionAgroambiental,
)
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_FINALIZADA,
    EVALUACION_VIABILIDAD_COMPLETADA,
    FAILURE_EVENTS,
    RECOMENDACION_GENERADA,
    VECTOR_AGROAMBIENTAL_GENERADO,
)
from via.shared.orchestration.evaluation_process_manager.ports import IParcelGeometryReadModelPort, IRulebookReadModelPort
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel
from via.shared.orchestration.evaluation_process_manager.saga_repository import EvaluationSagaRepository
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.outbox_writer import OutboxWriter


PROCESS_MANAGER_CONSUMER = "evaluation-process-manager"
AGGREGATE_TYPE = "EvaluationSaga"


class EvaluationProcessManager(IdempotentConsumerMixin):
    """Coordinate evaluation workflow state and outgoing saga messages."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        rulebook_read_model_port: IRulebookReadModelPort,
        parcel_geometry_read_model_port: IParcelGeometryReadModelPort,
        outbox_writer: OutboxWriter | None = None,
        repository_type: type[EvaluationSagaRepository] = EvaluationSagaRepository,
    ) -> None:
        """Create a synchronous Process Manager with caller-provided adapters."""

        self._session_factory = session_factory
        self._rulebook_read_model_port = rulebook_read_model_port
        self._parcel_geometry_read_model_port = parcel_geometry_read_model_port
        self._outbox_writer = outbox_writer or OutboxWriter()
        self._repository_type = repository_type

    def start_evaluation(
        self,
        parcel_id: UUID,
        requested_by: UUID,
        crop_candidates: list[str],
        temporal_window: dict[str, Any],
    ) -> UUID:
        """Create a saga and enqueue the first extraction command atomically."""

        evaluation_id = uuid4()
        required_extraction_spec = self._rulebook_read_model_port.get_required_extraction_spec(
            crop_candidates,
            temporal_window,
        )
        parcel_geometry = self._parcel_geometry_read_model_port.get_parcel_geometry(parcel_id)
        command = IniciarExtraccionAgroambiental(
            evaluation_id=evaluation_id,
            parcel_id=parcel_id,
            parcel_geometry=_to_payload(parcel_geometry.geometry),
            crop_candidates=crop_candidates,
            temporal_window=temporal_window,
            required_extraction_spec=_to_payload(required_extraction_spec),
        )
        message = Message.command(INICIAR_EXTRACCION_AGROAMBIENTAL, command.to_payload(), correlation_id=evaluation_id)

        with self._transaction() as session:
            repository = self._repository_type(session)
            saga = EvaluationSagaModel(
                id=evaluation_id,
                parcel_id=parcel_id,
                requested_by=requested_by,
                crop_candidates=crop_candidates,
                temporal_window=temporal_window,
                status=EvaluationSagaStatus.INICIADA.value,
            )
            repository.add(saga)
            repository.record_transition(
                evaluation_id,
                None,
                EvaluationSagaStatus.INICIADA.value,
                message.id,
            )
            self._outbox_writer.write(session, message, AGGREGATE_TYPE, evaluation_id)

        return evaluation_id

    def handle_event(self, message: Message, consumer_name: str = PROCESS_MANAGER_CONSUMER) -> None:
        """Handle one saga event idempotently within a single transaction."""

        evaluation_id = _extract_evaluation_id(message)
        with self._transaction() as session:
            if self.is_already_processed(session, message.id, consumer_name):
                return

            repository = self._repository_type(session)
            saga = repository.get(evaluation_id)
            if saga is None:
                self.mark_as_processed(session, message.id, consumer_name)
                return

            outgoing = self._transition_for_event(repository, saga, message)
            for outgoing_message in _as_messages(outgoing):
                self._outbox_writer.write(session, outgoing_message, AGGREGATE_TYPE, evaluation_id)
            self.mark_as_processed(session, message.id, consumer_name)

    def _transition_for_event(
        self,
        repository: EvaluationSagaRepository,
        saga: EvaluationSagaModel,
        message: Message,
    ) -> Message | list[Message] | None:
        """Apply the state transition for a known event and build the next message."""

        evaluation_id = saga.id
        if message.type == VECTOR_AGROAMBIENTAL_GENERADO:
            changed = repository.transition(saga, EvaluationSagaStatus.EXTRACCION_COMPLETADA.value, message.id)
            if not changed:
                return None
            command = EjecutarEvaluacionViabilidad(evaluation_id=evaluation_id, extraction_result=message.payload)
            return Message.command(EJECUTAR_EVALUACION_VIABILIDAD, command.to_payload(), correlation_id=evaluation_id)

        if message.type == EVALUACION_VIABILIDAD_COMPLETADA:
            changed = repository.transition(saga, EvaluationSagaStatus.EVALUACION_COMPLETADA.value, message.id)
            if not changed:
                return None
            return [
                Message.command(
                    GENERAR_RECOMENDACION_SOLICITADA,
                    GenerarRecomendacionSolicitada(
                        evaluation_id=evaluation_id,
                        parcel_id=saga.parcel_id,
                        crop_id=crop_id,
                    ).to_payload(),
                    correlation_id=_outgoing_correlation_id(message, evaluation_id),
                )
                for crop_id in _recommendable_crop_ids(message.payload)
            ]

        if message.type == RECOMENDACION_GENERADA:
            changed = repository.transition(saga, EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value, message.id)
            if changed:
                return Message.event(
                    EVALUACION_FINALIZADA,
                    {"evaluation_id": str(evaluation_id)},
                    correlation_id=_outgoing_correlation_id(message, evaluation_id),
                )
            return None

        if message.type in FAILURE_EVENTS:
            failure_cause = str(message.payload.get("failure_cause") or message.payload.get("error") or message.type)
            repository.transition(saga, EvaluationSagaStatus.FALLIDA.value, message.id, failure_cause=failure_cause)
            return None

        repository.record_invalid_transition(saga, saga.status, message.id, f"Unhandled event {message.type}")
        return None

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


def _extract_evaluation_id(message: Message) -> UUID:
    raw_value = message.payload.get("evaluation_id") or message.correlation_id
    if raw_value is None:
        raise ValueError("Saga message requires evaluation_id or correlation_id")
    return raw_value if isinstance(raw_value, UUID) else UUID(str(raw_value))


def _outgoing_correlation_id(message: Message, fallback_evaluation_id: UUID) -> UUID:
    return message.correlation_id or fallback_evaluation_id


def _recommendable_crop_ids(payload: dict[str, Any]) -> list[str | None]:
    results = payload.get("results")
    if not isinstance(results, list):
        return [None]

    crop_ids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        category = str(result.get("viability_category") or "")
        crop_id = result.get("crop_id")
        if category not in {"VIABLE", "CONDICIONAL"}:
            continue
        if crop_id is None:
            continue
        crop_ids.append(str(crop_id))
    return list(dict.fromkeys(crop_ids))


def _as_messages(value: Message | list[Message] | None) -> list[Message]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_payload(value: Any) -> Any:
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_to_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_to_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_payload(item) for key, item in value.items()}
    return value
