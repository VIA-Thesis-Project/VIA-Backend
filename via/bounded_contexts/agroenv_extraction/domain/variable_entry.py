"""Variable entry entity for Agroenvironmental Extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError, VariableStatus


@dataclass(frozen=True)
class VariableEntry:
    """Extracted agroenvironmental variable with full traceability."""

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
    source: str
    extraction_date: date
    status: VariableStatus
    value: float | None = None
    id: UUID | None = None

    def __post_init__(self) -> None:
        """Validate required traceability fields and value/status consistency."""

        object.__setattr__(self, "id", self.id or uuid4())
        required = {
            "variable_name": self.variable_name,
            "criterion_id": self.criterion_id,
            "crop_id": self.crop_id,
            "phase_id": self.phase_id,
            "dataset_key": self.dataset_key,
            "band": self.band,
            "unit": self.unit,
            "temporal_resolution": self.temporal_resolution,
            "reducer": self.reducer,
            "aggregation_method": self.aggregation_method,
            "period_key": self.period_key,
            "source": self.source,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise AgroenvExtractionError(f"{field_name} must not be empty")
        if not isinstance(self.status, VariableStatus):
            raise AgroenvExtractionError("status must be OK or CRITERIO_FALTANTE")
        if self.scale is not None and self.scale <= 0:
            raise AgroenvExtractionError("scale must be positive")
        if self.status == VariableStatus.OK and self.value is None:
            raise AgroenvExtractionError("OK variable entries require a value")

    def to_payload(self) -> dict[str, Any]:
        """Serialize entry data for events and tests."""

        return {
            "id": str(self.id),
            "variable_name": self.variable_name,
            "criterion_id": self.criterion_id,
            "crop_id": self.crop_id,
            "phase_id": self.phase_id,
            "dataset_key": self.dataset_key,
            "band": self.band,
            "unit": self.unit,
            "temporal_resolution": self.temporal_resolution,
            "spatial_resolution": self.spatial_resolution,
            "scale": self.scale,
            "reducer": self.reducer,
            "aggregation_method": self.aggregation_method,
            "quality_mask": self.quality_mask,
            "fallback_allowed": self.fallback_allowed,
            "value": self.value,
            "source": self.source,
            "extraction_date": self.extraction_date.isoformat(),
            "period_key": self.period_key,
            "status": self.status.value,
        }
