"""Synchronous SQLAlchemy database foundation for VIA."""

from via.shared.database.base import Base, DOCUMENTAL_SCHEMA, TRANSACTIONAL_SCHEMA
from via.shared.database.session import create_session, get_engine, get_session_factory
from via.shared.database.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "Base",
    "DOCUMENTAL_SCHEMA",
    "TRANSACTIONAL_SCHEMA",
    "SqlAlchemyUnitOfWork",
    "create_session",
    "get_engine",
    "get_session_factory",
]
