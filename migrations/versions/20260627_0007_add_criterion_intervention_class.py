"""add intervention_class to rulebook_criteria

Revision ID: 20260627_0007
Revises: 20260625_0006
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260627_0007"
down_revision = "20260625_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default is required only to satisfy NOT NULL during ADD COLUMN on
    # existing rows. It is removed immediately so the DB rejects any insert that
    # does not supply the value — the domain is the single source of truth.
    op.add_column(
        "rulebook_criteria",
        sa.Column(
            "intervention_class",
            sa.String(20),
            nullable=False,
            server_default="MITIGABLE",
        ),
        schema="transactional",
    )
    op.alter_column(
        "rulebook_criteria",
        "intervention_class",
        server_default=None,
        schema="transactional",
    )


def downgrade() -> None:
    op.drop_column("rulebook_criteria", "intervention_class", schema="transactional")
