"""SQLAlchemy IAM user repository adapters."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.iam.application.ports import IAuthAuditRepository, IUserRepository
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.iam.infrastructure.orm_models import AuthAuditLogModel, UserModel


class SQLAlchemyUserRepository(IUserRepository):
    """Load IAM users from the transactional schema."""

    def __init__(self, session: Session) -> None:
        """Create a repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def get_by_email(self, email: str) -> User | None:
        """Return a user aggregate by normalized email when present."""

        statement = select(UserModel).where(UserModel.email == email.strip().lower())
        model = self._session.execute(statement).scalar_one_or_none()
        if model is None:
            return None
        return _to_domain(model)


class SQLAlchemyAuthAuditRepository(IAuthAuditRepository):
    """Record failed IAM authentication attempts."""

    def __init__(self, session: Session) -> None:
        """Create an audit repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def record_failed_attempt(self, attempted_user: str | None, ip_address: str | None) -> None:
        """Add a failed authentication audit row without committing."""

        self._session.add(AuthAuditLogModel(attempted_user=attempted_user, ip_address=ip_address, success=False))


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        hashed_password=model.hashed_password,
        role=Role(model.role),
    )
