"""E2E tests for lote 25B: MCDA evaluation flow on real PostgreSQL.

Flow validated here:
  POST /evaluaciones
  → EvaluationProcessManager (controlled rulebook/parcel ports — no DB reads for setup data)
  → Outbox (PostgreSQL real, transactional.outbox_messages)
  → RelayWorker real (FOR UPDATE SKIP LOCKED — PostgreSQL native row locking)
  → ControlledExtractionClient (returns deterministic values, never calls GEE)
  → Agroenv vector stored in PostgreSQL (transactional.agroenv_vectors)
  → Outbox (PostgreSQL real)
  → RelayWorker real (second wave)
  → ViabilityEvaluationConsumer (controlled rulebook evaluation port, real MCDA domain)
  → Evaluation results persisted in PostgreSQL (transactional.evaluation_results)
  → Saga reaches EVALUACION_COMPLETADA in PostgreSQL
  → GET /evaluaciones/{id}/estado   (reads saga from real PostgreSQL)
  → GET /evaluaciones/{id}/resultado-mcda  (reads evaluation_results from real PostgreSQL)

Infrastructure used (real):
- PostgreSQL via pg_migrated (alembic downgrade base → upgrade head)
- RelayWorker (real implementation, uses WITH FOR UPDATE SKIP LOCKED)
- InMemoryEventBus (real, synchronous)
- transactional.outbox_messages, evaluation_sagas, agroenv_vectors, evaluation_results in PostgreSQL

Controlled (to avoid external services):
- ControlledExtractionClient — returns deterministic values, never calls GEE
- ControlledRulebookReadModelPort — returns RequiredExtractionSpec without DB read
- ControlledParcelGeometryPort — returns GeoJSON snapshot without DB read (avoids PostGIS insert)
- ControlledRulebookEvaluationPort — returns RulebookEvaluationData without DB read

NOT used: GEE, LLM, Recommendation, DDL manual, LockFreeRelayWorker,
          asyncpg, AsyncSession, Celery, Kafka, Redis, RabbitMQ.
"""

from __future__ import annotations

import inspect
import sys
from datetime import date
from typing import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.application.ports import (
    ExtractionClientResult,
    ExtractionRequest,
)
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
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
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    get_current_user as get_evaluation_current_user,
)
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import (
    get_evaluation_query_service,
    get_process_manager,
)
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


# ──────────────────────────── deterministic fixture data ──────────────────────

CROP_MAIZ = "maiz_amarillo_duro"
CROP_PAPA = "papa"
_PHASE = "vegetativo"
_P1 = "2026-Q1"
_P2 = "2026-Q2"
TEMPORAL_WINDOW = {"start": "2026-03-01", "end": "2026-08-31"}

# Fixed UUIDs for parcel and requester — these are never persisted to PostgreSQL
# because ControlledParcelGeometryPort bypasses the DB lookup.
_PARCEL_ID = UUID("aaaaaaaa-bbbb-4000-8000-cccccccccccc")
_REQUESTED_BY = UUID("dddddddd-eeee-4000-8000-ffffffffffff")


class _AuthenticatedUserStub:
    """Authenticated user double whose id matches the saga's requested_by."""

    def __init__(self, user_id: UUID, role: Role = Role.USUARIO_AGRICOLA) -> None:
        self.id = user_id
        self.role = role


def _fake_evaluation_user() -> _AuthenticatedUserStub:
    return _AuthenticatedUserStub(_REQUESTED_BY)

# Valid WGS-84 MultiPolygon (Perú coastal region) — returned by controlled port
_PARCEL_GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [-75.0, -10.0],
                [-75.0, -10.5],
                [-74.5, -10.5],
                [-74.5, -10.0],
                [-75.0, -10.0],
            ]
        ]
    ],
}

# Deterministic extraction values (same as 25A for reproducibility):
# maiz/temperatura TRAPEZOIDAL(18,22,30,35): both periods in plateau → membership 1.0
# maiz/precipitacion TRAPEZOIDAL(400,600,900,1100): Q1=800mm→1.0, Q2=480mm→0.4
#   WGM_precip = sqrt(1.0 * 0.4) ≈ 0.632; score_maiz ≈ 1.0^0.6 * 0.632^0.4 ≈ 0.793 → VIABLE rank 1
#   gap: precipitacion Q2 480mm < optimal 600mm → gap_value = -120mm
# papa/temperatura TRAPEZOIDAL(10,14,18,22): Q1=20°C→0.5, Q2=21°C→0.25
#   WGM_temp = sqrt(0.5*0.25) ≈ 0.354; score_papa ≈ 0.354^0.6 ≈ 0.536 → CONDICIONAL rank 2
#   gap: temperatura Q2 21°C > optimal 18°C → gap_value = +3°C
_CONTROLLED_VALUES: dict[tuple[str, str, str], float] = {
    (CROP_MAIZ, "temperatura_media", _P1): 26.0,
    (CROP_MAIZ, "temperatura_media", _P2): 28.0,
    (CROP_MAIZ, "precipitacion_acumulada", _P1): 800.0,
    (CROP_MAIZ, "precipitacion_acumulada", _P2): 480.0,
    (CROP_PAPA, "temperatura_media", _P1): 20.0,
    (CROP_PAPA, "temperatura_media", _P2): 21.0,
    (CROP_PAPA, "precipitacion_acumulada", _P1): 750.0,
    (CROP_PAPA, "precipitacion_acumulada", _P2): 650.0,
}

_RULEBOOK_ID_MAIZ = UUID("11111111-0000-4000-8000-000000000001")
_RULEBOOK_ID_PAPA = UUID("22222222-0000-4000-8000-000000000002")

_TEMPORAL_PERIODS = [
    {"period_key": _P1, "temporal_weight": 0.5},
    {"period_key": _P2, "temporal_weight": 0.5},
]


# ──────────────────────────── controlled ports ────────────────────────────────


class ControlledExtractionClient:
    """Returns pre-defined values per (crop_id, variable_name, period_key); never calls GEE."""

    def __init__(self) -> None:
        self.call_count = 0

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        self.call_count += 1
        value = _CONTROLLED_VALUES.get((request.crop_id, request.variable_name, request.period_key))
        if value is None:
            return None
        return ExtractionClientResult(
            value=value,
            source="controlled_pg_e2e_fixture",
            extraction_date=date(2026, 6, 1),
        )


class ControlledRulebookReadModelPort:
    """Returns RequiredExtractionSpec for maiz/papa without reading DB."""

    def get_required_extraction_spec(
        self,
        crop_candidates: list[str],
        temporal_window: dict,
    ) -> RequiredExtractionSpec:
        variables: list[RequiredVariableForEvaluation] = []
        for crop_id in crop_candidates:
            variables.extend(_required_variables_for_crop(crop_id))
        return RequiredExtractionSpec(variables=variables)


class ControlledParcelGeometryPort:
    """Returns fixed MultiPolygon snapshot without DB read (avoids PostGIS geometry insert)."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry=_PARCEL_GEOMETRY)


class ControlledRulebookEvaluationPort:
    """Returns RulebookEvaluationData for maiz/papa without DB read or LLM call."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        if crop_id == CROP_MAIZ:
            return _rulebook_maiz()
        if crop_id == CROP_PAPA:
            return _rulebook_papa()
        raise ValueError(f"No controlled rulebook for crop: {crop_id}")


# ──────────────────────────── saga driver ────────────────────────────────────


def drive_saga_to_completion(
    relay: RelayWorker,
    session_factory: sessionmaker,
    evaluation_id: UUID,
    target_statuses: frozenset[str] | None = None,
    max_waves: int = 10,
) -> str:
    """Drive the real RelayWorker until the saga reaches a terminal MCDA status.

    Calls relay.process_batch() repeatedly. After each wave reads the saga status
    from PostgreSQL. Returns early when target status is reached or max_waves hit.
    """
    ready = target_statuses or frozenset({
        EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
        EvaluationSagaStatus.FALLIDA.value,
    })
    for _ in range(max_waves):
        relay.process_batch()
        with session_factory() as session:
            saga = session.get(EvaluationSagaModel, evaluation_id)
            if saga is not None and saga.status in ready:
                return saga.status
    with session_factory() as session:
        saga = session.get(EvaluationSagaModel, evaluation_id)
        return saga.status if saga else "NOT_FOUND"


# ──────────────────────────── session-scoped fixtures ─────────────────────────


@pytest.fixture(scope="session")
def pg25b_session_factory(pg_migrated):
    """Session factory bound to the real migrated PostgreSQL test database."""
    return sessionmaker(bind=pg_migrated, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session")
def pg25b_cleanup(pg_migrated, pg25b_session_factory):
    """Truncate all saga/outbox/result tables before the 25B E2E session.

    Ensures 25B starts with a clean state regardless of data left by earlier
    integration tests (e.g., 22B) in the same pytest session.
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
def pg25b_controlled_extraction_client():
    return ControlledExtractionClient()


@pytest.fixture(scope="session")
def pg25b_process_manager(pg25b_session_factory, pg25b_cleanup):
    return EvaluationProcessManager(
        session_factory=pg25b_session_factory,
        rulebook_read_model_port=ControlledRulebookReadModelPort(),
        parcel_geometry_read_model_port=ControlledParcelGeometryPort(),
    )


@pytest.fixture(scope="session")
def pg25b_extraction_consumer(pg25b_session_factory, pg25b_cleanup, pg25b_controlled_extraction_client):
    service = AgroenvExtractionCommandService(
        session_factory=pg25b_session_factory,
        extraction_client=pg25b_controlled_extraction_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


@pytest.fixture(scope="session")
def pg25b_evaluation_consumer(pg25b_session_factory, pg25b_cleanup):
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )
    service = ViabilityEvaluationCommandService(
        session_factory=pg25b_session_factory,
        rulebook_port=ControlledRulebookEvaluationPort(),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(pg25b_session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=settings,
    )
    return ViabilityEvaluationConsumer(service)


@pytest.fixture(scope="session")
def pg25b_event_bus(pg25b_process_manager, pg25b_extraction_consumer, pg25b_evaluation_consumer):
    """Real InMemoryEventBus with handlers for extraction and evaluation (no Recommendation)."""
    bus = InMemoryEventBus()
    pm_handler = EvaluationProcessManagerEventHandler(pg25b_process_manager)
    bus.register(VECTOR_AGROAMBIENTAL_GENERADO, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_COMPLETADA, pm_handler)
    bus.register(EXTRACCION_FALLIDA, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_FALLIDA, pm_handler)
    bus.register(RECOMENDACION_GENERADA, pm_handler)
    bus.register(RECOMENDACION_FALLIDA, pm_handler)
    bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, pg25b_extraction_consumer.handle)
    bus.register(EJECUTAR_EVALUACION_VIABILIDAD, pg25b_evaluation_consumer.handle)
    return bus


@pytest.fixture(scope="session")
def pg25b_relay(pg25b_session_factory, pg25b_event_bus, pg25b_cleanup):
    """Real RelayWorker using PostgreSQL FOR UPDATE SKIP LOCKED; driven manually."""
    return RelayWorker(
        session_factory=pg25b_session_factory,
        event_bus=pg25b_event_bus,
        batch_size=20,
    )


@pytest.fixture(scope="session")
def pg25b_client(pg25b_process_manager, pg25b_session_factory, pg25b_cleanup):
    """FastAPI TestClient with process manager and query service bound to real PostgreSQL."""
    from via.main import app

    def _pm_dep():
        return pg25b_process_manager

    def _qs_dep() -> Generator[EvaluationQueryService, None, None]:
        session = pg25b_session_factory()
        try:
            yield EvaluationQueryService(EvaluationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_process_manager] = _pm_dep
    app.dependency_overrides[get_evaluation_query_service] = _qs_dep
    app.dependency_overrides[get_evaluation_current_user] = _fake_evaluation_user
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_process_manager, None)
        app.dependency_overrides.pop(get_evaluation_query_service, None)
        app.dependency_overrides.pop(get_evaluation_current_user, None)


@pytest.fixture(scope="session")
def completed_pg_e2e_evaluation(pg25b_client, pg25b_relay, pg25b_session_factory):
    """Run one full MCDA E2E evaluation on real PostgreSQL; shared by all test functions.

    The evaluation drives through the full saga:
      POST /evaluaciones → outbox → relay → extraction → outbox → relay → MCDA → EVALUACION_COMPLETADA
    All state is persisted to PostgreSQL. Results are verified via HTTP endpoints.
    """
    response = pg25b_client.post(
        "/evaluaciones",
        json={
            "parcel_id": str(_PARCEL_ID),
            "crop_candidates": [CROP_MAIZ, CROP_PAPA],
            "temporal_window": TEMPORAL_WINDOW,
        },
    )
    assert response.status_code == 202, f"POST /evaluaciones failed: {response.text}"
    evaluation_id = UUID(response.json()["evaluation_id"])

    final_status = drive_saga_to_completion(pg25b_relay, pg25b_session_factory, evaluation_id)

    estado_response = pg25b_client.get(f"/evaluaciones/{evaluation_id}/estado")
    mcda_response = pg25b_client.get(f"/evaluaciones/{evaluation_id}/resultado-mcda")

    return {
        "evaluation_id": evaluation_id,
        "final_status": final_status,
        "estado_response": estado_response,
        "mcda_response": mcda_response,
    }


# ──────────────────────────── required tests (8 minimum) ─────────────────────


def test_postgres_e2e_evaluation_reaches_completed_state(completed_pg_e2e_evaluation) -> None:
    """Saga must reach EVALUACION_COMPLETADA (not FALLIDA) for MCDA results to be available."""
    assert completed_pg_e2e_evaluation["final_status"] == EvaluationSagaStatus.EVALUACION_COMPLETADA.value, (
        f"Saga did not reach EVALUACION_COMPLETADA; final status: {completed_pg_e2e_evaluation['final_status']}"
    )


def test_postgres_e2e_resultado_mcda_returns_persisted_results(
    completed_pg_e2e_evaluation, pg25b_session_factory
) -> None:
    """Results must be persisted to PostgreSQL and served by the query endpoint, not in-memory."""
    assert completed_pg_e2e_evaluation["mcda_response"].status_code == 200, (
        f"GET resultado-mcda returned {completed_pg_e2e_evaluation['mcda_response'].status_code}: "
        f"{completed_pg_e2e_evaluation['mcda_response'].text}"
    )
    evaluation_id = completed_pg_e2e_evaluation["evaluation_id"]
    session = pg25b_session_factory()
    try:
        repo = EvaluationQueryRepository(session)
        crop_results = repo.find_crop_results(evaluation_id)
    finally:
        session.close()
    assert len(crop_results) >= 2, (
        f"Expected ≥2 persisted crop results in PostgreSQL, got {len(crop_results)}"
    )
    stored_ids = {r.crop_id for r in crop_results}
    assert CROP_MAIZ in stored_ids, f"maiz not in persisted results: {stored_ids}"
    assert CROP_PAPA in stored_ids, f"papa not in persisted results: {stored_ids}"


def test_postgres_e2e_result_contains_ranking(completed_pg_e2e_evaluation) -> None:
    """At least two crops must have rank_position assigned after MCDA evaluation."""
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    ranked = [r for r in results if r.get("rank_position") is not None]
    assert len(ranked) >= 2, f"Expected ≥2 crops with rank_position, got: {ranked}"


def test_postgres_e2e_result_contains_agronomic_gaps(completed_pg_e2e_evaluation) -> None:
    """At least one agronomic gap with most_limiting_period must exist in the results."""
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    gaps_with_period = [
        gap
        for r in results
        for gap in r.get("gaps", [])
        if gap.get("most_limiting_period")
    ]
    assert len(gaps_with_period) >= 1, (
        "Expected ≥1 agronomic gap with most_limiting_period in results"
    )


def test_postgres_e2e_outbox_messages_are_dispatched(completed_pg_e2e_evaluation, pg_migrated) -> None:
    """All outbox messages for this evaluation must be DISPATCHED in PostgreSQL."""
    evaluation_id = completed_pg_e2e_evaluation["evaluation_id"]
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


def test_postgres_e2e_uses_real_relay_not_lockfree(completed_pg_e2e_evaluation, pg25b_relay) -> None:
    """The relay must be the real RelayWorker with FOR UPDATE SKIP LOCKED, not LockFreeRelayWorker."""
    source = inspect.getsource(pg25b_relay._load_pending)
    assert "with_for_update" in source, "RelayWorker._load_pending must use with_for_update"
    assert "skip_locked" in source, "RelayWorker._load_pending must use skip_locked=True"
    assert type(pg25b_relay).__name__ == "RelayWorker", (
        f"Expected RelayWorker, got {type(pg25b_relay).__name__} — "
        "LockFreeRelayWorker must not be used in lote 25B"
    )


def test_postgres_e2e_does_not_call_gee_or_llm(completed_pg_e2e_evaluation) -> None:
    """No GEE or LLM module must be imported during the PostgreSQL E2E evaluation."""
    for mod_name in sys.modules:
        assert "earthengine" not in mod_name, f"earthengine module was imported: {mod_name}"
        assert mod_name != "ee", "ee (earthengine-api) module was imported"
    llm_indicators = ("openai", "anthropic", "google.generativeai", "vertexai", "transformers")
    for mod_name in sys.modules:
        for indicator in llm_indicators:
            assert not mod_name.startswith(indicator), f"LLM module imported: {mod_name}"


def test_postgres_e2e_does_not_create_tables_manually() -> None:
    """Structural check: tables come from Alembic ORM models, not hand-written DDL.

    Uses AST to detect actual execute()/text() calls with DDL string arguments.
    Then verifies via ORM metadata that the expected tables are registered (i.e.,
    they exist in Alembic migrations and not as manual CREATE TABLE statements).
    This avoids self-referential false positives from naive string scanning.
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
    # Positive check: ORM models are registered via Alembic, not hand-created
    import via.shared.database.models  # noqa: F401 — side-effect: registers all ORM models
    from via.shared.database.base import Base
    _table_names = {t.name for t in Base.metadata.sorted_tables}
    assert "outbox_messages" in _table_names, "outbox_messages not found in ORM metadata"
    assert "evaluation_sagas" in _table_names, "evaluation_sagas not found in ORM metadata"
    assert "evaluation_results" in _table_names, "evaluation_results not found in ORM metadata"


# ──────────────────────────── additional validation tests ─────────────────────


def test_postgres_e2e_estado_endpoint_returns_200(completed_pg_e2e_evaluation) -> None:
    assert completed_pg_e2e_evaluation["estado_response"].status_code == 200


def test_postgres_e2e_estado_reflects_evaluacion_completada(completed_pg_e2e_evaluation) -> None:
    body = completed_pg_e2e_evaluation["estado_response"].json()
    assert body["status"] == EvaluationSagaStatus.EVALUACION_COMPLETADA.value


def test_postgres_e2e_maiz_rank_position_1(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    assert maiz["rank_position"] == 1, f"maiz rank_position={maiz['rank_position']}, expected 1"


def test_postgres_e2e_papa_rank_position_2(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    assert papa["rank_position"] == 2, f"papa rank_position={papa['rank_position']}, expected 2"


def test_postgres_e2e_maiz_viability_is_viable(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    assert maiz["viability_category"] == "VIABLE", f"maiz viability_category={maiz['viability_category']}"


def test_postgres_e2e_papa_viability_is_condicional(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    assert papa["viability_category"] == "CONDICIONAL", f"papa viability_category={papa['viability_category']}"


def test_postgres_e2e_maiz_score_greater_than_papa(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    papa = _find_crop(results, CROP_PAPA)
    assert maiz["score"] > papa["score"], (
        f"maiz score={maiz['score']} should be > papa score={papa['score']}"
    )


def test_postgres_e2e_precipitation_gap_exists_for_maiz(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    maiz = _find_crop(results, CROP_MAIZ)
    precip_gaps = [g for g in maiz["gaps"] if g["criterion_id"] == "precipitacion"]
    assert len(precip_gaps) >= 1, "maiz should have a precipitation gap (Q2=480mm < optimal 600mm)"
    gap = precip_gaps[0]
    assert gap["gap_value"] < 0, f"maiz precipitation gap should be negative (deficit), got {gap['gap_value']}"


def test_postgres_e2e_temperature_gap_exists_for_papa(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    papa = _find_crop(results, CROP_PAPA)
    temp_gaps = [g for g in papa["gaps"] if g["criterion_id"] == "temperatura"]
    assert len(temp_gaps) >= 1, "papa should have a temperature gap (Q2=21°C > optimal 18°C)"
    gap = temp_gaps[0]
    assert gap["gap_value"] > 0, f"papa temperature gap should be positive (excess), got {gap['gap_value']}"


def test_postgres_e2e_no_recommendation_field_in_response(completed_pg_e2e_evaluation) -> None:
    body = completed_pg_e2e_evaluation["mcda_response"].json()
    assert "recommendation" not in body, "resultado-mcda must not expose Recommendation"
    assert "recommendations" not in body, "resultado-mcda must not expose Recommendation"


def test_postgres_e2e_controlled_extraction_was_called(
    completed_pg_e2e_evaluation, pg25b_controlled_extraction_client
) -> None:
    assert pg25b_controlled_extraction_client.call_count > 0, (
        "ControlledExtractionClient.extract_variable was never called — extraction did not run"
    )


def test_postgres_e2e_all_gaps_have_required_fields(completed_pg_e2e_evaluation) -> None:
    results = completed_pg_e2e_evaluation["mcda_response"].json()["results"]
    required = {"criterion_id", "phase_id", "most_limiting_period", "observed_value", "optimal_limit", "gap_value"}
    for r in results:
        for gap in r.get("gaps", []):
            missing = required - set(gap.keys())
            assert not missing, f"{r['crop_id']} gap missing fields: {missing}"


# ──────────────────────────── helpers ────────────────────────────────────────


def _find_crop(results: list[dict], crop_id: str) -> dict:
    for r in results:
        if r["crop_id"] == crop_id:
            return r
    raise AssertionError(f"Crop '{crop_id}' not found in results: {[r['crop_id'] for r in results]}")


def _required_variables_for_crop(crop_id: str) -> list[RequiredVariableForEvaluation]:
    return [
        RequiredVariableForEvaluation(
            variable_name="temperatura_media",
            criterion_id="temperatura",
            crop_id=crop_id,
            phase_id=_PHASE,
            dataset_key="ERA5",
            band="mean_2m_air_temperature",
            unit="°C",
            temporal_resolution="monthly",
            reducer="mean",
            aggregation_method="mean",
            fallback_allowed=True,
            temporal_periods=_TEMPORAL_PERIODS,
        ),
        RequiredVariableForEvaluation(
            variable_name="precipitacion_acumulada",
            criterion_id="precipitacion",
            crop_id=crop_id,
            phase_id=_PHASE,
            dataset_key="CHIRPS",
            band="precipitation",
            unit="mm",
            temporal_resolution="monthly",
            reducer="sum",
            aggregation_method="sum",
            fallback_allowed=True,
            temporal_periods=_TEMPORAL_PERIODS,
        ),
    ]


def _rulebook_maiz() -> RulebookEvaluationData:
    return RulebookEvaluationData(
        crop_id=CROP_MAIZ,
        rulebook_id=_RULEBOOK_ID_MAIZ,
        version=1,
        criteria=[
            EvaluationCriterionSpec(
                criterion_id="temperatura",
                crop_id=CROP_MAIZ,
                phase_id=_PHASE,
                variable_name="temperatura_media",
                w_ahp=0.6,
                phase_weight=1.0,
                temporal_periods=_TEMPORAL_PERIODS,
                membership_fn={"type": "TRAPEZOIDAL", "a": 18.0, "b": 22.0, "c": 30.0, "d": 35.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="25B E2E fixture — Maiz temperatura",
            ),
            EvaluationCriterionSpec(
                criterion_id="precipitacion",
                crop_id=CROP_MAIZ,
                phase_id=_PHASE,
                variable_name="precipitacion_acumulada",
                w_ahp=0.4,
                phase_weight=1.0,
                temporal_periods=_TEMPORAL_PERIODS,
                membership_fn={"type": "TRAPEZOIDAL", "a": 400.0, "b": 600.0, "c": 900.0, "d": 1100.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="25B E2E fixture — Maiz precipitacion",
            ),
        ],
    )


def _rulebook_papa() -> RulebookEvaluationData:
    return RulebookEvaluationData(
        crop_id=CROP_PAPA,
        rulebook_id=_RULEBOOK_ID_PAPA,
        version=1,
        criteria=[
            EvaluationCriterionSpec(
                criterion_id="temperatura",
                crop_id=CROP_PAPA,
                phase_id=_PHASE,
                variable_name="temperatura_media",
                w_ahp=0.6,
                phase_weight=1.0,
                temporal_periods=_TEMPORAL_PERIODS,
                membership_fn={"type": "TRAPEZOIDAL", "a": 10.0, "b": 14.0, "c": 18.0, "d": 22.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="25B E2E fixture — Papa temperatura",
            ),
            EvaluationCriterionSpec(
                criterion_id="precipitacion",
                crop_id=CROP_PAPA,
                phase_id=_PHASE,
                variable_name="precipitacion_acumulada",
                w_ahp=0.4,
                phase_weight=1.0,
                temporal_periods=_TEMPORAL_PERIODS,
                membership_fn={"type": "TRAPEZOIDAL", "a": 400.0, "b": 600.0, "c": 900.0, "d": 1100.0},
                critical_policy="NONE",
                penalty_factor=None,
                doc_source="25B E2E fixture — Papa precipitacion",
            ),
        ],
    )
