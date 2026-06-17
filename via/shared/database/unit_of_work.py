"""Synchronous SQLAlchemy unit of work."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from via.shared.database.session import get_session_factory


class SqlAlchemyUnitOfWork:
    """Coordinate commit and rollback for one synchronous SQLAlchemy Session."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()
        self.session: Session | None = None

    def __enter__(self) -> Session:
        """Open and expose a synchronous SQLAlchemy Session."""

        self.session = self._session_factory()
        return self.session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback on errors and always close the active Session."""

        if self.session is None:
            return
        if exc_type is not None:
            self.rollback()
        self.session.close()
        self.session = None

    def commit(self) -> None:
        """Commit the active Session transaction."""

        self._require_session().commit()

    def rollback(self) -> None:
        """Rollback the active Session transaction."""

        self._require_session().rollback()

    def _require_session(self) -> Session:
        if self.session is None:
            raise RuntimeError("Unit of work session is not active")
        return self.session
