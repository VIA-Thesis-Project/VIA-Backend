"""API resources for Rulebook Management."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MembershipFunctionResource(BaseModel):
    """Trapezoidal membership function request data."""

    model_config = ConfigDict(populate_by_name=True)

    function_type: str = Field(default="TRAPEZOIDAL", alias="type")
    a: float
    b: float
    c: float
    d: float


class TemporalPeriodResource(BaseModel):
    """Weighted temporal period request data."""

    period_key: str
    temporal_weight: float
    start_day: int | None = None
    end_day: int | None = None


class CriterionResource(BaseModel):
    """Criterion request data."""

    id: UUID
    name: str
    is_critical: bool = False
    critical_policy: str | None = None
    penalty_factor: float | None = None
    ahp_weight: float
    intervention_class: str
    doc_source: str | None = None
    technical_notes: str | None = None


class PhenologicalPhaseResource(BaseModel):
    """Phenological phase request data."""

    id: UUID
    name: str
    duration_days: int
    sequence_order: int


class ExtractionBindingResource(BaseModel):
    """Data needed by the RequiredExtractionSpec read model."""

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


class PhaseRequirementResource(BaseModel):
    """Phase requirement request data."""

    id: UUID
    criterion_id: UUID
    phase_id: UUID
    membership_fn: MembershipFunctionResource
    phase_weight: float
    temporal_periods: list[TemporalPeriodResource]
    extraction: ExtractionBindingResource


class CreateRulebookRequest(BaseModel):
    """Request body to create one rulebook version."""

    crop_id: str
    criteria: list[CriterionResource]
    phases: list[PhenologicalPhaseResource]
    phase_requirements: list[PhaseRequirementResource]


class RulebookResponse(BaseModel):
    """Rulebook response summary."""

    id: UUID
    crop_id: str
    version: int
    status: str


class RulebookDetailResponse(RulebookResponse):
    """Rulebook response with versioned rule content."""

    criteria: list[CriterionResource]
    phases: list[PhenologicalPhaseResource]
    phase_requirements: list[PhaseRequirementResource]
