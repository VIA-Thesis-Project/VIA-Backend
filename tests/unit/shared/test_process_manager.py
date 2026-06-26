"""Unit tests for the Lote 3 evaluation Process Manager."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import (
    EJECUTAR_EVALUACION_VIABILIDAD,
    GENERAR_RECOMENDACION_SOLICITADA,
    INICIAR_EXTRACCION_AGROAMBIENTAL,
)
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    EXTRACCION_FALLIDA,
    RECOMENDACION_FALLIDA,
    RECOMENDACION_GENERADA,
    VECTOR_AGROAMBIENTAL_GENERADO,
)
from via.shared.orchestration.evaluation_process_manager.ports import (
    ParcelGeometrySnapshot,
    RequiredExtractionSpec,
    RequiredVariableForEvaluation,
)
from via.shared.orchestration.evaluation_process_manager.process_manager import (
    PROCESS_MANAGER_CONSUMER,
    EvaluationProcessManager,
)
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel, SagaTransitionModel
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.models import OutboxMessageModel


ROOT = Path(__file__).resolve().parents[3]


class FakeRulebookReadModel:
    """Rulebook read model test double returning a precomputed extraction spec."""

    def __init__(self) -> None:
        """Initialize the fake with no recorded calls."""

        self.calls = []
        self.spec = RequiredExtractionSpec(
            variables=[
                RequiredVariableForEvaluation(
                    variable_name="ndvi",
                    criterion_id="soil_cover",
                    crop_id="cacao",
                    phase_id="initial",
                    dataset_key="sentinel-2",
                    band="B8",
                    unit="index",
                    temporal_resolution="monthly",
                )
            ]
        )

    def get_required_extraction_spec(self, crop_candidates: list[str], temporal_window: dict) -> RequiredExtractionSpec:
        """Return a deterministic required extraction spec."""

        self.calls.append((crop_candidates, temporal_window))
        return self.spec


class FakeParcelGeometryReadModel:
    """Parcel geometry read model test double returning GeoJSON snapshots."""

    def __init__(self, geometry: dict | None = None) -> None:
        """Initialize the fake geometry provider."""

        self.calls = []
        self.geometry = geometry or _polygon()

    def get_parcel_geometry(self, parcel_id) -> ParcelGeometrySnapshot:
        """Return a deterministic parcel geometry snapshot."""

        self.calls.append(parcel_id)
        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry=self.geometry)


class FakeSession:
    """Small synchronous session double for saga transaction tests."""

    def __init__(self) -> None:
        """Create empty stores for ORM objects."""

        self.added = []
        self.sagas = {}
        self.processed = set()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        """Track added models and keep in-memory lookup indexes."""

        self.added.append(model)
        if isinstance(model, EvaluationSagaModel):
            self.sagas[model.id] = model
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))

    def get(self, model_type: type, key: object) -> object | None:
        """Return models by the same keys used by repository code."""

        if model_type is EvaluationSagaModel:
            return self.sagas.get(key)
        if model_type is ProcessedMessageIdModel:
            return key if key in self.processed else None
        return None

    def commit(self) -> None:
        """Record commits performed by the Process Manager."""

        self.commits += 1

    def rollback(self) -> None:
        """Record rollbacks performed by the Process Manager."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record session closure."""

        self.closed = True


def test_start_evaluation_creates_saga_and_outbox_command_atomically() -> None:
    session = FakeSession()
    read_model = FakeRulebookReadModel()
    geometry_read_model = FakeParcelGeometryReadModel()
    manager = EvaluationProcessManager(lambda: session, read_model, geometry_read_model)
    parcel_id = uuid4()
    requested_by = uuid4()
    temporal_window = {"start": "2026-01-01", "end": "2026-03-31"}

    evaluation_id = manager.start_evaluation(parcel_id, requested_by, ["cacao"], temporal_window)

    saga = session.sagas[evaluation_id]
    outbox = _single_added(session, OutboxMessageModel)
    assert read_model.calls == [(["cacao"], temporal_window)]
    assert saga.status == EvaluationSagaStatus.INICIADA.value
    assert outbox.aggregate_type == "EvaluationSaga"
    assert outbox.aggregate_id == evaluation_id
    assert outbox.message_type == INICIAR_EXTRACCION_AGROAMBIENTAL
    assert outbox.correlation_id == evaluation_id
    assert geometry_read_model.calls == [parcel_id]
    assert outbox.payload_json["parcel_geometry"]["type"] == "Polygon"
    assert outbox.payload_json["required_extraction_spec"]["variables"][0]["variable_name"] == "ndvi"
    assert session.commits == 1


def test_vector_generated_moves_to_extraction_completed_and_enqueues_next_command() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.INICIADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        VECTOR_AGROAMBIENTAL_GENERADO,
        {"evaluation_id": str(saga.id), "vector_id": "vector-1"},
        correlation_id=saga.id,
    )

    manager.handle_event(event)

    outbox = _single_added(session, OutboxMessageModel)
    assert saga.status == EvaluationSagaStatus.EXTRACCION_COMPLETADA.value
    assert outbox.message_type == EJECUTAR_EVALUACION_VIABILIDAD
    assert outbox.correlation_id == saga.id
    assert (event.id, PROCESS_MANAGER_CONSUMER) in session.processed


def test_duplicate_event_is_ignored_by_message_id_and_consumer() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.INICIADA.value)
    session.sagas[saga.id] = saga
    event = Message.event(VECTOR_AGROAMBIENTAL_GENERADO, {"evaluation_id": str(saga.id)}, correlation_id=saga.id)
    session.processed.add((event.id, PROCESS_MANAGER_CONSUMER))
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())

    manager.handle_event(event)

    assert saga.status == EvaluationSagaStatus.INICIADA.value
    assert not any(isinstance(model, OutboxMessageModel) for model in session.added)


def test_invalid_transition_is_logged_without_changing_state() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.INICIADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(EVALUACION_VIABILIDAD_COMPLETADA, {"evaluation_id": str(saga.id)}, correlation_id=saga.id)

    manager.handle_event(event)
    transition = _single_added(session, SagaTransitionModel)
    assert saga.status == EvaluationSagaStatus.INICIADA.value
    assert transition.from_status == EvaluationSagaStatus.INICIADA.value
    assert transition.to_status == EvaluationSagaStatus.INICIADA.value
    assert "Invalid transition" in transition.failure_cause
    assert not any(isinstance(model, OutboxMessageModel) for model in session.added)


def test_evaluation_completed_enqueues_recommendation_command_with_saga_correlation() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        EVALUACION_VIABILIDAD_COMPLETADA,
        {"evaluation_id": str(saga.id), "score": 0.82},
        correlation_id=saga.id,
    )

    manager.handle_event(event)

    outbox = _single_added(session, OutboxMessageModel)
    assert saga.status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    assert outbox.message_type == GENERAR_RECOMENDACION_SOLICITADA
    assert outbox.correlation_id == saga.id
    assert outbox.payload_json["evaluation_id"] == str(saga.id)
    assert outbox.payload_json["parcel_id"] == str(saga.parcel_id)
    assert outbox.payload_json["crop_id"] is None
    assert outbox.payload_json["max_fragments"] == 5


def test_evaluation_completed_enqueues_recommendation_for_each_recommendable_crop() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        EVALUACION_VIABILIDAD_COMPLETADA,
        {
            "evaluation_id": str(saga.id),
            "results": [
                {"crop_id": "maiz_amarillo_duro", "viability_category": "VIABLE"},
                {"crop_id": "mandarina_murcott", "viability_category": "CONDICIONAL"},
                {"crop_id": "palta_hass", "viability_category": "NO_VIABLE"},
                {"crop_id": "uva_de_mesa_sweet_globe", "viability_category": "NO_CONCLUYENTE"},
            ],
        },
        correlation_id=saga.id,
    )

    manager.handle_event(event)

    outbox = [model for model in session.added if isinstance(model, OutboxMessageModel)]
    assert saga.status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    assert [item.message_type for item in outbox] == [
        GENERAR_RECOMENDACION_SOLICITADA,
        GENERAR_RECOMENDACION_SOLICITADA,
    ]
    assert [item.payload_json["crop_id"] for item in outbox] == [
        "maiz_amarillo_duro",
        "mandarina_murcott",
    ]
    assert all(item.payload_json["evaluation_id"] == str(saga.id) for item in outbox)


def test_evaluation_completed_preserves_incoming_correlation_id_for_recommendation_command() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    incoming_correlation_id = uuid4()
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        EVALUACION_VIABILIDAD_COMPLETADA,
        {"evaluation_id": str(saga.id)},
        correlation_id=incoming_correlation_id,
    )

    manager.handle_event(event)

    outbox = _single_added(session, OutboxMessageModel)
    assert outbox.message_type == GENERAR_RECOMENDACION_SOLICITADA
    assert outbox.correlation_id == incoming_correlation_id
    assert outbox.payload_json["evaluation_id"] == str(saga.id)
    assert outbox.payload_json["parcel_id"] == str(saga.parcel_id)


def test_recommendation_generated_completes_saga_and_emits_final_event() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EVALUACION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        RECOMENDACION_GENERADA,
        {"evaluation_id": str(saga.id), "recommendation_id": str(uuid4())},
        correlation_id=saga.id,
    )

    manager.handle_event(event)

    outbox = _single_added(session, OutboxMessageModel)
    assert saga.status == EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value
    assert outbox.message_type == "EvaluacionFinalizada"
    assert outbox.correlation_id == saga.id


def test_failure_event_can_move_any_phase_to_failed() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        EXTRACCION_FALLIDA,
        {"evaluation_id": str(saga.id), "failure_cause": "missing imagery"},
        correlation_id=saga.id,
    )

    manager.handle_event(event)
    assert saga.status == EvaluationSagaStatus.FALLIDA.value


def test_recommendation_failure_moves_saga_to_failed() -> None:
    session = FakeSession()
    saga = _saga(EvaluationSagaStatus.EVALUACION_COMPLETADA.value)
    session.sagas[saga.id] = saga
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    event = Message.event(
        RECOMENDACION_FALLIDA,
        {"evaluation_id": str(saga.id), "failure_cause": "no evidence"},
        correlation_id=saga.id,
    )

    manager.handle_event(event)

    assert saga.status == EvaluationSagaStatus.FALLIDA.value


def test_process_manager_does_not_interpret_rulebooks_or_variables() -> None:
    path = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"
    source = path.read_text(encoding="utf-8")
    imports = _imports_from(path)

    forbidden_terms = ["dataset_key", "band", "quality_mask", "membership_fn", "criteria"]
    forbidden_imports = [
        "via.bounded_contexts.rulebook_management.domain",
        "via.bounded_contexts.agroenv_extraction.domain",
        "via.bounded_contexts.parcel_management.domain",
    ]
    assert not any(term in source for term in forbidden_terms)
    assert not any(imported.startswith(tuple(forbidden_imports)) for imported in imports)


def test_process_manager_does_not_import_or_call_recommendation_services() -> None:
    path = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"
    source = path.read_text(encoding="utf-8")
    imports = _imports_from(path)

    assert not any(imported.startswith("via.bounded_contexts.recommendation") for imported in imports)
    assert "RecommendationCommandService" not in source
    assert "RecommendationConsumer" not in source


def test_process_manager_does_not_calculate_recommendation_or_mcda() -> None:
    path = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"
    source = path.read_text(encoding="utf-8")

    forbidden_terms = ["score", "membership", "w_ahp", "w_entropy", "w_hybrid", "gap_value", "rank_position"]
    assert not any(term in source for term in forbidden_terms)


def _saga(status: str) -> EvaluationSagaModel:
    return EvaluationSagaModel(id=uuid4(), parcel_id=uuid4(), requested_by=uuid4(), crop_candidates=["cacao"], temporal_window={}, status=status)


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _single_added(session: FakeSession, model_type: type) -> object:
    matches = [model for model in session.added if isinstance(model, model_type)]
    assert len(matches) == 1
    return matches[0]


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
