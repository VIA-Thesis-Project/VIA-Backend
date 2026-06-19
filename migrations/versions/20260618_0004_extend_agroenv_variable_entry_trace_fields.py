"""extend agroenv variable entry trace fields

Revision ID: 20260618_0004
Revises: 20260618_0003
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260618_0004"
down_revision = "20260618_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agroenv_variable_entries",
        "source",
        existing_type=sa.String(50),
        type_=sa.Text(),
        existing_nullable=False,
        schema="transactional",
    )
    op.alter_column(
        "agroenv_variable_entries",
        "band",
        existing_type=sa.String(100),
        type_=sa.String(128),
        existing_nullable=False,
        schema="transactional",
    )
    op.alter_column(
        "agroenv_variable_entries",
        "period_key",
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=False,
        schema="transactional",
    )


def downgrade() -> None:
    op.alter_column(
        "agroenv_variable_entries",
        "period_key",
        existing_type=sa.String(100),
        type_=sa.String(50),
        existing_nullable=False,
        schema="transactional",
    )
    op.alter_column(
        "agroenv_variable_entries",
        "band",
        existing_type=sa.String(128),
        type_=sa.String(100),
        existing_nullable=False,
        schema="transactional",
    )
    op.alter_column(
        "agroenv_variable_entries",
        "source",
        existing_type=sa.Text(),
        type_=sa.String(50),
        existing_nullable=False,
        schema="transactional",
    )
