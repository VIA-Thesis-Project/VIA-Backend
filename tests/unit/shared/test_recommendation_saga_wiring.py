"""Integration tests for Recommendation wiring through the Event Bus."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

from via.bounded_contexts.recommendation.application.command_service import (
    RECOMMENDATION_CONSUMER,
    RecommendationCommandService,
    RecommendationMessageCommandService,
)
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvaluationRecommendationData,
    EvidenceData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import SQLAlchemyRecommendationRepository
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.shared.event_bus import InMemoryEventBus
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_FINALIZADA,
    EVALUACION_VIABILIDAD_COMPLETADA,
    RECOMENDACION_FALLIDA,
    RECOMENDACION_GENERADA,
)
from via.shared.orchestration.evaluation_process_manager.ports import ParcelGeometrySnapshot
from via.shared.orchestration.evaluation_process_manager.process_manager import (
    PROCESS_MANAGER_CONSUMER,
    EvaluationProcessManager,
)
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.event_bus_registration import register_recommendation_saga_flow


ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ID = UUID("00000000-0000-0000-0000-0000000010c2")


def test_evaluation_completed_flows_to_recommendation_and_finishes_saga() -> None:
    session = SagaRecommendationSession()
    saga = _seed_saga(session, EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    correlation_id = uuid4()
    bus = _registered_bus(session)
    event = Message.event(
        EVALUACION_VIABILIDAD_COMPLETADA,
        {"evaluation_id": str(saga.id)},
        correlation_id=correlation_id,
    )

    bus.publish(event)
    recommendation_command = _outbox_message(session, GENERAR_RECOMENDACION_SOLICITADA)
    _relay_all_pending(session, bus)
    generated_event = _outbox_message(session, RECOMENDACION_GENERADA)
    _relay_all_pending(session, bus)
    final_event = _outbox_message(session, EVALUACION_FINALIZADA)

    assert recommendation_command.correlation_id == correlation_id
    assert recommendation_command.payload_json["evaluation_id"] == str(saga.id)
    assert recommendation_command.payload_json["parcel_id"] == str(saga.parcel_id)
    assert generated_event.correlation_id == correlation_id
    assert final_event.correlation_id == correlation_id
    assert saga.status == EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value
    assert len(_recommendations(session)) == 1
    assert session.drafting_provider.external_calls == 0
    assert (event.id, PROCESS_MANAGER_CONSUMER) in session.processed
    assert (recommendation_command.id, RECOMMENDATION_CONSUMER) in session.processed
    assert (generated_event.id, PROCESS_MANAGER_CONSUMER) in session.processed


def test_recommendation_failure_returns_to_process_manager_and_fails_saga() -> None:
    session = SagaRecommendationSession(evaluation_data=EvaluationRecommendationData(EVALUATION_ID, []))
    saga = _seed_saga(session, EvaluationSagaStatus.EXTRACCION_COMPLETADA.value)
    correlation_id = uuid4()
    bus = _registered_bus(session)

    bus.publish(
        Message.event(
            EVALUACION_VIABILIDAD_COMPLETADA,
            {"evaluation_id": str(saga.id)},
            correlation_id=correlation_id,
        )
    )
    _relay_all_pending(session, bus)
    failure_event = _outbox_message(session, RECOMENDACION_FALLIDA)
    _relay_all_pending(session, bus)

    assert failure_event.correlation_id == correlation_id
    assert saga.status == EvaluationSagaStatus.FALLIDA.value
    assert _recommendations(session) == []


def test_duplicate_recommendation_command_does_not_duplicate_effects() -> None:
    session = SagaRecommendationSession()
    _seed_saga(session, EvaluationSagaStatus.EVALUACION_COMPLETADA.value)
    bus = _registered_bus(session)
    message = Message.command(
        GENERAR_RECOMENDACION_SOLICITADA,
        {"evaluation_id": str(EVALUATION_ID), "parcel_id": str(uuid4()), "max_fragments": 5},
        correlation_id=uuid4(),
    )

    bus.publish(message)
    bus.publish(message)

    assert len(_recommendations(session)) == 1
    assert len(_outbox_by_type(session, RECOMENDACION_GENERADA)) == 1
    assert (message.id, RECOMMENDATION_CONSUMER) in session.processed


def test_process_manager_still_has_no_recommendation_or_mcda_logic() -> None:
    path = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"
    source = path.read_text(encoding="utf-8")
    imports = _imports_from(path)

    assert not any(imported.startswith("via.bounded_contexts.recommendation") for imported in imports)
    forbidden_terms = ["RecommendationCommandService", "RecommendationConsumer", "score", "membership", "rank_position"]
    assert not any(term in source for term in forbidden_terms)


class SagaRecommendationSession:
    """In-memory session double for recommendation saga wiring tests."""

    def __init__(self, evaluation_data: EvaluationRecommendationData | None = None) -> None:
        """Create a session with deterministic recommendation fakes."""

        self.added: list[object] = []
        self.sagas: dict[UUID, EvaluationSagaModel] = {}
        self.processed: set[tuple[UUID, str]] = set()
        self.evaluation_data = evaluation_data or _evaluation_data()
        self.drafting_provider = RecordingTemplateProvider()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        """Record ORM-like additions and idempotency markers."""

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
        """Record transaction commit calls."""

        self.commits += 1

    def rollback(self) -> None:
        """Record transaction rollback calls."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record session closure."""

        self.closed = True


class FakeRulebookReadModel:
    """Rulebook read-model double unused by event handling."""

    def get_required_extraction_spec(self, crop_candidates: list[str], temporal_window: dict) -> dict:
        """Return an empty extraction spec."""

        return {}


class FakeParcelGeometryReadModel:
    """Parcel geometry read-model double unused by event handling."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        """Return a valid GeoJSON geometry snapshot."""

        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry={"type": "Polygon", "coordinates": []})


class FakeEvaluationResultsPort:
    """Recommendation evaluation-results port returning precomputed data."""

    def __init__(self, session: SagaRecommendationSession) -> None:
        """Keep the shared session."""

        self._session = session

    def get_results_for_recommendation(self, evaluation_id: UUID) -> EvaluationRecommendationData:
        """Return deterministic already-computed evaluation results."""

        return self._session.evaluation_data


class FakeEvidencePort:
    """Document evidence port returning deterministic fragments."""

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        """Return fake documentary evidence without external calls."""

        return [
            EvidenceData(
                fragment_id=uuid4(),
                document_id=uuid4(),
                text="Manual tecnico cacao",
                crop_tags=[crop_id],
                page_ref=3,
                score=0.91,
            )
        ][:max_fragments]


class RecordingTemplateProvider(TemplateRecommendationDraftingProvider):
    """Template provider recorder that never calls external services."""

    def __init__(self) -> None:
        """Create the recorder."""

        self.external_calls = 0
        self.contexts: list[RecommendationDraftContext] = []

    def draft(self, context: RecommendationDraftContext) -> str:
        """Record the context and delegate to the deterministic template."""

        self.contexts.append(context)
        return super().draft(context)


def _registered_bus(session: SagaRecommendationSession) -> InMemoryEventBus:
    bus = InMemoryEventBus()
    process_manager = EvaluationProcessManager(lambda: session, FakeRulebookReadModel(), FakeParcelGeometryReadModel())

    def service_factory(active_session: SagaRecommendationSession) -> RecommendationCommandService:
        return RecommendationCommandService(
            evaluation_results_port=FakeEvaluationResultsPort(session),
            evidence_port=FakeEvidencePort(),
            drafting_provider=session.drafting_provider,
            repository=SQLAlchemyRecommendationRepository(active_session),  # type: ignore[arg-type]
        )

    recommendation_service = RecommendationMessageCommandService(
        session_factory=lambda: session,  # type: ignore[arg-type]
        service_factory=service_factory,  # type: ignore[arg-type]
    )
    register_recommendation_saga_flow(bus, process_manager, RecommendationConsumer(recommendation_service))
    return bus


def _relay_all_pending(session: SagaRecommendationSession, bus: InMemoryEventBus) -> None:
    worker = RelayWorker(session_factory=lambda: session, event_bus=bus, poll_interval_seconds=1)
    while True:
        pending = [message for message in _outbox(session) if message.status == OutboxStatus.PENDING.value]
        if not pending:
            return
        for message in pending:
            worker._publish_one(message)


def _seed_saga(session: SagaRecommendationSession, status: str) -> EvaluationSagaModel:
    saga = EvaluationSagaModel(
        id=EVALUATION_ID,
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
        status=status,
    )
    session.sagas[saga.id] = saga
    return saga


def _evaluation_data() -> EvaluationRecommendationData:
    return EvaluationRecommendationData(
        evaluation_id=EVALUATION_ID,
        crop_results=[
            CropEvaluationResultData(
                crop_id="cacao",
                score=0.83,
                rank_position=1,
                calc_condition="COMPLETA",
                viability_category="VIABLE",
                gaps=[
                    GapData(
                        criterion_id="rain",
                        phase_id="flowering",
                        most_limiting_period="2026-01",
                        observed_value=5.0,
                        optimal_limit=10.0,
                        gap_value=-5.0,
                    )
                ],
                limiting_factors=[
                    LimitingFactorData(
                        criterion_id="rain",
                        phase_id="flowering",
                        policy="PENALIZE",
                        penalty_factor=0.5,
                        observed_value=5.0,
                        optimal_limit=10.0,
                        membership=0.0,
                        doc_source="manual",
                    )
                ],
            )
        ],
    )


def _outbox(session: SagaRecommendationSession) -> list[OutboxMessageModel]:
    return [model for model in session.added if isinstance(model, OutboxMessageModel)]


def _outbox_by_type(session: SagaRecommendationSession, message_type: str) -> list[OutboxMessageModel]:
    return [message for message in _outbox(session) if message.message_type == message_type]


def _outbox_message(session: SagaRecommendationSession, message_type: str) -> OutboxMessageModel:
    matches = _outbox_by_type(session, message_type)
    assert len(matches) == 1
    return matches[0]


def _recommendations(session: SagaRecommendationSession) -> list[RecommendationModel]:
    return [model for model in session.added if isinstance(model, RecommendationModel)]


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
