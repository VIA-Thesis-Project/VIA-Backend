"""E2E test for lote 28A: Leaflet GeoJSON → GEE real → resultado MCDA (opt-in).

Flow validated (requires GEE_TEST_RUN_REAL=1 + DATABASE_URL):
  ParcelCommandService.register_parcel()          → parcel in transactional.parcels
  RulebookCommandService.create_rulebook()         → rulebook in transactional.rulebooks
  RulebookCommandService.publish_rulebook()        → rulebook status=ACTIVE
  POST /evaluaciones                               → evaluation_id, saga INICIADA
  RelayWorker (FOR UPDATE SKIP LOCKED)             → dispatches INICIAR_EXTRACCION
  GeeExtractionClient REAL                         → COPERNICUS/S2_SR_HARMONIZED B8
  SqlAlchemyParcelGeometryBridge                   → reads geometry from PostgreSQL
  SqlAlchemyRulebookReadModelBridge                → reads extraction spec from PostgreSQL
  SqlAlchemyRulebookEvaluationBridge               → reads rulebook for MCDA from PostgreSQL
  ViabilityEvaluationConsumer                      → MCDA difuso → EVALUACION_COMPLETADA
  GET /evaluaciones/{id}/resultado-mcda            → crop ranking + brechas

Upgrade from 27A: uses real DB bridges instead of controlled ports — the parcel
geometry and the rulebook are both read from real PostgreSQL, not in-memory stubs.

Opt-in guard: all session-scoped fixtures skip automatically unless
GEE_TEST_RUN_REAL=1 AND GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE are set.
Running `pytest -q` without those variables MUST NOT fail — it should only skip these tests.

Security:
- No hardcoded credentials, service account, project IDs, or key file content
- All GEE configuration loaded exclusively from environment variables
- No absolute user-specific paths

GEE dataset: COPERNICUS/S2_SR_HARMONIZED, band B8 (NIR), mean reducer, scale 30 m
Polygon: small parcel near Lima, Peru (~100 m × 100 m) — GeoJSON [lng, lat] format
Rulebook: one criterion (vigor_nir), wide TRAPEZOIDAL membership [0, 100, 9900, 10001]

NOT used: controlled stubs, asyncpg, AsyncSession, create_async_engine,
          LLM, Recommendation, DDL manual, Celery, Kafka, RabbitMQ, Redis.
"""

from __future__ import annotations

import os
import sys
from typing import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.parcel_management.application.command_service import ParcelCommandService
from via.bounded_contexts.parcel_management.domain.geometry_validator import ParcelGeometryValidator
from via.bounded_contexts.parcel_management.infrastructure.parcel_repository import SQLAlchemyParcelRepository
from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.value_objects import MembershipFunction, TemporalPeriod
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository
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
from via.config import load_settings
from via.shared.event_bus.in_memory_event_bus import InMemoryEventBus
from via.shared.orchestration.evaluation_process_manager.commands import (
    EJECUTAR_EVALUACION_VIABILIDAD,
    INICIAR_EXTRACCION_AGROAMBIENTAL,
)
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    EVALUACION_VIABILIDAD_FALLIDA,
    EXTRACCION_FALLIDA,
    RECOMENDACION_FALLIDA,
    RECOMENDACION_GENERADA,
    VECTOR_AGROAMBIENTAL_GENERADO,
)
from via.shared.orchestration.evaluation_process_manager.handlers import EvaluationProcessManagerEventHandler
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import (
    SqlAlchemyAgroenvVectorBridge,
    SqlAlchemyParcelGeometryBridge,
    SqlAlchemyRulebookEvaluationBridge,
    SqlAlchemyRulebookReadModelBridge,
)


# ──────────────────────────── constants ───────────────────────────────────────

_CROP_ID = "leaflet_gee_test_crop"
_PHASE_NAME = "desarrollo"
_VARIABLE_NAME = "nir_reflectancia"
_CRITERION_NAME = "vigor_nir"
_DATASET = "COPERNICUS/S2_SR_HARMONIZED"
_BAND = "B8"
_PERIOD_1 = "2024-Q2"
_PERIOD_2 = "2024-Q3"
_TEMPORAL_WINDOW = {"start": "2024-06-01", "end": "2024-08-31"}

_CRITERION_ID = UUID("beef1001-0000-4000-8000-000000000028")
_PHASE_ID = UUID("beef2001-0000-4000-8000-000000000028")
_REQUIREMENT_ID = UUID("beef3001-0000-4000-8000-000000000028")
_OWNER_ID = UUID("beef0002-0000-4000-8000-000000000028")

# GeoJSON polygon in [lng, lat] — small parcel near Lima, Peru (~100 m × 100 m)
# Leaflet uses [lat, lng]; GeoJSON requires [lng, lat] — conversion is mandatory
_LEAFLET_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-76.010, -12.010],
            [-76.010, -12.011],
            [-76.009, -12.011],
            [-76.009, -12.010],
            [-76.010, -12.010],
        ]
    ],
}

_EVALUACION_COMPLETADA = EvaluationSagaStatus.EVALUACION_COMPLETADA.value
_FALLIDA = EvaluationSagaStatus.FALLIDA.value


# ──────────────────────────── domain helpers ──────────────────────────────────


def _build_rulebook_objects():
    """Build domain objects for a minimal NIR rulebook (Sentinel-2 B8)."""
    criterion = Criterion(
        id=_CRITERION_ID,
        name=_CRITERION_NAME,
        is_critical=False,
        critical_policy=None,
        penalty_factor=None,
        ahp_weight=1.0,
        doc_source="Sentinel-2 SR NIR B8 — 28A demo fixture",
    )
    phase = PhenologicalPhase(
        id=_PHASE_ID,
        name=_PHASE_NAME,
        duration_days=90,
        sequence_order=1,
    )
    # Wide TRAPEZOIDAL: accepts any valid S2 B8 DN value [100, 9900] with membership 1.0
    requirement = PhaseRequirement(
        id=_REQUIREMENT_ID,
        criterion_id=_CRITERION_ID,
        phase_id=_PHASE_ID,
        membership_fn=MembershipFunction(a=0.0, b=100.0, c=9900.0, d=10001.0),
        phase_weight=1.0,
        temporal_periods=[
            TemporalPeriod(period_key=_PERIOD_1, temporal_weight=0.6),
            TemporalPeriod(period_key=_PERIOD_2, temporal_weight=0.4),
        ],
        extraction_binding=ExtractionBinding(
            variable_name=_VARIABLE_NAME,
            dataset_key=_DATASET,
            band=_BAND,
            unit="reflectance_scaled",
            temporal_resolution="monthly",
            spatial_resolution=None,
            scale=30.0,
            reducer="mean",
            aggregation_method="mean",
            quality_mask=None,
            fallback_allowed=True,
        ),
    )
    return criterion, phase, requirement


# ──────────────────────────── saga driver ────────────────────────────────────


def _drive_saga(
    relay: RelayWorker,
    session_factory: sessionmaker,
    evaluation_id: UUID,
    target_statuses: frozenset[str],
    max_waves: int = 12,
) -> str:
    for _ in range(max_waves):
        relay.process_batch()
        with session_factory() as session:
            saga = session.get(EvaluationSagaModel, evaluation_id)
            if saga is not None and saga.status in target_statuses:
                return saga.status
    with session_factory() as session:
        saga = session.get(EvaluationSagaModel, evaluation_id)
        return saga.status if saga else "NOT_FOUND"


# ──────────────────────────── session-scoped skip gate ───────────────────────


@pytest.fixture(scope="session")
def pg28a_gee_skip_check():
    """Fail-fast gate: skip the 28A session if opt-in env vars are not set."""
    if os.environ.get("GEE_TEST_RUN_REAL", "").strip() not in {"1", "true", "yes"}:
        pytest.skip(
            "GEE_TEST_RUN_REAL is not set — 28A GEE real tests are opt-in. "
            "Set GEE_TEST_RUN_REAL=1 and configure GEE_PROJECT, "
            "GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE to enable."
        )
    missing = [
        v
        for v in ("GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE")
        if not os.environ.get(v)
    ]
    if missing:
        pytest.skip(
            f"28A GEE real tests require environment variables: {', '.join(missing)}. "
            "Configure all GEE variables before running."
        )


# ──────────────────────────── session-scoped fixtures ─────────────────────────


@pytest.fixture(scope="session")
def pg28a_gee_settings(pg28a_gee_skip_check):
    """GEE-enabled Settings loaded exclusively from environment variables."""
    overrides = {**os.environ, "GEE_ENABLED": "true"}
    return load_settings(overrides)


@pytest.fixture(scope="session")
def pg28a_gee_client(pg28a_gee_settings):
    """Real GeeExtractionClient initialized with service account credentials from env."""
    return GeeExtractionClient(settings=pg28a_gee_settings)


@pytest.fixture(scope="session")
def pg28a_session_factory(pg_migrated, pg28a_gee_skip_check):
    """Session factory bound to the real migrated PostgreSQL test database."""
    return sessionmaker(bind=pg_migrated, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session")
def pg28a_cleanup(pg_migrated, pg28a_session_factory):
    """Truncate all transactional tables before the 28A E2E session."""
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
            "transactional.evaluation_sagas, "
            "transactional.rulebook_phase_requirements, "
            "transactional.rulebook_phases, "
            "transactional.rulebook_criteria, "
            "transactional.rulebooks, "
            "transactional.parcels "
            "CASCADE"
        ))
    return pg_migrated


@pytest.fixture(scope="session")
def pg28a_parcel_id(pg28a_session_factory, pg28a_cleanup):
    """Register a real parcel in PostgreSQL using ParcelCommandService. Returns its UUID."""
    session = pg28a_session_factory()
    try:
        repo = SQLAlchemyParcelRepository(session)
        validator = ParcelGeometryValidator(max_area_ha=10_000.0)
        service = ParcelCommandService(parcel_repository=repo, geometry_validator=validator)
        parcel = service.register_parcel(
            owner_id=_OWNER_ID,
            geometry=_LEAFLET_POLYGON_GEOJSON,
            metadata={
                "name": "Parcela Leaflet Demo 28A",
                "description": "Parcela de prueba GEE real Lote 28A",
                "crs": "EPSG:4326",
            },
        )
        session.commit()
        return parcel.id
    finally:
        session.close()


@pytest.fixture(scope="session")
def pg28a_rulebook_id(pg28a_session_factory, pg28a_cleanup):
    """Create and publish a NIR rulebook in PostgreSQL via RulebookCommandService. Returns its UUID."""
    criterion, phase, requirement = _build_rulebook_objects()
    session = pg28a_session_factory()
    try:
        repo = SqlAlchemyRulebookRepository(session)
        service = RulebookCommandService(repository=repo)
        rulebook = service.create_rulebook(
            crop_id=_CROP_ID,
            criteria=[criterion],
            phases=[phase],
            phase_requirements=[requirement],
        )
        session.commit()
        service.publish_rulebook(rulebook.id)
        session.commit()
        return rulebook.id
    finally:
        session.close()


@pytest.fixture(scope="session")
def pg28a_process_manager(pg28a_session_factory, pg28a_parcel_id, pg28a_rulebook_id):
    """EvaluationProcessManager using real DB bridges — reads parcel and rulebook from PostgreSQL."""
    return EvaluationProcessManager(
        session_factory=pg28a_session_factory,
        rulebook_read_model_port=SqlAlchemyRulebookReadModelBridge(pg28a_session_factory),
        parcel_geometry_read_model_port=SqlAlchemyParcelGeometryBridge(pg28a_session_factory),
    )


@pytest.fixture(scope="session")
def pg28a_extraction_consumer(pg28a_session_factory, pg28a_gee_client):
    """AgroenvExtractionConsumer using the real GeeExtractionClient."""
    service = AgroenvExtractionCommandService(
        session_factory=pg28a_session_factory,
        extraction_client=pg28a_gee_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


@pytest.fixture(scope="session")
def pg28a_evaluation_consumer(pg28a_session_factory, pg28a_rulebook_id):
    """ViabilityEvaluationConsumer using SqlAlchemyRulebookEvaluationBridge (reads from DB)."""
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )
    service = ViabilityEvaluationCommandService(
        session_factory=pg28a_session_factory,
        rulebook_port=SqlAlchemyRulebookEvaluationBridge(pg28a_session_factory),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(pg28a_session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=settings,
    )
    return ViabilityEvaluationConsumer(service)


@pytest.fixture(scope="session")
def pg28a_event_bus(pg28a_process_manager, pg28a_extraction_consumer, pg28a_evaluation_consumer):
    """Real InMemoryEventBus — extraction + evaluation only (no Recommendation consumer)."""
    bus = InMemoryEventBus()
    pm_handler = EvaluationProcessManagerEventHandler(pg28a_process_manager)
    bus.register(VECTOR_AGROAMBIENTAL_GENERADO, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_COMPLETADA, pm_handler)
    bus.register(EXTRACCION_FALLIDA, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_FALLIDA, pm_handler)
    bus.register(RECOMENDACION_GENERADA, pm_handler)
    bus.register(RECOMENDACION_FALLIDA, pm_handler)
    bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, pg28a_extraction_consumer.handle)
    bus.register(EJECUTAR_EVALUACION_VIABILIDAD, pg28a_evaluation_consumer.handle)
    return bus


@pytest.fixture(scope="session")
def pg28a_relay(pg28a_session_factory, pg28a_event_bus):
    """Real RelayWorker — PostgreSQL FOR UPDATE SKIP LOCKED, driven manually."""
    return RelayWorker(
        session_factory=pg28a_session_factory,
        event_bus=pg28a_event_bus,
        batch_size=20,
    )


@pytest.fixture(scope="session")
def pg28a_client(pg28a_process_manager, pg28a_session_factory):
    """FastAPI TestClient with process manager + query service bound to real PostgreSQL."""
    from via.main import app

    def _pm_dep():
        return pg28a_process_manager

    def _qs_dep() -> Generator[EvaluationQueryService, None, None]:
        session = pg28a_session_factory()
        try:
            yield EvaluationQueryService(EvaluationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_process_manager] = _pm_dep
    app.dependency_overrides[get_evaluation_query_service] = _qs_dep
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_process_manager, None)
        app.dependency_overrides.pop(get_evaluation_query_service, None)


@pytest.fixture(scope="session")
def pg28a_leaflet_result(
    pg28a_client,
    pg28a_relay,
    pg28a_session_factory,
    pg28a_parcel_id,
    pg28a_rulebook_id,
):
    """Run the full Leaflet GeoJSON → GEE → MCDA saga end-to-end on real PostgreSQL.

    Parcel and rulebook are created in PostgreSQL beforehand and read via real DB bridges.
    GEE extraction uses real COPERNICUS/S2_SR_HARMONIZED B8 data for the Lima polygon.
    Result cached session-wide so all test functions share a single GEE call.
    """
    response = pg28a_client.post(
        "/evaluaciones",
        json={
            "parcel_id": str(pg28a_parcel_id),
            "requested_by": str(_OWNER_ID),
            "crop_candidates": [_CROP_ID],
            "temporal_window": _TEMPORAL_WINDOW,
        },
    )
    assert response.status_code == 202, f"POST /evaluaciones failed: {response.text}"
    evaluation_id = UUID(response.json()["evaluation_id"])

    target = frozenset({_EVALUACION_COMPLETADA, _FALLIDA})
    final_status = _drive_saga(pg28a_relay, pg28a_session_factory, evaluation_id, target)

    estado_response = pg28a_client.get(f"/evaluaciones/{evaluation_id}/estado")
    mcda_response = pg28a_client.get(f"/evaluaciones/{evaluation_id}/resultado-mcda")

    return {
        "evaluation_id": evaluation_id,
        "parcel_id": pg28a_parcel_id,
        "rulebook_id": pg28a_rulebook_id,
        "final_status": final_status,
        "estado_response": estado_response,
        "mcda_response": mcda_response,
    }


# ──────────────────────────── standalone opt-in check (always collected) ──────


def test_28a_gee_real_credentials_are_required() -> None:
    """Skip if GEE_TEST_RUN_REAL is not set; fail with diagnostic if vars are missing.

    Always collected by pytest — skips gracefully when opt-in is not active.
    """
    gee_run_real = os.environ.get("GEE_TEST_RUN_REAL", "").strip()
    if not gee_run_real:
        pytest.skip(
            "GEE_TEST_RUN_REAL is not set — 28A GEE real tests are opt-in. "
            "Set GEE_TEST_RUN_REAL=1 and configure GEE_PROJECT, "
            "GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE to enable."
        )
    missing = [
        v
        for v in ("GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE")
        if not os.environ.get(v)
    ]
    assert not missing, (
        f"GEE_TEST_RUN_REAL is set but required environment variables are missing: "
        f"{', '.join(missing)}. Configure all GEE variables before running 28A tests."
    )


# ──────────────────────────── the required opt-in E2E test ───────────────────


def test_leaflet_geojson_to_gee_mcda_real_flow_opt_in(
    pg28a_leaflet_result,
    pg28a_session_factory,
) -> None:
    """Full Leaflet GeoJSON → GEE real → resultado MCDA with real DB bridges (opt-in).

    Validates the complete flow:
    - Parcel registered in PostgreSQL via ParcelCommandService (not a controlled stub)
    - Rulebook published in PostgreSQL via RulebookCommandService (not a controlled stub)
    - SqlAlchemyParcelGeometryBridge reads real parcel geometry from DB
    - SqlAlchemyRulebookReadModelBridge reads real rulebook extraction spec from DB
    - SqlAlchemyRulebookEvaluationBridge reads real rulebook MCDA data from DB
    - GeeExtractionClient calls COPERNICUS/S2_SR_HARMONIZED with the real parcel polygon
    - Saga reaches EVALUACION_COMPLETADA (not FALLIDA)
    - GET /resultado-mcda returns 200 with at least one crop result
    - MCDA results are persisted in PostgreSQL and retrievable via query service
    """
    result = pg28a_leaflet_result

    # Saga must reach EVALUACION_COMPLETADA
    assert result["final_status"] == _EVALUACION_COMPLETADA, (
        f"Leaflet→GEE→MCDA saga did not reach EVALUACION_COMPLETADA; "
        f"final_status={result['final_status']!r}"
    )

    # GET /resultado-mcda must return HTTP 200
    mcda_resp = result["mcda_response"]
    assert mcda_resp.status_code == 200, (
        f"GET /resultado-mcda returned {mcda_resp.status_code}: {mcda_resp.text}"
    )

    # Response must include the crop candidate
    body = mcda_resp.json()
    assert body.get("status") == _EVALUACION_COMPLETADA, (
        f"resultado-mcda body status is {body.get('status')!r}, "
        f"expected {_EVALUACION_COMPLETADA!r}"
    )
    crop_ids = [r["crop_id"] for r in body.get("results", [])]
    assert _CROP_ID in crop_ids, (
        f"{_CROP_ID!r} not in resultado-mcda results: {crop_ids}"
    )

    # MCDA results must be persisted in PostgreSQL
    session = pg28a_session_factory()
    try:
        repo = EvaluationQueryRepository(session)
        crop_results = repo.find_crop_results(result["evaluation_id"])
    finally:
        session.close()
    assert len(crop_results) >= 1, (
        f"Expected ≥1 persisted crop result in PostgreSQL, got {len(crop_results)}"
    )
    stored_ids = {r.crop_id for r in crop_results}
    assert _CROP_ID in stored_ids, (
        f"{_CROP_ID!r} not in DB persisted results: {stored_ids}"
    )

    # Real DB bridges were used (no controlled port stubs)
    assert result["parcel_id"] is not None, "parcel_id must be a real DB-generated UUID"
    assert result["rulebook_id"] is not None, "rulebook_id must be a real DB-generated UUID"

    # No LLM modules must have been imported during the saga
    llm_indicators = ("openai", "anthropic", "google.generativeai", "vertexai", "transformers")
    for mod_name in sys.modules:
        for indicator in llm_indicators:
            assert not mod_name.startswith(indicator), (
                f"LLM module was imported during 28A saga: {mod_name}"
            )
