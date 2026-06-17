"""Crop-level viability evaluation result aggregate member."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.agronomy_gap import AgronomyGap
from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.limiting_factor import LimitingFactor
from via.bounded_contexts.viability_evaluation.domain.value_objects import (
    CalcCondition,
    EvaluationDomainError,
    ViabilityCategory,
    ensure_non_empty,
    ensure_unit_interval,
)


@dataclass
class CropResult:
    """Store the result and traceability for one crop candidate."""

    crop_id: str
    score: Real | None
    rank_position: int | None
    calc_condition: CalcCondition
    viability_category: ViabilityCategory
    criterion_details: list[CriterionDetail] = field(default_factory=list)
    gaps: list[AgronomyGap] = field(default_factory=list)
    limiting_factors: list[LimitingFactor] = field(default_factory=list)
    missing_criteria: list[str] = field(default_factory=list)
    unrecognized_variables: list[str] = field(default_factory=list)
    entropy_series_sufficient: bool = False

    def __post_init__(self) -> None:
        """Validate result metadata without ranking or classifying crops."""

        ensure_non_empty(self.crop_id, "crop_id")
        ensure_unit_interval(self.score, "score")
        if self.rank_position is not None and self.rank_position < 1:
            raise EvaluationDomainError("rank_position must be positive when present")
