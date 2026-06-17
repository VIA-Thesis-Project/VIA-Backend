"""Parcel aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata


@dataclass
class Parcel:
    """Agricultural parcel owned by one authenticated user."""

    id: UUID
    owner_id: UUID
    geometry: GeoJSONGeometry
    metadata: ParcelMetadata

    @classmethod
    def create(cls, owner_id: UUID, geometry: GeoJSONGeometry, metadata: ParcelMetadata) -> "Parcel":
        """Create a new parcel aggregate."""

        return cls(id=uuid4(), owner_id=owner_id, geometry=geometry, metadata=metadata)

    def update(self, geometry: GeoJSONGeometry | None = None, metadata: ParcelMetadata | None = None) -> None:
        """Update parcel geometry and/or metadata."""

        if geometry is not None:
            self.geometry = geometry
        if metadata is not None:
            self.metadata = metadata
