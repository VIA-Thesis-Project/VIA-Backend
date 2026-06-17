"""22A: Validate that VIA logical schemas exist after running migrations."""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _schema_exists(conn, schema_name: str) -> bool:
    result = conn.execute(
        text("SELECT 1 FROM pg_namespace WHERE nspname = :name"),
        {"name": schema_name},
    )
    return result.fetchone() is not None


@pytest.mark.slow
def test_transactional_schema_exists(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        exists = _schema_exists(conn, "transactional")
    assert exists, (
        "Schema 'transactional' does not exist. "
        "Verify that migration 20260614_0001 ran: CREATE SCHEMA IF NOT EXISTS transactional"
    )


@pytest.mark.slow
def test_documental_schema_exists(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        exists = _schema_exists(conn, "documental")
    assert exists, (
        "Schema 'documental' does not exist. "
        "Verify that migration 20260614_0001 ran: CREATE SCHEMA IF NOT EXISTS documental"
    )


@pytest.mark.slow
def test_schemas_are_isolated_from_each_other(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        trans_exists = _schema_exists(conn, "transactional")
        doc_exists = _schema_exists(conn, "documental")
    assert trans_exists and doc_exists, (
        "Both schemas must exist to satisfy the isolation requirement."
    )


@pytest.mark.slow
def test_public_schema_is_not_the_only_schema(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND nspname NOT LIKE 'pg_%'"
            )
        )
        schemas = {row[0] for row in result}
    assert "transactional" in schemas, "'transactional' schema missing after migration"
    assert "documental" in schemas, "'documental' schema missing after migration"
