"""Pydantic response schemas for viability evaluation API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GapResponse(BaseModel):
    """Agronomic gap for a criterion/phase pair."""

    criterion_id: str
    phase_id: str
    most_limiting_period: str
    observed_value: float
    optimal_limit: float
    gap_value: float


class LimitingFactorResponse(BaseModel):
    """Critical limiting factor that influenced the crop viability score."""

    criterion_id: str
    phase_id: str
    policy: str
    penalty_factor: float | None
    observed_value: float
    optimal_limit: float
    membership: float
    doc_source: str | None


class CropResultResponse(BaseModel):
    """Persisted MCDA result for one crop candidate."""

    crop_id: str
    score: float | None
    rank_position: int | None
    calc_condition: str
    viability_category: str
    gaps: list[GapResponse]
    limiting_factors: list[LimitingFactorResponse]
    missing_criteria: list[str]
    unrecognized_variables: list[str]


class EvaluationStatusResponse(BaseModel):
    """Current saga lifecycle state for an evaluation."""

    evaluation_id: UUID
    status: str
    current_phase: str
    last_transition: datetime | None
    failure_reason: str | None


class EvaluationMcdaResultResponse(BaseModel):
    """Persisted MCDA ranking and gaps for a completed evaluation.

    failure_reason is set when the saga is FALLIDA; does not include Recommendation.
    """

    evaluation_id: UUID
    status: str
    results: list[CropResultResponse]
    failure_reason: str | None = None
