"""extend viability_category to VARCHAR(20) for NO_CONCLUYENTE

Revision ID: 20260618_0003
Revises: 20260614_0002
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260618_0003"
down_revision = "20260614_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "evaluation_results",
        "viability_category",
        existing_type=sa.String(15),
        type_=sa.String(20),
        schema="transactional",
    )


def downgrade() -> None:
    op.alter_column(
        "evaluation_results",
        "viability_category",
        existing_type=sa.String(20),
        type_=sa.String(15),
        schema="transactional",
    )
