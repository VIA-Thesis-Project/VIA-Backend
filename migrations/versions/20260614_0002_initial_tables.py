"""initial tables

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "20260614_0002"
down_revision = "20260614_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial transactional and documental tables for VIA."""

    op.execute("""
CREATE TABLE transactional.evaluation_sagas (
    id UUID PRIMARY KEY,
    parcel_id UUID NOT NULL,
    requested_by UUID NOT NULL,
    crop_candidates JSONB NOT NULL,
    temporal_window JSONB NOT NULL,
    status VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.saga_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saga_id UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    from_status VARCHAR(30),
    to_status VARCHAR(30) NOT NULL,
    triggered_by UUID,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    failure_cause TEXT
)
""")
    op.execute("""
CREATE TABLE transactional.outbox_messages (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(100) NOT NULL,
    aggregate_id UUID NOT NULL,
    message_type VARCHAR(150) NOT NULL,
    message_kind VARCHAR(10) NOT NULL CHECK (message_kind IN ('COMMAND', 'EVENT')),
    payload_json JSONB NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DISPATCHED', 'PERMANENT_FAILURE')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    correlation_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at TIMESTAMPTZ
)
""")
    op.execute("CREATE INDEX idx_outbox_status_created ON transactional.outbox_messages (status, created_at, id)")
    op.execute("""
CREATE TABLE transactional.processed_message_ids (
    message_id UUID NOT NULL,
    consumer VARCHAR(100) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer)
)
""")
    op.execute("""
CREATE TABLE transactional.users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.auth_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempted_user VARCHAR(255),
    ip_address VARCHAR(45),
    success BOOLEAN NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.parcels (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    geometry GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.parcel_version_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES transactional.parcels(id),
    metadata_snapshot JSONB NOT NULL,
    geometry_snapshot GEOMETRY(MULTIPOLYGON, 4326),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.rulebooks (
    id UUID PRIMARY KEY,
    crop_id VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL,
    status VARCHAR(10) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(crop_id, version)
)
""")
    op.execute("""
CREATE TABLE transactional.rulebook_criteria (
    id UUID PRIMARY KEY,
    rulebook_id UUID NOT NULL REFERENCES transactional.rulebooks(id),
    name VARCHAR(150) NOT NULL,
    is_critical BOOLEAN NOT NULL DEFAULT FALSE,
    critical_policy VARCHAR(20),
    penalty_factor NUMERIC(4,3),
    ahp_weight NUMERIC(6,5) NOT NULL,
    doc_source TEXT,
    technical_notes TEXT
)
""")
    op.execute("""
CREATE TABLE transactional.rulebook_phases (
    id UUID PRIMARY KEY,
    rulebook_id UUID NOT NULL REFERENCES transactional.rulebooks(id),
    name VARCHAR(100) NOT NULL,
    duration_days INTEGER NOT NULL,
    sequence_order INTEGER NOT NULL
)
""")
    op.execute("""
CREATE TABLE transactional.rulebook_phase_requirements (
    id UUID PRIMARY KEY,
    criterion_id UUID NOT NULL REFERENCES transactional.rulebook_criteria(id),
    phase_id UUID NOT NULL REFERENCES transactional.rulebook_phases(id),
    membership_fn JSONB NOT NULL,
    phase_weight NUMERIC(6,5) NOT NULL,
    temporal_periods JSONB NOT NULL,
    extraction_binding JSONB NOT NULL,
    UNIQUE(criterion_id, phase_id)
)
""")
    op.execute("""
CREATE TABLE transactional.agroenv_vectors (
    id UUID PRIMARY KEY,
    evaluation_id UUID NOT NULL,
    parcel_id UUID NOT NULL,
    temporal_window JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.agroenv_variable_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vector_id UUID NOT NULL REFERENCES transactional.agroenv_vectors(id),
    variable_name VARCHAR(100) NOT NULL,
    criterion_id VARCHAR(100) NOT NULL,
    crop_id VARCHAR(100) NOT NULL,
    phase_id VARCHAR(100) NOT NULL,
    dataset_key VARCHAR(150) NOT NULL,
    band VARCHAR(100) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    temporal_resolution VARCHAR(50) NOT NULL,
    spatial_resolution VARCHAR(50),
    scale NUMERIC,
    reducer VARCHAR(100) NOT NULL,
    aggregation_method VARCHAR(100) NOT NULL,
    quality_mask JSONB,
    fallback_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    value NUMERIC,
    source VARCHAR(50) NOT NULL,
    extraction_date DATE NOT NULL,
    period_key VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL
)
""")
    op.execute("""
CREATE TABLE transactional.evaluation_results (
    id UUID PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    crop_id VARCHAR(100) NOT NULL,
    score NUMERIC(5,4),
    calc_condition VARCHAR(20) NOT NULL,
    viability_category VARCHAR(15) NOT NULL,
    rank_position INTEGER NULL,
    rulebook_version INTEGER NOT NULL,
    entropy_used BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE transactional.evaluation_criterion_details (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id VARCHAR(100) NOT NULL,
    memberships_by_period JSONB NOT NULL,
    aggregated_by_phase JSONB NOT NULL,
    aggregated_membership NUMERIC(5,4) NOT NULL,
    w_ahp NUMERIC(6,5) NOT NULL,
    w_entropy NUMERIC(6,5),
    w_hybrid NUMERIC(6,5) NOT NULL,
    entropy_series_used BOOLEAN NOT NULL,
    entropy_fallback_reason TEXT NULL
)
""")
    op.execute("""
CREATE TABLE transactional.agronomy_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id VARCHAR(100) NOT NULL,
    phase_id VARCHAR(100) NOT NULL,
    most_limiting_period VARCHAR(50) NOT NULL,
    observed_value NUMERIC NOT NULL,
    optimal_limit NUMERIC NOT NULL,
    gap_value NUMERIC NOT NULL
)
""")
    op.execute("""
CREATE TABLE transactional.limiting_factors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id VARCHAR(100) NOT NULL,
    phase_id VARCHAR(100) NOT NULL,
    policy VARCHAR(20) NOT NULL,
    penalty_factor NUMERIC(4,3),
    observed_value NUMERIC NOT NULL,
    optimal_limit NUMERIC NOT NULL,
    membership NUMERIC(5,4) NOT NULL,
    doc_source TEXT
)
""")
    op.execute("""
CREATE TABLE transactional.recommendations (
    id UUID PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    crop_id VARCHAR(100) NOT NULL,
    text TEXT NOT NULL,
    fragment_ids JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE TABLE documental.documents (
    id UUID PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    format VARCHAR(10) NOT NULL,
    crop_tags JSONB NOT NULL,
    size_bytes BIGINT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
)
""")
    op.execute("""
CREATE TABLE documental.document_fragments (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documental.documents(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    page_ref INTEGER,
    crop_tags JSONB NOT NULL,
    token_count INTEGER NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""")
    op.execute("CREATE INDEX idx_fragments_embedding ON documental.document_fragments USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")


def downgrade() -> None:
    """Drop initial tables in dependency order."""

    tables = (
        "documental.document_fragments",
        "documental.documents",
        "transactional.recommendations",
        "transactional.limiting_factors",
        "transactional.agronomy_gaps",
        "transactional.evaluation_criterion_details",
        "transactional.evaluation_results",
        "transactional.agroenv_variable_entries",
        "transactional.agroenv_vectors",
        "transactional.rulebook_phase_requirements",
        "transactional.rulebook_phases",
        "transactional.rulebook_criteria",
        "transactional.rulebooks",
        "transactional.parcel_version_history",
        "transactional.parcels",
        "transactional.auth_audit_log",
        "transactional.users",
        "transactional.processed_message_ids",
        "transactional.outbox_messages",
        "transactional.saga_transitions",
        "transactional.evaluation_sagas",
    )
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

