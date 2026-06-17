"""create schemas and extensions

Revision ID: 20260614_0001
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "20260614_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create VIA logical schemas and required PostgreSQL extensions."""

    op.execute("CREATE SCHEMA IF NOT EXISTS transactional")
    op.execute("CREATE SCHEMA IF NOT EXISTS documental")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Leave extensions installed and drop only VIA-owned schemas."""

    op.execute("DROP SCHEMA IF EXISTS documental CASCADE")
    op.execute("DROP SCHEMA IF EXISTS transactional CASCADE")
