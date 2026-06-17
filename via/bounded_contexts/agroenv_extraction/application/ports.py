"""Application ports for Agroenvironmental Extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from via.bounded_contexts.agroenv_extraction.domain.agroenv_vector import AgroenvVector


@dataclass(frozen=True)
class ExtractionRequest:
    """Request sent to an external extraction client for one variable period."""

    parcel_id: UUID
    parcel_geometry: dict[str, Any]
    temporal_window: dict[str, Any]
    variable_name: str
    criterion_id: str
    crop_id: str
    phase_id: str
    dataset_key: str
    band: str
    unit: str
    temporal_resolution: str
    spatial_resolution: str | None
    scale: float | None
    reducer: str
    aggregation_method: str
    quality_mask: dict[str, Any] | None
    fallback_allowed: bool
    period_key: str
    period_start: str | None = None
    period_end: str | None = None


@dataclass(frozen=True)
class ExtractionClientResult:
    """External extraction result for one variable period."""

    value: float | None
    source: str
    extraction_date: date


@dataclass(frozen=True)
class StartExtractionCommand:
    """Parsed IniciarExtraccionAgroambiental command."""

    evaluation_id: UUID
    parcel_id: UUID
    parcel_geometry: dict[str, Any]
    crop_candidates: list[str]
    temporal_window: dict[str, Any]
    required_extraction_spec: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StartExtractionCommand":
        """Build the command from a bus message payload."""

        return cls(
            evaluation_id=UUID(str(payload["evaluation_id"])),
            parcel_id=UUID(str(payload["parcel_id"])),
            parcel_geometry=normalize_parcel_geometry(payload.get("parcel_geometry")),
            crop_candidates=[str(item) for item in payload.get("crop_candidates", [])],
            temporal_window=dict(payload["temporal_window"]),
            required_extraction_spec=dict(payload["required_extraction_spec"]),
        )


class IExtractionClient(Protocol):
    """External geospatial extraction client contract."""

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        """Return an extracted value or None when unavailable."""


class IExtractionAcl(Protocol):
    """ACL contract that builds domain vectors from command specs."""

    def build_vector(self, command: StartExtractionCommand, extraction_client: IExtractionClient) -> AgroenvVector:
        """Translate the command and external results into a domain vector."""


class IExtractionRepository(Protocol):
    """Persistence contract for agroenvironmental vectors."""

    def save(self, vector: AgroenvVector) -> None:
        """Persist an extracted vector."""


class ExtractionContractError(ValueError):
    """Raised when an extraction command cannot be converted into valid requests."""


def normalize_parcel_geometry(geometry: object) -> dict[str, Any]:
    """Return a GeoJSON MultiPolygon from Polygon or MultiPolygon input."""

    if not isinstance(geometry, dict):
        raise ExtractionContractError("parcel_geometry is required")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        _validate_polygon(coordinates)
        return {"type": "MultiPolygon", "coordinates": [coordinates]}
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise ExtractionContractError("parcel_geometry MultiPolygon coordinates must not be empty")
        for polygon in coordinates:
            _validate_polygon(polygon)
        return {"type": "MultiPolygon", "coordinates": coordinates}
    raise ExtractionContractError("parcel_geometry type must be Polygon or MultiPolygon")


def _validate_polygon(polygon: object) -> None:
    if not isinstance(polygon, list) or not polygon:
        raise ExtractionContractError("parcel_geometry polygon must contain at least one ring")
    exterior = polygon[0]
    if not isinstance(exterior, list) or len(exterior) < 4:
        raise ExtractionContractError("parcel_geometry exterior ring must contain at least 4 points")
    for ring in polygon:
        _validate_ring(ring)


def _validate_ring(ring: object) -> None:
    if not isinstance(ring, list) or len(ring) < 4:
        raise ExtractionContractError("parcel_geometry ring must contain at least 4 points")
    points = [_coordinate(point) for point in ring]
    if points[0] != points[-1]:
        raise ExtractionContractError("parcel_geometry rings must be closed")


def _coordinate(point: object) -> tuple[float, float]:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        raise ExtractionContractError("parcel_geometry coordinates must be [longitude, latitude]")
    longitude = float(point[0])
    latitude = float(point[1])
    if not -180.0 <= longitude <= 180.0:
        raise ExtractionContractError("parcel_geometry longitude must be within WGS-84 bounds")
    if not -90.0 <= latitude <= 90.0:
        raise ExtractionContractError("parcel_geometry latitude must be within WGS-84 bounds")
    return longitude, latitude
