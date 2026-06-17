"""Recommendation sections."""

from __future__ import annotations

from dataclasses import dataclass

from via.bounded_contexts.recommendation.domain.value_objects import RecommendationSectionType, ensure_non_empty


@dataclass(frozen=True)
class RecommendationSection:
    """A titled section of supported recommendation text."""

    section_type: RecommendationSectionType
    title: str
    content: str

    def __post_init__(self) -> None:
        """Validate section text."""

        object.__setattr__(self, "title", ensure_non_empty(self.title, "section title"))
        object.__setattr__(self, "content", ensure_non_empty(self.content, "section content"))
