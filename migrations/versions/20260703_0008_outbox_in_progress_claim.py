"""outbox: add IN_PROGRESS status and claimed_at for lock-free relay dispatch

Revision ID: 20260703_0008
Revises: 20260627_0007
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260703_0008"
down_revision = "20260627_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The original CHECK was created inline (auto-named by PostgreSQL); the ORM
    # declares ck_outbox_status. Drop both spellings before recreating.
    op.execute(
        "ALTER TABLE transactional.outbox_messages "
        "DROP CONSTRAINT IF EXISTS outbox_messages_status_check"
    )
    op.execute(
        "ALTER TABLE transactional.outbox_messages "
        "DROP CONSTRAINT IF EXISTS ck_outbox_status"
    )
    op.execute(
        "ALTER TABLE transactional.outbox_messages "
        "ADD CONSTRAINT ck_outbox_status "
        "CHECK (status IN ('PENDING', 'IN_PROGRESS', 'DISPATCHED', 'PERMANENT_FAILURE'))"
    )
    op.add_column(
        "outbox_messages",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        schema="transactional",
    )


def downgrade() -> None:
    # Revert in-flight claims so the narrower CHECK can be restored.
    op.execute(
        "UPDATE transactional.outbox_messages "
        "SET status = 'PENDING' WHERE status = 'IN_PROGRESS'"
    )
    op.drop_column("outbox_messages", "claimed_at", schema="transactional")
    op.execute(
        "ALTER TABLE transactional.outbox_messages "
        "DROP CONSTRAINT IF EXISTS ck_outbox_status"
    )
    op.execute(
        "ALTER TABLE transactional.outbox_messages "
        "ADD CONSTRAINT ck_outbox_status "
        "CHECK (status IN ('PENDING', 'DISPATCHED', 'PERMANENT_FAILURE'))"
    )
