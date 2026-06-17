"""Phase requirement entity for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.value_objects import (
    MembershipFunction,
    RulebookValidationError,
    TemporalPeriod,
    validate_unit_weight,
    validate_weight_sum,
)


@dataclass(frozen=True)
class ExtractionBinding:
    """Read-model data needed to request agro-environmental extraction."""

    variable_name: str
    dataset_key: str
    band: str
    unit: str
    temporal_resolution: str
    spatial_resolution: str | None = None
    scale: float | None = None
    reducer: str | None = None
    aggregation_method: str | None = None
    quality_mask: dict[str, Any] | None = None
    fallback_allowed: bool = False

    def __post_init__(self) -> None:
        """Validate fields needed by RequiredExtractionSpec."""

        required = {
            "variable_name": self.variable_name,
            "dataset_key": self.dataset_key,
            "band": self.band,
            "unit": self.unit,
            "temporal_resolution": self.temporal_resolution,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise RulebookValidationError(f"{field_name} must not be empty")
        if self.scale is not None and self.scale <= 0:
            raise RulebookValidationError("scale must be positive")

    def to_mapping(self) -> dict[str, Any]:
        """Serialize extraction binding data."""

        return {
            "variable_name": self.variable_name,
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
        }


@dataclass(frozen=True)
class PhaseRequirement:
    """Criterion requirement specialized for one phenological phase."""

    id: UUID
    criterion_id: UUID
    phase_id: UUID
    membership_fn: MembershipFunction
    phase_weight: float
    temporal_periods: list[TemporalPeriod]
    extraction_binding: ExtractionBinding = field(default_factory=lambda: ExtractionBinding(
        variable_name="unknown",
        dataset_key="unknown",
        band="unknown",
        unit="unknown",
        temporal_resolution="unknown",
    ))

    def __post_init__(self) -> None:
        """Validate phase and temporal weights."""

        validate_unit_weight(self.phase_weight, "phase_weight")
        validate_weight_sum([period.temporal_weight for period in self.temporal_periods], "temporal", 0.001)

    def temporal_period_payload(self) -> list[dict[str, Any]]:
        """Return the temporal periods as read-model payload data."""

        return [period.to_mapping() for period in self.temporal_periods]
