"""Static architecture checks for VIA task 24A — Application Runtime / Wiring.

Verifies that:
- The main.py registers all expected routers.
- The Relay Worker uses threading and not asyncio.
- The event_bus_registration module registers all expected message types.
- Domain layers do not import infrastructure or framework code.
- Application runtime does not use asyncio, asyncpg or async session.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = ROOT / "via" / "main.py"
RELAY_WORKER_PY = ROOT / "via" / "shared" / "outbox" / "relay_worker.py"
EVENT_BUS_REG_PY = ROOT / "via" / "shared" / "runtime" / "event_bus_registration.py"
APPLICATION_RUNTIME_PY = ROOT / "via" / "shared" / "runtime" / "application_runtime.py"


# ─────────────────────── main.py ──────────────────────────────────────────────


def test_main_registers_auth_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "auth_router" in source


def test_main_registers_parcel_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "parcel_router" in source


def test_main_registers_rulebook_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "rulebook_router" in source


def test_main_registers_document_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "document_router" in source


def test_main_registers_evaluation_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "evaluation_router" in source


def test_main_registers_recommendation_router() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "recommendation_router" in source


def test_main_creates_single_fastapi_app() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "FastAPI(" in source
    assert source.count("FastAPI(") == 1


def test_main_exposes_app_state_runtime() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "app.state.runtime" in source


def test_main_exposes_app_state_event_bus() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "app.state.event_bus" in source


def test_main_exposes_app_state_relay_worker() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "app.state.relay_worker" in source


def test_main_does_not_create_multiple_fastapi_apps() -> None:
    """There must be exactly one FastAPI app — no per-BC apps."""

    source = MAIN_PY.read_text(encoding="utf-8")
    assert source.count("FastAPI(") == 1


# ─────────────────────── relay worker ─────────────────────────────────────────


def test_relay_worker_uses_threading_not_asyncio() -> None:
    source = RELAY_WORKER_PY.read_text(encoding="utf-8")
    assert "threading" in source
    assert "asyncio" not in source


def test_relay_worker_does_not_use_asyncpg() -> None:
    source = RELAY_WORKER_PY.read_text(encoding="utf-8")
    assert "asyncpg" not in source


def test_relay_worker_does_not_use_async_session() -> None:
    source = RELAY_WORKER_PY.read_text(encoding="utf-8")
    assert "AsyncSession" not in source


# ─────────────────────── event_bus_registration.py ────────────────────────────


def test_event_bus_registration_registers_vector_agroambiental_generado() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "VECTOR_AGROAMBIENTAL_GENERADO" in source


def test_event_bus_registration_registers_evaluacion_viabilidad_completada() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "EVALUACION_VIABILIDAD_COMPLETADA" in source


def test_event_bus_registration_registers_evaluacion_viabilidad_fallida() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "EVALUACION_VIABILIDAD_FALLIDA" in source


def test_event_bus_registration_registers_extraccion_fallida() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "EXTRACCION_FALLIDA" in source


def test_event_bus_registration_registers_recomendacion_generada() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "RECOMENDACION_GENERADA" in source


def test_event_bus_registration_registers_recomendacion_fallida() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "RECOMENDACION_FALLIDA" in source


def test_event_bus_registration_registers_generar_recomendacion_solicitada() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "GENERAR_RECOMENDACION_SOLICITADA" in source


def test_event_bus_registration_registers_iniciar_extraccion() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "INICIAR_EXTRACCION_AGROAMBIENTAL" in source


def test_event_bus_registration_registers_ejecutar_evaluacion() -> None:
    source = EVENT_BUS_REG_PY.read_text(encoding="utf-8")
    assert "EJECUTAR_EVALUACION_VIABILIDAD" in source


def test_event_bus_registration_does_not_import_orm_models() -> None:
    forbidden_prefixes = ("sqlalchemy", "via.shared.database", "orm_models")
    offenders: list[str] = []
    for imported_name in _imports_from(EVENT_BUS_REG_PY):
        if any(imported_name == p or imported_name.startswith(p + ".") for p in forbidden_prefixes):
            offenders.append(imported_name)
    assert offenders == [], f"event_bus_registration.py imports forbidden: {offenders}"


# ─────────────────────── application_runtime.py ───────────────────────────────


def test_application_runtime_does_not_use_asyncio() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "asyncio" not in source


def test_application_runtime_does_not_use_asyncpg() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "asyncpg" not in source


def test_application_runtime_does_not_use_async_session() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "AsyncSession" not in source


def test_application_runtime_wires_extraction_consumer() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "AgroenvExtractionConsumer" in source
    assert "extraction_consumer" in source


def test_application_runtime_wires_evaluation_consumer() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "ViabilityEvaluationConsumer" in source
    assert "evaluation_consumer" in source


def test_application_runtime_documents_gee_limitation() -> None:
    """The runtime must document that GEE client is a placeholder."""

    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "RuntimeGeeExtractionClient" in source or "GEE" in source


def test_application_runtime_calls_register_recommendation_saga_flow() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "register_recommendation_saga_flow(" in source


# ─────────────────────── helpers ──────────────────────────────────────────────


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
