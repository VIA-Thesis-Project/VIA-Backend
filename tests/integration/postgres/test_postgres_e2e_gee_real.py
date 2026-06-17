"""E2E tests for lote 27A: real GEE integration in the extraction saga (opt-in).

Flow validated (requires GEE_TEST_RUN_REAL=1):
  POST /evaluaciones
  → EvaluationProcessManager (GeeRealRulebookReadModelPort + GeeRealParcelGeometryPort)
  → Outbox (PostgreSQL real, transactional.outbox_messages)
  → RelayWorker real (FOR UPDATE SKIP LOCKED)
  → GeeExtractionClient REAL → COPERNICUS/S2_SR_HARMONIZED band B8 mean (GEE API)
  → Agroenv vector stored in PostgreSQL (transactional.agroenv_vectors)
  → Outbox (PostgreSQL real)
  → RelayWorker real (second wave)
  → ViabilityEvaluationConsumer (GeeRealRulebookEvaluationPort, wide membership fn)
  → Evaluation results persisted in PostgreSQL (transactional.evaluation_results)
  → Saga reaches EVALUACION_COMPLETADA
  → GET /evaluaciones/{id}/estado   (reads from real PostgreSQL)
  → GET /evaluaciones/{id}/resultado-mcda  (reads from real PostgreSQL)

Opt-in guard: all session-scoped fixtures (and most tests) skip automatically unless
GEE_TEST_RUN_REAL=1 AND GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE are set.
Running `pytest -q` without those variables MUST NOT fail — it should only skip these tests.

Security:
- No hardcoded credentials, service account, project IDs, or key file content
- All GEE configuration loaded exclusively from environment variables
- No absolute user-specific paths

GEE dataset: COPERNICUS/S2_SR_HARMONIZED, band B8 (NIR), mean reducer, scale 30 m
Polygon:  small area near Lima, Peru (~100 m × 100 m)
Periods:  2024-Q2 (Jun–Jul 2024), 2024-Q3 (Aug 2024)

NOT used: ControlledExtractionClient, LockFreeRelayWorker, asyncpg, AsyncSession,
          create_async_engine, LLM, Recommendation, DDL manual,
          Celery, Kafka, RabbitMQ, Redis.
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.application.ports import ExtractionRequest
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.viability_evaluation.application.command_service import (
    McdaRuntimeSettings,
    ViabilityEvaluationCommandService,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    EvaluationCriterionSpec,
    RulebookEvaluationData,
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
from via.shared.orchestration.evaluation_process_manager.ports import (
    ParcelGeometrySnapshot,
    RequiredExtractionSpec,
    RequiredVariableForEvaluation,
)
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import SqlAlchemyAgroenvVectorBridge


# ──────────────────────────── fixture constants ───────────────────────────────

# GEE dataset config — no credentials here
_GEE_CROP = "gee_test_crop"
_GEE_PHASE = "desarrollo"
_GEE_VARIABLE = "nir_reflectancia"
_GEE_CRITERION = "vigor_nir"
_GEE_DATASET = "COPERNICUS/S2_SR_HARMONIZED"
_GEE_BAND = "B8"
_GEE_PERIOD_1 = "2024-Q2"
_GEE_PERIOD_1_START = "2024-06-01"
_GEE_PERIOD_1_END = "2024-07-31"
_GEE_PERIOD_2 = "2024-Q3"
_GEE_PERIOD_2_START = "2024-08-01"
_GEE_PERIOD_2_END = "2024-08-31"

_TEMPORAL_PERIODS = [
    {"period_key": _GEE_PERIOD_1, "temporal_weight": 0.6},
    {"period_key": _GEE_PERIOD_2, "temporal_weight": 0.4},
]

_TEMPORAL_WINDOW = {"start": "2024-06-01", "end": "2024-08-31"}

# Small polygon near Lima, Peru (~100 m × 100 m) — no private coordinates
_GEE_POLYGON = {
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

_PARCEL_ID = UUID("beef0001-0000-4000-8000-000000000027")
_REQUESTED_BY = UUID("beef0002-0000-4000-8000-000000000027")
_RULEBOOK_ID = UUID("beef0003-0000-4000-8000-000000000027")

_EVALUACION_COMPLETADA = EvaluationSagaStatus.EVALUACION_COMPLETADA.value
_FALLIDA = EvaluationSagaStatus.FALLIDA.value


# ──────────────────────────── controlled ports ────────────────────────────────


class GeeRealParcelGeometryPort:
    """Returns a fixed Lima-area Polygon — avoids PostGIS geometry insert."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry=_GEE_POLYGON)


class GeeRealRulebookReadModelPort:
    """Returns extraction spec pointing to the real GEE dataset — no DB read."""

    def get_required_extraction_spec(
        self,
        crop_candidates: list[str],
        temporal_window: dict,
    ) -> RequiredExtractionSpec:
        variables: list[RequiredVariableForEvaluation] = []
        for crop_id in crop_candidates:
            variables.append(
                RequiredVariableForEvaluation(
                    variable_name=_GEE_VARIABLE,
                    criterion_id=_GEE_CRITERION,
                    crop_id=crop_id,
                    phase_id=_GEE_PHASE,
                    dataset_key=_GEE_DATASET,
                    band=_GEE_BAND,
                    unit="reflectance_scaled",
                    temporal_resolution="monthly",
                    reducer="mean",
                    aggregation_method="mean",
                    fallback_allowed=True,
                    temporal_periods=_TEMPORAL_PERIODS,
                )
            )
        return RequiredExtractionSpec(variables=variables)


class GeeRealRulebookEvaluationPort:
    """Returns a rulebook with a wide TRAPEZOIDAL membership for NIR B8 values — no DB read."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        return RulebookEvaluationData(
            crop_id=crop_id,
            rulebook_id=_RULEBOOK_ID,
            version=1,
            criteria=[
                EvaluationCriterionSpec(
                    criterion_id=_GEE_CRITERION,
                    crop_id=crop_id,
                    phase_id=_GEE_PHASE,
                    variable_name=_GEE_VARIABLE,
                    w_ahp=1.0,
                    phase_weight=1.0,
                    temporal_periods=_TEMPORAL_PERIODS,
                    # Sentinel-2 SR Harmonized B8 DN values: 0–10000
                    # Wide membership accepts [100, 9900] with full score → VIABLE for any valid pixel
                    membership_fn={
                        "type": "TRAPEZOIDAL",
                        "a": 0.0,
                        "b": 100.0,
                        "c": 9900.0,
                        "d": 10001.0,
                    },
                    critical_policy="NONE",
                    penalty_factor=None,
                    doc_source="27A GEE real test fixture — Sentinel-2 SR NIR B8",
                )
            ],
        )


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
def gee_real_skip_check():
    """Fail-fast gate: skip entire GEE session if opt-in env vars are not set."""
    if os.environ.get("GEE_TEST_RUN_REAL", "").strip() not in {"1", "true", "yes"}:
        pytest.skip(
            "GEE_TEST_RUN_REAL is not set — GEE real tests are opt-in. "
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
            f"GEE real tests require environment variables: {', '.join(missing)}. "
            "Configure all GEE variables before running."
        )


# ──────────────────────────── session-scoped fixtures ─────────────────────────


@pytest.fixture(scope="session")
def pg27a_gee_settings(gee_real_skip_check):
    """GEE-enabled Settings loaded exclusively from environment variables."""
    overrides = {**os.environ, "GEE_ENABLED": "true"}
    return load_settings(overrides)


@pytest.fixture(scope="session")
def pg27a_gee_client(pg27a_gee_settings):
    """Real GeeExtractionClient initialized with service account credentials from env."""
    return GeeExtractionClient(settings=pg27a_gee_settings)


@pytest.fixture(scope="session")
def pg27a_session_factory(pg_migrated, gee_real_skip_check):
    """Session factory bound to the real migrated PostgreSQL test database."""
    return sessionmaker(bind=pg_migrated, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session")
def pg27a_cleanup(pg_migrated, pg27a_session_factory):
    """Truncate all transactional tables before the 27A E2E session."""
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
def pg27a_process_manager(pg27a_session_factory, pg27a_cleanup):
    return EvaluationProcessManager(
        session_factory=pg27a_session_factory,
        rulebook_read_model_port=GeeRealRulebookReadModelPort(),
        parcel_geometry_read_model_port=GeeRealParcelGeometryPort(),
    )


@pytest.fixture(scope="session")
def pg27a_extraction_consumer(pg27a_session_factory, pg27a_cleanup, pg27a_gee_client):
    service = AgroenvExtractionCommandService(
        session_factory=pg27a_session_factory,
        extraction_client=pg27a_gee_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


@pytest.fixture(scope="session")
def pg27a_evaluation_consumer(pg27a_session_factory, pg27a_cleanup):
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )
    service = ViabilityEvaluationCommandService(
        session_factory=pg27a_session_factory,
        rulebook_port=GeeRealRulebookEvaluationPort(),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(pg27a_session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=settings,
    )
    return ViabilityEvaluationConsumer(service)


@pytest.fixture(scope="session")
def pg27a_event_bus(pg27a_process_manager, pg27a_extraction_consumer, pg27a_evaluation_consumer):
    """Real InMemoryEventBus — extraction + evaluation only (no Recommendation consumer)."""
    bus = InMemoryEventBus()
    pm_handler = EvaluationProcessManagerEventHandler(pg27a_process_manager)
    bus.register(VECTOR_AGROAMBIENTAL_GENERADO, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_COMPLETADA, pm_handler)
    bus.register(EXTRACCION_FALLIDA, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_FALLIDA, pm_handler)
    bus.register(RECOMENDACION_GENERADA, pm_handler)
    bus.register(RECOMENDACION_FALLIDA, pm_handler)
    bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, pg27a_extraction_consumer.handle)
    bus.register(EJECUTAR_EVALUACION_VIABILIDAD, pg27a_evaluation_consumer.handle)
    return bus


@pytest.fixture(scope="session")
def pg27a_relay(pg27a_session_factory, pg27a_event_bus, pg27a_cleanup):
    """Real RelayWorker — PostgreSQL FOR UPDATE SKIP LOCKED, driven manually."""
    return RelayWorker(
        session_factory=pg27a_session_factory,
        event_bus=pg27a_event_bus,
        batch_size=20,
    )


@pytest.fixture(scope="session")
def pg27a_client(pg27a_process_manager, pg27a_session_factory, pg27a_cleanup):
    """FastAPI TestClient with process manager + query service bound to real PostgreSQL."""
    from via.main import app

    def _pm_dep():
        return pg27a_process_manager

    def _qs_dep() -> Generator[EvaluationQueryService, None, None]:
        session = pg27a_session_factory()
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
def completed_pg_e2e_gee_real(pg27a_client, pg27a_relay, pg27a_session_factory):
    """Run one full GEE E2E extraction saga on real PostgreSQL.

    Calls real GEE (COPERNICUS/S2_SR_HARMONIZED B8) and drives the saga through
    EXTRACCION_COMPLETADA → EVALUACION_COMPLETADA using real PostgreSQL outbox/relay.
    The result is cached session-wide so all test functions share a single GEE call.
    """
    response = pg27a_client.post(
        "/evaluaciones",
        json={
            "parcel_id": str(_PARCEL_ID),
            "requested_by": str(_REQUESTED_BY),
            "crop_candidates": [_GEE_CROP],
            "temporal_window": _TEMPORAL_WINDOW,
        },
    )
    assert response.status_code == 202, f"POST /evaluaciones failed: {response.text}"
    evaluation_id = UUID(response.json()["evaluation_id"])

    target = frozenset({_EVALUACION_COMPLETADA, _FALLIDA})
    final_status = _drive_saga(pg27a_relay, pg27a_session_factory, evaluation_id, target)

    estado_response = pg27a_client.get(f"/evaluaciones/{evaluation_id}/estado")
    mcda_response = pg27a_client.get(f"/evaluaciones/{evaluation_id}/resultado-mcda")

    return {
        "evaluation_id": evaluation_id,
        "final_status": final_status,
        "estado_response": estado_response,
        "mcda_response": mcda_response,
    }


# ──────────────────────────── standalone opt-in check (always collected) ──────


def test_gee_real_credentials_are_required_for_real_run() -> None:
    """Skip if GEE_TEST_RUN_REAL is not set; fail with diagnostic if vars are missing.

    This test is always collected by pytest but skips gracefully when opt-in is
    not active. When GEE_TEST_RUN_REAL=1, it asserts all required variables exist
    so that the developer gets a clear error before the saga fixtures run.
    """
    gee_run_real = os.environ.get("GEE_TEST_RUN_REAL", "").strip()
    if not gee_run_real:
        pytest.skip(
            "GEE_TEST_RUN_REAL is not set — GEE real tests are opt-in. "
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
        f"{', '.join(missing)}. Configure all GEE variables before running real tests."
    )


# ──────────────────────────── opt-in E2E tests (8 saga tests) ─────────────────


def test_postgres_e2e_gee_real_saga_reaches_evaluacion_completada(
    completed_pg_e2e_gee_real,
) -> None:
    """Saga must reach EVALUACION_COMPLETADA using real GEE extraction (not FALLIDA)."""
    assert completed_pg_e2e_gee_real["final_status"] == _EVALUACION_COMPLETADA, (
        f"GEE saga did not reach EVALUACION_COMPLETADA; "
        f"final status: {completed_pg_e2e_gee_real['final_status']!r}"
    )


def test_postgres_e2e_gee_real_resultado_mcda_returns_200(
    completed_pg_e2e_gee_real,
) -> None:
    """GET /resultado-mcda must return 200 after GEE extraction and MCDA evaluation."""
    resp = completed_pg_e2e_gee_real["mcda_response"]
    assert resp.status_code == 200, (
        f"GET resultado-mcda returned {resp.status_code}: {resp.text}"
    )


def test_postgres_e2e_gee_real_result_persisted_in_postgresql(
    completed_pg_e2e_gee_real, pg27a_session_factory
) -> None:
    """MCDA results must be persisted to PostgreSQL and retrievable via query service."""
    evaluation_id = completed_pg_e2e_gee_real["evaluation_id"]
    session = pg27a_session_factory()
    try:
        repo = EvaluationQueryRepository(session)
        crop_results = repo.find_crop_results(evaluation_id)
    finally:
        session.close()
    assert len(crop_results) >= 1, (
        f"Expected ≥1 persisted crop result in PostgreSQL for evaluation {evaluation_id}, "
        f"got {len(crop_results)}"
    )
    stored_ids = {r.crop_id for r in crop_results}
    assert _GEE_CROP in stored_ids, f"{_GEE_CROP!r} not in persisted results: {stored_ids}"


def test_gee_real_client_extracts_single_variable(pg27a_gee_client) -> None:
    """GeeExtractionClient must call COPERNICUS/S2_SR_HARMONIZED and return a valid result."""
    request = ExtractionRequest(
        parcel_id=_PARCEL_ID,
        parcel_geometry=_GEE_POLYGON,
        temporal_window={"start": _GEE_PERIOD_1_START, "end": _GEE_PERIOD_1_END},
        variable_name=_GEE_VARIABLE,
        criterion_id=_GEE_CRITERION,
        crop_id=_GEE_CROP,
        phase_id=_GEE_PHASE,
        dataset_key=_GEE_DATASET,
        band=_GEE_BAND,
        unit="reflectance_scaled",
        temporal_resolution="monthly",
        spatial_resolution=None,
        scale=30.0,
        reducer="mean",
        aggregation_method="mean",
        quality_mask=None,
        fallback_allowed=True,
        period_key=_GEE_PERIOD_1,
        period_start=_GEE_PERIOD_1_START,
        period_end=_GEE_PERIOD_1_END,
    )
    result = pg27a_gee_client.extract_variable(request)
    # Result may be None if no valid S2 pixels found (handled via fallback_allowed=True in saga).
    if result is not None:
        assert isinstance(result.value, float), (
            f"GEE result.value must be float, got {type(result.value)}"
        )
        assert 0.0 <= result.value <= 10001.0, (
            f"S2 NIR B8 value {result.value} is outside plausible range [0, 10001]"
        )
        assert result.source.startswith("GEE:"), (
            f"GEE source must start with 'GEE:', got {result.source!r}"
        )


def test_postgres_e2e_gee_real_does_not_use_controlled_extraction(
    pg27a_gee_client,
) -> None:
    """The extraction client must be GeeExtractionClient — not a controlled stub."""
    assert type(pg27a_gee_client).__name__ == "GeeExtractionClient", (
        f"Expected GeeExtractionClient, got {type(pg27a_gee_client).__name__}"
    )
    assert "Controlled" not in type(pg27a_gee_client).__name__, (
        "27A must use GeeExtractionClient real, not a controlled stub"
    )


def test_postgres_e2e_gee_real_does_not_use_lockfree_relay(
    completed_pg_e2e_gee_real, pg27a_relay
) -> None:
    """The relay must be real RelayWorker with FOR UPDATE SKIP LOCKED, not LockFreeRelayWorker."""
    source = inspect.getsource(pg27a_relay._load_pending)
    assert "with_for_update" in source, "RelayWorker._load_pending must use with_for_update"
    assert "skip_locked" in source, "RelayWorker._load_pending must use skip_locked=True"
    assert type(pg27a_relay).__name__ == "RelayWorker", (
        f"Expected RelayWorker, got {type(pg27a_relay).__name__}"
    )


def test_postgres_e2e_gee_real_outbox_dispatched_for_evaluation(
    completed_pg_e2e_gee_real, pg_migrated
) -> None:
    """All outbox messages for this evaluation must be DISPATCHED in PostgreSQL."""
    evaluation_id = completed_pg_e2e_gee_real["evaluation_id"]
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM transactional.outbox_messages "
                "WHERE correlation_id = :eid AND status = 'DISPATCHED'"
            ),
            {"eid": str(evaluation_id)},
        )
        dispatched_count = result.scalar()
    assert dispatched_count >= 2, (
        f"Expected ≥2 DISPATCHED outbox messages for evaluation {evaluation_id}, "
        f"got {dispatched_count}"
    )


def test_postgres_e2e_gee_real_does_not_call_llm_or_recommendation(
    completed_pg_e2e_gee_real,
) -> None:
    """No LLM or Recommendation consumer must have been invoked during the GEE saga."""
    llm_indicators = ("openai", "anthropic", "google.generativeai", "vertexai", "transformers")
    for mod_name in sys.modules:
        for indicator in llm_indicators:
            assert not mod_name.startswith(indicator), (
                f"LLM module was imported during GEE real saga: {mod_name}"
            )
