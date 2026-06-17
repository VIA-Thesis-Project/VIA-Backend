"""bcrypt password hasher adapter for IAM."""

from __future__ import annotations

from via.bounded_contexts.iam.application.ports import IPasswordHasher


class BcryptPasswordHasher(IPasswordHasher):
    """Verify passwords using the bcrypt library."""

    def hash(self, plain_password: str) -> str:
        """Hash a password using bcrypt for seed/test data creation."""

        bcrypt = _load_bcrypt()
        return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Return whether a plain password matches a bcrypt hash."""

        bcrypt = _load_bcrypt()
        return bool(bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8")))


def _load_bcrypt():
    try:
        import bcrypt
    except ImportError as exc:
        raise RuntimeError("bcrypt is required for IAM password hashing") from exc
    return bcrypt
