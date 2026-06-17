"""Parcel geometry read model adapter for saga extraction commands."""

from __future__ import annotations

from uuid import UUID

from via.bounded_contexts.parcel_management.application.ports import IParcelRepository
from via.shared.orchestration.evaluation_process_manager.ports import ParcelGeometrySnapshot


class ParcelGeometryReadModelAdapter:
    """Expose parcel geometry snapshots without leaking parcel internals."""

    def __init__(self, parcel_repository: IParcelRepository) -> None:
        """Create the adapter with a parcel repository port."""

        self._parcel_repository = parcel_repository

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        """Return the current parcel geometry as a GeoJSON snapshot."""

        parcel = self._parcel_repository.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelGeometryNotFoundError(f"Parcel geometry not found: {parcel_id}")
        return ParcelGeometrySnapshot(parcel_id=parcel.id, geometry=parcel.geometry.to_geojson())


class ParcelGeometryNotFoundError(LookupError):
    """Raised when the parcel geometry read model cannot find a parcel."""
