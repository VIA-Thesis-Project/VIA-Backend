"""Recommendation domain value objects."""

from __future__ import annotations

from enum import StrEnum


class RecommendationDomainError(ValueError):
    """Raised when recommendation domain invariants are violated."""


class RecommendationStatus(StrEnum):
    """Lifecycle status for a supported recommendation."""

    DRAFTED = "DRAFTED"
    GENERATED = "GENERATED"


class RecommendationSectionType(StrEnum):
    """Supported recommendation section categories."""

    SUMMARY = "SUMMARY"
    VIABILITY_RESULT = "VIABILITY_RESULT"
    AGRONOMIC_GAPS = "AGRONOMIC_GAPS"
    LIMITING_FACTORS = "LIMITING_FACTORS"
    DOCUMENTARY_EVIDENCE = "DOCUMENTARY_EVIDENCE"


def ensure_non_empty(value: str, field_name: str) -> str:
    """Return stripped text or raise when it is empty."""

    stripped = value.strip()
    if not stripped:
        raise RecommendationDomainError(f"{field_name} is required")
    return stripped
