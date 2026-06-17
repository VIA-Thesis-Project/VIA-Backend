"""Unit tests for IAM authentication application service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.iam.application.command_service import INVALID_CREDENTIALS_MESSAGE, AuthenticateUserCommandService, InvalidCredentialsError
from via.bounded_contexts.iam.application.ports import TokenPair
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User


class FakeUserRepository:
    """In-memory user repository test double."""

    def __init__(self, user: User | None) -> None:
        """Store the user returned by get_by_email."""

        self.user = user
        self.requested_emails = []

    def get_by_email(self, email: str) -> User | None:
        """Return the configured user and record the normalized email."""

        self.requested_emails.append(email)
        return self.user


class FakePasswordHasher:
    """Password hasher test double."""

    def __init__(self, valid: bool) -> None:
        """Configure the verification result."""

        self.valid = valid
        self.calls = []

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Record verification input and return the configured result."""

        self.calls.append((plain_password, hashed_password))
        return self.valid


class FakeTokenService:
    """Token service test double."""

    def __init__(self) -> None:
        """Initialize an empty call log."""

        self.calls = []

    def create_access_token(self, user: User) -> TokenPair:
        """Return a deterministic token and record the user."""

        self.calls.append(user)
        return TokenPair(access_token="token", token_type="bearer", expires_in_seconds=3600)


class FakeAuditRepository:
    """Authentication audit repository test double."""

    def __init__(self) -> None:
        """Initialize an empty failed-attempt log."""

        self.failed_attempts = []

    def record_failed_attempt(self, attempted_user: str | None, ip_address: str | None) -> None:
        """Record failed attempts."""

        self.failed_attempts.append((attempted_user, ip_address))


def test_authenticate_valid_credentials_returns_generic_token_response() -> None:
    user = User.create(uuid4(), "user@example.com", "stored-hash", Role.ADMINISTRADOR)
    audit_repository = FakeAuditRepository()
    token_service = FakeTokenService()
    service = AuthenticateUserCommandService(
        FakeUserRepository(user),
        FakePasswordHasher(valid=True),
        token_service,
        audit_repository,
    )

    authenticated = service.authenticate(" USER@example.com ", "secret", "127.0.0.1")

    assert authenticated.user_id == user.id
    assert authenticated.role == Role.ADMINISTRADOR.value
    assert authenticated.token.access_token == "token"
    assert token_service.calls == [user]
    assert audit_repository.failed_attempts == []


@pytest.mark.parametrize("user_exists, password_valid", [(False, True), (True, False)])
def test_invalid_credentials_raise_generic_error_and_audit_failure(user_exists: bool, password_valid: bool) -> None:
    user = User.create(uuid4(), "user@example.com", "stored-hash", Role.USUARIO_AGRICOLA) if user_exists else None
    audit_repository = FakeAuditRepository()
    service = AuthenticateUserCommandService(
        FakeUserRepository(user),
        FakePasswordHasher(valid=password_valid),
        FakeTokenService(),
        audit_repository,
    )

    with pytest.raises(InvalidCredentialsError) as exc_info:
        service.authenticate("missing@example.com", "wrong", "10.0.0.1")

    assert str(exc_info.value) == INVALID_CREDENTIALS_MESSAGE
    assert audit_repository.failed_attempts == [("missing@example.com", "10.0.0.1")]
