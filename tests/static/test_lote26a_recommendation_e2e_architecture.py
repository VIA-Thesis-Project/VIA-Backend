"""26A: Static architecture tests for E2E PostgreSQL Recommendation saga.

Verifies without running a database:
- E2E test file exists with all required test functions
- Uses real RelayWorker (not LockFreeRelayWorker)
- Uses TemplateRecommendationDraftingProvider (not LLM / Gemini / Vertex / local_http)
- Uses SqlAlchemyEvaluationResultsBridge (reads from PostgreSQL, not mocks)
- Uses RecommendationConsumer (recommendation BC is integrated)
- No SQLite, asyncpg, or async session
- No manual DDL
- EmptyDocumentEvidencePort avoids real RAG
- register_recommendation_saga_flow wires the full bus
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_E2E_FILE = _REPO_ROOT / "tests" / "integration" / "postgres" / "test_postgres_e2e_recommendation.py"
_STATIC_FILE = pathlib.Path(__file__)


# ─────────────────── file existence ──────────────────────────────────────────


def test_26a_e2e_test_file_exists() -> None:
    assert _E2E_FILE.exists(), (
        "tests/integration/postgres/test_postgres_e2e_recommendation.py does not exist. "
        "Run lote 26A implementation."
    )


# ─────────────────── required test functions ─────────────────────────────────


def _e2e_source() -> str:
    return _E2E_FILE.read_text(encoding="utf-8")


_REQUIRED_TEST_FUNCTIONS = [
    "test_postgres_e2e_rec_saga_reaches_recomendacion_completada",
    "test_postgres_e2e_rec_recomendacion_final_returns_200",
    "test_postgres_e2e_rec_recomendacion_final_from_real_db",
    "test_postgres_e2e_rec_recommendation_persisted_in_postgresql",
    "test_postgres_e2e_rec_provider_is_template",
    "test_postgres_e2e_rec_text_is_not_empty",
    "test_postgres_e2e_rec_outbox_has_recomendacion_generada_dispatched",
    "test_postgres_e2e_rec_uses_real_relay_not_lockfree",
    "test_postgres_e2e_rec_does_not_call_gee_or_llm",
    "test_postgres_e2e_rec_does_not_create_tables_manually",
]


def test_26a_has_required_test_function_saga_reaches_status() -> None:
    assert "test_postgres_e2e_rec_saga_reaches_recomendacion_completada" in _e2e_source()


def test_26a_has_required_test_function_200_response() -> None:
    assert "test_postgres_e2e_rec_recomendacion_final_returns_200" in _e2e_source()


def test_26a_has_required_test_function_from_real_db() -> None:
    assert "test_postgres_e2e_rec_recomendacion_final_from_real_db" in _e2e_source()


def test_26a_has_required_test_function_persisted() -> None:
    assert "test_postgres_e2e_rec_recommendation_persisted_in_postgresql" in _e2e_source()


def test_26a_has_required_test_function_provider_template() -> None:
    assert "test_postgres_e2e_rec_provider_is_template" in _e2e_source()


def test_26a_has_required_test_function_text_not_empty() -> None:
    assert "test_postgres_e2e_rec_text_is_not_empty" in _e2e_source()


def test_26a_has_required_test_function_outbox_dispatched() -> None:
    assert "test_postgres_e2e_rec_outbox_has_recomendacion_generada_dispatched" in _e2e_source()


def test_26a_has_required_test_function_real_relay() -> None:
    assert "test_postgres_e2e_rec_uses_real_relay_not_lockfree" in _e2e_source()


def test_26a_has_required_test_function_no_gee_llm() -> None:
    assert "test_postgres_e2e_rec_does_not_call_gee_or_llm" in _e2e_source()


def test_26a_has_required_test_function_no_manual_ddl() -> None:
    assert "test_postgres_e2e_rec_does_not_create_tables_manually" in _e2e_source()


def test_26a_has_at_least_ten_test_functions() -> None:
    src = _e2e_source()
    found = [fn for fn in _REQUIRED_TEST_FUNCTIONS if fn in src]
    assert len(found) >= 10, (
        f"Expected ≥10 required test functions in E2E file, found {len(found)}: {found}"
    )


# ─────────────────── prohibited: SQLite ──────────────────────────────────────


def test_26a_does_not_use_sqlite() -> None:
    src = _e2e_source()
    assert "sqlite" not in src.lower(), (
        "26A E2E file must not use SQLite — PostgreSQL is required"
    )


def test_26a_does_not_use_sqlite_memory() -> None:
    src = _e2e_source()
    assert ":memory:" not in src, (
        "26A E2E file must not use SQLite :memory: — PostgreSQL is required"
    )


# ─────────────────── prohibited: LockFreeRelayWorker ─────────────────────────


def test_26a_does_not_import_lockfree_relay_worker() -> None:
    """AST-based: no import of LockFreeRelayWorker anywhere in the E2E file."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "LockFreeRelayWorker", (
                    "26A E2E file must not import LockFreeRelayWorker — "
                    "RelayWorker with FOR UPDATE SKIP LOCKED is required"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "LockFreeRelayWorker" not in alias.name, (
                    "26A E2E file must not import LockFreeRelayWorker"
                )


# ─────────────────── prohibited: asyncpg / AsyncSession ──────────────────────


def test_26a_does_not_use_asyncpg() -> None:
    """AST-based: no import of asyncpg anywhere in the E2E file."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            if "asyncpg" in mod:
                raise AssertionError(f"26A E2E file must not import asyncpg (found in: {mod!r})")
            for alias in node.names:
                if "asyncpg" in alias.name:
                    raise AssertionError(f"26A E2E file must not import asyncpg (found: {alias.name!r})")


def test_26a_does_not_use_async_session() -> None:
    """AST-based: AsyncSession must not be imported in the E2E file."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "AsyncSession", (
                    "26A E2E file must not import AsyncSession — synchronous session required"
                )


def test_26a_does_not_use_create_async_engine() -> None:
    """AST-based: create_async_engine must not be imported in the E2E file."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "create_async_engine", (
                    "26A E2E file must not import create_async_engine"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "create_async_engine" not in alias.name


# ─────────────────── prohibited: LLM providers ───────────────────────────────


def test_26a_does_not_use_gemini_provider() -> None:
    """AST-based: GeminiApiDraftingProvider must not be imported or instantiated."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert "Gemini" not in alias.name, (
                    "26A E2E file must not import GeminiApiDraftingProvider — provider must be template"
                )


def test_26a_does_not_use_vertex_provider() -> None:
    """AST-based: VertexGemmaDraftingProvider must not be imported or instantiated."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert "Vertex" not in alias.name, (
                    "26A E2E file must not import VertexGemmaDraftingProvider — provider must be template"
                )


def test_26a_does_not_use_local_http_provider() -> None:
    """AST-based: LocalHttpLlmDraftingProvider must not be imported or instantiated."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert "LocalHttp" not in alias.name, (
                    "26A E2E file must not import LocalHttpLlmDraftingProvider — provider must be template"
                )


# ─────────────────── required: key infrastructure components ─────────────────


def test_26a_uses_template_drafting_provider() -> None:
    assert "TemplateRecommendationDraftingProvider" in _e2e_source(), (
        "26A E2E file must use TemplateRecommendationDraftingProvider"
    )


def test_26a_uses_evaluation_results_bridge() -> None:
    assert "SqlAlchemyEvaluationResultsBridge" in _e2e_source(), (
        "26A E2E file must use SqlAlchemyEvaluationResultsBridge "
        "(reads evaluation results from PostgreSQL, not in-memory objects)"
    )


def test_26a_uses_recommendation_consumer() -> None:
    assert "RecommendationConsumer" in _e2e_source(), (
        "26A E2E file must wire RecommendationConsumer into the event bus"
    )


def test_26a_uses_register_recommendation_saga_flow() -> None:
    assert "register_recommendation_saga_flow" in _e2e_source(), (
        "26A E2E file must use register_recommendation_saga_flow to wire the full bus"
    )


def test_26a_uses_empty_document_evidence_port() -> None:
    assert "EmptyDocumentEvidencePort" in _e2e_source(), (
        "26A E2E file must use EmptyDocumentEvidencePort (no RAG, no embedding)"
    )


def test_26a_uses_real_relay_worker() -> None:
    assert "RelayWorker" in _e2e_source(), (
        "26A E2E file must use the real RelayWorker"
    )


def test_26a_uses_pg_migrated_fixture() -> None:
    assert "pg_migrated" in _e2e_source(), (
        "26A E2E file must use pg_migrated fixture (Alembic migrations, not manual DDL)"
    )


def test_26a_overrides_get_recommendation_query_service() -> None:
    assert "get_recommendation_query_service" in _e2e_source(), (
        "26A E2E file must override get_recommendation_query_service dependency "
        "so the endpoint reads from PostgreSQL, not the unconfigured default"
    )


def test_26a_targets_recomendacion_completada_status() -> None:
    assert "RECOMENDACION_COMPLETADA" in _e2e_source(), (
        "26A E2E file must target RECOMENDACION_COMPLETADA saga status"
    )


# ─────────────────── prohibited: external services ───────────────────────────


def test_26a_does_not_import_gee_client() -> None:
    """AST-based: no import of GEEClient or earthengine modules."""
    tree = ast.parse(_e2e_source())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            assert "earthengine" not in mod.lower(), (
                f"26A E2E file must not import earthengine (found module: {mod!r})"
            )
            for alias in node.names:
                assert "GEEClient" not in alias.name, (
                    "26A E2E file must not import GEEClient"
                )
                assert "earthengine" not in alias.name.lower(), (
                    f"26A E2E file must not import earthengine (found: {alias.name!r})"
                )


def test_26a_does_not_import_celery_kafka_redis() -> None:
    """AST-based: no imports of Celery, Kafka, RabbitMQ, or Redis."""
    tree = ast.parse(_e2e_source())
    forbidden_modules = ("celery", "kafka", "rabbitmq", "redis")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (getattr(node, "module", "") or "").lower()
            for forbidden in forbidden_modules:
                assert forbidden not in mod, (
                    f"26A E2E file must not import {forbidden} — saga uses in-process Outbox+Relay"
                )
            for alias in node.names:
                for forbidden in forbidden_modules:
                    assert forbidden not in alias.name.lower(), (
                        f"26A E2E file must not import {forbidden} (found: {alias.name!r})"
                    )


# ─────────────────── no hardcoded credentials ────────────────────────────────


def test_26a_has_no_openai_api_key_pattern() -> None:
    import re
    src = _e2e_source()
    matches = re.findall(r'\bsk-[A-Za-z0-9]{20,}\b', src)
    assert not matches, f"26A E2E file contains what looks like an OpenAI API key: {matches}"


def test_26a_has_no_google_api_key_pattern() -> None:
    import re
    src = _e2e_source()
    matches = re.findall(r'\bAIza[A-Za-z0-9_\-]{35}\b', src)
    assert not matches, f"26A E2E file contains what looks like a Google API key: {matches}"


# ─────────────────── AST: no manual DDL in static file ───────────────────────


def test_26a_static_test_file_has_no_manual_ddl() -> None:
    src = _STATIC_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
            if fn in ("execute", "text"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and "CREATE TABLE" in str(arg.value).upper():
                        raise AssertionError(
                            "Manual DDL (CREATE TABLE) found in static test file. "
                            "Tables must come from Alembic migrations."
                        )
