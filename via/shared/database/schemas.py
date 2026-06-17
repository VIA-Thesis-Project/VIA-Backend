"""Schema helpers for the two isolated PostgreSQL persistence areas."""

from __future__ import annotations

from sqlalchemy.schema import CreateSchema

from via.shared.database.base import DOCUMENTAL_SCHEMA, TRANSACTIONAL_SCHEMA


def schema_creation_statements() -> tuple[CreateSchema, CreateSchema]:
    """Build idempotent SQLAlchemy DDL objects for approved PostgreSQL schemas."""

    return (
        CreateSchema(TRANSACTIONAL_SCHEMA, if_not_exists=True),
        CreateSchema(DOCUMENTAL_SCHEMA, if_not_exists=True),
    )
