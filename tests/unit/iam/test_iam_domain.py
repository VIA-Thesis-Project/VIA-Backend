"""Unit tests for IAM domain roles and users."""

from __future__ import annotations

from uuid import uuid4

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User


def test_roles_are_exactly_the_approved_values() -> None:
    roles = {role.value for role in Role}

    assert roles == {"ADMINISTRADOR", "ESPECIALISTA_TECNICO", "USUARIO_AGRICOLA"}


def test_role_hierarchy_allows_higher_roles_to_satisfy_lower_roles() -> None:
    assert Role.ADMINISTRADOR.includes(Role.ESPECIALISTA_TECNICO)
    assert Role.ESPECIALISTA_TECNICO.includes(Role.USUARIO_AGRICOLA)
    assert not Role.USUARIO_AGRICOLA.includes(Role.ESPECIALISTA_TECNICO)


def test_user_normalizes_email_and_checks_role() -> None:
    user = User.create(uuid4(), "  USER@Example.COM ", "hashed", Role.ESPECIALISTA_TECNICO)

    assert user.email == "user@example.com"
    assert user.has_role(Role.USUARIO_AGRICOLA)
    assert not user.has_role(Role.ADMINISTRADOR)
