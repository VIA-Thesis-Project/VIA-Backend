"""JWT token service adapter for IAM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from via.bounded_contexts.iam.application.ports import ITokenService, TokenPair
from via.bounded_contexts.iam.domain.user import User
from via.config import Settings


class JWTTokenService(ITokenService):
    """Issue signed JWT access tokens using configured expiration."""

    def __init__(self, settings: Settings) -> None:
        """Create a token service from validated VIA settings."""

        self._settings = settings

    def create_access_token(self, user: User) -> TokenPair:
        """Create a signed access token for an authenticated IAM user."""

        jwt = _load_jwt()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._settings.jwt_access_token_expire_minutes)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
            "exp": expires_at,
        }
        token = jwt.encode(payload, self._settings.jwt_secret_key, algorithm=self._settings.jwt_algorithm)
        return TokenPair(
            access_token=token,
            token_type="bearer",
            expires_in_seconds=self._settings.jwt_access_token_expire_minutes * 60,
        )


def _load_jwt():
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("PyJWT is required for IAM token creation") from exc
    return jwt
