"""Process pending Outbox messages for a specific VIA evaluation.

Usage:
    python scripts/process_outbox_for_evaluation.py <evaluation_id> \\
        [--max-rounds N] [--pause-seconds N] [--until-completed] [--dry-run]

⚠  IMPORTANT: The RelayWorker processes ALL PENDING outbox messages globally,
   not only those belonging to the given evaluation_id.  The evaluation_id is
   used solely to display saga status and to filter the pre/post inspection of
   related messages.  If other evaluations have PENDING messages they will be
   processed in the same batches.

Requirements:
    DATABASE_URL            postgresql+psycopg2://...
    GEE_PROJECT             Google Earth Engine project id
    GEE_SERVICE_ACCOUNT     GEE service-account email
    GEE_PRIVATE_KEY_FILE    path to the GEE JSON key file

Example:
    $env:DATABASE_URL="postgresql+psycopg2://<user>:<password>@localhost:5433/via_test"
    $env:GEE_PROJECT="my-gcp-project"
    $env:GEE_SERVICE_ACCOUNT="sa@my-gcp-project.iam.gserviceaccount.com"
    $env:GEE_PRIVATE_KEY_FILE="C:/keys/gee-key.json"
    python scripts/process_outbox_for_evaluation.py c0345c1c-2085-41af-b3ac-82950ab276a2 --max-rounds 10 --pause-seconds 1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from via.bounded_contexts.agroenv_extraction.application.command_service import AgroenvExtractionCommandService
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_repository import SqlAlchemyExtractionRepository
from via.bounded_contexts.agroenv_extraction.infrastructure.gee_client import GeeExtractionClient
from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.viability_evaluation.application.command_service import (
    McdaRuntimeSettings,
    ViabilityEvaluationCommandService,
)
from via.bounded_contexts.viability_evaluation.application.query_service import EvaluationQueryService
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_query_repository import EvaluationQueryRepository
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
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
from via.shared.outbox.models import OutboxMessageModel, OutboxStatus
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.bridges import (
    SqlAlchemyAgroenvVectorBridge,
    SqlAlchemyParcelGeometryBridge,
    SqlAlchemyRulebookEvaluationBridge,
    SqlAlchemyRulebookReadModelBridge,
)


_TERMINAL_STATUSES: frozenset[str] = frozenset({
    EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
    EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value,
    EvaluationSagaStatus.FALLIDA.value,
})


# ─── Argument parsing ─────────────────────────────────────────────────────────


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"UUID inválido: {value!r}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="process_outbox_for_evaluation.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "evaluation_id",
        type=_parse_uuid,
        help="UUID de la evaluación (ej. c0345c1c-2085-41af-b3ac-82950ab276a2)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=10,
        metavar="N",
        help="Número máximo de rondas de procesamiento (default: 10)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        metavar="N",
        help="Pausa en segundos entre rondas (default: 2.0)",
    )
    parser.add_argument(
        "--until-completed",
        action="store_true",
        help="Detener cuando la saga llegue a un estado terminal",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sólo mostrar estado y mensajes pendientes; no procesar nada",
    )
    return parser.parse_args(argv)


# ─── Environment validation ───────────────────────────────────────────────────


def _check_env() -> None:
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("ERROR: DATABASE_URL es requerida.", file=sys.stderr)
        sys.exit(1)
    if not db_url.startswith("postgresql+psycopg2://"):
        print("ERROR: DATABASE_URL debe usar el esquema postgresql+psycopg2://", file=sys.stderr)
        sys.exit(1)

    gee_required = ["GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE"]
    missing = [v for v in gee_required if not os.environ.get(v, "").strip()]
    if missing:
        print(f"ERROR: Variables de GEE no configuradas: {', '.join(missing)}", file=sys.stderr)
        print(
            "       La extracción agroambiental (IniciarExtraccionAgroambiental) requiere\n"
            "       acceso real a Google Earth Engine.  Configura esas variables y vuelve\n"
            "       a intentarlo, o revisa el estado de GEE antes de procesar el Outbox.",
            file=sys.stderr,
        )
        sys.exit(1)


# ─── Inspection helpers ───────────────────────────────────────────────────────


def _print_saga_status(session_factory, evaluation_id: UUID, label: str) -> str | None:
    with session_factory() as session:
        saga = session.get(EvaluationSagaModel, evaluation_id)
    if saga is None:
        print(f"  [{label}] Saga no encontrada (evaluation_id={evaluation_id})")
        return None
    print(
        f"  [{label}] status={saga.status}"
        f"  parcel={saga.parcel_id}"
        f"  crops={saga.crop_candidates}"
    )
    return saga.status


def _print_pending_for_evaluation(session_factory, evaluation_id: UUID) -> int:
    with session_factory() as session:
        stmt = (
            select(OutboxMessageModel)
            .where(OutboxMessageModel.correlation_id == evaluation_id)
            .where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
            .order_by(OutboxMessageModel.created_at)
        )
        rows = list(session.execute(stmt).scalars().all())

    if not rows:
        print(f"  Sin mensajes PENDING en Outbox para correlation_id={evaluation_id}")
        return 0

    print(f"  Mensajes PENDING con correlation_id={evaluation_id}: {len(rows)}")
    for msg in rows:
        print(
            f"    id={msg.id}"
            f"  type={msg.message_type}"
            f"  kind={msg.message_kind}"
            f"  retry={msg.retry_count}"
        )
    return len(rows)


def _print_global_pending_warning(session_factory) -> int:
    with session_factory() as session:
        stmt = select(OutboxMessageModel).where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
        total = len(list(session.execute(stmt).scalars().all()))
    if total > 0:
        print(
            f"\n  ⚠  Total de mensajes PENDING globales en el Outbox: {total}"
            f"\n     El RelayWorker los procesará TODOS, no sólo los de esta evaluación."
        )
    return total


def _print_mcda_result(session_factory, evaluation_id: UUID) -> None:
    with session_factory() as session:
        service = EvaluationQueryService(EvaluationQueryRepository(session))
        result = service.get_mcda_result(evaluation_id)

    if result is None:
        print("  Resultado MCDA no encontrado (la evaluación puede no existir).")
        return

    if not result.results:
        print(f"  Resultado MCDA no disponible (status={result.status}  reason={result.failure_reason})")
        return

    sep = "─" * 52
    print(f"  {sep}")
    print(f"  Resultado MCDA  status={result.status}")
    for r in result.results:
        score_str = f"{r.score:.4f}" if r.score is not None else "N/A"
        print(f"    Cultivo   : {r.crop_id}")
        print(f"    Score     : {score_str}   Posición: {r.rank_position}   Cat: {r.viability_category}")
        if r.gaps:
            print(f"    Brechas   : {len(r.gaps)}")
            for gap in r.gaps[:3]:
                print(
                    f"      {gap.criterion_id}[{gap.most_limiting_period}]"
                    f"  obs={gap.observed_value:.2f}"
                    f"  gap={gap.gap_value:.2f}"
                )
    print(f"  {sep}")


# ─── Runtime construction ─────────────────────────────────────────────────────


def _build_relay(session_factory, settings) -> RelayWorker:
    """Build a RelayWorker wired with the real GEE extraction client."""

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
            settings=McdaRuntimeSettings.from_settings(settings),
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

    return RelayWorker(session_factory=session_factory, event_bus=bus, batch_size=20)


# ─── Processing loop ─────────────────────────────────────────────────────────


def run_rounds(
    relay: RelayWorker,
    session_factory,
    evaluation_id: UUID,
    max_rounds: int,
    pause_seconds: float,
    until_completed: bool,
) -> str | None:
    """Run up to max_rounds processing rounds; return the final saga status."""

    final_status: str | None = None

    for round_num in range(1, max_rounds + 1):
        print(f"\n[Ronda {round_num}/{max_rounds}] Procesando Outbox global...")
        processed = relay.process_batch()
        print(f"  Mensajes procesados en esta ronda : {processed}")

        with session_factory() as session:
            saga = session.get(EvaluationSagaModel, evaluation_id)
            status = saga.status if saga else "NOT_FOUND"

        print(f"  Estado de la saga                 : {status}")
        final_status = status

        if until_completed and status in _TERMINAL_STATUSES:
            print(f"  → Estado terminal alcanzado: {status}")
            break

        if round_num < max_rounds:
            time.sleep(pause_seconds)

    return final_status


# ─── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    evaluation_id: UUID = args.evaluation_id

    _check_env()

    database_url = os.environ["DATABASE_URL"]
    settings = load_settings({**os.environ, "GEE_ENABLED": "true"})

    print(f"\n=== VIA: Procesado manual del Outbox ===")
    print(f"  evaluation_id  : {evaluation_id}")
    print(f"  max_rounds     : {args.max_rounds}")
    print(f"  pause_seconds  : {args.pause_seconds}")
    print(f"  until_completed: {args.until_completed}")
    print(f"  dry_run        : {args.dry_run}")

    engine = create_engine(database_url, echo=False)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    try:
        print("\n── Estado inicial ─────────────────────────────────────────")
        _print_saga_status(session_factory, evaluation_id, "INICIAL")
        print()
        _print_pending_for_evaluation(session_factory, evaluation_id)
        _print_global_pending_warning(session_factory)

        if args.dry_run:
            print("\n[DRY-RUN] Modo inspección: no se procesará ningún mensaje.")
            return

        print()
        relay = _build_relay(session_factory, settings)

        final_status = run_rounds(
            relay=relay,
            session_factory=session_factory,
            evaluation_id=evaluation_id,
            max_rounds=args.max_rounds,
            pause_seconds=args.pause_seconds,
            until_completed=args.until_completed,
        )

        print("\n── Estado final ───────────────────────────────────────────")
        _print_saga_status(session_factory, evaluation_id, "FINAL")
        print()
        _print_mcda_result(session_factory, evaluation_id)

    finally:
        engine.dispose()

    if final_status == EvaluationSagaStatus.EVALUACION_COMPLETADA.value:
        print("\n[OK] Evaluación completada.")
    elif final_status == EvaluationSagaStatus.FALLIDA.value:
        print(
            "\n[ERROR] La saga terminó en estado FALLIDA.\n"
            "        Revisá los logs de GEE y que la parcela tenga píxeles Sentinel-2 válidos.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print(
            f"\n[AVISO] La saga quedó en estado '{final_status}'.\n"
            f"        Puede requerir más rondas (actual: --max-rounds {args.max_rounds})."
        )


if __name__ == "__main__":
    main()
