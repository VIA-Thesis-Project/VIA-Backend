"""E2E test infrastructure for lote 25A: MCDA evaluation flow without GEE or Recommendation.

Uses a file-based SQLite database with an ATTACHed transactional schema so that
multiple SQLAlchemy sessions can operate on the same data concurrently (SQLite WAL mode).
Tables are created with hand-written SQL to bypass JSONB/UUID DDL incompatibility.
LockFreeRelayWorker removes WITH FOR UPDATE SKIP LOCKED which SQLite does not support.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone
from typing import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from via.bounded_contexts.agroenv_extraction.application.ports import (
    ExtractionClientResult,
    ExtractionRequest,
)
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
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
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import SqlAlchemyAgroenvVectorBridge


# ──────────────────────────── controlled fixture data ─────────────────────────

_PARCEL_ID = UUID("aaaaaaaa-bbbb-4000-8000-cccccccccccc")
_REQUESTED_BY = UUID("dddddddd-eeee-4000-8000-ffffffffffff")
_PHASE = "vegetativo"
_P1 = "2026-Q1"
_P2 = "2026-Q2"
CROP_MAIZ = "maiz_amarillo_duro"
CROP_PAPA = "papa"
TEMPORAL_WINDOW = {"start": "2026-03-01", "end": "2026-08-31"}


class _AuthenticatedUserStub:
    """Authenticated user double whose id matches the saga's requested_by."""

    def __init__(self, user_id: UUID, role: Role = Role.USUARIO_AGRICOLA) -> None:
        self.id = user_id
        self.role = role


def _fake_evaluation_user() -> _AuthenticatedUserStub:
    return _AuthenticatedUserStub(_REQUESTED_BY)

# GeoJSON MultiPolygon (Perú coastal coordinate, WGS-84 valid)
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

# Controlled values: (crop_id, variable_name, period_key) -> float
# These are independent of scripts/evaluation_smoke_test.py.
# maiz/temperatura in TRAPEZOIDAL(18,22,30,35): both periods in plateau → membership 1.0
# maiz/precipitacion in TRAPEZOIDAL(400,600,900,1100): Q1=800mm→1.0, Q2=480mm→0.4
#   WGM_precip = sqrt(1.0 * 0.4) ≈ 0.632; score_maiz ≈ 1.0^0.6 * 0.632^0.4 ≈ 0.793 → VIABLE rank 1
#   gap: precipitacion Q2 480mm < optimal 600mm → gap_value = -120mm
# papa/temperatura in TRAPEZOIDAL(10,14,18,22): Q1=20°C→0.5, Q2=21°C→0.25
#   WGM_temp = sqrt(0.5*0.25) ≈ 0.354; score_papa ≈ 0.354^0.6 ≈ 0.536 → CONDICIONAL rank 2
#   gap: temperatura Q2 21°C > optimal 18°C → gap_value = +3°C
# papa/precipitacion in TRAPEZOIDAL(400,600,900,1100): both 1.0 → no gap
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


# ──────────────────────── SQLite-compatible table creation ────────────────────

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS "transactional"."evaluation_sagas" (
    id TEXT PRIMARY KEY,
    parcel_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    crop_candidates TEXT NOT NULL,
    temporal_window TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS "transactional"."outbox_messages" (
    id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    message_type TEXT NOT NULL,
    message_kind TEXT NOT NULL CHECK (message_kind IN ('COMMAND', 'EVENT')),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'DISPATCHED', 'PERMANENT_FAILURE')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    correlation_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    dispatched_at TEXT,
    claimed_at TEXT
);

CREATE TABLE IF NOT EXISTS "transactional"."processed_message_ids" (
    message_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (message_id, consumer)
);

CREATE TABLE IF NOT EXISTS "transactional"."saga_transitions" (
    id TEXT PRIMARY KEY,
    saga_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    triggered_by TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
    failure_cause TEXT
);

CREATE TABLE IF NOT EXISTS "transactional"."agroenv_vectors" (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    parcel_id TEXT NOT NULL,
    temporal_window TEXT NOT NULL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS "transactional"."agroenv_variable_entries" (
    id TEXT PRIMARY KEY,
    vector_id TEXT NOT NULL,
    variable_name TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    crop_id TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    dataset_key TEXT NOT NULL,
    band TEXT NOT NULL,
    unit TEXT NOT NULL,
    temporal_resolution TEXT NOT NULL,
    spatial_resolution TEXT,
    scale REAL,
    reducer TEXT NOT NULL,
    aggregation_method TEXT NOT NULL,
    quality_mask TEXT,
    fallback_allowed INTEGER NOT NULL DEFAULT 0,
    value REAL,
    source TEXT NOT NULL,
    extraction_date TEXT NOT NULL,
    period_key TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS "transactional"."evaluation_results" (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    crop_id TEXT NOT NULL,
    score REAL,
    calc_condition TEXT NOT NULL,
    viability_category TEXT NOT NULL,
    rank_position INTEGER,
    rulebook_version INTEGER NOT NULL,
    entropy_used INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS "transactional"."evaluation_criterion_details" (
    id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    memberships_by_period TEXT NOT NULL,
    aggregated_by_phase TEXT NOT NULL,
    aggregated_membership REAL NOT NULL,
    w_ahp REAL NOT NULL,
    w_entropy REAL,
    w_hybrid REAL NOT NULL,
    entropy_series_used INTEGER NOT NULL,
    entropy_fallback_reason TEXT
);

CREATE TABLE IF NOT EXISTS "transactional"."agronomy_gaps" (
    id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    most_limiting_period TEXT NOT NULL,
    observed_value REAL NOT NULL,
    optimal_limit REAL NOT NULL,
    gap_value REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS "transactional"."limiting_factors" (
    id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    penalty_factor REAL,
    observed_value REAL NOT NULL,
    optimal_limit REAL NOT NULL,
    membership REAL NOT NULL,
    doc_source TEXT
);

CREATE TABLE IF NOT EXISTS "transactional"."recommendations" (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    crop_id TEXT NOT NULL,
    text TEXT NOT NULL,
    fragment_ids TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _create_tables(engine) -> None:
    with engine.connect() as conn:
        for stmt in _CREATE_TABLES_SQL.strip().split(";\n\n"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()


# ──────────────────────────── controlled stubs ────────────────────────────────


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
            source="controlled_e2e_fixture",
            extraction_date=date(2026, 6, 1),
        )


class ControlledRulebookReadModelPort:
    """Returns a hard-coded RequiredExtractionSpec for maiz and papa; never reads DB."""

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
    """Returns a fixed MultiPolygon snapshot; never reads DB."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        return ParcelGeometrySnapshot(parcel_id=parcel_id, geometry=_PARCEL_GEOMETRY)


class ControlledRulebookEvaluationPort:
    """Returns RulebookEvaluationData for maiz/papa; never reads DB or calls LLM."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        if crop_id == CROP_MAIZ:
            return _rulebook_maiz()
        if crop_id == CROP_PAPA:
            return _rulebook_papa()
        raise ValueError(f"No controlled rulebook for crop: {crop_id}")


# ──────────────────────────── relay without FOR UPDATE SKIP LOCKED ────────────


class LockFreeRelayWorker(RelayWorker):
    """RelayWorker subclass that omits FOR UPDATE SKIP LOCKED for SQLite compatibility."""

    def _load_pending(self, session: Session) -> list[OutboxMessageModel]:
        statement = (
            select(OutboxMessageModel)
            .where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
            .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
            .limit(self.batch_size)
        )
        return list(session.execute(statement).scalars().all())


# ──────────────────────────── saga driver helper ──────────────────────────────


def drive_saga_to_completion(
    relay: LockFreeRelayWorker,
    session_factory: sessionmaker,
    evaluation_id: UUID,
    target_statuses: frozenset[str] | None = None,
    max_waves: int = 8,
) -> str:
    """Drive the relay until the saga reaches a terminal MCDA status or max_waves."""
    ready = target_statuses or frozenset({
        EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
        EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value,
        EvaluationSagaStatus.FALLIDA.value,
    })
    for _ in range(max_waves):
        relay.process_batch()
        session = session_factory()
        try:
            saga = session.get(EvaluationSagaModel, evaluation_id)
            if saga is not None and saga.status in ready:
                return saga.status
        finally:
            session.close()
    session = session_factory()
    try:
        saga = session.get(EvaluationSagaModel, evaluation_id)
        return saga.status if saga else "NOT_FOUND"
    finally:
        session.close()


# ──────────────────────────── fixtures ────────────────────────────────────────


class _RelayWorkerDisabled:
    """Placeholder without start/stop so the app lifespan does not launch the
    background RelayWorker thread."""


@pytest.fixture(scope="session", autouse=True)
def disable_app_background_relay_worker():
    """Keep the module-level app's RelayWorker thread out of the E2E session.

    These tests relay outbox messages manually with LockFreeRelayWorker over
    SQLite. The app lifespan would otherwise start a background thread polling
    the DATABASE_URL database for the whole pytest session, interfering with
    any other test package that shares that database.
    """
    from via.main import app

    original = app.state.relay_worker
    app.state.relay_worker = _RelayWorkerDisabled()
    yield
    app.state.relay_worker = original


@pytest.fixture(scope="session")
def e2e_db_files():
    main_file = tempfile.mktemp(suffix="_via_e2e_main.db")
    trans_file = tempfile.mktemp(suffix="_via_e2e_trans.db")
    yield main_file, trans_file
    for path in (main_file, trans_file):
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture(scope="session")
def e2e_engine(e2e_db_files):
    main_file, trans_file = e2e_db_files
    engine = create_engine(f"sqlite:///{main_file}", echo=False, poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_conn, _):
        dbapi_conn.execute(f"ATTACH DATABASE '{trans_file}' AS transactional")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    _create_tables(engine)
    return engine


@pytest.fixture(scope="session")
def e2e_session_factory(e2e_engine):
    return sessionmaker(bind=e2e_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session")
def controlled_extraction_client():
    return ControlledExtractionClient()


@pytest.fixture(scope="session")
def e2e_process_manager(e2e_session_factory):
    return EvaluationProcessManager(
        session_factory=e2e_session_factory,
        rulebook_read_model_port=ControlledRulebookReadModelPort(),
        parcel_geometry_read_model_port=ControlledParcelGeometryPort(),
    )


@pytest.fixture(scope="session")
def e2e_extraction_consumer(e2e_session_factory, controlled_extraction_client):
    service = AgroenvExtractionCommandService(
        session_factory=e2e_session_factory,
        extraction_client=controlled_extraction_client,
        acl=ExtractionAcl(),
        repository_factory=lambda session: SqlAlchemyExtractionRepository(session),
    )
    return AgroenvExtractionConsumer(service)


@pytest.fixture(scope="session")
def e2e_evaluation_consumer(e2e_session_factory):
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )
    service = ViabilityEvaluationCommandService(
        session_factory=e2e_session_factory,
        rulebook_port=ControlledRulebookEvaluationPort(),
        agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(e2e_session_factory),
        repository_factory=lambda session: EvaluationRepository(session),
        settings=settings,
    )
    return ViabilityEvaluationConsumer(service)


@pytest.fixture(scope="session")
def e2e_event_bus(e2e_process_manager, e2e_extraction_consumer, e2e_evaluation_consumer):
    bus = InMemoryEventBus()
    pm_handler = EvaluationProcessManagerEventHandler(e2e_process_manager)
    bus.register(VECTOR_AGROAMBIENTAL_GENERADO, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_COMPLETADA, pm_handler)
    bus.register(EXTRACCION_FALLIDA, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_FALLIDA, pm_handler)
    bus.register(RECOMENDACION_GENERADA, pm_handler)
    bus.register(RECOMENDACION_FALLIDA, pm_handler)
    bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, e2e_extraction_consumer.handle)
    bus.register(EJECUTAR_EVALUACION_VIABILIDAD, e2e_evaluation_consumer.handle)
    return bus


@pytest.fixture(scope="session")
def e2e_relay(e2e_session_factory, e2e_event_bus):
    return LockFreeRelayWorker(
        session_factory=e2e_session_factory,
        event_bus=e2e_event_bus,
        batch_size=20,
    )


@pytest.fixture(scope="session")
def e2e_client(e2e_process_manager, e2e_session_factory):
    from via.main import app

    def _pm_dep():
        return e2e_process_manager

    def _qs_dep() -> Generator[EvaluationQueryService, None, None]:
        session = e2e_session_factory()
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
def completed_e2e_evaluation(e2e_client, e2e_relay, e2e_session_factory):
    """Run one full MCDA E2E evaluation; shared by all tests in the session."""
    response = e2e_client.post(
        "/evaluaciones",
        json={
            "parcel_id": str(_PARCEL_ID),
            "crop_candidates": [CROP_MAIZ, CROP_PAPA],
            "temporal_window": TEMPORAL_WINDOW,
        },
    )
    assert response.status_code == 202, f"POST /evaluaciones failed: {response.text}"
    data = response.json()
    evaluation_id = UUID(data["evaluation_id"])

    final_status = drive_saga_to_completion(e2e_relay, e2e_session_factory, evaluation_id)

    estado_response = e2e_client.get(f"/evaluaciones/{evaluation_id}/estado")
    mcda_response = e2e_client.get(f"/evaluaciones/{evaluation_id}/resultado-mcda")

    return {
        "evaluation_id": evaluation_id,
        "final_status": final_status,
        "estado_response": estado_response,
        "mcda_response": mcda_response,
    }


# ─────────────────────── controlled data helpers ──────────────────────────────


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
                doc_source="E2E fixture — Maíz temperatura",
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
                doc_source="E2E fixture — Maíz precipitacion",
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
                doc_source="E2E fixture — Papa temperatura",
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
                doc_source="E2E fixture — Papa precipitacion",
            ),
        ],
    )
