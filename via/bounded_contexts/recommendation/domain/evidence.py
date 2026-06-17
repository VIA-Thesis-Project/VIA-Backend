"""Documentary evidence cited by a recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.recommendation.domain.value_objects import RecommendationDomainError, ensure_non_empty


@dataclass(frozen=True)
class DocumentaryEvidence:
    """Trace a document fragment used as recommendation evidence."""

    fragment_id: UUID
    document_id: UUID
    text: str
    crop_tags: list[str]
    page_ref: int | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        """Validate evidence traceability."""

        object.__setattr__(self, "text", ensure_non_empty(self.text, "evidence text"))
        tags = [tag.strip() for tag in self.crop_tags if tag.strip()]
        if not tags:
            raise RecommendationDomainError("evidence crop_tags are required")
        object.__setattr__(self, "crop_tags", tags)
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise RecommendationDomainError("evidence score must be in [0,1]")
