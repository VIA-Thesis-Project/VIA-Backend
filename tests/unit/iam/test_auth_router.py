"""Unit tests for IAM auth router."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from via.bounded_contexts.iam.application.command_service import INVALID_CREDENTIALS_MESSAGE, InvalidCredentialsError
from via.bounded_contexts.iam.application.ports import AuthenticatedUser, TokenPair
from via.bounded_contexts.iam.interfaces.auth_router import LoginRequest, login, router


class FakeAuthService:
    """Authentication service test double."""

    def __init__(self, should_fail: bool = False) -> None:
        """Configure the fake route dependency."""

        self.should_fail = should_fail
        self.calls = []

    def authenticate(self, email: str, password: str, ip_address: str | None = None) -> AuthenticatedUser:
        """Return a token response or raise an invalid credentials error."""

        self.calls.append((email, password, ip_address))
        if self.should_fail:
            raise InvalidCredentialsError()
        return AuthenticatedUser(
            user_id=uuid4(),
            email=email,
            role="ADMINISTRADOR",
            token=TokenPair(access_token="token", token_type="bearer", expires_in_seconds=3600),
        )


def test_login_returns_token_response() -> None:
    service = FakeAuthService()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    response = login(LoginRequest(email="user@example.com", password="secret"), request, service)

    assert response.access_token == "token"
    assert response.token_type == "bearer"
    assert response.expires_in_seconds == 3600
    assert service.calls == [("user@example.com", "secret", "127.0.0.1")]


def test_login_invalid_credentials_returns_generic_http_401() -> None:
    service = FakeAuthService(should_fail=True)
    request = SimpleNamespace(client=None)

    with pytest.raises(HTTPException) as exc_info:
        login(LoginRequest(email="user@example.com", password="wrong"), request, service)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == INVALID_CREDENTIALS_MESSAGE


def test_router_exposes_public_auth_endpoints() -> None:
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/auth/login" in paths
    assert "/auth/register" in paths
    login_route = next(r for r in router.routes if getattr(r, "path", None) == "/auth/login")
    register_route = next(r for r in router.routes if getattr(r, "path", None) == "/auth/register")
    assert login_route.methods == {"POST"}
    assert register_route.methods == {"POST"}
