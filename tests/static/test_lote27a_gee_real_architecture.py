"""27A: Static architecture tests for the GEE real integration E2E file.

Verifies without running a database or GEE:
- E2E test file exists with all 9 required test functions
- Tests are opt-in (skip if GEE_TEST_RUN_REAL not set)
- GeeExtractionClient is imported (not ControlledExtractionClient)
- No LockFreeRelayWorker, asyncpg, AsyncSession, create_async_engine
- No SQLite, no manual DDL
- No hardcoded credential patterns
- No absolute user-specific paths in the test source
- No LLM / Recommendation / Gemini / Vertex providers
"""

from __future__ import annotations

import ast
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_E2E_FILE = _REPO_ROOT / "tests" / "integration" / "postgres" / "test_postgres_e2e_gee_real.py"
_STATIC_FILE = pathlib.Path(__file__)

_REQUIRED_TEST_FUNCTIONS = [
    "test_gee_real_credentials_are_required_for_real_run",
    "test_postgres_e2e_gee_real_saga_reaches_evaluacion_completada",
    "test_postgres_e2e_gee_real_resultado_mcda_returns_200",
    "test_postgres_e2e_gee_real_result_persisted_in_postgresql",
    "test_gee_real_client_extracts_single_variable",
    "test_postgres_e2e_gee_real_does_not_use_controlled_extraction",
    "test_postgres_e2e_gee_real_does_not_use_lockfree_relay",
    "test_postgres_e2e_gee_real_outbox_dispatched_for_evaluation",
    "test_postgres_e2e_gee_real_does_not_call_llm_or_recommendation",
]


def _e2e_source() -> str:
    return _E2E_FILE.read_text(encoding="utf-8")


def _e2e_tree() -> ast.Module:
    return ast.parse(_e2e_source())


# ─────────────────── file existence ──────────────────────────────────────────


def test_27a_e2e_test_file_exists() -> None:
    assert _E2E_FILE.exists(), (
        "tests/integration/postgres/test_postgres_e2e_gee_real.py does not exist. "
        "Run lote 27A implementation."
    )


# ─────────────────── required test functions ─────────────────────────────────


def test_27a_has_test_gee_real_credentials_required() -> None:
    assert "test_gee_real_credentials_are_required_for_real_run" in _e2e_source()


def test_27a_has_test_saga_reaches_evaluacion_completada() -> None:
    assert "test_postgres_e2e_gee_real_saga_reaches_evaluacion_completada" in _e2e_source()


def test_27a_has_test_resultado_mcda_returns_200() -> None:
    assert "test_postgres_e2e_gee_real_resultado_mcda_returns_200" in _e2e_source()


def test_27a_has_test_result_persisted_in_postgresql() -> None:
    assert "test_postgres_e2e_gee_real_result_persisted_in_postgresql" in _e2e_source()


def test_27a_has_test_gee_client_extracts_single_variable() -> None:
    assert "test_gee_real_client_extracts_single_variable" in _e2e_source()


def test_27a_has_test_does_not_use_controlled_extraction() -> None:
    assert "test_postgres_e2e_gee_real_does_not_use_controlled_extraction" in _e2e_source()


def test_27a_has_test_does_not_use_lockfree_relay() -> None:
    assert "test_postgres_e2e_gee_real_does_not_use_lockfree_relay" in _e2e_source()


def test_27a_has_test_outbox_dispatched() -> None:
    assert "test_postgres_e2e_gee_real_outbox_dispatched_for_evaluation" in _e2e_source()


def test_27a_has_test_does_not_call_llm_or_recommendation() -> None:
    assert "test_postgres_e2e_gee_real_does_not_call_llm_or_recommendation" in _e2e_source()


def test_27a_has_all_nine_required_test_functions() -> None:
    src = _e2e_source()
    found = [fn for fn in _REQUIRED_TEST_FUNCTIONS if fn in src]
    assert len(found) == 9, (
        f"Expected 9 required test functions in 27A E2E file, found {len(found)}: "
        f"missing: {[f for f in _REQUIRED_TEST_FUNCTIONS if f not in src]}"
    )


# ─────────────────── opt-in mechanism ────────────────────────────────────────


def test_27a_uses_gee_test_run_real_opt_in() -> None:
    assert "GEE_TEST_RUN_REAL" in _e2e_source(), (
        "27A E2E file must check GEE_TEST_RUN_REAL env var as the opt-in gate"
    )


def test_27a_uses_pytest_skip_for_opt_in() -> None:
    assert "pytest.skip" in _e2e_source(), (
        "27A E2E file must call pytest.skip() when GEE_TEST_RUN_REAL is not set"
    )


def test_27a_skip_gate_checks_gee_project() -> None:
    assert "GEE_PROJECT" in _e2e_source(), (
        "27A E2E file must check GEE_PROJECT env var before running"
    )


def test_27a_skip_gate_checks_gee_service_account() -> None:
    assert "GEE_SERVICE_ACCOUNT" in _e2e_source(), (
        "27A E2E file must check GEE_SERVICE_ACCOUNT env var before running"
    )


def test_27a_skip_gate_checks_gee_private_key_file() -> None:
    assert "GEE_PRIVATE_KEY_FILE" in _e2e_source(), (
        "27A E2E file must check GEE_PRIVATE_KEY_FILE env var before running"
    )


# ─────────────────── required: GeeExtractionClient ───────────────────────────


def test_27a_imports_gee_extraction_client() -> None:
    assert "GeeExtractionClient" in _e2e_source(), (
        "27A E2E file must import and use GeeExtractionClient"
    )


def test_27a_imports_gee_extraction_client_from_correct_module() -> None:
    """AST-based: GeeExtractionClient must be imported from the infrastructure module."""
    tree = _e2e_tree()
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "gee_client" in node.module:
                for alias in node.names:
                    if alias.name == "GeeExtractionClient":
                        found = True
    assert found, (
        "GeeExtractionClient must be imported from the gee_client infrastructure module"
    )


# ─────────────────── required: load_settings from env ────────────────────────


def test_27a_uses_load_settings() -> None:
    assert "load_settings" in _e2e_source(), (
        "27A E2E file must use load_settings to build GEE settings from env vars"
    )


# ─────────────────── prohibited: ControlledExtractionClient ──────────────────


def test_27a_does_not_import_controlled_extraction_client() -> None:
    """AST-based: ControlledExtractionClient must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "ControlledExtractionClient", (
                    "27A E2E file must not import ControlledExtractionClient — "
                    "use GeeExtractionClient real instead"
                )


# ─────────────────── prohibited: SQLite ──────────────────────────────────────


def test_27a_does_not_import_sqlite() -> None:
    """AST-based: no import of sqlite3 or pysqlite in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (getattr(node, "module", "") or "").lower()
            if "sqlite" in mod:
                raise AssertionError(
                    f"27A E2E file must not import SQLite-related modules (found: {mod!r}). "
                    "Use PostgreSQL only."
                )
            for alias in node.names:
                if "sqlite" in alias.name.lower():
                    raise AssertionError(
                        f"27A E2E file must not import SQLite (found: {alias.name!r}). "
                        "Use PostgreSQL only."
                    )


def test_27a_does_not_use_sqlite_memory() -> None:
    assert ":memory:" not in _e2e_source(), (
        "27A E2E file must not use SQLite :memory: — PostgreSQL is required"
    )


# ─────────────────── prohibited: LockFreeRelayWorker ─────────────────────────


def test_27a_does_not_import_lockfree_relay_worker() -> None:
    """AST-based: LockFreeRelayWorker must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "LockFreeRelayWorker", (
                    "27A E2E file must not import LockFreeRelayWorker — "
                    "RelayWorker with FOR UPDATE SKIP LOCKED is required"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "LockFreeRelayWorker" not in alias.name


# ─────────────────── prohibited: asyncpg / AsyncSession ──────────────────────


def test_27a_does_not_use_asyncpg() -> None:
    """AST-based: asyncpg must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            if "asyncpg" in mod:
                raise AssertionError(f"27A E2E file must not import asyncpg (found in: {mod!r})")
            for alias in node.names:
                if "asyncpg" in alias.name:
                    raise AssertionError(f"27A E2E file must not import asyncpg (found: {alias.name!r})")


def test_27a_does_not_use_async_session() -> None:
    """AST-based: AsyncSession must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "AsyncSession", (
                    "27A E2E file must not import AsyncSession — synchronous session required"
                )


def test_27a_does_not_use_create_async_engine() -> None:
    """AST-based: create_async_engine must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "create_async_engine", (
                    "27A E2E file must not import create_async_engine"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "create_async_engine" not in alias.name


# ─────────────────── prohibited: LLM providers ───────────────────────────────


def test_27a_does_not_use_gemini_provider() -> None:
    """AST-based: GeminiApiDraftingProvider must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert "Gemini" not in alias.name, (
                    "27A E2E file must not import GeminiApiDraftingProvider"
                )


def test_27a_does_not_use_vertex_provider() -> None:
    """AST-based: VertexGemmaDraftingProvider must not be imported in the 27A E2E file."""
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert "Vertex" not in alias.name, (
                    "27A E2E file must not import VertexGemmaDraftingProvider"
                )


def test_27a_does_not_import_celery_kafka_redis() -> None:
    """AST-based: no imports of Celery, Kafka, RabbitMQ, or Redis."""
    tree = _e2e_tree()
    forbidden = ("celery", "kafka", "rabbitmq", "redis")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (getattr(node, "module", "") or "").lower()
            for f in forbidden:
                assert f not in mod, (
                    f"27A E2E file must not import {f}"
                )
            for alias in node.names:
                for f in forbidden:
                    assert f not in alias.name.lower(), (
                        f"27A E2E file must not import {f} (found: {alias.name!r})"
                    )


# ─────────────────── prohibited: hardcoded credentials ───────────────────────


def test_27a_has_no_hardcoded_service_account_pattern() -> None:
    """Service account email must not appear verbatim in the E2E file."""
    src = _e2e_source()
    # Look for .iam.gserviceaccount.com literal (service account pattern)
    matches = re.findall(r'[a-z0-9_\-]+@[a-z0-9\-]+\.iam\.gserviceaccount\.com', src)
    assert not matches, (
        f"27A E2E file contains hardcoded service account email(s): {matches}. "
        "Use os.environ.get('GEE_SERVICE_ACCOUNT') instead."
    )


def test_27a_has_no_google_api_key_pattern() -> None:
    src = _e2e_source()
    matches = re.findall(r'\bAIza[A-Za-z0-9_\-]{35}\b', src)
    assert not matches, f"27A E2E file contains what looks like a Google API key: {matches}"


def test_27a_has_no_openai_api_key_pattern() -> None:
    src = _e2e_source()
    matches = re.findall(r'\bsk-[A-Za-z0-9]{20,}\b', src)
    assert not matches, f"27A E2E file contains what looks like an OpenAI API key: {matches}"


def test_27a_has_no_private_key_content() -> None:
    """Private key data must never appear in source."""
    src = _e2e_source()
    assert "BEGIN RSA PRIVATE KEY" not in src, "Private key content found in 27A E2E file"
    assert "BEGIN PRIVATE KEY" not in src, "Private key content found in 27A E2E file"
    assert "-----BEGIN" not in src, "PEM header found in 27A E2E file — remove private key content"


def test_27a_has_no_absolute_windows_user_path() -> None:
    """User-specific absolute paths (e.g. C:\\Users\\Usuario) must not appear in the file."""
    src = _e2e_source()
    assert "Users\\Usuario" not in src, (
        "27A E2E file must not contain absolute user-specific paths like C:\\Users\\Usuario. "
        "Use environment variables for all credential paths."
    )
    assert "Users/Usuario" not in src, (
        "27A E2E file must not contain absolute user-specific paths."
    )


# ─────────────────── static test file integrity ───────────────────────────────


def test_27a_static_test_file_has_no_manual_ddl() -> None:
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
