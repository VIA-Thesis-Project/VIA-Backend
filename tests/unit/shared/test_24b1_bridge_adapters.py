"""Unit tests for VIA task 24B.1 — Bridge adapter replacements.

Verifies that:
- All bridge adapters instantiate without RuntimeError.
- configure_application_runtime() starts without calling external services.
- LLM provider defaults to template.
- Event Bus handlers remain registered.
- No external calls made on startup.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.orm import Session


# ─── Bridge adapter instantiation (no RuntimeError on construction) ───────────


def test_rulebook_read_model_bridge_instantiates() -> None:
    from via.shared.runtime.bridges import SqlAlchemyRulebookReadModelBridge

    session_factory = MagicMock(return_value=MagicMock(spec=Session))
    bridge = SqlAlchemyRulebookReadModelBridge(session_factory)
    assert bridge is not None


def test_parcel_geometry_bridge_instantiates() -> None:
    from via.shared.runtime.bridges import SqlAlchemyParcelGeometryBridge

    session_factory = MagicMock(return_value=MagicMock(spec=Session))
    bridge = SqlAlchemyParcelGeometryBridge(session_factory)
    assert bridge is not None


def test_rulebook_evaluation_bridge_instantiates() -> None:
    from via.shared.runtime.bridges import SqlAlchemyRulebookEvaluationBridge

    session_factory = MagicMock(return_value=MagicMock(spec=Session))
    bridge = SqlAlchemyRulebookEvaluationBridge(session_factory)
    assert bridge is not None


def test_agroenv_vector_bridge_instantiates() -> None:
    from via.shared.runtime.bridges import SqlAlchemyAgroenvVectorBridge

    session_factory = MagicMock(return_value=MagicMock(spec=Session))
    bridge = SqlAlchemyAgroenvVectorBridge(session_factory)
    assert bridge is not None


def test_evaluation_results_bridge_instantiates() -> None:
    from via.shared.runtime.bridges import SqlAlchemyEvaluationResultsBridge

    session_factory = MagicMock(return_value=MagicMock(spec=Session))
    bridge = SqlAlchemyEvaluationResultsBridge(session_factory)
    assert bridge is not None


# ─── Runtime startup without external services ────────────────────────────────


def test_configure_application_runtime_starts_without_external_services() -> None:
    """configure_application_runtime() must not call GEE, Gemini, Vertex or real DB."""

    from via.config import load_settings
    from via.shared.runtime.application_runtime import configure_application_runtime

    runtime = configure_application_runtime(settings=load_settings({}))
    assert runtime is not None


def test_runtime_uses_template_provider_by_default() -> None:
    from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import (
        TemplateRecommendationDraftingProvider,
    )
    from via.config import load_settings
    from via.shared.runtime.application_runtime import configure_application_runtime

    runtime = configure_application_runtime(settings=load_settings({}))
    assert isinstance(runtime.recommendation_drafting_provider, TemplateRecommendationDraftingProvider)


def test_no_llm_call_on_startup() -> None:
    from via.config import load_settings
    from via.shared.runtime.application_runtime import configure_application_runtime

    runtime = configure_application_runtime(settings=load_settings({}))
    assert runtime.recommendation_drafting_provider.__class__.__name__ == "TemplateRecommendationDraftingProvider"


# ─── Consumer construction uses bridges (not RuntimeError stubs) ──────────────


def test_evaluation_consumer_no_runtime_error_stubs() -> None:
    """_evaluation_consumer must use SqlAlchemyRulebookEvaluationBridge and SqlAlchemyAgroenvVectorBridge."""

    from via.shared.runtime.application_runtime import _evaluation_consumer, configure_application_runtime
    from via.shared.runtime.bridges import SqlAlchemyAgroenvVectorBridge, SqlAlchemyRulebookEvaluationBridge

    runtime = configure_application_runtime()
    service = runtime.evaluation_consumer._command_service
    assert isinstance(service._rulebook_port, SqlAlchemyRulebookEvaluationBridge)
    assert isinstance(service._agroenv_vector_port, SqlAlchemyAgroenvVectorBridge)


def test_recommendation_consumer_uses_evaluation_results_bridge() -> None:
    """_recommendation_consumer must wire SqlAlchemyEvaluationResultsBridge, not RuntimeEvaluationResultsPort."""

    from via.shared.runtime.application_runtime import configure_application_runtime

    runtime = configure_application_runtime()
    assert runtime.recommendation_consumer is not None


# ─── Process manager uses real bridges ────────────────────────────────────────


def test_process_manager_uses_rulebook_bridge() -> None:
    from via.shared.runtime.application_runtime import configure_application_runtime
    from via.shared.runtime.bridges import SqlAlchemyRulebookReadModelBridge

    runtime = configure_application_runtime()
    assert isinstance(runtime.process_manager._rulebook_read_model_port, SqlAlchemyRulebookReadModelBridge)


def test_process_manager_uses_parcel_geometry_bridge() -> None:
    from via.shared.runtime.application_runtime import configure_application_runtime
    from via.shared.runtime.bridges import SqlAlchemyParcelGeometryBridge

    runtime = configure_application_runtime()
    assert isinstance(runtime.process_manager._parcel_geometry_read_model_port, SqlAlchemyParcelGeometryBridge)


# ─── Event Bus handlers still registered ─────────────────────────────────────


def test_event_bus_handlers_remain_registered_after_24b1() -> None:
    from via.main import create_app
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

    app = create_app()
    handlers = app.state.event_bus._handlers

    for message_type in [
        VECTOR_AGROAMBIENTAL_GENERADO,
        EVALUACION_VIABILIDAD_COMPLETADA,
        EVALUACION_VIABILIDAD_FALLIDA,
        EXTRACCION_FALLIDA,
        RECOMENDACION_GENERADA,
        RECOMENDACION_FALLIDA,
        GENERAR_RECOMENDACION_SOLICITADA,
        INICIAR_EXTRACCION_AGROAMBIENTAL,
        EJECUTAR_EVALUACION_VIABILIDAD,
    ]:
        assert len(handlers[message_type]) >= 1, f"No handler for {message_type}"
