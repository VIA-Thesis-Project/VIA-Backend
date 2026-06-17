"""Parcel command application services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from via.bounded_contexts.parcel_management.application.ports import IParcelRepository
from via.bounded_contexts.parcel_management.domain.geometry_validator import ParcelGeometryValidator
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import ParcelMetadata


class ParcelNotFoundError(LookupError):
    """Raised when a parcel does not exist."""


class ParcelAccessDeniedError(PermissionError):
    """Raised when a user attempts to access another user's parcel."""


class ParcelCommandService:
    """Create and update parcels through domain validation and repository ports."""

    def __init__(self, parcel_repository: IParcelRepository, geometry_validator: ParcelGeometryValidator) -> None:
        """Create the service with repository and validator ports."""

        self._parcel_repository = parcel_repository
        self._geometry_validator = geometry_validator

    def register_parcel(self, owner_id: UUID, geometry: dict[str, Any], metadata: dict[str, Any]) -> Parcel:
        """Validate and persist a new parcel for the owner."""

        normalized_geometry = self._geometry_validator.validate(geometry)
        parcel_metadata = ParcelMetadata.from_mapping(metadata)
        parcel = Parcel.create(owner_id=owner_id, geometry=normalized_geometry, metadata=parcel_metadata)
        self._parcel_repository.add(parcel)
        return parcel

    def update_parcel(
        self,
        parcel_id: UUID,
        owner_id: UUID,
        geometry: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Parcel:
        """Update an owned parcel after validating geometry and metadata."""

        parcel = self._parcel_repository.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelNotFoundError("Parcel not found")
        if parcel.owner_id != owner_id:
            raise ParcelAccessDeniedError("Access denied")

        normalized_geometry = self._geometry_validator.validate(geometry) if geometry is not None else None
        parcel_metadata = ParcelMetadata.from_mapping(metadata) if metadata is not None else None
        self._parcel_repository.record_version_snapshot(parcel)
        parcel.update(geometry=normalized_geometry, metadata=parcel_metadata)
        self._parcel_repository.save(parcel)
        return parcel
