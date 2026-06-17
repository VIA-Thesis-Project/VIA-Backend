"""Application service for supported recommendation generation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvidenceData,
    IDocumentEvidencePort,
    IEvaluationResultsPort,
    IRecommendationDraftingProvider,
    IRecommendationRepository,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.domain.evidence import DocumentaryEvidence
from via.bounded_contexts.recommendation.domain.recommendation import Recommendation
from via.bounded_contexts.recommendation.domain.section import RecommendationSection
from via.bounded_contexts.recommendation.domain.value_objects import (
    RecommendationDomainError,
    RecommendationSectionType,
)
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.orchestration.evaluation_process_manager.events import RECOMENDACION_FALLIDA, RECOMENDACION_GENERADA
from via.shared.outbox.outbox_writer import OutboxWriter


RECOMMENDATION_CONSUMER = "recommendation-consumer"
AGGREGATE_TYPE = "Recommendation"


@dataclass(frozen=True)
class GenerateRecommendationCommand:
    """Command to draft a supported recommendation for one evaluation."""

    evaluation_id: UUID
    crop_id: str | None = None
    max_fragments: int = 5
    persist: bool = True

    @classmethod
    def from_payload(cls, payload: dict) -> "GenerateRecommendationCommand":
        """Deserialize a GenerarRecomendacionSolicitada payload."""

        return cls(
            evaluation_id=UUID(str(payload["evaluation_id"])),
            crop_id=payload.get("crop_id"),
            max_fragments=int(payload.get("max_fragments", 5)),
            persist=True,
        )


class RecommendationCommandService:
    """Create recommendations from existing evaluation results and evidence."""

    def __init__(
        self,
        evaluation_results_port: IEvaluationResultsPort,
        evidence_port: IDocumentEvidencePort,
        drafting_provider: IRecommendationDraftingProvider,
        repository: IRecommendationRepository | None = None,
    ) -> None:
        """Create the service with injectable ports."""

        self._evaluation_results_port = evaluation_results_port
        self._evidence_port = evidence_port
        self._drafting_provider = drafting_provider
        self._repository = repository

    def generate(self, command: GenerateRecommendationCommand) -> Recommendation:
        """Draft and optionally persist a recommendation."""

        if command.max_fragments <= 0:
            raise RecommendationDomainError("max_fragments must be positive")
        evaluation = self._evaluation_results_port.get_results_for_recommendation(command.evaluation_id)
        crop_result = _select_crop_result(evaluation.crop_results, command.crop_id)
        evidence = self._evidence_port.search_evidence(
            crop_id=crop_result.crop_id,
            gaps=crop_result.gaps,
            max_fragments=command.max_fragments,
        )
        context = RecommendationDraftContext(
            evaluation_id=command.evaluation_id,
            crop_result=crop_result,
            evidence=evidence,
        )
        text = self._drafting_provider.draft(context)
        recommendation = Recommendation(
            evaluation_id=command.evaluation_id,
            crop_id=crop_result.crop_id,
            text=text,
            sections=_build_sections(crop_result, evidence),
            evidence=[_evidence_to_domain(item) for item in evidence],
        )
        if command.persist and self._repository is not None:
            self._repository.save(recommendation)
        return recommendation


class RecommendationMessageCommandService(IdempotentConsumerMixin):
    """Consume recommendation generation messages idempotently."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        service_factory: Callable[[Session], RecommendationCommandService],
        outbox_writer: OutboxWriter | None = None,
    ) -> None:
        """Create the message service with transactional dependencies."""

        self._session_factory = session_factory
        self._service_factory = service_factory
        self._outbox_writer = outbox_writer or OutboxWriter()

    def handle_generation_requested(self, message: Message, consumer_name: str = RECOMMENDATION_CONSUMER) -> None:
        """Handle one GenerarRecomendacionSolicitada command."""

        if message.type != GENERAR_RECOMENDACION_SOLICITADA:
            return
        command = GenerateRecommendationCommand.from_payload(message.payload)
        with self._transaction() as session:
            if self.is_already_processed(session, message.id, consumer_name):
                return

            try:
                recommendation = self._service_factory(session).generate(command)
                self._outbox_writer.write(
                    session,
                    _recommendation_generated_event(
                        recommendation,
                        correlation_id=_outgoing_correlation_id(message, command.evaluation_id),
                    ),
                    AGGREGATE_TYPE,
                    recommendation.id,
                )
            except RecommendationDomainError as exc:
                self._outbox_writer.write(
                    session,
                    _recommendation_failed_event(
                        command.evaluation_id,
                        str(exc),
                        correlation_id=_outgoing_correlation_id(message, command.evaluation_id),
                    ),
                    "EvaluationSaga",
                    command.evaluation_id,
                )

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


def _select_crop_result(
    crop_results: list[CropEvaluationResultData],
    crop_id: str | None,
) -> CropEvaluationResultData:
    if not crop_results:
        raise RecommendationDomainError("evaluation results are required")
    if crop_id is not None:
        for result in crop_results:
            if result.crop_id == crop_id:
                return result
        raise RecommendationDomainError(f"crop result not found: {crop_id}")

    if len(crop_results) == 1:
        return crop_results[0]

    top_ranked = [result for result in crop_results if result.rank_position == 1]
    if not top_ranked:
        raise RecommendationDomainError("rank_position=1 is required when crop_id is not provided")
    if len(top_ranked) > 1:
        raise RecommendationDomainError("ambiguous rank_position=1 results when crop_id is not provided")
    return top_ranked[0]


def _build_sections(
    crop_result: CropEvaluationResultData,
    evidence: list[EvidenceData],
) -> list[RecommendationSection]:
    return [
        RecommendationSection(
            section_type=RecommendationSectionType.SUMMARY,
            title="Resumen",
            content=f"Recomendacion sustentada para {crop_result.crop_id}.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.VIABILITY_RESULT,
            title="Resultado de viabilidad",
            content=(
                f"Score={crop_result.score}; condicion={crop_result.calc_condition}; "
                f"categoria={crop_result.viability_category}; ranking={crop_result.rank_position}."
            ),
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.AGRONOMIC_GAPS,
            title="Brechas agronomicas",
            content="; ".join(
                f"{gap.criterion_id}/{gap.phase_id}: {gap.gap_value}"
                for gap in crop_result.gaps
            )
            or "No se recibieron brechas agronomicas.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.LIMITING_FACTORS,
            title="Factores limitantes",
            content="; ".join(
                f"{factor.criterion_id}/{factor.phase_id}: {factor.policy}"
                for factor in crop_result.limiting_factors
            )
            or "No se recibieron factores limitantes.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.DOCUMENTARY_EVIDENCE,
            title="Evidencia documental",
            content="; ".join(str(item.fragment_id) for item in evidence)
            or "No se encontro evidencia documental suficiente.",
        ),
    ]


def _evidence_to_domain(item: EvidenceData) -> DocumentaryEvidence:
    return DocumentaryEvidence(
        fragment_id=item.fragment_id,
        document_id=item.document_id,
        text=item.text,
        crop_tags=item.crop_tags,
        page_ref=item.page_ref,
        score=item.score,
    )


def _recommendation_generated_event(recommendation: Recommendation, correlation_id: UUID) -> Message:
    return Message.event(
        RECOMENDACION_GENERADA,
        {
            "recommendation_id": str(recommendation.id),
            "evaluation_id": str(recommendation.evaluation_id),
            "crop_id": recommendation.crop_id,
            "fragment_ids": [str(fragment_id) for fragment_id in recommendation.fragment_ids],
            "text": recommendation.text,
        },
        correlation_id=correlation_id,
    )


def _recommendation_failed_event(evaluation_id: UUID, failure_cause: str, correlation_id: UUID) -> Message:
    return Message.event(
        RECOMENDACION_FALLIDA,
        {
            "evaluation_id": str(evaluation_id),
            "failure_cause": failure_cause,
        },
        correlation_id=correlation_id,
    )


def _outgoing_correlation_id(message: Message, fallback_evaluation_id: UUID) -> UUID:
    return message.correlation_id or fallback_evaluation_id
