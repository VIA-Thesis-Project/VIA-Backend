"""Phenological phase entity for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.value_objects import RulebookValidationError


@dataclass(frozen=True)
class PhenologicalPhase:
    """Named crop phase participating in a rulebook version."""

    id: UUID
    name: str
    duration_days: int
    sequence_order: int

    def __post_init__(self) -> None:
        """Validate phase identity and ordering fields."""

        if not self.name.strip():
            raise RulebookValidationError("phase name must not be empty")
        if self.duration_days <= 0:
            raise RulebookValidationError("phase duration_days must be positive")
        if self.sequence_order <= 0:
            raise RulebookValidationError("phase sequence_order must be positive")
