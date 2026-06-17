"""Application ports for Rulebook Management."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook


class IRulebookRepository(Protocol):
    """Persistence contract for versioned rulebooks."""

    def next_version_for_crop(self, crop_id: str) -> int:
        """Return the next version number for a crop."""

    def add(self, rulebook: Rulebook) -> None:
        """Persist a new rulebook aggregate."""

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        """Return one rulebook by id or None."""

    def get_active_by_crop(self, crop_id: str) -> Rulebook | None:
        """Return the active rulebook for one crop or None."""

    def list_all(self) -> list[Rulebook]:
        """Return all rulebook versions."""

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        """Deactivate the current active version for a crop."""

    def save(self, rulebook: Rulebook) -> None:
        """Persist changes to an existing rulebook aggregate."""


class IRulebookUnitOfWork(Protocol):
    """Minimal unit of work used by rulebook command services."""

    rulebooks: IRulebookRepository

    def __enter__(self) -> "IRulebookUnitOfWork":
        """Open the unit of work."""

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the unit of work."""

    def commit(self) -> None:
        """Commit the active transaction."""

    def rollback(self) -> None:
        """Rollback the active transaction."""
