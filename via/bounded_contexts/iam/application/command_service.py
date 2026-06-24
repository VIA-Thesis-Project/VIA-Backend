"""IAM command application services."""

from __future__ import annotations

from uuid import uuid4

from via.bounded_contexts.iam.application.ports import (
    AuthenticatedUser,
    IAuthAuditRepository,
    IPasswordHasher,
    ITokenService,
    IUserRepository,
)
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User


INVALID_CREDENTIALS_MESSAGE = "Invalid credentials"


class InvalidCredentialsError(ValueError):
    """Raised when user credentials cannot be authenticated."""

    def __init__(self) -> None:
        """Create the generic invalid credentials error."""

        super().__init__(INVALID_CREDENTIALS_MESSAGE)


class AuthenticateUserCommandService:
    """Authenticate users through IAM application ports."""

    def __init__(
        self,
        user_repository: IUserRepository,
        password_hasher: IPasswordHasher,
        token_service: ITokenService,
        auth_audit_repository: IAuthAuditRepository,
    ) -> None:
        """Create the service with infrastructure supplied through ports."""

        self._user_repository = user_repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._auth_audit_repository = auth_audit_repository

    def authenticate(self, email: str, password: str, ip_address: str | None = None) -> AuthenticatedUser:
        """Validate credentials and return a signed token response."""

        normalized_email = email.strip().lower()
        user = self._user_repository.get_by_email(normalized_email)
        if user is None:
            self._record_failed_attempt(normalized_email, ip_address)
            raise InvalidCredentialsError()

        if not self._password_hasher.verify(password, user.hashed_password):
            self._record_failed_attempt(normalized_email, ip_address)
            raise InvalidCredentialsError()

        token = self._token_service.create_access_token(user)
        return AuthenticatedUser(user_id=user.id, email=user.email, role=user.role.value, token=token)

    def _record_failed_attempt(self, attempted_user: str | None, ip_address: str | None) -> None:
        self._auth_audit_repository.record_failed_attempt(attempted_user, ip_address)


class EmailAlreadyExistsError(ValueError):
    """Raised when a registration email is already in use."""


class RegisterUserCommandService:
    """Register new users with the USUARIO_AGRICOLA role."""

    MIN_PASSWORD_LENGTH = 8

    def __init__(self, user_repository: IUserRepository, password_hasher: IPasswordHasher) -> None:
        self._user_repository = user_repository
        self._password_hasher = password_hasher

    def register(self, email: str, password: str) -> User:
        """Create and persist a new user; raise on duplicate email or weak password."""

        if len(password) < self.MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {self.MIN_PASSWORD_LENGTH} characters")
        normalized = email.strip().lower()
        if self._user_repository.get_by_email(normalized) is not None:
            raise EmailAlreadyExistsError("Email already registered")
        hashed = self._password_hasher.hash(password)
        user = User.create(uuid4(), normalized, hashed, Role.USUARIO_AGRICOLA)
        self._user_repository.save(user)
        return user
