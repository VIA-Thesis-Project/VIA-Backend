"""Recommendation aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from via.bounded_contexts.recommendation.domain.evidence import DocumentaryEvidence
from via.bounded_contexts.recommendation.domain.section import RecommendationSection
from via.bounded_contexts.recommendation.domain.value_objects import (
    RecommendationDomainError,
    RecommendationStatus,
    ensure_non_empty,
)


@dataclass
class Recommendation:
    """Supported agricultural recommendation generated from existing results."""

    evaluation_id: UUID
    crop_id: str
    text: str
    sections: list[RecommendationSection]
    evidence: list[DocumentaryEvidence]
    structured_output: dict = field(default_factory=dict)
    status: RecommendationStatus = RecommendationStatus.GENERATED
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        """Validate recommendation aggregate invariants."""

        object.__setattr__(self, "crop_id", ensure_non_empty(self.crop_id, "crop_id"))
        object.__setattr__(self, "text", ensure_non_empty(self.text, "recommendation text"))
        if not self.sections:
            raise RecommendationDomainError("recommendation sections are required")

    @property
    def fragment_ids(self) -> list[UUID]:
        """Return fragment identifiers cited by the recommendation."""

        return [item.fragment_id for item in self.evidence]
