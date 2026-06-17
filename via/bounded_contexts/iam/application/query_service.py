"""IAM query and authorization application services."""

from __future__ import annotations

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User


class InsufficientPermissionsError(PermissionError):
    """Raised when an authenticated user lacks enough privileges."""


class IAMQueryService:
    """Expose read-only IAM authorization helpers."""

    def ensure_role(self, user: User, required_role: Role) -> None:
        """Raise when the user does not satisfy the required role."""

        if not user.has_role(required_role):
            raise InsufficientPermissionsError("Insufficient permissions")
