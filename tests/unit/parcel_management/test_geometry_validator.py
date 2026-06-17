"""Unit tests for parcel GeoJSON validation."""

from __future__ import annotations

import pytest

from via.bounded_contexts.parcel_management.domain.geometry_validator import ParcelGeometryValidator
from via.bounded_contexts.parcel_management.domain.value_objects import GeometryValidationError


def test_polygon_is_normalized_to_multipolygon() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)

    geometry = validator.validate(_polygon())

    assert geometry.to_geojson()["type"] == "MultiPolygon"
    assert geometry.coordinates == [_polygon()["coordinates"]]


@pytest.mark.parametrize("geometry_type", ["Point", "LineString", "GeometryCollection"])
def test_rejects_non_polygon_geometry_types(geometry_type: str) -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)

    with pytest.raises(GeometryValidationError, match="Polygon or MultiPolygon"):
        validator.validate({"type": geometry_type, "coordinates": [0, 0]})


def test_rejects_open_rings() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)
    geometry = _polygon([[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01]])

    with pytest.raises(GeometryValidationError, match="closed"):
        validator.validate(geometry)


def test_rejects_coordinates_outside_wgs84() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)
    geometry = _polygon([[181, 0], [181, 1], [182, 1], [181, 0]])

    with pytest.raises(GeometryValidationError, match="Longitude"):
        validator.validate(geometry)


def test_rejects_exterior_ring_with_less_than_four_points() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)
    geometry = _polygon([[0, 0], [0.01, 0], [0, 0]])

    with pytest.raises(GeometryValidationError, match="at least 4 points"):
        validator.validate(geometry)


def test_rejects_self_intersecting_polygon() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)
    geometry = _polygon([[0, 0], [0.01, 0.01], [0, 0.01], [0.01, 0], [0, 0]])

    with pytest.raises(GeometryValidationError, match="self-intersections"):
        validator.validate(geometry)


def test_rejects_polygon_exceeding_max_area() -> None:
    validator = ParcelGeometryValidator(max_area_ha=1)

    with pytest.raises(GeometryValidationError, match="exceeds maximum"):
        validator.validate(_polygon())


def test_computes_area_for_valid_polygon() -> None:
    validator = ParcelGeometryValidator(max_area_ha=50_000)
    geometry = validator.validate(_polygon())

    assert validator.area_ha(geometry) > 100


def _polygon(ring: list | None = None) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [ring or [[-76.0, -12.0], [-75.99, -12.0], [-75.99, -11.99], [-76.0, -11.99], [-76.0, -12.0]]],
    }
