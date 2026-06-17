"""Shared value objects for viability evaluation results."""

from __future__ import annotations

from enum import StrEnum
from numbers import Real


class EvaluationDomainError(ValueError):
    """Raised when an evaluation domain object receives invalid data."""


class CalcCondition(StrEnum):
    """Supported calculation completeness conditions for a crop result."""

    DEFINITIVO = "DEFINITIVO"
    PARCIAL = "PARCIAL"
    NO_CONCLUYENTE = "NO_CONCLUYENTE"


class ViabilityCategory(StrEnum):
    """Supported viability categories for a crop result."""

    VIABLE = "VIABLE"
    CONDICIONAL = "CONDICIONAL"
    NO_VIABLE = "NO_VIABLE"


class CriticalPolicy(StrEnum):
    """Supported critical criterion policies."""

    NO_VIABLE = "NO_VIABLE"
    PENALIZE = "PENALIZE"


def ensure_non_empty(value: str, field_name: str) -> None:
    """Ensure a text identifier has content."""

    if not value:
        raise EvaluationDomainError(f"{field_name} is required")


def ensure_unit_interval(value: Real | None, field_name: str) -> None:
    """Ensure an optional numeric value is between zero and one."""

    if value is None:
        return
    if value < 0 or value > 1:
        raise EvaluationDomainError(f"{field_name} must be between 0 and 1")
