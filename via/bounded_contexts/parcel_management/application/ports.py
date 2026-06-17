"""Application ports for Parcel Management."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from via.bounded_contexts.parcel_management.domain.parcel import Parcel


class IParcelRepository(Protocol):
    """Persistence port for parcel aggregates."""

    def add(self, parcel: Parcel) -> None:
        """Persist a new parcel."""

    def get_by_id(self, parcel_id: UUID) -> Parcel | None:
        """Return one parcel regardless of owner."""

    def list_by_owner(self, owner_id: UUID) -> list[Parcel]:
        """Return parcels owned by the supplied owner."""

    def save(self, parcel: Parcel) -> None:
        """Persist changes to an existing parcel."""

    def record_version_snapshot(self, parcel: Parcel) -> None:
        """Record a snapshot before updating a parcel."""
