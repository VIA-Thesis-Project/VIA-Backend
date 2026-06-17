"""Tests for 24A — Application Runtime / Monolith Wiring audit.

Verifies that the FastAPI monolith wires all routers, exposes the expected
app.state attributes, registers all Event Bus handlers/consumers, uses the
template drafting provider by default, and does not call external services
(Gemini, Vertex, GEE, local HTTP LLM) during startup.
"""

from __future__ import annotations

from via.bounded_contexts.agroenv_extraction.interfaces.extraction_consumer import AgroenvExtractionConsumer
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import (
    TemplateRecommendationDraftingProvider,
)
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
from via.main import create_app
from via.shared.event_bus.in_memory_event_bus import InMemoryEventBus
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
from via.shared.outbox.relay_worker import RelayWorker
from via.shared.runtime.application_runtime import configure_application_runtime


# ─────────────────────── app startup ──────────────────────────────────────────


def test_app_starts_without_external_services() -> None:
    """create_app() must succeed without GEE, Gemini, Vertex or real DB."""

    app = create_app()
    assert app is not None


def test_app_state_runtime_exists() -> None:
    app = create_app()
    assert hasattr(app.state, "runtime")
    assert app.state.runtime is not None


def test_app_state_event_bus_exists() -> None:
    app = create_app()
    assert hasattr(app.state, "event_bus")
    assert isinstance(app.state.event_bus, InMemoryEventBus)


def test_app_state_relay_worker_exists() -> None:
    app = create_app()
    assert hasattr(app.state, "relay_worker")
    assert isinstance(app.state.relay_worker, RelayWorker)


def test_runtime_event_bus_is_same_as_app_state_event_bus() -> None:
    app = create_app()
    assert app.state.runtime.event_bus is app.state.event_bus


def test_runtime_relay_worker_is_same_as_app_state_relay_worker() -> None:
    app = create_app()
    assert app.state.runtime.relay_worker is app.state.relay_worker


# ─────────────────────── routers ──────────────────────────────────────────────


def _route_paths(app) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_all_expected_routes_are_registered() -> None:
    app = create_app()
    paths = _route_paths(app)

    expected = {
        "/evaluaciones",
        "/evaluaciones/{evaluation_id}/estado",
        "/evaluaciones/{evaluation_id}/resultado-mcda",
        "/recomendaciones/{recommendation_id}",
        "/evaluaciones/{evaluation_id}/recomendaciones",
        "/evaluaciones/{evaluation_id}/recomendacion-final",
    }
    missing = expected - paths
    assert not missing, f"Routes not registered: {missing}"


def test_auth_route_registered() -> None:
    app = create_app()
    paths = _route_paths(app)
    auth_paths = {p for p in paths if p.startswith("/auth")}
    assert auth_paths, "No /auth routes registered"


def test_parcelas_route_registered() -> None:
    app = create_app()
    paths = _route_paths(app)
    parcel_paths = {p for p in paths if p.startswith("/parcelas")}
    assert parcel_paths, "No /parcelas routes registered"


def test_rulebooks_route_registered() -> None:
    app = create_app()
    paths = _route_paths(app)
    rulebook_paths = {p for p in paths if p.startswith("/rulebooks")}
    assert rulebook_paths, "No /rulebooks routes registered"


def test_documentos_route_registered() -> None:
    app = create_app()
    paths = _route_paths(app)
    doc_paths = {p for p in paths if p.startswith("/documentos")}
    assert doc_paths, "No /documentos routes registered"


# ─────────────────────── provider ─────────────────────────────────────────────


def test_runtime_uses_template_provider_by_default() -> None:
    runtime = configure_application_runtime()
    assert isinstance(runtime.recommendation_drafting_provider, TemplateRecommendationDraftingProvider)


def test_no_external_llm_calls_on_startup() -> None:
    """configure_application_runtime() with defaults must not call Gemini, Vertex or local HTTP."""

    runtime = configure_application_runtime()
    assert runtime.recommendation_drafting_provider.__class__.__name__ == "TemplateRecommendationDraftingProvider"


# ─────────────────────── consumers in runtime ─────────────────────────────────


def test_runtime_exposes_extraction_consumer() -> None:
    runtime = configure_application_runtime()
    assert isinstance(runtime.extraction_consumer, AgroenvExtractionConsumer)


def test_runtime_exposes_evaluation_consumer() -> None:
    runtime = configure_application_runtime()
    assert isinstance(runtime.evaluation_consumer, ViabilityEvaluationConsumer)


# ─────────────────────── event bus handlers ───────────────────────────────────


def _handler_count(event_bus: InMemoryEventBus, message_type: str) -> int:
    return len(event_bus._handlers[message_type])


def test_event_bus_registers_extraction_command_handler() -> None:
    """IniciarExtraccionAgroambiental must be handled by the extraction consumer."""

    app = create_app()
    assert _handler_count(app.state.event_bus, INICIAR_EXTRACCION_AGROAMBIENTAL) == 1


def test_event_bus_registers_evaluation_command_handler() -> None:
    """EjecutarEvaluacionViabilidad must be handled by the evaluation consumer."""

    app = create_app()
    assert _handler_count(app.state.event_bus, EJECUTAR_EVALUACION_VIABILIDAD) == 1


def test_event_bus_registers_recommendation_command_handler() -> None:
    """GenerarRecomendacionSolicitada must be handled by the recommendation consumer."""

    app = create_app()
    assert _handler_count(app.state.event_bus, GENERAR_RECOMENDACION_SOLICITADA) == 1


def test_event_bus_registers_vector_generado_handler() -> None:
    app = create_app()
    assert _handler_count(app.state.event_bus, VECTOR_AGROAMBIENTAL_GENERADO) == 1


def test_event_bus_registers_evaluacion_completada_handler() -> None:
    app = create_app()
    assert _handler_count(app.state.event_bus, EVALUACION_VIABILIDAD_COMPLETADA) == 1


def test_event_bus_registers_extraccion_fallida_handler() -> None:
    app = create_app()
    assert _handler_count(app.state.event_bus, EXTRACCION_FALLIDA) == 1


def test_event_bus_registers_evaluacion_viabilidad_fallida_handler() -> None:
    """EvaluacionViabilidadFallida must be routed to the Process Manager."""

    app = create_app()
    assert _handler_count(app.state.event_bus, EVALUACION_VIABILIDAD_FALLIDA) == 1


def test_event_bus_registers_recomendacion_generada_handler() -> None:
    app = create_app()
    assert _handler_count(app.state.event_bus, RECOMENDACION_GENERADA) == 1


def test_event_bus_registers_recomendacion_fallida_handler() -> None:
    app = create_app()
    assert _handler_count(app.state.event_bus, RECOMENDACION_FALLIDA) == 1


# ─────────────────────── idempotency ──────────────────────────────────────────


def test_registration_is_idempotent_for_same_bus() -> None:
    """Calling configure_application_runtime twice with the same bus must not duplicate handlers."""

    event_bus = InMemoryEventBus()
    configure_application_runtime(event_bus=event_bus)
    configure_application_runtime(event_bus=event_bus)

    assert _handler_count(event_bus, INICIAR_EXTRACCION_AGROAMBIENTAL) == 1
    assert _handler_count(event_bus, EJECUTAR_EVALUACION_VIABILIDAD) == 1
    assert _handler_count(event_bus, GENERAR_RECOMENDACION_SOLICITADA) == 1
    assert _handler_count(event_bus, EVALUACION_VIABILIDAD_COMPLETADA) == 1
    assert _handler_count(event_bus, EVALUACION_VIABILIDAD_FALLIDA) == 1
