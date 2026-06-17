"""Ports consumed by the evaluation Process Manager."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class RequiredVariableForEvaluation:
    """Extraction variable required by a rulebook read model."""

    variable_name: str
    criterion_id: str
    crop_id: str
    phase_id: str
    dataset_key: str
    band: str
    unit: str
    temporal_resolution: str
    spatial_resolution: str | None = None
    scale: float | None = None
    reducer: str | None = None
    aggregation_method: str | None = None
    temporal_window: dict[str, Any] | None = None
    temporal_periods: list[dict[str, Any]] | None = None
    quality_mask: dict[str, Any] | None = None
    fallback_allowed: bool = False

    def to_payload(self) -> dict[str, Any]:
        """Serialize the required variable as JSON-compatible data."""

        return asdict(self)


@dataclass(frozen=True)
class RequiredExtractionSpec:
    """Read-model projection of all variables required for extraction."""

    variables: list[RequiredVariableForEvaluation]

    def to_payload(self) -> dict[str, Any]:
        """Serialize the extraction spec as JSON-compatible data."""

        return {"variables": [variable.to_payload() for variable in self.variables]}


@dataclass(frozen=True)
class ParcelGeometrySnapshot:
    """Parcel geometry read model captured for extraction messages."""

    parcel_id: UUID
    geometry: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Serialize the geometry snapshot as JSON-compatible data."""

        return {"parcel_id": str(self.parcel_id), "geometry": self.geometry}


class IRulebookReadModelPort(Protocol):
    """Read side used to discover extraction needs without interpreting rulebooks."""

    def get_required_extraction_spec(
        self,
        crop_candidates: list[str],
        temporal_window: dict[str, Any],
    ) -> RequiredExtractionSpec:
        """Return the required agro-environmental extraction specification."""


class IParcelGeometryReadModelPort(Protocol):
    """Read side used to capture parcel geometry without exposing parcel internals."""

    def get_parcel_geometry(self, parcel_id: UUID) -> ParcelGeometrySnapshot:
        """Return a GeoJSON geometry snapshot for the parcel."""
