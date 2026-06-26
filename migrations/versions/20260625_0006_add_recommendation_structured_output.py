"""add structured output to recommendations

Revision ID: 20260625_0006
Revises: 20260618_0005
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260625_0006"
down_revision = "20260618_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column(
            "structured_output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="transactional",
    )


def downgrade() -> None:
    op.drop_column("recommendations", "structured_output", schema="transactional")
