"""Parcel query application services."""

from __future__ import annotations

from uuid import UUID

from via.bounded_contexts.parcel_management.application.command_service import ParcelAccessDeniedError, ParcelNotFoundError
from via.bounded_contexts.parcel_management.application.ports import IParcelRepository
from via.bounded_contexts.parcel_management.domain.parcel import Parcel


class ParcelQueryService:
    """Read parcel data scoped to the authenticated owner."""

    def __init__(self, parcel_repository: IParcelRepository) -> None:
        """Create the query service with a repository port."""

        self._parcel_repository = parcel_repository

    def list_parcels(self, owner_id: UUID) -> list[Parcel]:
        """Return parcels owned by the authenticated user."""

        return self._parcel_repository.list_by_owner(owner_id)

    def get_parcel(self, parcel_id: UUID, owner_id: UUID) -> Parcel:
        """Return an owned parcel, hiding existence of foreign parcels behind 403."""

        parcel = self._parcel_repository.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelNotFoundError("Parcel not found")
        if parcel.owner_id != owner_id:
            raise ParcelAccessDeniedError("Access denied")
        return parcel
