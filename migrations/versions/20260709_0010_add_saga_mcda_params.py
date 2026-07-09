"""add mcda_params to evaluation_sagas

Stores per-evaluation MCDA parameters (user-defined viability thresholds) so
the saga can thread them into the EjecutarEvaluacionViabilidad command when
the extraction phase completes. Nullable: evaluations without explicit
parameters keep using the deployment defaults.

Revision ID: 20260709_0010
Revises: 20260706_0009
Create Date: 2026-07-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260709_0010"
down_revision = "20260706_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluation_sagas",
        sa.Column("mcda_params", JSONB, nullable=True),
        schema="transactional",
    )


def downgrade() -> None:
    op.drop_column("evaluation_sagas", "mcda_params", schema="transactional")
