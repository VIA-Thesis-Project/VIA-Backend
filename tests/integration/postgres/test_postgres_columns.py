"""22A: Validate critical column definitions in key VIA tables after migrations."""

from __future__ import annotations

import pytest
from sqlalchemy import text

_CRITICAL_COLUMNS: list[tuple[str, str, list[str]]] = [
    (
        "transactional",
        "evaluation_sagas",
        ["id", "parcel_id", "requested_by", "crop_candidates", "temporal_window", "status", "created_at", "updated_at"],
    ),
    (
        "transactional",
        "outbox_messages",
        ["id", "aggregate_type", "aggregate_id", "message_type", "message_kind", "payload_json", "status", "retry_count", "created_at"],
    ),
    (
        "transactional",
        "processed_message_ids",
        ["message_id", "consumer", "processed_at"],
    ),
    (
        "transactional",
        "saga_transitions",
        ["id", "saga_id", "from_status", "to_status", "occurred_at"],
    ),
    (
        "transactional",
        "agroenv_vectors",
        ["id", "evaluation_id", "parcel_id", "temporal_window", "extracted_at"],
    ),
    (
        "transactional",
        "agroenv_variable_entries",
        ["id", "vector_id", "variable_name", "criterion_id", "crop_id", "phase_id", "value", "source", "extraction_date", "period_key", "status"],
    ),
    (
        "transactional",
        "evaluation_results",
        ["id", "evaluation_id", "crop_id", "score", "calc_condition", "viability_category", "rank_position", "rulebook_version"],
    ),
    (
        "transactional",
        "evaluation_criterion_details",
        ["id", "result_id", "criterion_id", "memberships_by_period", "aggregated_membership", "w_ahp", "w_hybrid"],
    ),
    (
        "transactional",
        "agronomy_gaps",
        ["id", "result_id", "criterion_id", "phase_id", "most_limiting_period", "observed_value", "optimal_limit", "gap_value"],
    ),
    (
        "transactional",
        "limiting_factors",
        ["id", "result_id", "criterion_id", "phase_id", "policy", "observed_value", "optimal_limit", "membership"],
    ),
    (
        "transactional",
        "recommendations",
        ["id", "evaluation_id", "crop_id", "text", "fragment_ids", "generated_at"],
    ),
    (
        "transactional",
        "users",
        ["id", "email", "hashed_password", "role", "created_at"],
    ),
    (
        "transactional",
        "parcels",
        ["id", "owner_id", "geometry", "metadata", "created_at"],
    ),
    (
        "transactional",
        "rulebooks",
        ["id", "crop_id", "version", "status", "created_at"],
    ),
    (
        "transactional",
        "rulebook_criteria",
        ["id", "rulebook_id", "name", "is_critical", "ahp_weight"],
    ),
    (
        "transactional",
        "rulebook_phases",
        ["id", "rulebook_id", "name", "duration_days", "sequence_order"],
    ),
    (
        "transactional",
        "rulebook_phase_requirements",
        ["id", "criterion_id", "phase_id", "membership_fn", "phase_weight", "temporal_periods", "extraction_binding"],
    ),
    (
        "documental",
        "documents",
        ["id", "title", "format", "crop_tags", "size_bytes", "uploaded_at", "status"],
    ),
    (
        "documental",
        "document_fragments",
        ["id", "document_id", "text", "page_ref", "crop_tags", "token_count", "embedding", "created_at"],
    ),
]


def _columns_in_table(conn, schema: str, table: str) -> set[str]:
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema, "table": table},
    )
    return {row[0] for row in result}


@pytest.mark.slow
@pytest.mark.parametrize(
    "schema,table,expected_cols",
    _CRITICAL_COLUMNS,
    ids=[f"{s}.{t}" for s, t, _ in _CRITICAL_COLUMNS],
)
def test_critical_columns_exist(pg_migrated, schema: str, table: str, expected_cols: list[str]) -> None:
    with pg_migrated.connect() as conn:
        actual = _columns_in_table(conn, schema, table)
    missing = set(expected_cols) - actual
    assert not missing, (
        f"Table '{schema}.{table}' is missing columns: {sorted(missing)}. "
        f"Actual columns: {sorted(actual)}"
    )


@pytest.mark.slow
def test_outbox_messages_payload_is_jsonb(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = 'transactional' "
                "AND table_name = 'outbox_messages' "
                "AND column_name = 'payload_json'"
            )
        )
        row = result.fetchone()
    assert row is not None, "Column 'payload_json' not found in outbox_messages"
    assert row[1] == "jsonb", (
        f"Column 'payload_json' should be JSONB, got udt_name='{row[1]}'"
    )


@pytest.mark.slow
def test_document_fragments_embedding_is_vector(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = 'documental' "
                "AND table_name = 'document_fragments' "
                "AND column_name = 'embedding'"
            )
        )
        row = result.fetchone()
    assert row is not None, "Column 'embedding' not found in document_fragments"
    assert row[0] == "vector", (
        f"Column 'embedding' should be VECTOR type, got udt_name='{row[0]}'"
    )


@pytest.mark.slow
def test_parcels_geometry_is_geometry_type(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = 'transactional' "
                "AND table_name = 'parcels' "
                "AND column_name = 'geometry'"
            )
        )
        row = result.fetchone()
    assert row is not None, "Column 'geometry' not found in parcels"
    assert row[0] == "geometry", (
        f"Column 'geometry' should be PostGIS geometry type, got udt_name='{row[0]}'"
    )


@pytest.mark.slow
def test_evaluation_sagas_crop_candidates_is_jsonb(pg_migrated) -> None:
    with pg_migrated.connect() as conn:
        result = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = 'transactional' "
                "AND table_name = 'evaluation_sagas' "
                "AND column_name = 'crop_candidates'"
            )
        )
        row = result.fetchone()
    assert row is not None, "Column 'crop_candidates' not found in evaluation_sagas"
    assert row[0] == "jsonb", (
        f"Column 'crop_candidates' should be JSONB, got udt_name='{row[0]}'"
    )
