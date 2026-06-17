"""IAM user aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.iam.domain.role import Role


@dataclass(frozen=True)
class User:
    """Authenticated principal persisted by IAM."""

    id: UUID
    email: str
    hashed_password: str
    role: Role

    def has_role(self, required_role: Role) -> bool:
        """Return whether the user has enough privilege for a role-gated action."""

        return self.role.includes(required_role)

    @classmethod
    def create(cls, user_id: UUID, email: str, hashed_password: str, role: Role) -> "User":
        """Create a user aggregate after applying basic domain invariants."""

        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("User email is required")
        if not hashed_password:
            raise ValueError("User hashed password is required")
        return cls(id=user_id, email=normalized_email, hashed_password=hashed_password, role=role)
