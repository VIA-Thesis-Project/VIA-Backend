"""Demo script: Leaflet GeoJSON → GEE real → resultado MCDA (Lote 28A).

Simula el flujo completo que un frontend Leaflet ejecutaría para obtener
una evaluación agroambiental real:

  1. Registra una parcela en PostgreSQL (geometría GeoJSON [lng, lat])
  2. Crea y publica un rulebook mínimo de NIR (Sentinel-2 B8)
  3. Inicia una evaluación vía POST /evaluaciones (in-process con TestClient)
  4. Ejecuta la saga: GEE real → MCDA difuso → EVALUACION_COMPLETADA
  5. Consulta GET /evaluaciones/{id}/resultado-mcda → imprime ranking + brechas

Requisitos:
  - DATABASE_URL (postgresql+psycopg2://...)
  - GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE
  - Migraciones aplicadas: alembic upgrade head

Uso:
  export DATABASE_URL=postgresql+psycopg2://via:pass@localhost:5432/via_test
  export GEE_PROJECT=tu-proyecto
  export GEE_SERVICE_ACCOUNT=tu-cuenta@proyecto.iam.gserviceaccount.com
  export GEE_PRIVATE_KEY_FILE=/ruta/al/keyfile.json
  python scripts/leaflet_to_gee_mcda_demo.py

Seguridad:
  - No se incluyen credenciales en este archivo
  - No imprimir el contenido de GEE_PRIVATE_KEY_FILE
  - No rutas absolutas de usuario en el código
"""

from __future__ import annotations

import json
import os
import sys
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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


# ──────────────────────────── configuración del demo ─────────────────────────

_CROP_ID = "leaflet_demo_crop"
_OWNER_ID = UUID("de000001-0000-4000-8000-000000000028")

# GeoJSON [lng, lat] — polígono ~100 m × 100 m cerca de Lima, Perú
# (Leaflet usa [lat, lng]; GeoJSON requiere [lng, lat] — la conversión es obligatoria)
_POLYGON_GEOJSON = {
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

_TEMPORAL_WINDOW = {"start": "2024-06-01", "end": "2024-08-31"}

_CRITERION_ID = UUID("de001001-0000-4000-8000-000000000028")
_PHASE_ID = UUID("de002001-0000-4000-8000-000000000028")
_REQUIREMENT_ID = UUID("de003001-0000-4000-8000-000000000028")

_MCDA_SETTINGS = McdaRuntimeSettings(
    mcda_alpha=0.7,
    mcda_min_temporal_series_length=3,
    mcda_entropy_min_divergence=1e-9,
    mcda_viable_threshold=0.70,
    mcda_condicional_threshold=0.40,
    mcda_penalize_epsilon=0.01,
)


# ──────────────────────────── validación de entorno ──────────────────────────


def _check_env() -> None:
    """Verificar que las variables de entorno necesarias estén configuradas."""
    required = ["DATABASE_URL", "GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Faltan variables de entorno requeridas: {', '.join(missing)}")
        print()
        print("Configura las variables antes de ejecutar el script:")
        print("  export DATABASE_URL=postgresql+psycopg2://via:pass@localhost:5432/via_test")
        print("  export GEE_PROJECT=tu-proyecto")
        print("  export GEE_SERVICE_ACCOUNT=tu-cuenta@proyecto.iam.gserviceaccount.com")
        print("  export GEE_PRIVATE_KEY_FILE=/ruta/al/keyfile.json")
        sys.exit(1)

    db_url = os.environ["DATABASE_URL"]
    if "psycopg2" not in db_url:
        print("[ERROR] DATABASE_URL debe usar el driver psycopg2.")
        print("  Ejemplo: postgresql+psycopg2://usuario:pass@localhost:5432/via_test")
        sys.exit(1)

    db_name = db_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name.lower():
        print(f"[ERROR] Seguridad: DATABASE_URL debe apuntar a una base de datos de prueba.")
        print(f"  El nombre de la base de datos debe contener 'test'. Nombre detectado: '{db_name}'")
        sys.exit(1)


# ──────────────────────────── construcción del rulebook ──────────────────────


def _build_rulebook_objects():
    """Construye los objetos de dominio para el rulebook mínimo de NIR (B8 Sentinel-2)."""
    criterion = Criterion(
        id=_CRITERION_ID,
        name="vigor_nir",
        is_critical=False,
        critical_policy=None,
        penalty_factor=None,
        ahp_weight=1.0,
        doc_source="Sentinel-2 SR NIR B8 — demo 28A",
    )
    phase = PhenologicalPhase(
        id=_PHASE_ID,
        name="desarrollo",
        duration_days=90,
        sequence_order=1,
    )
    # Membresía TRAPEZOIDAL ancha: acepta cualquier DN válido de B8 [100, 9900] con membresía 1.0
    requirement = PhaseRequirement(
        id=_REQUIREMENT_ID,
        criterion_id=_CRITERION_ID,
        phase_id=_PHASE_ID,
        membership_fn=MembershipFunction(a=0.0, b=100.0, c=9900.0, d=10001.0),
        phase_weight=1.0,
        temporal_periods=[
            TemporalPeriod(period_key="2024-Q2", temporal_weight=0.6),
            TemporalPeriod(period_key="2024-Q3", temporal_weight=0.4),
        ],
        extraction_binding=ExtractionBinding(
            variable_name="nir_reflectancia",
            dataset_key="COPERNICUS/S2_SR_HARMONIZED",
            band="B8",
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


# ──────────────────────────── lógica principal ───────────────────────────────


def run_demo() -> None:
    _check_env()

    database_url = os.environ["DATABASE_URL"]
    overrides = {**os.environ, "GEE_ENABLED": "true"}
    settings = load_settings(overrides)

    print("[1/7] Conectando a PostgreSQL y preparando session factory...")
    engine = create_engine(database_url, echo=False)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    print("[2/7] Limpiando tablas transaccionales (TRUNCATE CASCADE)...")
    with engine.begin() as conn:
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

    print("[3/7] Registrando parcela Leaflet en PostgreSQL...")
    print(f"      Geometría: Polygon GeoJSON [lng, lat] ~ Lima, Perú")
    session = session_factory()
    try:
        parcel_repo = SQLAlchemyParcelRepository(session)
        validator = ParcelGeometryValidator(max_area_ha=10_000.0)
        parcel_service = ParcelCommandService(parcel_repository=parcel_repo, geometry_validator=validator)
        parcel = parcel_service.register_parcel(
            owner_id=_OWNER_ID,
            geometry=_POLYGON_GEOJSON,
            metadata={
                "name": "Parcela Leaflet Demo 28A",
                "description": "Parcela de prueba GEE real Lote 28A",
                "crs": "EPSG:4326",
            },
        )
        session.commit()
        parcel_id = parcel.id
    finally:
        session.close()
    print(f"      parcel_id = {parcel_id}")

    print("[4/7] Creando y publicando rulebook NIR en PostgreSQL...")
    criterion, phase, requirement = _build_rulebook_objects()
    session = session_factory()
    try:
        rulebook_repo = SqlAlchemyRulebookRepository(session)
        rulebook_service = RulebookCommandService(repository=rulebook_repo)
        rulebook = rulebook_service.create_rulebook(
            crop_id=_CROP_ID,
            criteria=[criterion],
            phases=[phase],
            phase_requirements=[requirement],
        )
        session.commit()
        rulebook_service.publish_rulebook(rulebook.id)
        session.commit()
        rulebook_id = rulebook.id
    finally:
        session.close()
    print(f"      rulebook_id = {rulebook_id}  (status=ACTIVE)")

    print("[5/7] Construyendo componentes del sistema (bridges reales)...")
    gee_client = GeeExtractionClient(settings=settings)

    process_manager = EvaluationProcessManager(
        session_factory=session_factory,
        rulebook_read_model_port=SqlAlchemyRulebookReadModelBridge(session_factory),
        parcel_geometry_read_model_port=SqlAlchemyParcelGeometryBridge(session_factory),
    )

    extraction_consumer = AgroenvExtractionConsumer(
        AgroenvExtractionCommandService(
            session_factory=session_factory,
            extraction_client=gee_client,
            acl=ExtractionAcl(),
            repository_factory=lambda s: SqlAlchemyExtractionRepository(s),
        )
    )

    evaluation_consumer = ViabilityEvaluationConsumer(
        ViabilityEvaluationCommandService(
            session_factory=session_factory,
            rulebook_port=SqlAlchemyRulebookEvaluationBridge(session_factory),
            agroenv_vector_port=SqlAlchemyAgroenvVectorBridge(session_factory),
            repository_factory=lambda s: EvaluationRepository(s),
            settings=_MCDA_SETTINGS,
        )
    )

    bus = InMemoryEventBus()
    pm_handler = EvaluationProcessManagerEventHandler(process_manager)
    bus.register(VECTOR_AGROAMBIENTAL_GENERADO, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_COMPLETADA, pm_handler)
    bus.register(EXTRACCION_FALLIDA, pm_handler)
    bus.register(EVALUACION_VIABILIDAD_FALLIDA, pm_handler)
    bus.register(RECOMENDACION_GENERADA, pm_handler)
    bus.register(RECOMENDACION_FALLIDA, pm_handler)
    bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, extraction_consumer.handle)
    bus.register(EJECUTAR_EVALUACION_VIABILIDAD, evaluation_consumer.handle)

    relay = RelayWorker(session_factory=session_factory, event_bus=bus, batch_size=20)

    print("[6/7] Iniciando evaluación y ejecutando saga (GEE real)...")

    from via.main import app

    def _pm_dep():
        return process_manager

    def _qs_dep():
        session = session_factory()
        try:
            yield EvaluationQueryService(EvaluationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_process_manager] = _pm_dep
    app.dependency_overrides[get_evaluation_query_service] = _qs_dep

    evaluation_id: UUID | None = None
    final_status: str = "NOT_STARTED"

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/evaluaciones",
                json={
                    "parcel_id": str(parcel_id),
                    "requested_by": str(_OWNER_ID),
                    "crop_candidates": [_CROP_ID],
                    "temporal_window": _TEMPORAL_WINDOW,
                },
            )
            if resp.status_code != 202:
                print(f"[ERROR] POST /evaluaciones falló: {resp.status_code} {resp.text}")
                sys.exit(1)

            evaluation_id = UUID(resp.json()["evaluation_id"])
            print(f"      evaluation_id = {evaluation_id}")

            target = frozenset({
                EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
                EvaluationSagaStatus.FALLIDA.value,
            })

            print("      Ejecutando waves del relay worker...")
            for wave in range(1, 13):
                relay.process_batch()
                with session_factory() as s:
                    saga = s.get(EvaluationSagaModel, evaluation_id)
                    if saga is not None and saga.status in target:
                        final_status = saga.status
                        print(f"      Wave {wave}: saga → {final_status}")
                        break
                print(f"      Wave {wave}: saga en progreso...")
            else:
                with session_factory() as s:
                    saga = s.get(EvaluationSagaModel, evaluation_id)
                    final_status = saga.status if saga else "NOT_FOUND"

            print(f"\n[7/7] Consultando resultado MCDA (estado final: {final_status})...")
            mcda_resp = client.get(f"/evaluaciones/{evaluation_id}/resultado-mcda")

    finally:
        app.dependency_overrides.pop(get_process_manager, None)
        app.dependency_overrides.pop(get_evaluation_query_service, None)
        engine.dispose()

    print(f"      HTTP {mcda_resp.status_code}")
    print()

    if mcda_resp.status_code != 200:
        print(f"[AVISO] resultado-mcda retornó {mcda_resp.status_code}:")
        print(mcda_resp.text)
    else:
        result = mcda_resp.json()
        print("─" * 60)
        print(f"  Evaluación : {result.get('evaluation_id')}")
        print(f"  Estado     : {result.get('status')}")
        print()
        for crop_result in result.get("results", []):
            print(f"  Cultivo    : {crop_result['crop_id']}")
            print(f"  Score      : {crop_result.get('score', '?'):.4f}")
            print(f"  Posición   : {crop_result.get('rank_position', '?')}")
            print(f"  Categoría  : {crop_result.get('viability_category', '?')}")
            print(f"  Condición  : {crop_result.get('calc_condition', '?')}")
            gaps = crop_result.get("gaps", [])
            if gaps:
                print(f"  Brechas    : {len(gaps)} brecha(s)")
                for gap in gaps[:3]:
                    print(
                        f"    - {gap.get('criterion_id')} "
                        f"[{gap.get('most_limiting_period')}] "
                        f"observado={gap.get('observed_value')} "
                        f"gap={gap.get('gap_value')}"
                    )
        print("─" * 60)
        print()
        print("Resultado JSON completo:")
        print(json.dumps(result, indent=2, default=str))

    if final_status != EvaluationSagaStatus.EVALUACION_COMPLETADA.value:
        print(f"\n[AVISO] La saga terminó en '{final_status}' (no EVALUACION_COMPLETADA).")
        print("  Verifica los logs de extracción GEE y que el polígono tenga píxeles S2 válidos.")
        sys.exit(1)

    print("\n[OK] Demo completado exitosamente.")


if __name__ == "__main__":
    run_demo()
