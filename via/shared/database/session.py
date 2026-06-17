"""Synchronous SQLAlchemy engine and session factory configuration."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from via.config import Settings, get_settings


def get_engine(settings: Settings | None = None) -> Engine:
    """Create a synchronous SQLAlchemy Engine backed by psycopg2."""

    resolved_settings = settings or get_settings()
    return create_engine(resolved_settings.database_url, future=True)


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Create a synchronous SQLAlchemy Session factory."""

    resolved_engine = engine or get_engine()
    return sessionmaker(bind=resolved_engine, class_=Session, autoflush=False, expire_on_commit=False)


def create_session(session_factory: sessionmaker[Session] | None = None) -> Session:
    """Create one synchronous SQLAlchemy Session instance."""

    resolved_factory = session_factory or get_session_factory()
    return resolved_factory()
