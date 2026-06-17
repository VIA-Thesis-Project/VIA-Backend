"""22B: Static architecture validation for Outbox/Relay/Idempotency integration tests.

Verifies structural constraints:
- Required test file exists
- Imports RelayWorker (not LockFreeRelayWorker)
- Uses real PostgreSQL via pg_migrated/pg_outbox_env
- No SQLite, no manual DDL, no mocks replacing PostgreSQL
- No hardcoded credentials
- No asyncpg / async infrastructure
- FOR UPDATE SKIP LOCKED is validated in the tests
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_INTEGRATION_DIR = _REPO_ROOT / "tests" / "integration" / "postgres"
_TARGET_FILE = _INTEGRATION_DIR / "test_outbox_relay_idempotency.py"


# ─────────────────────── file existence ───────────────────────────────────────


def test_outbox_relay_test_file_exists() -> None:
    assert _TARGET_FILE.exists(), (
        "tests/integration/postgres/test_outbox_relay_idempotency.py does not exist. "
        "Run lote 22B implementation."
    )


# ─────────────────────── required imports ─────────────────────────────────────


def test_imports_real_relay_worker() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "from via.shared.outbox.relay_worker import RelayWorker" in source, (
        "Must import RelayWorker from via.shared.outbox.relay_worker (the real production worker)"
    )


def test_does_not_import_lock_free_relay_worker() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    import_lines = [
        line for line in source.splitlines()
        if "import" in line and "LockFree" in line
    ]
    assert not import_lines, (
        "test_outbox_relay_idempotency.py must not import LockFreeRelayWorker (SQLite E2E variant). "
        "Use the real RelayWorker with FOR UPDATE SKIP LOCKED."
    )


def test_imports_in_memory_event_bus() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "InMemoryEventBus" in source, (
        "Must use InMemoryEventBus (real implementation) as the event bus"
    )


def test_imports_idempotent_consumer_mixin() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "IdempotentConsumerMixin" in source, (
        "Must use IdempotentConsumerMixin for the idempotency tests"
    )


def test_imports_outbox_writer() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "OutboxWriter" in source, (
        "Must use OutboxWriter for inserting test messages"
    )


# ─────────────────────── no banned patterns ───────────────────────────────────


def test_no_sqlite_engine_usage() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    actual_sqlite_patterns = [
        "sqlite://",
        'create_engine("sqlite',
        "create_engine('sqlite",
        "ATTACH DATABASE",
    ]
    for pattern in actual_sqlite_patterns:
        assert pattern not in source, (
            f"test_outbox_relay_idempotency.py: actual SQLite engine usage found: {pattern!r}. "
            "22B tests must use real PostgreSQL."
        )


def test_no_manual_create_table() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    actual_ddl_patterns = [
        'execute("CREATE',
        "execute('CREATE",
        'text("CREATE',
        "text('CREATE",
    ]
    for pattern in actual_ddl_patterns:
        assert pattern not in source, (
            f"test_outbox_relay_idempotency.py: manual DDL in SQL execution: {pattern!r}. "
            "Tables must come from Alembic migrations."
        )


def test_no_mock_replacing_postgresql() -> None:
    mock_indicators = [
        "unittest.mock",
        "from unittest import mock",
        "MagicMock(",
        "@patch(",
        "@mock.patch",
        "FakeSession",
    ]
    source = _TARGET_FILE.read_text(encoding="utf-8")
    for indicator in mock_indicators:
        assert indicator not in source, (
            f"test_outbox_relay_idempotency.py: mock pattern '{indicator}' found. "
            "22B must not replace PostgreSQL with mocks."
        )


def test_no_hardcoded_credentials() -> None:
    banned = ["password='", 'password="', "psycopg2://user:pass", "psycopg2://admin:"]
    source = _TARGET_FILE.read_text(encoding="utf-8")
    for pattern in banned:
        assert pattern not in source, (
            f"test_outbox_relay_idempotency.py: hardcoded credential pattern '{pattern}' found."
        )


def test_no_gee_or_llm_references() -> None:
    banned = ["earthengine", "ee.Initialize", "vertexai", "openai", "anthropic", "generativeai"]
    source = _TARGET_FILE.read_text(encoding="utf-8")
    for indicator in banned:
        assert indicator not in source, (
            f"test_outbox_relay_idempotency.py: external service '{indicator}' found. "
            "22B must not call external services."
        )


# ─────────────────────── no async ─────────────────────────────────────────────


def test_no_async_def_in_test_file() -> None:
    tree = ast.parse(_TARGET_FILE.read_text(encoding="utf-8"))
    async_fns = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
    ]
    assert not async_fns, (
        f"test_outbox_relay_idempotency.py: async test functions: {async_fns}. "
        "22B tests must be synchronous (psycopg2)."
    )


def test_no_asyncpg_imports() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "asyncpg" not in source, "Must not import asyncpg"
    assert "AsyncSession" not in source, "Must not use AsyncSession"
    assert "create_async_engine" not in source, "Must not use create_async_engine"


# ─────────────────────── required test coverage ───────────────────────────────


def test_covers_skip_locked_validation() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "skip_locked" in source, (
        "Must contain a test that validates FOR UPDATE SKIP LOCKED is used"
    )


def test_covers_dispatched_status() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "DISPATCHED" in source, (
        "Must validate that messages are marked as DISPATCHED after relay"
    )


def test_covers_idempotency_constraint() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "IntegrityError" in source or "idempotent" in source.lower(), (
        "Must test the database-level idempotency constraint"
    )


def test_covers_permanent_failure() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "PERMANENT_FAILURE" in source, (
        "Must test that PERMANENT_FAILURE is set after max_retries"
    )


# ─────────────────────── pg_migrated used ──────────────────────────────────────


def test_uses_pg_migrated_via_pg_outbox_env() -> None:
    source = _TARGET_FILE.read_text(encoding="utf-8")
    assert "pg_outbox_env" in source or "pg_migrated" in source, (
        "Must use pg_migrated (via pg_outbox_env) to ensure tables exist before tests run"
    )
