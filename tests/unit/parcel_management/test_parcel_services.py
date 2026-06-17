"""Unit tests for Parcel Management application services."""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.parcel_management.application.command_service import ParcelAccessDeniedError, ParcelCommandService
from via.bounded_contexts.parcel_management.application.query_service import ParcelQueryService
from via.bounded_contexts.parcel_management.domain.geometry_validator import ParcelGeometryValidator
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata


class FakeParcelRepository:
    """In-memory parcel repository test double."""

    def __init__(self) -> None:
        """Initialize empty parcel stores."""

        self.parcels = {}
        self.snapshots = []

    def add(self, parcel: Parcel) -> None:
        """Store a new parcel."""

        self.parcels[parcel.id] = parcel

    def get_by_id(self, parcel_id):
        """Return one parcel by id."""

        return self.parcels.get(parcel_id)

    def list_by_owner(self, owner_id):
        """Return parcels owned by the supplied owner."""

        return [parcel for parcel in self.parcels.values() if parcel.owner_id == owner_id]

    def save(self, parcel: Parcel) -> None:
        """Persist changes."""

        self.parcels[parcel.id] = parcel

    def record_version_snapshot(self, parcel: Parcel) -> None:
        """Record a snapshot before mutation."""

        self.snapshots.append((parcel.id, parcel.metadata.to_mapping(), parcel.geometry.to_geojson()))


def test_register_parcel_normalizes_geometry_and_sets_owner() -> None:
    repository = FakeParcelRepository()
    service = ParcelCommandService(repository, ParcelGeometryValidator(max_area_ha=50_000))
    owner_id = uuid4()

    parcel = service.register_parcel(owner_id, _polygon(), _metadata("Farm A"))

    assert parcel.owner_id == owner_id
    assert parcel.geometry.to_geojson()["type"] == "MultiPolygon"
    assert repository.parcels[parcel.id] is parcel


def test_list_parcels_returns_only_authenticated_owner_parcels() -> None:
    repository = FakeParcelRepository()
    owner_id = uuid4()
    other_owner_id = uuid4()
    owned = _parcel(owner_id, "Owned")
    foreign = _parcel(other_owner_id, "Foreign")
    repository.add(owned)
    repository.add(foreign)

    parcels = ParcelQueryService(repository).list_parcels(owner_id)

    assert parcels == [owned]


def test_get_foreign_parcel_raises_access_denied_without_returning_data() -> None:
    repository = FakeParcelRepository()
    owner_id = uuid4()
    foreign = _parcel(uuid4(), "Foreign")
    repository.add(foreign)

    with pytest.raises(ParcelAccessDeniedError):
        ParcelQueryService(repository).get_parcel(foreign.id, owner_id)


def test_update_owned_parcel_records_snapshot_and_updates_metadata() -> None:
    repository = FakeParcelRepository()
    owner_id = uuid4()
    parcel = _parcel(owner_id, "Old")
    repository.add(parcel)
    service = ParcelCommandService(repository, ParcelGeometryValidator(max_area_ha=50_000))

    updated = service.update_parcel(parcel.id, owner_id, metadata=_metadata("New"))

    assert updated.metadata.name == "New"
    assert repository.snapshots[0][1]["name"] == "Old"


def _parcel(owner_id, name: str) -> Parcel:
    return Parcel.create(
        owner_id=owner_id,
        geometry=GeoJSONGeometry.from_geojson(_polygon()),
        metadata=ParcelMetadata.from_mapping(_metadata(name)),
    )


def _metadata(name: str) -> dict:
    return {"name": name, "description": "Plot", "crs": "EPSG:4326"}


def _polygon() -> dict:
    return {"type": "Polygon", "coordinates": [[[-76, -12], [-75.99, -12], [-75.99, -11.99], [-76, -11.99], [-76, -12]]]}
