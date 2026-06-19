"""add provider column to recommendations

Revision ID: 20260618_0005
Revises: 20260618_0004
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260618_0005"
down_revision = "20260618_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("provider", sa.String(50), nullable=False, server_default="template"),
        schema="transactional",
    )


def downgrade() -> None:
    op.drop_column("recommendations", "provider", schema="transactional")
