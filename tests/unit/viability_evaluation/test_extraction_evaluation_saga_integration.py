"""Integration tests for the extraction-to-evaluation saga handoff."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

from via.bounded_contexts.viability_evaluation.application.command_service import (
    McdaRuntimeSettings,
    ViabilityEvaluationCommandService,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableData,
    AgroenvVectorData,
    EvaluationCriterionSpec,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import EJECUTAR_EVALUACION_VIABILIDAD
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    EVALUACION_VIABILIDAD_FALLIDA,
    VECTOR_AGROAMBIENTAL_GENERADO,
    VECTOR_BRECHAS_GENERADO,
)
from via.shared.orchestration.evaluation_process_manager.ports import ParcelGeometrySnapshot
from via.shared.orchestration.evaluation_process_manager.process_manager import (
    PROCESS_MANAGER_CONSUMER,
    EvaluationProcessManager,
)
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel, SagaTransitionModel
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.models import OutboxMessageModel


ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ID = UUID("00000000-0000-0000-0000-00000000800d")


def test_vector_generated_flows_to_evaluation_and_completes_saga() -> None:
    session = SagaIntegrationSession()
    saga = _seed_saga(session, EvaluationSagaStatus.INICIADA.value)
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    vector_event = Message.event(
        VECTOR_AGROAMBIENTAL_GENERADO,
        {
            "evaluation_id": str(saga.id),
            "crop_candidates": ["cacao"],
            "temporal_window": {"start": "2026-01-01", "end": "2026-02-28"},
            "vector_id": "vector-1",
        },
        correlation_id=saga.id,
    )

    manager.handle_event(vector_event)

    execute_command = _outbox_message(session, EJECUTAR_EVALUACION_VIABILIDAD).to_message()
    assert saga.status == EvaluationSagaStatus.EXTRACCION_COMPLETADA.value
    assert execute_command.correlation_id == saga.id
    assert execute_command.payload["evaluation_id"] == str(saga.id)

    consumer = ViabilityEvaluationConsumer(_evaluation_service(session))
    consumer.handle(execute_command)

    completed_event = _outbox_message(session, EVALUACION_VIABILIDAD_COMPLETADA).to_message()
    gaps_event = _outbox_message(session, VECTOR_BRECHAS_GENERADO).to_message()
    assert len(session.saved_evaluations) == 1
    assert completed_event.correlation_id == saga.id
    assert gaps_event.correlation_id == saga.id
    assert gaps_event.payload["gaps"] != []
    assert gaps_event.payload["gaps"][0]["most_limiting_period"] == "2026-01"
    assert gaps_event.payload["gaps"][0]["gap_value"] == -5.0

    manager.handle_event(completed_event)

    assert saga.status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    assert (vector_event.id, PROCESS_MANAGER_CONSUMER) in session.processed
    assert (execute_command.id, "viability-evaluation-consumer") in session.processed
    assert (completed_event.id, PROCESS_MANAGER_CONSUMER) in session.processed
    assert all(message.correlation_id == saga.id for message in _outbox(session))


def test_evaluation_failure_event_moves_saga_to_failed() -> None:
    session = SagaIntegrationSession()
    saga = _seed_saga(session, EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())
    command = Message.command(
        EJECUTAR_EVALUACION_VIABILIDAD,
        {"evaluation_id": str(saga.id), "extraction_result": {"crop_candidates": ["cacao"]}},
        correlation_id=saga.id,
    )

    ViabilityEvaluationConsumer(_evaluation_service(session, agroenv_port=FailingAgroenvVectorPort())).handle(command)

    failure_event = _outbox_message(session, EVALUACION_VIABILIDAD_FALLIDA).to_message()
    assert failure_event.correlation_id == saga.id
    assert failure_event.payload["evaluation_id"] == str(saga.id)

    manager.handle_event(failure_event)

    assert saga.status == EvaluationSagaStatus.FALLIDA.value


def test_duplicate_execute_command_does_not_repeat_evaluation_effects() -> None:
    session = SagaIntegrationSession()
    _seed_saga(session, EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    consumer = ViabilityEvaluationConsumer(_evaluation_service(session))
    command = Message.command(
        EJECUTAR_EVALUACION_VIABILIDAD,
        {"evaluation_id": str(EVALUATION_ID), "extraction_result": {"crop_candidates": ["cacao"]}},
        correlation_id=EVALUATION_ID,
    )

    consumer.handle(command)
    consumer.handle(command)

    assert len(session.saved_evaluations) == 1
    assert len(_outbox_by_type(session, EVALUACION_VIABILIDAD_COMPLETADA)) == 1
    assert len(_outbox_by_type(session, VECTOR_BRECHAS_GENERADO)) == 1
    assert (command.id, "viability-evaluation-consumer") in session.processed


def test_process_manager_does_not_import_or_calculate_mcda() -> None:
    path = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"
    imports = _imports_from(path)
    source = path.read_text(encoding="utf-8")

    forbidden_imports = [
        "via.bounded_contexts.viability_evaluation.domain",
        "via.bounded_contexts.agroenv_extraction.domain",
        "via.bounded_contexts.rulebook_management.domain",
    ]
    assert not any(imported.startswith(tuple(forbidden_imports)) for imported in imports)
    assert "TrapezoidalMembershipFunction" not in source
    assert "CriticalPolicyService" not in source
    assert "GapCalculationService" not in source
    assert "membership_fn" not in source


class SagaIntegrationSession:
    """In-memory session double shared by saga and evaluation services."""

    def __init__(self) -> None:
        """Create empty stores for the integration flow."""

        self.added: list[object] = []
        self.sagas: dict[UUID, EvaluationSagaModel] = {}
        self.processed: set[tuple[UUID, str]] = set()
        self.saved_evaluations: list[Evaluation] = []
        self.saved_versions: list[dict[str, int]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        """Track ORM-like models added by repositories and idempotency stores."""

        self.added.append(model)
        if isinstance(model, EvaluationSagaModel):
            self.sagas[model.id] = model
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))

    def get(self, model_type: type, key: object) -> object | None:
        """Resolve saga and idempotency lookups used by production code."""

        if model_type is EvaluationSagaModel:
            return self.sagas.get(key)
        if model_type is ProcessedMessageIdModel:
            return object() if key in self.processed else None
        return None

    def commit(self) -> None:
        """Record transaction commits."""

        self.commits += 1

    def rollback(self) -> None:
        """Record transaction rollbacks."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record session closure."""

        self.closed = True


class FakeRulebookReadModel:
    """Unused Process Manager read-model double for event handling."""

    def get_required_extraction_spec(self, crop_candidates: list[str], temporal_window: dict) -> dict:
        """Return an empty extraction spec when start_evaluation is not under test."""

        return {}


class FakeParcelGeometryReadModel:
    """Parcel geometry read model double for saga integration tests."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        """Return a valid GeoJSON parcel snapshot."""

        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry=_polygon())


class FakeRulebookEvaluationPort:
    """Rulebook ACL double returning evaluation-facing rulebook data."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        """Return one criterion whose first period produces a real deficit gap."""

        return RulebookEvaluationData(
            crop_id=crop_id,
            rulebook_id=uuid4(),
            version=3,
            criteria=[
                EvaluationCriterionSpec(
                    criterion_id="rain",
                    crop_id=crop_id,
                    phase_id="flowering",
                    variable_name="rain",
                    w_ahp=1.0,
                    phase_weight=1.0,
                    temporal_periods=[
                        {"period_key": "2026-01", "temporal_weight": 0.5},
                        {"period_key": "2026-02", "temporal_weight": 0.5},
                    ],
                    membership_fn={"type": "TRAPEZOIDAL", "a": 0.0, "b": 10.0, "c": 20.0, "d": 30.0},
                    critical_policy="PENALIZE",
                    penalty_factor=0.5,
                    doc_source="manual",
                )
            ],
        )


class FakeAgroenvVectorPort:
    """Agroenvironmental-vector ACL double with two observed periods."""

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Return a deterministic vector for the evaluation command."""

        return AgroenvVectorData(
            evaluation_id=evaluation_id,
            parcel_id=uuid4(),
            variables=[
                _variable(evaluation_id, "2026-01", 5.0),
                _variable(evaluation_id, "2026-02", 15.0),
            ],
        )


class FailingAgroenvVectorPort:
    """Agroenvironmental-vector ACL double that triggers evaluation failure."""

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Raise a deterministic adapter failure."""

        raise RuntimeError("vector not available")


class FakeEvaluationRepository:
    """Evaluation repository double recording persisted aggregates."""

    def __init__(self, session: SagaIntegrationSession) -> None:
        """Keep the shared session for assertions."""

        self._session = session

    def save(self, evaluation: Evaluation, rulebook_versions: dict[str, int]) -> None:
        """Record aggregate persistence without recalculating MCDA."""

        self._session.saved_evaluations.append(evaluation)
        self._session.saved_versions.append(rulebook_versions)


def _evaluation_service(
    session: SagaIntegrationSession,
    agroenv_port: object | None = None,
) -> ViabilityEvaluationCommandService:
    return ViabilityEvaluationCommandService(
        session_factory=lambda: session,
        rulebook_port=FakeRulebookEvaluationPort(),
        agroenv_vector_port=agroenv_port or FakeAgroenvVectorPort(),
        repository_factory=FakeEvaluationRepository,
        settings=McdaRuntimeSettings(
            mcda_alpha=0.7,
            mcda_min_temporal_series_length=3,
            mcda_entropy_min_divergence=1e-9,
            mcda_viable_threshold=0.70,
            mcda_condicional_threshold=0.40,
            mcda_penalize_epsilon=0.01,
        ),
    )


def _seed_saga(session: SagaIntegrationSession, status: str) -> EvaluationSagaModel:
    saga = EvaluationSagaModel(
        id=EVALUATION_ID,
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={"start": "2026-01-01", "end": "2026-02-28"},
        status=status,
    )
    session.sagas[saga.id] = saga
    return saga


def _variable(evaluation_id: UUID, period_key: str, value: float) -> AgroenvVariableData:
    return AgroenvVariableData(
        variable_name="rain",
        criterion_id="rain",
        crop_id="cacao",
        phase_id="flowering",
        period_key=period_key,
        value=value,
        unit="mm",
        status="OK",
        dataset_key="gee",
        band="rain",
        source=f"stub:{evaluation_id}",
    )


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _outbox(session: SagaIntegrationSession) -> list[OutboxMessageModel]:
    return [model for model in session.added if isinstance(model, OutboxMessageModel)]


def _outbox_by_type(session: SagaIntegrationSession, message_type: str) -> list[OutboxMessageModel]:
    return [message for message in _outbox(session) if message.message_type == message_type]


def _outbox_message(session: SagaIntegrationSession, message_type: str) -> OutboxMessageModel:
    matches = _outbox_by_type(session, message_type)
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
