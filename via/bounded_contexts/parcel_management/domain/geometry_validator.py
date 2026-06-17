"""Domain service for GeoJSON parcel validation."""

from __future__ import annotations

from math import cos, pi, radians
from typing import Any

from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, GeometryValidationError


EARTH_RADIUS_M = 6_371_000.0


class ParcelGeometryValidator:
    """Validate and measure GeoJSON parcel geometries without infrastructure dependencies."""

    def __init__(self, max_area_ha: float) -> None:
        """Create a validator with a configured maximum area in hectares."""

        self._max_area_ha = max_area_ha

    def validate(self, geometry: dict[str, Any]) -> GeoJSONGeometry:
        """Validate geometry and return a normalized MultiPolygon value object."""

        normalized = GeoJSONGeometry.from_geojson(geometry)
        if not isinstance(normalized.coordinates, list) or not normalized.coordinates:
            raise GeometryValidationError("MultiPolygon coordinates must not be empty")

        total_area = 0.0
        for polygon_index, polygon in enumerate(normalized.coordinates):
            total_area += self._validate_polygon(polygon, polygon_index)
        if total_area > self._max_area_ha:
            raise GeometryValidationError(
                f"Parcel area {total_area:.2f} ha exceeds maximum {self._max_area_ha:.2f} ha"
            )
        return normalized

    def area_ha(self, geometry: GeoJSONGeometry) -> float:
        """Return the approximate total area in hectares for a normalized geometry."""

        return sum(_polygon_area_ha(polygon) for polygon in geometry.coordinates)

    def _validate_polygon(self, polygon: list, polygon_index: int) -> float:
        if not isinstance(polygon, list) or not polygon:
            raise GeometryValidationError(f"Polygon {polygon_index} must contain at least one ring")

        exterior = polygon[0]
        self._validate_ring(exterior, polygon_index, 0, require_minimum_points=True)
        for ring_index, ring in enumerate(polygon[1:], start=1):
            self._validate_ring(ring, polygon_index, ring_index, require_minimum_points=False)
        area = _polygon_area_ha(polygon)
        if area > self._max_area_ha:
            raise GeometryValidationError(
                f"Polygon {polygon_index} area {area:.2f} ha exceeds maximum {self._max_area_ha:.2f} ha"
            )
        return area

    def _validate_ring(self, ring: list, polygon_index: int, ring_index: int, require_minimum_points: bool) -> None:
        if not isinstance(ring, list):
            raise GeometryValidationError(f"Ring {ring_index} in polygon {polygon_index} must be a list")
        if require_minimum_points and len(ring) < 4:
            raise GeometryValidationError(f"Exterior ring in polygon {polygon_index} must contain at least 4 points")
        if len(ring) < 4:
            raise GeometryValidationError(f"Ring {ring_index} in polygon {polygon_index} must contain at least 4 points")
        points = [_coordinate(point, polygon_index, ring_index) for point in ring]
        if points[0] != points[-1]:
            raise GeometryValidationError(f"Ring {ring_index} in polygon {polygon_index} must be closed")
        if _has_self_intersection(points):
            raise GeometryValidationError(f"Ring {ring_index} in polygon {polygon_index} has self-intersections")


def _coordinate(point: object, polygon_index: int, ring_index: int) -> tuple[float, float]:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        raise GeometryValidationError(f"Invalid coordinate in ring {ring_index} polygon {polygon_index}")
    longitude = float(point[0])
    latitude = float(point[1])
    if not -180.0 <= longitude <= 180.0:
        raise GeometryValidationError("Longitude must be within WGS-84 bounds")
    if not -90.0 <= latitude <= 90.0:
        raise GeometryValidationError("Latitude must be within WGS-84 bounds")
    return longitude, latitude


def _has_self_intersection(points: list[tuple[float, float]]) -> bool:
    segments = list(zip(points, points[1:]))
    for index, segment_a in enumerate(segments):
        for other_index, segment_b in enumerate(segments[index + 1 :], start=index + 1):
            if _segments_are_adjacent(index, other_index, len(segments)):
                continue
            if _segments_intersect(segment_a[0], segment_a[1], segment_b[0], segment_b[1]):
                return True
    return False


def _segments_are_adjacent(first: int, second: int, segment_count: int) -> bool:
    return abs(first - second) == 1 or {first, second} == {0, segment_count - 1}


def _segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    orientation_1 = _orientation(a, b, c)
    orientation_2 = _orientation(a, b, d)
    orientation_3 = _orientation(c, d, a)
    orientation_4 = _orientation(c, d, b)

    if orientation_1 == 0 and _on_segment(a, c, b):
        return True
    if orientation_2 == 0 and _on_segment(a, d, b):
        return True
    if orientation_3 == 0 and _on_segment(c, a, d):
        return True
    if orientation_4 == 0 and _on_segment(c, b, d):
        return True
    return orientation_1 != orientation_2 and orientation_3 != orientation_4


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> int:
    value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else 2


def _on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


def _polygon_area_ha(polygon: list) -> float:
    exterior_area = abs(_ring_area_m2(polygon[0]))
    holes_area = sum(abs(_ring_area_m2(ring)) for ring in polygon[1:])
    return max(exterior_area - holes_area, 0.0) / 10_000.0


def _ring_area_m2(ring: list) -> float:
    points = [(float(point[0]), float(point[1])) for point in ring]
    mean_latitude = sum(point[1] for point in points) / len(points)
    projected = [
        (EARTH_RADIUS_M * radians(lon) * cos(radians(mean_latitude)), EARTH_RADIUS_M * radians(lat))
        for lon, lat in points
    ]
    area = 0.0
    for current, following in zip(projected, projected[1:]):
        area += current[0] * following[1] - following[0] * current[1]
    return area / 2.0
