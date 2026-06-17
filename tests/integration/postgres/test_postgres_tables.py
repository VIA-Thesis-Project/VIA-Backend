"""22A: Validate that all critical VIA tables exist after running migrations."""

from __future__ import annotations

import pytest
from sqlalchemy import text

_TRANSACTIONAL_TABLES = [
    "evaluation_sagas",
    "saga_transitions",
    "outbox_messages",
    "processed_message_ids",
    "users",
    "auth_audit_log",
    "parcels",
    "parcel_version_history",
    "rulebooks",
    "rulebook_criteria",
    "rulebook_phases",
    "rulebook_phase_requirements",
    "agroenv_vectors",
    "agroenv_variable_entries",
    "evaluation_results",
    "evaluation_criterion_details",
    "agronomy_gaps",
    "limiting_factors",
    "recommendations",
]

_DOCUMENTAL_TABLES = [
    "documents",
    "document_fragments",
]


def _table_exists(conn, schema: str, table: str) -> bool:
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema, "table": table},
    )
    return result.fetchone() is not None


@pytest.mark.slow
@pytest.mark.parametrize("table_name", _TRANSACTIONAL_TABLES)
def test_transactional_table_exists(pg_migrated, table_name: str) -> None:
    with pg_migrated.connect() as conn:
        exists = _table_exists(conn, "transactional", table_name)
    assert exists, (
        f"Table 'transactional.{table_name}' does not exist after upgrade head. "
        "Check migration 20260614_0002."
    )


@pytest.mark.slow
@pytest.mark.parametrize("table_name", _DOCUMENTAL_TABLES)
def test_documental_table_exists(pg_migrated, table_name: str) -> None:
    with pg_migrated.connect() as conn:
        exists = _table_exists(conn, "documental", table_name)
    assert exists, (
        f"Table 'documental.{table_name}' does not exist after upgrade head. "
        "Check migration 20260614_0002."
    )


@pytest.mark.slow
def test_total_transactional_table_count(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'transactional'"
            )
        )
        count = result.scalar_one()
    assert count == len(_TRANSACTIONAL_TABLES), (
        f"Expected {len(_TRANSACTIONAL_TABLES)} tables in 'transactional' schema, "
        f"found {count}. Check migrations for missing or extra tables."
    )


@pytest.mark.slow
def test_total_documental_table_count(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'documental'"
            )
        )
        count = result.scalar_one()
    assert count == len(_DOCUMENTAL_TABLES), (
        f"Expected {len(_DOCUMENTAL_TABLES)} tables in 'documental' schema, "
        f"found {count}. Check migrations for missing or extra tables."
    )
