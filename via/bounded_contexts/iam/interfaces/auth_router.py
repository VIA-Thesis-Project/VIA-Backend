"""Public IAM authentication routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from via.bounded_contexts.iam.application.command_service import (
    INVALID_CREDENTIALS_MESSAGE,
    AuthenticateUserCommandService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    RegisterUserCommandService,
)


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Credentials submitted to IAM login."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """JWT response returned after a successful login."""

    access_token: str
    token_type: str
    expires_in_seconds: int


class RegisterRequest(BaseModel):
    """Credentials submitted to IAM registration."""

    email: str
    password: str


class RegisterResponse(BaseModel):
    """User data returned after successful registration."""

    user_id: UUID
    email: str
    role: str


def get_authentication_service() -> AuthenticateUserCommandService:
    """Return the configured IAM authentication service dependency."""

    raise RuntimeError("IAM authentication service dependency is not configured")


def get_register_service() -> RegisterUserCommandService:
    """Return the configured IAM registration service dependency."""

    raise RuntimeError("IAM registration service dependency is not configured")


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    register_service: RegisterUserCommandService = Depends(get_register_service),
) -> RegisterResponse:
    """Register a new user with role USUARIO_AGRICOLA."""

    try:
        user = register_service.register(email=body.email, password=body.password)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RegisterResponse(user_id=user.id, email=user.email, role=user.role.value)


@router.post("/login", response_model=TokenResponse)
def login(
    credentials: LoginRequest,
    request: Request,
    auth_service: AuthenticateUserCommandService = Depends(get_authentication_service),
) -> TokenResponse:
    """Authenticate credentials and return an access token."""

    try:
        authenticated = auth_service.authenticate(
            email=credentials.email,
            password=credentials.password,
            ip_address=request.client.host if request.client else None,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_MESSAGE) from exc

    return TokenResponse(
        access_token=authenticated.token.access_token,
        token_type=authenticated.token.token_type,
        expires_in_seconds=authenticated.token.expires_in_seconds,
    )
