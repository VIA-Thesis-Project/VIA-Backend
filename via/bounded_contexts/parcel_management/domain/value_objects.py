"""Parcel value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class GeometryValidationError(ValueError):
    """Raised when parcel GeoJSON geometry violates domain rules."""


@dataclass(frozen=True)
class GeoJSONGeometry:
    """Normalized GeoJSON MultiPolygon value object."""

    coordinates: list

    @classmethod
    def from_geojson(cls, geometry: dict[str, Any]) -> "GeoJSONGeometry":
        """Create a normalized MultiPolygon geometry from Polygon or MultiPolygon GeoJSON."""

        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Polygon":
            return cls(coordinates=[coordinates])
        if geometry_type == "MultiPolygon":
            return cls(coordinates=coordinates)
        raise GeometryValidationError("Geometry type must be Polygon or MultiPolygon")

    def to_geojson(self) -> dict[str, Any]:
        """Return a GeoJSON MultiPolygon mapping."""

        return {"type": "MultiPolygon", "coordinates": self.coordinates}


@dataclass(frozen=True)
class ParcelMetadata:
    """Required descriptive metadata for a parcel."""

    name: str
    description: str
    crs: str

    @classmethod
    def from_mapping(cls, metadata: dict[str, Any]) -> "ParcelMetadata":
        """Create metadata after checking required text fields."""

        name = str(metadata.get("name", "")).strip()
        description = str(metadata.get("description", "")).strip()
        crs = str(metadata.get("crs", "")).strip()
        if not name:
            raise ValueError("Parcel metadata name is required")
        if not description:
            raise ValueError("Parcel metadata description is required")
        if not crs:
            raise ValueError("Parcel metadata crs is required")
        return cls(name=name, description=description, crs=crs)

    def to_mapping(self) -> dict[str, Any]:
        """Return JSON-compatible metadata."""

        return {"name": self.name, "description": self.description, "crs": self.crs}
