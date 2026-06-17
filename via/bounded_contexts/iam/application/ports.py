"""Application ports for the IAM bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from via.bounded_contexts.iam.domain.user import User


class IUserRepository(Protocol):
    """Persistence port for IAM users."""

    def get_by_email(self, email: str) -> User | None:
        """Return a user by normalized email when present."""


class IAuthAuditRepository(Protocol):
    """Persistence port for authentication audit rows."""

    def record_failed_attempt(self, attempted_user: str | None, ip_address: str | None) -> None:
        """Record a failed authentication attempt."""


class IPasswordHasher(Protocol):
    """Password verification port implemented by secure infrastructure adapters."""

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Return whether a plain password matches a stored secure hash."""


class ITokenService(Protocol):
    """Token issuing port implemented by infrastructure JWT adapters."""

    def create_access_token(self, user: User) -> "TokenPair":
        """Create a signed access token for an authenticated user."""


@dataclass(frozen=True)
class TokenPair:
    """Access token returned by IAM authentication."""

    access_token: str
    token_type: str
    expires_in_seconds: int


@dataclass(frozen=True)
class AuthenticatedUser:
    """Application DTO for a successful login."""

    user_id: UUID
    email: str
    role: str
    token: TokenPair
