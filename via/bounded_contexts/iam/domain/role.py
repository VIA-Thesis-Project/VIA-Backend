"""IAM role model and hierarchy rules."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Approved VIA IAM roles ordered by access level."""

    ADMINISTRADOR = "ADMINISTRADOR"
    ESPECIALISTA_TECNICO = "ESPECIALISTA_TECNICO"
    USUARIO_AGRICOLA = "USUARIO_AGRICOLA"

    def includes(self, required_role: "Role") -> bool:
        """Return whether this role satisfies the required role level."""

        return _ROLE_RANK[self] >= _ROLE_RANK[required_role]


_ROLE_RANK: dict[Role, int] = {
    Role.USUARIO_AGRICOLA: 1,
    Role.ESPECIALISTA_TECNICO: 2,
    Role.ADMINISTRADOR: 3,
}
