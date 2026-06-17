"""Unit tests for Recommendation 10B consumer and outbox flow."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

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
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import SQLAlchemyRecommendationRepository
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.orchestration.evaluation_process_manager.events import RECOMENDACION_FALLIDA, RECOMENDACION_GENERADA
from via.shared.outbox.models import OutboxMessageModel


def test_consumer_ignores_messages_that_are_not_generate_recommendation() -> None:
    service = FakeMessageService()
    consumer = RecommendationConsumer(service)  # type: ignore[arg-type]
    ignored = Message.command("OtroComando", {})
    handled = _message()

    consumer.handle(ignored)
    consumer.handle(handled)

    assert service.messages == [handled]


def test_consumer_processes_generar_recomendacion_solicitada_and_persists_recommendation() -> None:
    session = FakeSession()
    message = _message()
    service = _message_service(session)

    service.handle_generation_requested(message)

    recommendations = _recommendations(session)
    assert len(recommendations) == 1
    assert recommendations[0].evaluation_id == UUID(_EVALUATION_ID)
    assert recommendations[0].crop_id == "cacao"
    assert session.commits == 1
    assert session.rollbacks == 0


def test_success_publishes_recomendacion_generada_with_correlation_id() -> None:
    session = FakeSession()
    message = _message()

    _message_service(session).handle_generation_requested(message)

    outbox = _outbox(session)
    assert len(outbox) == 1
    assert outbox[0].message_type == RECOMENDACION_GENERADA
    assert outbox[0].correlation_id == UUID(_EVALUATION_ID)
    assert outbox[0].payload_json["evaluation_id"] == _EVALUATION_ID
    assert outbox[0].payload_json["crop_id"] == "cacao"
    assert outbox[0].payload_json["fragment_ids"] == [str(_FRAGMENT_ID)]


def test_controlled_generation_failure_publishes_recomendacion_fallida() -> None:
    session = FakeSession()
    empty_data = EvaluationRecommendationData(UUID(_EVALUATION_ID), [])
    service = _message_service(session, evaluation_port=FakeEvaluationResultsPort(empty_data))

    service.handle_generation_requested(_message())

    assert _recommendations(session) == []
    outbox = _outbox(session)
    assert len(outbox) == 1
    assert outbox[0].message_type == RECOMENDACION_FALLIDA
    assert outbox[0].correlation_id == UUID(_EVALUATION_ID)
    assert "evaluation results are required" in outbox[0].payload_json["failure_cause"]
    assert (outbox[0].id, RECOMMENDATION_CONSUMER) not in session.processed


def test_duplicate_message_does_not_repeat_recommendation_or_outbox() -> None:
    session = FakeSession()
    message = _message()
    session.processed.add((message.id, RECOMMENDATION_CONSUMER))

    _message_service(session).handle_generation_requested(message)

    assert _recommendations(session) == []
    assert _outbox(session) == []
    assert session.commits == 1


def test_idempotency_marker_is_written_in_same_transaction_after_effects() -> None:
    session = FakeSession()
    message = _message()

    _message_service(session).handle_generation_requested(message)

    assert (message.id, RECOMMENDATION_CONSUMER) in session.processed
    assert session.add_order == ["recommendation", RECOMENDACION_GENERADA, "processed"]


def test_template_provider_does_not_call_external_services_or_recalculate_scores() -> None:
    session = FakeSession()
    provider = RecordingTemplateProvider()

    _message_service(session, drafting_provider=provider).handle_generation_requested(_message())

    assert provider.external_calls == 0
    assert provider.last_context is not None
    assert provider.last_context.crop_result.score == 0.82
    assert provider.last_context.crop_result.rank_position == 1
    assert provider.last_context.crop_result.gaps[0].gap_value == -4.0
    assert _recommendations(session)[0].text.startswith("Recomendacion para cacao: score=0.82")


def test_technical_errors_are_not_hidden_as_failure_events() -> None:
    session = FakeSession()

    with pytest.raises(RuntimeError, match="provider down"):
        _message_service(session, drafting_provider=FailingDraftingProvider()).handle_generation_requested(_message())

    assert _outbox(session) == []
    assert _recommendations(session) == []
    assert session.processed == set()
    assert session.rollbacks == 1
    assert session.commits == 0


class FakeMessageService:
    """Message command service double for consumer tests."""

    def __init__(self) -> None:
        """Create an empty message recorder."""

        self.messages: list[Message] = []

    def handle_generation_requested(self, message: Message) -> None:
        """Record handled messages."""

        self.messages.append(message)


class FakeEvaluationResultsPort:
    """Fake evaluation results port."""

    def __init__(self, data: EvaluationRecommendationData) -> None:
        """Create the fake with prepared data."""

        self.data = data

    def get_results_for_recommendation(self, evaluation_id: UUID) -> EvaluationRecommendationData:
        """Return precomputed evaluation data."""

        return self.data


class FakeEvidencePort:
    """Fake document evidence port."""

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        """Return deterministic evidence."""

        return [
            EvidenceData(
                fragment_id=_FRAGMENT_ID,
                document_id=uuid4(),
                text="Manual tecnico cacao",
                crop_tags=[crop_id],
                page_ref=2,
                score=0.9,
            )
        ][:max_fragments]


class RecordingTemplateProvider(TemplateRecommendationDraftingProvider):
    """Template provider that records context and never calls external services."""

    def __init__(self) -> None:
        """Create a provider recorder."""

        self.external_calls = 0
        self.last_context: RecommendationDraftContext | None = None

    def draft(self, context: RecommendationDraftContext) -> str:
        """Record context and draft deterministically."""

        self.last_context = context
        return super().draft(context)


class FailingDraftingProvider:
    """Provider double for technical errors."""

    def draft(self, context: RecommendationDraftContext) -> str:
        """Raise a programming/infrastructure-style failure."""

        raise RuntimeError("provider down")


class FakeSession:
    """Session double for transactional recommendation tests."""

    def __init__(self) -> None:
        """Create an empty fake session."""

        self.added: list[object] = []
        self.add_order: list[str] = []
        self.processed: set[tuple[object, str]] = set()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        """Record ORM additions and idempotency markers."""

        self.added.append(model)
        if isinstance(model, RecommendationModel):
            self.add_order.append("recommendation")
        if isinstance(model, OutboxMessageModel):
            self.add_order.append(model.message_type)
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))
            self.add_order.append("processed")

    def get(self, model_type: type, key: tuple[object, str]) -> object | None:
        """Return an idempotency marker if present."""

        if model_type is ProcessedMessageIdModel and key in self.processed:
            return object()
        return None

    def commit(self) -> None:
        """Record a commit."""

        self.commits += 1

    def rollback(self) -> None:
        """Record a rollback."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record session close."""

        self.closed = True


_EVALUATION_ID = "00000000-0000-0000-0000-000000000321"
_FRAGMENT_ID = UUID("00000000-0000-0000-0000-000000000654")


def _message() -> Message:
    evaluation_id = UUID(_EVALUATION_ID)
    return Message.command(
        GENERAR_RECOMENDACION_SOLICITADA,
        {"evaluation_id": _EVALUATION_ID, "crop_id": "cacao", "max_fragments": 5},
        correlation_id=evaluation_id,
    )


def _message_service(
    session: FakeSession,
    evaluation_port: FakeEvaluationResultsPort | None = None,
    drafting_provider: object | None = None,
) -> RecommendationMessageCommandService:
    def service_factory(active_session: FakeSession) -> RecommendationCommandService:
        return RecommendationCommandService(
            evaluation_results_port=evaluation_port or FakeEvaluationResultsPort(_evaluation_data()),
            evidence_port=FakeEvidencePort(),
            drafting_provider=drafting_provider or RecordingTemplateProvider(),  # type: ignore[arg-type]
            repository=SQLAlchemyRecommendationRepository(active_session),  # type: ignore[arg-type]
        )

    return RecommendationMessageCommandService(
        session_factory=lambda: session,  # type: ignore[arg-type]
        service_factory=service_factory,  # type: ignore[arg-type]
    )


def _evaluation_data() -> EvaluationRecommendationData:
    return EvaluationRecommendationData(
        evaluation_id=UUID(_EVALUATION_ID),
        crop_results=[
            CropEvaluationResultData(
                crop_id="cacao",
                score=0.82,
                rank_position=1,
                calc_condition="DEFINITIVO",
                viability_category="VIABLE",
                gaps=[
                    GapData(
                        criterion_id="agua",
                        phase_id="floracion",
                        most_limiting_period="p2",
                        observed_value=18.0,
                        optimal_limit=22.0,
                        gap_value=-4.0,
                    )
                ],
                limiting_factors=[
                    LimitingFactorData(
                        criterion_id="temperatura",
                        phase_id="establecimiento",
                        policy="PENALIZE",
                        penalty_factor=0.5,
                        observed_value=35.0,
                        optimal_limit=30.0,
                        membership=0.0,
                        doc_source="manual",
                    )
                ],
            )
        ],
    )


def _outbox(session: FakeSession) -> list[OutboxMessageModel]:
    return [model for model in session.added if isinstance(model, OutboxMessageModel)]


def _recommendations(session: FakeSession) -> list[RecommendationModel]:
    return [model for model in session.added if isinstance(model, RecommendationModel)]
