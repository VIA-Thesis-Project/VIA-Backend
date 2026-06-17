"""Event Bus registration for saga orchestration and all BC consumers."""

from __future__ import annotations

from typing import Any

from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.shared.event_bus.event_bus_interface import EventBus
from via.shared.orchestration.evaluation_process_manager.commands import (
    EJECUTAR_EVALUACION_VIABILIDAD,
    GENERAR_RECOMENDACION_SOLICITADA,
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


_REGISTRATION_MARKER = "_via_recommendation_saga_flow_registered"


def register_recommendation_saga_flow(
    event_bus: EventBus,
    process_manager: EvaluationProcessManager,
    recommendation_consumer: RecommendationConsumer,
    extraction_consumer: Any | None = None,
    evaluation_consumer: Any | None = None,
) -> None:
    """Register handlers for the full evaluation saga flow on the Event Bus.

    Always registers:
    - Process Manager handles all saga events (VectorAgroambientalGenerado,
      EvaluacionViabilidadCompletada, ExtraccionFallida, EvaluacionViabilidadFallida,
      RecomendacionGenerada, RecomendacionFallida).
    - Recommendation consumer handles GenerarRecomendacionSolicitada.

    Optionally registers (when consumers are provided):
    - extraction_consumer handles IniciarExtraccionAgroambiental.
    - evaluation_consumer handles EjecutarEvaluacionViabilidad.

    Registration is idempotent per Event Bus instance.
    """

    if getattr(event_bus, _REGISTRATION_MARKER, False):
        return

    process_manager_handler = EvaluationProcessManagerEventHandler(process_manager)
    event_bus.register(VECTOR_AGROAMBIENTAL_GENERADO, process_manager_handler)
    event_bus.register(EVALUACION_VIABILIDAD_COMPLETADA, process_manager_handler)
    event_bus.register(EXTRACCION_FALLIDA, process_manager_handler)
    event_bus.register(EVALUACION_VIABILIDAD_FALLIDA, process_manager_handler)
    event_bus.register(RECOMENDACION_GENERADA, process_manager_handler)
    event_bus.register(RECOMENDACION_FALLIDA, process_manager_handler)
    event_bus.register(GENERAR_RECOMENDACION_SOLICITADA, recommendation_consumer.handle)

    if extraction_consumer is not None:
        event_bus.register(INICIAR_EXTRACCION_AGROAMBIENTAL, extraction_consumer.handle)

    if evaluation_consumer is not None:
        event_bus.register(EJECUTAR_EVALUACION_VIABILIDAD, evaluation_consumer.handle)

    setattr(event_bus, _REGISTRATION_MARKER, True)
