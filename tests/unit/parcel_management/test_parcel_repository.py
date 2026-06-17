"""Unit tests for parcel repository serialization helpers."""

from __future__ import annotations

import struct
from uuid import uuid4

import pytest

from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata
from via.bounded_contexts.parcel_management.infrastructure.parcel_geometry_read_model import (
    ParcelGeometryNotFoundError,
    ParcelGeometryReadModelAdapter,
)
from via.bounded_contexts.parcel_management.infrastructure.parcel_repository import geojson_multipolygon_to_wkt, wkt_to_geojson_multipolygon
from via.bounded_contexts.parcel_management.infrastructure.orm_models import ParcelModel
from via.shared.database.types import Geometry


def test_geojson_multipolygon_serializes_to_srid_4326_wkt() -> None:
    geometry = GeoJSONGeometry.from_geojson(_polygon())

    wkt = geojson_multipolygon_to_wkt(geometry)

    assert wkt.startswith("SRID=4326;MULTIPOLYGON")
    assert wkt_to_geojson_multipolygon(wkt).to_geojson() == geometry.to_geojson()


def test_parcel_orm_uses_multipolygon_4326_geometry_type() -> None:
    column_type = ParcelModel.__table__.columns["geometry"].type

    assert isinstance(column_type, Geometry)
    assert column_type.geometry_type == "MULTIPOLYGON"
    assert column_type.srid == 4326


def test_parcel_domain_can_be_constructed_for_repository_mapping() -> None:
    parcel = Parcel.create(uuid4(), GeoJSONGeometry.from_geojson(_polygon()), ParcelMetadata.from_mapping(_metadata()))

    assert parcel.geometry.to_geojson()["type"] == "MultiPolygon"


def test_parcel_geometry_read_model_returns_geojson_snapshot() -> None:
    parcel = Parcel.create(uuid4(), GeoJSONGeometry.from_geojson(_polygon()), ParcelMetadata.from_mapping(_metadata()))
    repository = FakeParcelRepository(parcel)

    snapshot = ParcelGeometryReadModelAdapter(repository).get_parcel_geometry(parcel.id)

    assert snapshot.parcel_id == parcel.id
    assert snapshot.geometry["type"] == "MultiPolygon"


def test_parcel_geometry_read_model_fails_when_parcel_missing() -> None:
    with pytest.raises(ParcelGeometryNotFoundError):
        ParcelGeometryReadModelAdapter(FakeParcelRepository(None)).get_parcel_geometry(uuid4())


class FakeParcelRepository:
    """Parcel repository fake for read-model adapter tests."""

    def __init__(self, parcel: Parcel | None) -> None:
        """Create a fake repository with an optional parcel."""

        self.parcel = parcel

    def get_by_id(self, parcel_id):
        """Return the configured parcel when ids match."""

        if self.parcel is not None and self.parcel.id == parcel_id:
            return self.parcel
        return None

    def add(self, parcel):
        """Unused repository method required by the port."""

    def list_by_owner(self, owner_id):
        """Unused repository method required by the port."""

        return []

    def save(self, parcel):
        """Unused repository method required by the port."""

    def record_version_snapshot(self, parcel):
        """Unused repository method required by the port."""


def test_wkt_to_geojson_multipolygon_handles_ewkb_hex_from_postgis() -> None:
    """EWKB hex string returned by psycopg2/PostGIS is decoded to GeoJSONGeometry."""
    ring = [(-76.0, -12.0), (-75.99, -12.0), (-75.99, -11.99), (-76.0, -11.99), (-76.0, -12.0)]
    ewkb_hex = _build_ewkb_multipolygon_hex([[ring]])

    result = wkt_to_geojson_multipolygon(ewkb_hex)

    assert result.to_geojson()["type"] == "MultiPolygon"
    outer_ring = result.coordinates[0][0]
    assert len(outer_ring) == 5
    assert abs(outer_ring[0][0] - (-76.0)) < 1e-10
    assert abs(outer_ring[0][1] - (-12.0)) < 1e-10


def test_wkt_to_geojson_multipolygon_handles_ewkb_bytes() -> None:
    """Binary EWKB bytes (e.g. from memoryview) are decoded to GeoJSONGeometry."""
    ring = [(-76.0, -12.0), (-75.99, -12.0), (-75.99, -11.99), (-76.0, -11.99), (-76.0, -12.0)]
    ewkb_bytes = bytes.fromhex(_build_ewkb_multipolygon_hex([[ring]]))

    result = wkt_to_geojson_multipolygon(ewkb_bytes)

    assert result.to_geojson()["type"] == "MultiPolygon"
    assert len(result.coordinates) == 1


def test_wkt_to_geojson_multipolygon_handles_ewkb_memoryview() -> None:
    """memoryview EWKB is decoded to GeoJSONGeometry."""
    ring = [(-76.0, -12.0), (-75.99, -12.0), (-75.99, -11.99), (-76.0, -11.99), (-76.0, -12.0)]
    ewkb_mv = memoryview(bytes.fromhex(_build_ewkb_multipolygon_hex([[ring]])))

    result = wkt_to_geojson_multipolygon(ewkb_mv)

    assert result.to_geojson()["type"] == "MultiPolygon"


def test_wkt_to_geojson_multipolygon_ewkb_round_trips_with_wkt_serializer() -> None:
    """EWKB-decoded geometry re-serializes to the same EWKT as the WKT path."""
    ring = [(-76.01, -12.01), (-76.009, -12.01), (-76.009, -12.009), (-76.01, -12.009), (-76.01, -12.01)]
    ewkb_hex = _build_ewkb_multipolygon_hex([[ring]])

    from_ewkb = wkt_to_geojson_multipolygon(ewkb_hex)
    wkt = geojson_multipolygon_to_wkt(from_ewkb)
    from_wkt = wkt_to_geojson_multipolygon(wkt)

    assert from_ewkb.to_geojson() == from_wkt.to_geojson()


def test_wkt_to_geojson_multipolygon_rejects_non_multipolygon_ewkb() -> None:
    """EWKB encoding a Polygon (WKB type 3) raises ValueError, not a silent wrong type."""
    buf = bytearray()
    buf += b"\x01"
    buf += struct.pack("<I", 3 | 0x20000000)  # Polygon with SRID flag — invalid for parcels
    buf += struct.pack("<I", 4326)
    ewkb_hex = buf.hex()

    with pytest.raises(ValueError, match="MULTIPOLYGON"):
        wkt_to_geojson_multipolygon(ewkb_hex)


def test_wkt_to_geojson_multipolygon_ewkb_uppercase_hex_accepted() -> None:
    """EWKB hex in uppercase (as sometimes returned by PostGIS) is accepted."""
    ring = [(-76.0, -12.0), (-75.99, -12.0), (-75.99, -11.99), (-76.0, -11.99), (-76.0, -12.0)]
    ewkb_hex_upper = _build_ewkb_multipolygon_hex([[ring]]).upper()

    result = wkt_to_geojson_multipolygon(ewkb_hex_upper)

    assert result.to_geojson()["type"] == "MultiPolygon"


def _build_ewkb_multipolygon_hex(
    polygons: list[list[list[tuple[float, float]]]], srid: int = 4326
) -> str:
    """Build EWKB hex string for a MULTIPOLYGON SRID={srid} in little-endian WKB format.

    ``polygons`` is a list of polygons; each polygon is a list of rings; each ring is a
    list of (x, y) tuples where x=longitude and y=latitude.  Matches the format produced
    by PostGIS for GEOMETRY(MULTIPOLYGON, 4326) columns.
    """
    buf = bytearray()
    buf += b"\x01"
    buf += struct.pack("<I", 6 | 0x20000000)  # MultiPolygon + EWKB SRID flag
    buf += struct.pack("<I", srid)
    buf += struct.pack("<I", len(polygons))
    for rings in polygons:
        buf += b"\x01"
        buf += struct.pack("<I", 3)  # Polygon sub-geometry, no SRID flag
        buf += struct.pack("<I", len(rings))
        for ring in rings:
            buf += struct.pack("<I", len(ring))
            for x, y in ring:
                buf += struct.pack("<d", x)
                buf += struct.pack("<d", y)
    return buf.hex()


def _polygon() -> dict:
    return {"type": "Polygon", "coordinates": [[[-76, -12], [-75.99, -12], [-75.99, -11.99], [-76, -11.99], [-76, -12]]]}


def _metadata() -> dict:
    return {"name": "Farm", "description": "Plot", "crs": "EPSG:4326"}
