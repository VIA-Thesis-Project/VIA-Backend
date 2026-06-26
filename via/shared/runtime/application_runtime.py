"""Application runtime composition for Event Bus, Relay Worker and saga handlers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.application.ports import (
    ExtractionClientResult,
    ExtractionRequest,
    IExtractionClient,
)
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.recommendation.application.command_service import RecommendationCommandService, RecommendationMessageCommandService
from via.bounded_contexts.recommendation.application.ports import (
    EvidenceData,
    GapData,
    IDocumentEvidencePort,
    IRecommendationDraftingProvider,
)
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import (
    GeminiApiConfig,
    GeminiApiDraftingProvider,
    LocalHttpLlmConfig,
    LocalHttpLlmDraftingProvider,
    VertexGemmaConfig,
    VertexGemmaDraftingProvider,
)
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import SQLAlchemyRecommendationRepository
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.bounded_contexts.viability_evaluation.application.command_service import (
    McdaRuntimeSettings,
    ViabilityEvaluationCommandService,
)
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
from via.config import Settings, get_settings
from via.shared.database.session import get_session_factory
from via.shared.event_bus.in_memory_event_bus import InMemoryEventBus
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import (
    SqlAlchemyAgroenvVectorBridge,
    SqlAlchemyEvaluationResultsBridge,
    SqlAlchemyParcelGeometryBridge,
    SqlAlchemyRulebookEvaluationBridge,
    SqlAlchemyRulebookReadModelBridge,
)
from via.shared.runtime.event_bus_registration import register_recommendation_saga_flow


@dataclass(frozen=True)
class ApplicationRuntime:
    """Runtime objects shared by the FastAPI app and background relay."""

    event_bus: InMemoryEventBus
    relay_worker: RelayWorker
    process_manager: EvaluationProcessManager
    recommendation_consumer: RecommendationConsumer
    recommendation_drafting_provider: IRecommendationDraftingProvider
    extraction_consumer: AgroenvExtractionConsumer
    evaluation_consumer: ViabilityEvaluationConsumer


def configure_application_runtime(
    *,
    session_factory: sessionmaker[Session] | None = None,
    event_bus: InMemoryEventBus | None = None,
    process_manager: EvaluationProcessManager | None = None,
    recommendation_consumer: RecommendationConsumer | None = None,
    extraction_consumer: AgroenvExtractionConsumer | None = None,
    evaluation_consumer: ViabilityEvaluationConsumer | None = None,
    settings: Settings | None = None,
) -> ApplicationRuntime:
    """Compose the real in-process bus wiring used by the monolith runtime."""

    resolved_session_factory = session_factory or get_session_factory()
    resolved_settings = settings or get_settings()
    resolved_event_bus = event_bus or InMemoryEventBus()
    resolved_process_manager = process_manager or EvaluationProcessManager(
        resolved_session_factory,
        SqlAlchemyRulebookReadModelBridge(resolved_session_factory),
        SqlAlchemyParcelGeometryBridge(resolved_session_factory),
    )
    drafting_provider = build_recommendation_drafting_provider(resolved_settings)
    resolved_recommendation_consumer = recommendation_consumer or build_recommendation_consumer(
        resolved_session_factory,
        drafting_provider,
        provider_name=resolved_settings.llm_drafting_provider,
    )
    resolved_extraction_consumer = extraction_consumer or _extraction_consumer(resolved_session_factory, resolved_settings)
    resolved_evaluation_consumer = evaluation_consumer or _evaluation_consumer(
        resolved_session_factory,
        resolved_settings,
    )
    register_recommendation_saga_flow(
        resolved_event_bus,
        resolved_process_manager,
        resolved_recommendation_consumer,
        extraction_consumer=resolved_extraction_consumer,
        evaluation_consumer=resolved_evaluation_consumer,
    )
    relay_worker = RelayWorker(session_factory=resolved_session_factory, event_bus=resolved_event_bus)
    return ApplicationRuntime(
        event_bus=resolved_event_bus,
        relay_worker=relay_worker,
        process_manager=resolved_process_manager,
        recommendation_consumer=resolved_recommendation_consumer,
        recommendation_drafting_provider=drafting_provider,
        extraction_consumer=resolved_extraction_consumer,
        evaluation_consumer=resolved_evaluation_consumer,
    )


# ─── Remaining runtime placeholder adapters ───────────────────────────────────


class RuntimeGeeExtractionClient(IExtractionClient):
    """Runtime placeholder — raises when GEE extraction is attempted.

    Reason: Google Earth Engine credentials are not available in this runtime.
    Replace with a real GEE client when credentials and extraction infra are configured.
    """

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        """Fail clearly instead of calling Google Earth Engine."""

        raise RuntimeError("GEE extraction client is not configured for this runtime")


class RuntimeDocumentEvidencePort(IDocumentEvidencePort):
    """Runtime document-evidence placeholder — returns empty evidence list.

    Reason: IDocumentEvidencePort.search_evidence() requires an external embedding
    provider (IEmbeddingProvider) to generate query vectors. No embedding service
    is configured in this runtime; calling one would be an external service call.
    Replace with a real DocumentEvidenceAdapter when an embedding provider is wired.
    """

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        """Return empty evidence until an embedding provider is connected."""

        return []


# ─── Consumer factory helpers ──────────────────────────────────────────────────


def build_recommendation_consumer(
    session_factory: sessionmaker[Session],
    drafting_provider: IRecommendationDraftingProvider,
    provider_name: str = "template",
) -> RecommendationConsumer:
    """Build a fully wired RecommendationConsumer for use in relay workers and tests."""

    eval_results_bridge = SqlAlchemyEvaluationResultsBridge(session_factory)

    def service_factory(session: Session) -> RecommendationCommandService:
        return RecommendationCommandService(
            evaluation_results_port=eval_results_bridge,
            evidence_port=RuntimeDocumentEvidencePort(),
            drafting_provider=drafting_provider,
            repository=SQLAlchemyRecommendationRepository(session, provider=provider_name),
        )

    return RecommendationConsumer(
        RecommendationMessageCommandService(
            session_factory=session_factory,
            service_factory=service_factory,
        )
    )


_recommendation_consumer = build_recommendation_consumer


def _extraction_consumer(session_factory: sessionmaker[Session], settings: Settings) -> AgroenvExtractionConsumer:
    """Build the extraction consumer, using the real GEE client when GEE is enabled."""

    if settings.gee_enabled:
        from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient
        extraction_client: IExtractionClient = GeeExtractionClient(settings=settings)
    else:
        extraction_client = RuntimeGeeExtractionClient()

    service = AgroenvExtractionCommandService(
        session_factory=session_factory,
        extraction_client=extraction_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


def _evaluation_consumer(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> ViabilityEvaluationConsumer:
    """Build the evaluation consumer with real rulebook, vector and repository adapters."""

    service = ViabilityEvaluationCommandService(
        session_factory=session_factory,
        rulebook_port=SqlAlchemyRulebookEvaluationBridge(session_factory),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=McdaRuntimeSettings.from_settings(settings),
    )
    return ViabilityEvaluationConsumer(service)


def build_recommendation_drafting_provider(settings: Settings) -> IRecommendationDraftingProvider:
    """Select the Recommendation drafting provider from validated runtime settings."""

    if settings.llm_drafting_provider == "template":
        return TemplateRecommendationDraftingProvider()
    if settings.llm_drafting_provider == "vertex_gemma":
        return VertexGemmaDraftingProvider(
            VertexGemmaConfig(
                project_id=str(settings.vertex_ai_project_id),
                location=str(settings.vertex_ai_location),
                endpoint_id=str(settings.vertex_ai_endpoint_id),
                model=str(settings.llm_model),
                timeout_seconds=settings.vertex_ai_timeout_seconds,
                max_prompt_chars=settings.llm_max_prompt_chars,
            )
        )
    if settings.llm_drafting_provider == "gemini_api":
        return GeminiApiDraftingProvider(
            GeminiApiConfig(
                api_key=str(settings.gemini_api_key),
                model=str(settings.gemini_api_model),
                base_url=settings.gemini_api_base_url,
                timeout_seconds=settings.gemini_api_timeout_seconds,
                max_prompt_chars=settings.llm_max_prompt_chars,
                max_output_tokens=settings.gemini_api_max_output_tokens,
            )
        )
    if settings.llm_drafting_provider == "openai_file_search":
        from via.bounded_contexts.recommendation.infrastructure.openai_file_search_provider import (
            OpenAIFileSearchConfig,
            OpenAIFileSearchDraftingProvider,
        )

        return OpenAIFileSearchDraftingProvider(
            OpenAIFileSearchConfig(
                api_key=str(settings.openai_api_key),
                model=str(settings.openai_rag_model),
                max_num_results=settings.openai_file_search_max_results,
                prompt_version=settings.openai_file_search_prompt_version,
                timeout_seconds=settings.llm_timeout_seconds,
                vector_store_map=_build_vector_store_map(settings),
            )
        )
    return LocalHttpLlmDraftingProvider(
        LocalHttpLlmConfig(
            endpoint=str(settings.llm_local_http_endpoint),
            model=str(settings.llm_model),
            timeout_seconds=settings.llm_timeout_seconds,
            max_prompt_chars=settings.llm_max_prompt_chars,
        )
    )


def _build_vector_store_map(settings: Settings) -> dict[str, str]:
    """Build crop_id -> vector_store_id map from validated settings."""
    candidates: dict[str, str | None] = {
        "maiz_amarillo_duro": settings.openai_vector_store_maiz_amarillo_duro_id,
        "palta_hass": settings.openai_vector_store_palta_hass_id,
        "mandarina_murcott": settings.openai_vector_store_mandarina_murcott_id,
        "maracuya_criolla_amarilla": settings.openai_vector_store_maracuya_criolla_amarilla_id,
        "uva_de_mesa_sweet_globe": settings.openai_vector_store_uva_de_mesa_sweet_globe_id,
    }
    return {crop_id: vs_id for crop_id, vs_id in candidates.items() if vs_id}
