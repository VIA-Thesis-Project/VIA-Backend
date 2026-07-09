"""add membership to agronomy_gaps

Severity is defined as 1 - membership (paper eq. 15), so the fuzzy membership of
the most limiting period must be persisted alongside each gap.

Revision ID: 20260706_0009
Revises: 20260703_0008
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260706_0009"
down_revision = "20260703_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default satisfies NOT NULL for any pre-existing rows during ADD
    # COLUMN, then is removed so the domain remains the single source of truth.
    # Agronomy gaps are transactional and recreated per evaluation, so stale
    # rows carrying the default are never read for a live evaluation.
    op.add_column(
        "agronomy_gaps",
        sa.Column(
            "membership",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0",
        ),
        schema="transactional",
    )
    op.alter_column(
        "agronomy_gaps",
        "membership",
        server_default=None,
        schema="transactional",
    )


def downgrade() -> None:
    op.drop_column("agronomy_gaps", "membership", schema="transactional")
