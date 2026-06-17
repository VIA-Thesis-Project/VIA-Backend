"""Static architecture checks for VIA Lote 2."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIA = ROOT / "via"
MIGRATIONS = ROOT / "migrations" / "versions"


def test_no_prohibited_infrastructure_tokens_in_lote2_code() -> None:
    tokens = (
        "async" + "pg",
        "Async" + "Session",
        "create_" + "async_" + "engine",
        "Cel" + "ery",
        "Kaf" + "ka",
        "Rabbit" + "MQ",
        "Re" + "dis",
    )
    offenders = []
    for path in _python_files(VIA):
        if any(token in path.read_text(encoding="utf-8") for token in tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_relay_worker_uses_threading_and_time_without_async_loop() -> None:
    text = (VIA / "shared" / "outbox" / "relay_worker.py").read_text(encoding="utf-8")

    assert "threading.Thread" in text
    assert "time.sleep" in text
    assert "async" + "io" not in text


def test_outbox_model_uses_id_as_only_message_identifier() -> None:
    tree = ast.parse((VIA / "shared" / "outbox" / "models.py").read_text(encoding="utf-8"))
    assigned_names = {node.target.id for node in ast.walk(tree) if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}

    assert "id" in assigned_names
    assert "message_id" not in assigned_names
    assert "aggregate_type" in assigned_names
    assert "aggregate_id" in assigned_names
    assert "message_type" in assigned_names
    assert "message_kind" in assigned_names
    assert "payload_json" in assigned_names
    assert "correlation_id" in assigned_names
    assert "last_attempt_at" not in assigned_names


def test_processed_messages_define_composite_primary_key() -> None:
    text = (VIA / "shared" / "idempotency" / "processed_message_store.py").read_text(encoding="utf-8")

    assert 'PrimaryKeyConstraint("message_id", "consumer")' in text
    assert '"schema": TRANSACTIONAL_SCHEMA' in text


def test_migrations_create_required_schemas_extensions_and_columns() -> None:
    schemas = (MIGRATIONS / "20260614_0001_create_schemas_and_extensions.py").read_text(encoding="utf-8")
    tables = (MIGRATIONS / "20260614_0002_initial_tables.py").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS transactional" in schemas
    assert "CREATE SCHEMA IF NOT EXISTS documental" in schemas
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in schemas
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schemas
    assert "CREATE TABLE transactional.outbox_messages" in tables
    outbox_definition = tables.split("CREATE TABLE transactional.outbox_messages", 1)[1].split(")\n", 1)[0]
    assert "message_id" not in outbox_definition
    assert "id UUID PRIMARY KEY" in outbox_definition
    assert "aggregate_type VARCHAR(100) NOT NULL" in outbox_definition
    assert "aggregate_id UUID NOT NULL" in outbox_definition
    assert "message_type VARCHAR(150) NOT NULL" in outbox_definition
    assert "message_kind VARCHAR(10) NOT NULL CHECK (message_kind IN ('COMMAND', 'EVENT'))" in outbox_definition
    assert "payload_json JSONB NOT NULL" in outbox_definition
    assert "correlation_id UUID NULL" in tables
    assert "message_id UUID NOT NULL" in tables
    assert "status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DISPATCHED', 'PERMANENT_FAILURE'))" in outbox_definition
    assert "last_attempt_at" not in outbox_definition
    assert "PRIMARY KEY (message_id, consumer)" in tables
    assert "rank_position INTEGER NULL" in tables
    assert "most_limiting_period VARCHAR(50) NOT NULL" in tables
    assert "entropy_fallback_reason TEXT NULL" in tables
    assert "membership_fn JSONB NOT NULL" in tables
    assert "GEOMETRY(MULTIPOLYGON, 4326)" in tables


def _python_files(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*.py") if "__pycache__" not in item.parts)
