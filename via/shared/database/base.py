"""Shared SQLAlchemy declarative base and approved PostgreSQL schemas."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from via.config import DEFAULT_DOCUMENTAL_SCHEMA, DEFAULT_TRANSACTIONAL_SCHEMA


TRANSACTIONAL_SCHEMA = DEFAULT_TRANSACTIONAL_SCHEMA
DOCUMENTAL_SCHEMA = DEFAULT_DOCUMENTAL_SCHEMA
APPROVED_SCHEMAS = (TRANSACTIONAL_SCHEMA, DOCUMENTAL_SCHEMA)


class Base(DeclarativeBase):
    """Declarative base shared by all future synchronous ORM models."""

    metadata = MetaData()


def get_approved_schema_names() -> tuple[str, str]:
    """Return the isolated PostgreSQL schemas approved for VIA persistence."""

    return APPROVED_SCHEMAS
