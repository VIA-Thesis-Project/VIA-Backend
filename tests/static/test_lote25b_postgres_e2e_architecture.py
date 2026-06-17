"""25B: Static architecture validation for PostgreSQL E2E MCDA tests.

Verifies structural constraints on tests/integration/postgres/test_postgres_e2e_mcda.py:
- Required test file exists
- Uses real RelayWorker (not LockFreeRelayWorker)
- LockFreeRelayWorker is not defined or imported
- No SQLite engine usage
- No manual DDL (CREATE TABLE, ATTACH DATABASE)
- No mocks replacing PostgreSQL
- No hardcoded credentials
- No GEE or LLM references
- No asyncpg / AsyncSession / create_async_engine
- No async def test functions
- Required coverage: DISPATCHED, EVALUACION_COMPLETADA, FOR UPDATE SKIP LOCKED
- Depends on pg_migrated (via pg25b_cleanup)
- drive_saga_to_completion helper is defined
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_INTEGRATION_DIR = _REPO_ROOT / "tests" / "integration" / "postgres"
_TARGET_FILE = _INTEGRATION_DIR / "test_postgres_e2e_mcda.py"


# ─────────────────────── file existence ──────────────────────────────────────


def test_postgres_e2e_mcda_file_exists() -> None:
    assert _TARGET_FILE.exists(), (
        "tests/integration/postgres/test_postgres_e2e_mcda.py does not exist. "
        "Run lote 25B implementation."
    )


# ─────────────────────── required imports ────────────────────────────────────


def test_imports_real_relay_worker() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "from via.shared.outbox.relay_worker import RelayWorker" in source, (
        "Must import RelayWorker from via.shared.outbox.relay_worker (real production worker)"
    )


def test_does_not_import_lock_free_relay_worker() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    import_lines = [
        line for line in source.splitlines()
        if "import" in line and "LockFree" in line
    ]
    assert not import_lines, (
        "test_postgres_e2e_mcda.py must not import LockFreeRelayWorker. "
        "Use the real RelayWorker with FOR UPDATE SKIP LOCKED."
    )


def test_does_not_define_lock_free_relay_worker() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "LockFreeRelayWorker" not in class_names, (
        "test_postgres_e2e_mcda.py must not define LockFreeRelayWorker — "
        "25B uses the real RelayWorker."
    )


def test_imports_in_memory_event_bus() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "InMemoryEventBus" in source, (
        "Must use InMemoryEventBus as the real synchronous event bus"
    )


def test_imports_evaluation_process_manager() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "EvaluationProcessManager" in source, (
        "Must use the real EvaluationProcessManager"
    )


# ─────────────────────── no SQLite ───────────────────────────────────────────


def test_no_sqlite_engine_usage() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    # No import of sqlite3 at the module level
    import_lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    sqlite_imports = [l for l in import_lines if "sqlite" in l.lower()]
    assert not sqlite_imports, f"SQLite import found: {sqlite_imports}"
    # No _CREATE_TABLES_SQL variable assignment (DDL block definition)
    assert "_CREATE_TABLES_SQL =" not in source, (
        "_CREATE_TABLES_SQL variable assignment found — 25B must not define manual DDL blocks."
    )
    # No actual ATTACH DATABASE call via text() using AST
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
            if func_name in ("text", "execute"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and "ATTACH DATABASE" in str(arg.value).upper():
                        raise AssertionError("text()/execute() with ATTACH DATABASE found — 25B must use PostgreSQL.")


# ─────────────────────── no manual DDL ───────────────────────────────────────


def test_no_manual_create_table() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    # Use AST to detect actual execute()/text() calls with CREATE TABLE string args.
    # This avoids false positives from string literals in self-check assertions.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
            if func_name in ("execute", "text"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and "CREATE TABLE" in str(arg.value).upper():
                        raise AssertionError(
                            f"Manual DDL found: {func_name}() called with CREATE TABLE string argument. "
                            "Tables must come from Alembic migrations."
                        )


# ─────────────────────── no mocks replacing PostgreSQL ───────────────────────


def test_no_mock_replacing_postgresql() -> None:
    mock_patterns = [
        "unittest.mock",
        "from unittest import mock",
        "MagicMock(",
        "@patch(",
        "@mock.patch",
        "FakeSession",
    ]
    source = _TARGET_FILE.read_text(encoding="utf-8")
    for pattern in mock_patterns:
        assert pattern not in source, (
            f"test_postgres_e2e_mcda.py: mock pattern '{pattern}' found. "
            "25B must not replace PostgreSQL with mocks."
        )


# ─────────────────────── no hardcoded credentials ────────────────────────────


def test_no_hardcoded_credentials() -> None:
    banned = [
        "password='",
        'password="',
        "psycopg2://user:pass",
        "psycopg2://admin:",
    ]
    source = _TARGET_FILE.read_text(encoding="utf-8")
    for pattern in banned:
        assert pattern not in source, (
            f"test_postgres_e2e_mcda.py: hardcoded credential pattern '{pattern}' found."
        )


# ─────────────────────── no GEE or LLM ──────────────────────────────────────


def test_no_gee_or_llm_references() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    # Only check import statement lines — string literals in self-check assertions are fine
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    banned_in_imports = ["earthengine", "ee.Initialize", "vertexai", "openai", "anthropic", "generativeai"]
    for indicator in banned_in_imports:
        matching = [l for l in import_lines if indicator.lower() in l.lower()]
        assert not matching, (
            f"test_postgres_e2e_mcda.py: external service import '{indicator}' found: {matching}. "
            "25B must not import external services."
        )


# ─────────────────────── no async infrastructure ─────────────────────────────


def test_no_async_def_in_test_functions() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    async_fns = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
    ]
    assert not async_fns, (
        f"test_postgres_e2e_mcda.py: async test functions found: {async_fns}. "
        "25B tests must be synchronous (psycopg2)."
    )


def test_no_asyncpg_imports() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    # Only check actual import lines — docstring mentions are fine
    import_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    banned_async = ["asyncpg", "AsyncSession", "create_async_engine"]
    for indicator in banned_async:
        matching = [l for l in import_lines if indicator in l]
        assert not matching, f"Async infrastructure import found: {matching}"


# ─────────────────────── required test coverage ──────────────────────────────


def test_covers_evaluacion_completada_status() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "EVALUACION_COMPLETADA" in source, (
        "Must validate that the saga reaches EVALUACION_COMPLETADA"
    )


def test_covers_dispatched_outbox_status() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "DISPATCHED" in source, (
        "Must validate that outbox messages are marked as DISPATCHED"
    )


def test_covers_skip_locked_validation() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "skip_locked" in source, (
        "Must contain a test that validates FOR UPDATE SKIP LOCKED is used"
    )


def test_covers_ranking_check() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "rank_position" in source, (
        "Must validate that crop results have rank_position"
    )


def test_covers_agronomic_gaps_check() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "most_limiting_period" in source, (
        "Must validate that agronomic gaps have most_limiting_period"
    )


# ─────────────────────── pg_migrated dependency ──────────────────────────────


def test_uses_pg_migrated_via_pg25b_cleanup() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "pg25b_cleanup" in source or "pg_migrated" in source, (
        "Must depend on pg_migrated (via pg25b_cleanup) to ensure Alembic migrations run first"
    )


def test_drive_saga_helper_defined() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "drive_saga_to_completion" in func_names, (
        "drive_saga_to_completion helper not found in test_postgres_e2e_mcda.py"
    )


# ─────────────────────── controlled stubs exist ──────────────────────────────


def test_controlled_extraction_client_defined() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "ControlledExtractionClient" in class_names, (
        "ControlledExtractionClient not defined — GEE call is not replaced"
    )


def test_controlled_rulebook_read_model_port_defined() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "ControlledRulebookReadModelPort" in class_names, (
        "ControlledRulebookReadModelPort not defined"
    )


def test_controlled_parcel_geometry_port_defined() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "ControlledParcelGeometryPort" in class_names, (
        "ControlledParcelGeometryPort not defined"
    )


def test_controlled_rulebook_evaluation_port_defined() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert "ControlledRulebookEvaluationPort" in class_names, (
        "ControlledRulebookEvaluationPort not defined"
    )
