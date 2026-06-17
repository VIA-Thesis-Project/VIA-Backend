"""22A: Static architecture validation for PostgreSQL integration test suite.

Checks that the integration/postgres package satisfies lote 22A constraints:
- Required files exist
- No hardcoded credentials
- No SQLite references
- No mock usage
- No GEE / LLM / external service calls
- DATABASE_URL read from environment variable
- All test functions are synchronous
- Correct pytest markers and skip logic
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_INTEGRATION_DIR = _REPO_ROOT / "tests" / "integration" / "postgres"

_REQUIRED_FILES = [
    "__init__.py",
    "conftest.py",
    "test_postgres_connection.py",
    "test_postgres_extensions.py",
    "test_postgres_schemas.py",
    "test_postgres_migrations.py",
    "test_postgres_tables.py",
    "test_postgres_columns.py",
    "test_postgres_no_async.py",
]

_BANNED_CREDENTIAL_PATTERNS = [
    "psycopg2://user:pass",
    'password="m4rcous"',
    "password='m4rcous'",
]

_BANNED_INFRA = [
    "sqlite",
    "earthengine",
    "ee.Initialize",
    "google.cloud.aiplatform",
    "vertexai",
    "openai",
    "anthropic",
    "genai",
    "LLM",
    "GEE",
]

_MOCK_PATTERNS = [
    "unittest.mock",
    "from unittest import mock",
    "MagicMock",
    "patch(",
    "@patch",
    "Mock(",
]


# ─────────────────────── file existence ───────────────────────────────────────


def test_integration_postgres_directory_exists() -> None:
    assert _INTEGRATION_DIR.exists(), (
        f"Directory {_INTEGRATION_DIR} does not exist. "
        "Run lote 22A implementation to create the integration test package."
    )


def test_all_required_files_exist() -> None:
    missing = [f for f in _REQUIRED_FILES if not (_INTEGRATION_DIR / f).exists()]
    assert not missing, (
        f"Missing files in tests/integration/postgres/: {missing}"
    )


def test_integration_init_exists() -> None:
    assert (_REPO_ROOT / "tests" / "integration" / "__init__.py").exists(), (
        "tests/integration/__init__.py is missing. The integration package must be a Python package."
    )


# ─────────────────────── no hardcoded credentials ─────────────────────────────


def test_no_hardcoded_credentials_in_any_file() -> None:
    for fname in _REQUIRED_FILES:
        if fname in _STATIC_CHECKER_FILES:
            continue
        fpath = _INTEGRATION_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for pattern in _BANNED_CREDENTIAL_PATTERNS:
            assert pattern not in source, (
                f"{fname}: contains what looks like a hardcoded credential: {pattern!r}. "
                "Read DATABASE_URL from os.environ only."
            )


# ─────────────────────── no banned infrastructure ─────────────────────────────


_STATIC_CHECKER_FILES = {"test_postgres_no_async.py"}


def test_no_sqlite_in_any_file() -> None:
    for fname in _REQUIRED_FILES:
        if fname in _STATIC_CHECKER_FILES:
            continue
        fpath = _INTEGRATION_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8").lower()
        assert "sqlite" not in source, (
            f"{fname}: references SQLite. Lote 22A tests must use real PostgreSQL."
        )


def test_no_gee_or_llm_in_any_file() -> None:
    for fname in _REQUIRED_FILES:
        if fname in _STATIC_CHECKER_FILES:
            continue
        fpath = _INTEGRATION_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for indicator in _BANNED_INFRA[1:]:
            assert indicator not in source, (
                f"{fname}: references banned external service: {indicator!r}"
            )


def test_no_mock_usage_in_test_files() -> None:
    test_files = [f for f in _REQUIRED_FILES if f.startswith("test_") and f not in _STATIC_CHECKER_FILES]
    for fname in test_files:
        fpath = _INTEGRATION_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for pattern in _MOCK_PATTERNS:
            assert pattern not in source, (
                f"{fname}: uses mock ({pattern!r}). "
                "Integration tests must hit the real PostgreSQL database."
            )


# ─────────────────────── DATABASE_URL from environment ─────────────────────────


def test_conftest_reads_database_url_from_environment() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "os.environ" in conftest or "os.getenv" in conftest, (
        "conftest.py must read DATABASE_URL from os.environ, not hardcode it."
    )


def test_conftest_skips_when_database_url_absent() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "pytest.skip" in conftest, (
        "conftest.py must call pytest.skip() when DATABASE_URL is not set."
    )


def test_conftest_validates_psycopg2_driver() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "psycopg2" in conftest, (
        "conftest.py must validate that DATABASE_URL uses the psycopg2 driver."
    )


# ─────────────────────── synchronous tests only ───────────────────────────────


def test_all_test_functions_are_synchronous() -> None:
    test_files = [f for f in _REQUIRED_FILES if f.startswith("test_")]
    for fname in test_files:
        fpath = _INTEGRATION_DIR / fname
        if not fpath.exists():
            continue
        tree = ast.parse(fpath.read_text(encoding="utf-8"))
        async_fns = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
        ]
        assert not async_fns, (
            f"{fname}: async test functions found: {async_fns}. "
            "VIA integration tests must be synchronous (psycopg2)."
        )


# ─────────────────────── pg_migrated used for migration-dependent tests ────────


def test_extension_tests_depend_on_pg_migrated() -> None:
    source = (_INTEGRATION_DIR / "test_postgres_extensions.py").read_text(encoding="utf-8")
    assert "pg_migrated" in source, (
        "test_postgres_extensions.py must use the pg_migrated fixture to ensure "
        "migration 20260614_0001 has run before checking extensions."
    )


def test_table_tests_depend_on_pg_migrated() -> None:
    source = (_INTEGRATION_DIR / "test_postgres_tables.py").read_text(encoding="utf-8")
    assert "pg_migrated" in source, (
        "test_postgres_tables.py must use the pg_migrated fixture."
    )


def test_column_tests_depend_on_pg_migrated() -> None:
    source = (_INTEGRATION_DIR / "test_postgres_columns.py").read_text(encoding="utf-8")
    assert "pg_migrated" in source, (
        "test_postgres_columns.py must use the pg_migrated fixture."
    )


# ─────────────────────── alembic used for migrations ──────────────────────────


def test_conftest_uses_alembic_not_raw_create_table() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "alembic" in conftest, (
        "conftest.py must use Alembic (not raw CREATE TABLE) to set up the database."
    )
    assert "CREATE TABLE" not in conftest.upper(), (
        "conftest.py must not use raw CREATE TABLE. Tables come from Alembic migrations."
    )


def test_conftest_runs_upgrade_head() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "upgrade" in conftest, (
        "conftest.py must call alembic upgrade (alembic_command.upgrade or similar)."
    )


# ─────────────────────── safety guard ─────────────────────────────────────────


def test_conftest_has_safety_guard_for_db_name() -> None:
    conftest = (_INTEGRATION_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "test" in conftest and ("safety" in conftest.lower() or "guard" in conftest.lower()), (
        "conftest.py must contain a safety guard that prevents running destructive "
        "migration operations against a non-test database."
    )
