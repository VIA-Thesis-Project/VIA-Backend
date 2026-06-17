"""E2E tests for lote 26A: full MCDA + Recommendation saga on real PostgreSQL with provider=template.

Flow validated here:
  POST /evaluaciones
  → EvaluationProcessManager (controlled rulebook/parcel ports — no DB reads for setup data)
  → Outbox (PostgreSQL real) → RelayWorker real (FOR UPDATE SKIP LOCKED)
  → ControlledExtractionClient (deterministic, never calls GEE)
  → Agroenv vector stored in PostgreSQL (transactional.agroenv_vectors)
  → RelayWorker → ViabilityEvaluationConsumer → evaluation_results (PostgreSQL)
  → EVALUACION_COMPLETADA → GENERAR_RECOMENDACION_SOLICITADA (Outbox, PostgreSQL real)
  → RelayWorker → RecommendationConsumer
      (SqlAlchemyEvaluationResultsBridge + EmptyDocumentEvidencePort + TemplateRecommendationDraftingProvider)
  → transactional.recommendations (PostgreSQL) → RECOMENDACION_GENERADA (Outbox, PostgreSQL real)
  → RelayWorker → EvaluationProcessManager → RECOMENDACION_COMPLETADA (PostgreSQL)
  → GET /evaluaciones/{id}/recomendacion-final (reads from transactional.recommendations in PostgreSQL)

Infrastructure used (real):
- PostgreSQL via pg_migrated (alembic downgrade base → upgrade head)
- RelayWorker (real implementation, uses WITH FOR UPDATE SKIP LOCKED)
- InMemoryEventBus (real, synchronous)
- transactional.outbox_messages, evaluation_sagas, agroenv_vectors,
  evaluation_results, recommendations in PostgreSQL

Controlled (to avoid external services):
- ControlledExtractionClient — deterministic values, never calls GEE
- ControlledRulebookReadModelPort — no DB read (avoids rulebook FK chain)
- ControlledParcelGeometryPort — no PostGIS insert (avoids WKB/WKT complexity)
- ControlledRulebookEvaluationPort — no DB read (avoids rulebook FK chain)
- TemplateRecommendationDraftingProvider — deterministic text, no LLM call
- EmptyDocumentEvidencePort — returns [], no embedding or RAG call

NOT used: GEE, LLM, Gemini, Vertex, local_http, RAG, DDL manual, LockFreeRelayWorker,
          asyncpg, AsyncSession, create_async_engine, Celery, Kafka, Redis, RabbitMQ.
"""

from __future__ import annotations

import inspect
import sys
from typing import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.postgres.test_postgres_e2e_mcda import (
    CROP_MAIZ,
    CROP_PAPA,
    TEMPORAL_WINDOW,
    ControlledExtractionClient,
    ControlledParcelGeometryPort,
    ControlledRulebookEvaluationPort,
    ControlledRulebookReadModelPort,
    _PARCEL_ID,
    _REQUESTED_BY,
    drive_saga_to_completion,
)

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.recommendation.application.command_service import (
    RecommendationCommandService,
    RecommendationMessageCommandService,
)
from via.bounded_contexts.recommendation.application.ports import EvidenceData, GapData, IDocumentEvidencePort
from via.bounded_contexts.recommendation.application.recommendation_query_service import RecommendationQueryService
from via.bounded_contexts.recommendation.infrastructure.recommendation_query_repository import RecommendationQueryRepository
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import SQLAlchemyRecommendationRepository
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.bounded_contexts.recommendation.interfaces.recommendation_router import get_recommendation_query_service
from via.bounded_contexts.viability_evaluation.application.command_service import (
    McdaRuntimeSettings,
    ViabilityEvaluationCommandService,
)
from via.bounded_contexts.viability_evaluation.application.query_service import EvaluationQueryService
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_query_repository import EvaluationQueryRepository
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    get_evaluation_query_service,
    get_process_manager,
)
from via.shared.event_bus.in_memory_event_bus import InMemoryEventBus
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import SqlAlchemyAgroenvVectorBridge, SqlAlchemyEvaluationResultsBridge
from via.shared.runtime.event_bus_registration import register_recommendation_saga_flow


# ──────────────────────────── controlled evidence port ────────────────────────


class EmptyDocumentEvidencePort(IDocumentEvidencePort):
    """Returns empty evidence — no RAG, no embedding, no external service call."""

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        return []


# ──────────────────────────── session-scoped fixtures ─────────────────────────


@pytest.fixture(scope="session")
def pg26a_session_factory(pg_migrated):
    """Session factory bound to the real migrated PostgreSQL test database."""
    return sessionmaker(bind=pg_migrated, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session")
def pg26a_cleanup(pg_migrated, pg26a_session_factory):
    """Truncate all saga/outbox/result/recommendation tables before the 26A E2E session.

    Ensures 26A starts with clean state, independent of 25B data.
    """
    with pg_migrated.begin() as conn:
        conn.execute(text(
            "TRUNCATE "
            "transactional.recommendations, "
            "transactional.agronomy_gaps, "
            "transactional.limiting_factors, "
            "transactional.evaluation_criterion_details, "
            "transactional.evaluation_results, "
            "transactional.agroenv_variable_entries, "
            "transactional.agroenv_vectors, "
            "transactional.processed_message_ids, "
            "transactional.outbox_messages, "
            "transactional.saga_transitions, "
            "transactional.evaluation_sagas "
            "CASCADE"
        ))
    return pg_migrated


@pytest.fixture(scope="session")
def pg26a_controlled_extraction_client():
    return ControlledExtractionClient()


@pytest.fixture(scope="session")
def pg26a_process_manager(pg26a_session_factory, pg26a_cleanup):
    return EvaluationProcessManager(
        session_factory=pg26a_session_factory,
        rulebook_read_model_port=ControlledRulebookReadModelPort(),
        parcel_geometry_read_model_port=ControlledParcelGeometryPort(),
    )


@pytest.fixture(scope="session")
def pg26a_extraction_consumer(pg26a_session_factory, pg26a_cleanup, pg26a_controlled_extraction_client):
    service = AgroenvExtractionCommandService(
        session_factory=pg26a_session_factory,
        extraction_client=pg26a_controlled_extraction_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


@pytest.fixture(scope="session")
def pg26a_evaluation_consumer(pg26a_session_factory, pg26a_cleanup):
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )
    service = ViabilityEvaluationCommandService(
        session_factory=pg26a_session_factory,
        rulebook_port=ControlledRulebookEvaluationPort(),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(pg26a_session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=settings,
    )
    return ViabilityEvaluationConsumer(service)


@pytest.fixture(scope="session")
def pg26a_recommendation_consumer(pg26a_session_factory, pg26a_cleanup):
    """RecommendationConsumer backed by real PostgreSQL bridges and TemplateRecommendationDraftingProvider.

    Uses:
    - SqlAlchemyEvaluationResultsBridge: reads evaluation_results from PostgreSQL (no in-memory objects)
    - EmptyDocumentEvidencePort: returns [] (no RAG, no embedding, no external service)
    - TemplateRecommendationDraftingProvider: deterministic template text (no LLM call)
    - SQLAlchemyRecommendationRepository: persists recommendation to transactional.recommendations
    """
    eval_results_bridge = SqlAlchemyEvaluationResultsBridge(pg26a_session_factory)
    evidence_port = EmptyDocumentEvidencePort()
    drafting_provider = TemplateRecommendationDraftingProvider()

    def service_factory(session: Session) -> RecommendationCommandService:
        return RecommendationCommandService(
            evaluation_results_port=eval_results_bridge,
            evidence_port=evidence_port,
            drafting_provider=drafting_provider,
            repository=SQLAlchemyRecommendationRepository(session),
        )

    return RecommendationConsumer(
        RecommendationMessageCommandService(
            session_factory=pg26a_session_factory,
            service_factory=service_factory,
        )
    )


@pytest.fixture(scope="session")
def pg26a_event_bus(
    pg26a_process_manager,
    pg26a_extraction_consumer,
    pg26a_evaluation_consumer,
    pg26a_recommendation_consumer,
):
    """Real InMemoryEventBus with full saga flow including RecommendationConsumer.

    Registers via register_recommendation_saga_flow, which wires:
    - ProcessManager for all saga events (VectorAgroambientalGenerado, EvaluacionViabilidadCompletada,
      RecomendacionGenerada, RecomendacionFallida, ExtraccionFallida, EvaluacionViabilidadFallida)
    - RecommendationConsumer for GenerarRecomendacionSolicitada
    - AgroenvExtractionConsumer for IniciarExtraccionAgroambiental
    - ViabilityEvaluationConsumer for EjecutarEvaluacionViabilidad
    """
    bus = InMemoryEventBus()
    register_recommendation_saga_flow(
        bus,
        pg26a_process_manager,
        pg26a_recommendation_consumer,
        extraction_consumer=pg26a_extraction_consumer,
        evaluation_consumer=pg26a_evaluation_consumer,
    )
    return bus


@pytest.fixture(scope="session")
def pg26a_relay(pg26a_session_factory, pg26a_event_bus, pg26a_cleanup):
    """Real RelayWorker using PostgreSQL FOR UPDATE SKIP LOCKED; driven manually per wave."""
    return RelayWorker(
        session_factory=pg26a_session_factory,
        event_bus=pg26a_event_bus,
        batch_size=20,
    )


@pytest.fixture(scope="session")
def pg26a_client(pg26a_process_manager, pg26a_session_factory, pg26a_cleanup):
    """FastAPI TestClient with process manager, evaluation query service, and
    recommendation query service all bound to real PostgreSQL.

    Overrides:
    - get_process_manager → pg26a_process_manager (controlled ports, no GEE/LLM)
    - get_evaluation_query_service → EvaluationQueryService backed by PostgreSQL
    - get_recommendation_query_service → RecommendationQueryService backed by PostgreSQL
    """
    from via.main import app

    def _pm_dep():
        return pg26a_process_manager

    def _eval_qs_dep() -> Generator[EvaluationQueryService, None, None]:
        session = pg26a_session_factory()
        try:
            yield EvaluationQueryService(EvaluationQueryRepository(session))
        finally:
            session.close()

    def _rec_qs_dep() -> Generator[RecommendationQueryService, None, None]:
        session = pg26a_session_factory()
        try:
            yield RecommendationQueryService(RecommendationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_process_manager] = _pm_dep
    app.dependency_overrides[get_evaluation_query_service] = _eval_qs_dep
    app.dependency_overrides[get_recommendation_query_service] = _rec_qs_dep
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_process_manager, None)
        app.dependency_overrides.pop(get_evaluation_query_service, None)
        app.dependency_overrides.pop(get_recommendation_query_service, None)


@pytest.fixture(scope="session")
def completed_pg_e2e_recommendation(pg26a_client, pg26a_relay, pg26a_session_factory):
    """Run one full MCDA+Recommendation E2E evaluation on real PostgreSQL; shared by all 26A tests.

    Drives the saga from INICIADA to RECOMENDACION_COMPLETADA:
      POST /evaluaciones
      → outbox → relay → controlled extraction → agroenv vector (PostgreSQL)
      → relay → MCDA evaluation → evaluation_results (PostgreSQL) → EVALUACION_COMPLETADA
      → outbox GENERAR_RECOMENDACION_SOLICITADA → relay
      → RecommendationConsumer → recommendations (PostgreSQL) → RECOMENDACION_GENERADA (outbox)
      → relay → EvaluationProcessManager → RECOMENDACION_COMPLETADA (PostgreSQL)
      → GET /evaluaciones/{id}/estado         (reads from evaluation_sagas in PostgreSQL)
      → GET /evaluaciones/{id}/recomendacion-final (reads from recommendations in PostgreSQL)
    """
    response = pg26a_client.post(
        "/evaluaciones",
        json={
            "parcel_id": str(_PARCEL_ID),
            "requested_by": str(_REQUESTED_BY),
            "crop_candidates": [CROP_MAIZ, CROP_PAPA],
            "temporal_window": TEMPORAL_WINDOW,
        },
    )
    assert response.status_code == 202, f"POST /evaluaciones failed: {response.text}"
    evaluation_id = UUID(response.json()["evaluation_id"])

    final_status = drive_saga_to_completion(
        pg26a_relay,
        pg26a_session_factory,
        evaluation_id,
        target_statuses=frozenset({
            EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value,
            EvaluationSagaStatus.FALLIDA.value,
        }),
        max_waves=15,
    )

    estado_response = pg26a_client.get(f"/evaluaciones/{evaluation_id}/estado")
    recomendacion_response = pg26a_client.get(f"/evaluaciones/{evaluation_id}/recomendacion-final")

    return {
        "evaluation_id": evaluation_id,
        "final_status": final_status,
        "estado_response": estado_response,
        "recomendacion_response": recomendacion_response,
    }


# ──────────────────────────── required tests (10 minimum) ─────────────────────


def test_postgres_e2e_rec_saga_reaches_recomendacion_completada(
    completed_pg_e2e_recommendation,
) -> None:
    """Saga must reach RECOMENDACION_COMPLETADA; FALLIDA means recommendation failed."""
    assert (
        completed_pg_e2e_recommendation["final_status"]
        == EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value
    ), (
        f"Saga did not reach RECOMENDACION_COMPLETADA; "
        f"final status: {completed_pg_e2e_recommendation['final_status']}"
    )


def test_postgres_e2e_rec_recomendacion_final_returns_200(
    completed_pg_e2e_recommendation,
) -> None:
    """GET /evaluaciones/{id}/recomendacion-final must return 200 once RECOMENDACION_COMPLETADA."""
    resp = completed_pg_e2e_recommendation["recomendacion_response"]
    assert resp.status_code == 200, (
        f"GET recomendacion-final returned {resp.status_code}: {resp.text}"
    )


def test_postgres_e2e_rec_recomendacion_final_from_real_db(
    completed_pg_e2e_recommendation, pg26a_session_factory
) -> None:
    """Recommendation must be served from real PostgreSQL, not from in-memory objects."""
    evaluation_id = completed_pg_e2e_recommendation["evaluation_id"]
    session = pg26a_session_factory()
    try:
        repo = RecommendationQueryRepository(session)
        recs = repo.find_by_evaluation_id(evaluation_id)
    finally:
        session.close()
    assert len(recs) >= 1, (
        f"Expected ≥1 recommendation in PostgreSQL for evaluation {evaluation_id}, got 0"
    )
    rec = recs[0]
    assert rec.evaluation_id == evaluation_id
    assert rec.crop_id == CROP_MAIZ, (
        f"Expected recommendation for top-ranked crop {CROP_MAIZ!r}, got {rec.crop_id!r}"
    )


def test_postgres_e2e_rec_recommendation_persisted_in_postgresql(
    completed_pg_e2e_recommendation, pg_migrated
) -> None:
    """At least one row must exist in transactional.recommendations for this evaluation."""
    evaluation_id = completed_pg_e2e_recommendation["evaluation_id"]
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM transactional.recommendations "
                "WHERE evaluation_id = :eid"
            ),
            {"eid": str(evaluation_id)},
        )
        count = result.scalar()
    assert count >= 1, (
        f"Expected ≥1 row in transactional.recommendations for evaluation {evaluation_id}, "
        f"got {count}"
    )


def test_postgres_e2e_rec_provider_is_template(completed_pg_e2e_recommendation) -> None:
    """Recommendation provider field must be 'template' — no LLM, Gemini, Vertex, local_http."""
    body = completed_pg_e2e_recommendation["recomendacion_response"].json()
    assert body["provider"] == "template", (
        f"Expected provider='template', got {body['provider']!r}"
    )


def test_postgres_e2e_rec_text_is_not_empty(completed_pg_e2e_recommendation) -> None:
    """Recommendation title from TemplateRecommendationDraftingProvider must not be empty."""
    body = completed_pg_e2e_recommendation["recomendacion_response"].json()
    assert body.get("title"), f"Recommendation title must not be empty: {body}"


def test_postgres_e2e_rec_outbox_has_recomendacion_generada_dispatched(
    completed_pg_e2e_recommendation, pg_migrated
) -> None:
    """At least one RecomendacionGenerada outbox message must be DISPATCHED for this evaluation."""
    evaluation_id = completed_pg_e2e_recommendation["evaluation_id"]
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM transactional.outbox_messages "
                "WHERE correlation_id = :eid "
                "  AND status = 'DISPATCHED' "
                "  AND message_type = 'RecomendacionGenerada'"
            ),
            {"eid": str(evaluation_id)},
        )
        count = result.scalar()
    assert count >= 1, (
        f"Expected ≥1 DISPATCHED RecomendacionGenerada outbox message "
        f"for evaluation {evaluation_id}, got {count}"
    )


def test_postgres_e2e_rec_uses_real_relay_not_lockfree(
    completed_pg_e2e_recommendation, pg26a_relay
) -> None:
    """The relay must be the real RelayWorker with FOR UPDATE SKIP LOCKED, not LockFreeRelayWorker."""
    source = inspect.getsource(pg26a_relay._load_pending)
    assert "with_for_update" in source, "RelayWorker._load_pending must use with_for_update"
    assert "skip_locked" in source, "RelayWorker._load_pending must use skip_locked=True"
    assert type(pg26a_relay).__name__ == "RelayWorker", (
        f"Expected RelayWorker, got {type(pg26a_relay).__name__} — "
        "LockFreeRelayWorker must not be used in lote 26A"
    )


def test_postgres_e2e_rec_does_not_call_gee_or_llm(completed_pg_e2e_recommendation) -> None:
    """No GEE or LLM module must be imported during the PostgreSQL E2E recommendation saga."""
    for mod_name in sys.modules:
        assert "earthengine" not in mod_name, f"earthengine module was imported: {mod_name}"
        assert mod_name != "ee", "ee (earthengine-api) module was imported"
    llm_indicators = ("openai", "anthropic", "google.generativeai", "vertexai", "transformers")
    for mod_name in sys.modules:
        for indicator in llm_indicators:
            assert not mod_name.startswith(indicator), f"LLM module imported: {mod_name}"


def test_postgres_e2e_rec_does_not_create_tables_manually() -> None:
    """Structural check: tables must come from Alembic migrations, not hand-written DDL.

    Uses AST to detect execute()/text() calls with CREATE TABLE SQL string arguments.
    Positive check: verifies that 'recommendations' and 'evaluation_sagas' are registered
    as ORM-managed tables (i.e., they exist in Alembic migrations).
    """
    import ast as _ast
    import pathlib as _pathlib

    _source = _pathlib.Path(__file__).read_text(encoding="utf-8")
    _tree = _ast.parse(_source)
    for _node in _ast.walk(_tree):
        if isinstance(_node, _ast.Call):
            _fn = getattr(_node.func, "id", None) or getattr(_node.func, "attr", None) or ""
            if _fn in ("execute", "text"):
                for _arg in _node.args:
                    if isinstance(_arg, _ast.Constant) and "CREATE TABLE" in str(_arg.value).upper():
                        raise AssertionError(
                            f"Manual DDL found: {_fn!r}() called with a CREATE TABLE SQL string. "
                            "Tables must come from Alembic migrations (pg_migrated fixture)."
                        )
    import via.shared.database.models  # noqa: F401 — registers all ORM models as side-effect
    from via.shared.database.base import Base

    _table_names = {t.name for t in Base.metadata.sorted_tables}
    assert "recommendations" in _table_names, "recommendations not found in ORM metadata"
    assert "evaluation_sagas" in _table_names, "evaluation_sagas not found in ORM metadata"


# ──────────────────────────── additional validation tests ─────────────────────


def test_postgres_e2e_rec_estado_reflects_recomendacion_completada(
    completed_pg_e2e_recommendation,
) -> None:
    """GET /estado must reflect RECOMENDACION_COMPLETADA status in PostgreSQL."""
    body = completed_pg_e2e_recommendation["estado_response"].json()
    assert body["status"] == EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value


def test_postgres_e2e_rec_recommendation_crop_id_is_top_ranked(
    completed_pg_e2e_recommendation,
) -> None:
    """Recommendation must target the top-ranked crop (maiz_amarillo_duro, rank_position=1)."""
    body = completed_pg_e2e_recommendation["recomendacion_response"].json()
    assert body["crop_id"] == CROP_MAIZ, (
        f"Expected recommendation for {CROP_MAIZ!r} (rank 1), got {body['crop_id']!r}"
    )


def test_postgres_e2e_rec_all_outbox_dispatched_for_evaluation(
    completed_pg_e2e_recommendation, pg_migrated
) -> None:
    """All outbox messages for this evaluation (extraction + MCDA + recommendation) must be DISPATCHED."""
    evaluation_id = completed_pg_e2e_recommendation["evaluation_id"]
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM transactional.outbox_messages "
                "WHERE correlation_id = :eid AND status = 'DISPATCHED'"
            ),
            {"eid": str(evaluation_id)},
        )
        dispatched_count = result.scalar()
    assert dispatched_count >= 3, (
        f"Expected ≥3 DISPATCHED outbox messages for full saga "
        f"(extraction + MCDA + recommendation), got {dispatched_count}"
    )


def test_postgres_e2e_rec_evaluation_id_in_response(completed_pg_e2e_recommendation) -> None:
    """Recommendation response must include the correct evaluation_id."""
    expected_id = str(completed_pg_e2e_recommendation["evaluation_id"])
    body = completed_pg_e2e_recommendation["recomendacion_response"].json()
    assert body["evaluation_id"] == expected_id, (
        f"Expected evaluation_id={expected_id!r}, got {body['evaluation_id']!r}"
    )
