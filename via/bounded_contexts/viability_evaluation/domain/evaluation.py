"""Viability evaluation aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError


@dataclass
class Evaluation:
    """Collect crop results for a parcel evaluation."""

    id: UUID
    parcel_id: UUID
    requested_by: UUID
    crop_candidates: list[str]
    temporal_window: dict[str, Any]
    crop_results: list[CropResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate aggregate identity and requested crop candidates."""

        if not self.crop_candidates:
            raise EvaluationDomainError("crop_candidates is required")

    def record_crop_result(self, result: CropResult) -> None:
        """Attach a previously computed crop result to this evaluation."""

        if result.crop_id not in self.crop_candidates:
            raise EvaluationDomainError("crop result does not belong to this evaluation")
        self.crop_results.append(result)
