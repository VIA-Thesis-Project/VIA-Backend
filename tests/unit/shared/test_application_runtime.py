"""Tests for real application runtime wiring."""

from __future__ import annotations

import ast
from pathlib import Path

from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.config import load_settings
from via.main import create_app
from via.shared.event_bus.in_memory_event_bus import InMemoryEventBus
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    RECOMENDACION_FALLIDA,
    RECOMENDACION_GENERADA,
)
from via.shared.runtime.application_runtime import configure_application_runtime


ROOT = Path(__file__).resolve().parents[3]


def test_create_app_registers_recommendation_saga_runtime() -> None:
    app = create_app()

    assert app.state.runtime.event_bus is app.state.event_bus
    assert app.state.runtime.relay_worker is app.state.relay_worker
    assert _handler_count(app.state.event_bus, EVALUACION_VIABILIDAD_COMPLETADA) == 1
    assert _handler_count(app.state.event_bus, GENERAR_RECOMENDACION_SOLICITADA) == 1
    assert _handler_count(app.state.event_bus, RECOMENDACION_GENERADA) == 1
    assert _handler_count(app.state.event_bus, RECOMENDACION_FALLIDA) == 1


def test_runtime_registration_is_idempotent_for_same_event_bus() -> None:
    event_bus = InMemoryEventBus()

    configure_application_runtime(event_bus=event_bus)
    configure_application_runtime(event_bus=event_bus)

    assert _handler_count(event_bus, EVALUACION_VIABILIDAD_COMPLETADA) == 1
    assert _handler_count(event_bus, GENERAR_RECOMENDACION_SOLICITADA) == 1
    assert _handler_count(event_bus, RECOMENDACION_GENERADA) == 1
    assert _handler_count(event_bus, RECOMENDACION_FALLIDA) == 1


def test_runtime_uses_template_provider_without_external_llm() -> None:
    runtime = configure_application_runtime()

    assert isinstance(runtime.recommendation_drafting_provider, TemplateRecommendationDraftingProvider)
    assert "openai" not in _imports_from(ROOT / "via" / "shared" / "runtime" / "application_runtime.py")
    assert "anthropic" not in _imports_from(ROOT / "via" / "shared" / "runtime" / "application_runtime.py")
    assert "google.generativeai" not in _imports_from(ROOT / "via" / "shared" / "runtime" / "application_runtime.py")


def test_runtime_uses_local_http_llm_provider_when_configured() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "local_http",
            "LLM_LOCAL_HTTP_ENDPOINT": "http://localhost:11434/api/generate",
            "LLM_MODEL": "gemma:2b",
        }
    )

    runtime = configure_application_runtime(settings=settings)

    assert runtime.recommendation_drafting_provider.__class__.__name__ == "LocalHttpLlmDraftingProvider"


def test_runtime_uses_vertex_gemma_provider_when_configured() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "vertex_gemma",
            "VERTEX_AI_PROJECT_ID": "via-project",
            "VERTEX_AI_LOCATION": "us-central1",
            "VERTEX_AI_ENDPOINT_ID": "123456789",
            "LLM_MODEL": "gemma-2-9b-it",
        }
    )

    runtime = configure_application_runtime(settings=settings)

    assert runtime.recommendation_drafting_provider.__class__.__name__ == "VertexGemmaDraftingProvider"


def test_runtime_uses_gemini_api_provider_when_configured() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "gemini_api",
            "GEMINI_API_KEY": "secret-key",
            "GEMINI_API_MODEL": "gemma-3-27b-it",
        }
    )

    runtime = configure_application_runtime(settings=settings)

    assert runtime.recommendation_drafting_provider.__class__.__name__ == "GeminiApiDraftingProvider"


def test_application_composition_calls_recommendation_saga_registration() -> None:
    source = (ROOT / "via" / "shared" / "runtime" / "application_runtime.py").read_text(encoding="utf-8")

    assert "register_recommendation_saga_flow(" in source


def _handler_count(event_bus: InMemoryEventBus, message_type: str) -> int:
    return len(event_bus._handlers[message_type])


def _imports_from(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports
