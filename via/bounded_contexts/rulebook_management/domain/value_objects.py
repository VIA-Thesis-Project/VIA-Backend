"""Value objects for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RulebookValidationError(ValueError):
    """Raised when a rulebook violates approved constraints."""


class RulebookStatus(StrEnum):
    """Allowed lifecycle states for a rulebook version."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CriticalPolicy(StrEnum):
    """Allowed policies for critical criteria."""

    NO_VIABLE = "NO_VIABLE"
    PENALIZE = "PENALIZE"


class InterventionClass(StrEnum):
    """Declarative classification of how a criterion gap can be addressed.

    DATA_QUALITY_REVIEW is intentionally excluded: it is a runtime diagnosis
    produced by gap_analysis, not a static property of the criterion.
    """

    STRUCTURAL = "STRUCTURAL"
    MITIGABLE = "MITIGABLE"
    CORRECTABLE = "CORRECTABLE"


@dataclass(frozen=True)
class MembershipFunction:
    """Trapezoidal membership function owned by a phase requirement."""

    a: float
    b: float
    c: float
    d: float
    function_type: str = "TRAPEZOIDAL"

    def __post_init__(self) -> None:
        """Validate trapezoid ordering and type."""

        if self.function_type != "TRAPEZOIDAL":
            raise RulebookValidationError("membership_fn type must be TRAPEZOIDAL")
        if not self.a <= self.b <= self.c <= self.d:
            raise RulebookValidationError("membership_fn trapezoid must satisfy a <= b <= c <= d")

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "MembershipFunction":
        """Build a membership function from persisted or request data."""

        return cls(
            a=float(data["a"]),
            b=float(data["b"]),
            c=float(data["c"]),
            d=float(data["d"]),
            function_type=str(data.get("type", data.get("function_type", "TRAPEZOIDAL"))),
        )

    def to_mapping(self) -> dict[str, float | str]:
        """Serialize the membership function as JSON-compatible data."""

        return {"type": self.function_type, "a": self.a, "b": self.b, "c": self.c, "d": self.d}


@dataclass(frozen=True)
class TemporalPeriod:
    """Weighted temporal period used by a phase requirement."""

    period_key: str
    temporal_weight: float
    start_day: int | None = None
    end_day: int | None = None

    def __post_init__(self) -> None:
        """Validate temporal period data."""

        if not self.period_key.strip():
            raise RulebookValidationError("temporal period key must not be empty")
        validate_unit_weight(self.temporal_weight, "temporal_weight")
        if self.start_day is not None and self.end_day is not None and self.start_day > self.end_day:
            raise RulebookValidationError("temporal period start_day must be <= end_day")

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TemporalPeriod":
        """Build a temporal period from persisted or request data."""

        return cls(
            period_key=str(data["period_key"]),
            temporal_weight=float(data["temporal_weight"]),
            start_day=int(data["start_day"]) if data.get("start_day") is not None else None,
            end_day=int(data["end_day"]) if data.get("end_day") is not None else None,
        )

    def to_mapping(self) -> dict[str, int | float | str | None]:
        """Serialize the temporal period as JSON-compatible data."""

        return {
            "period_key": self.period_key,
            "temporal_weight": self.temporal_weight,
            "start_day": self.start_day,
            "end_day": self.end_day,
        }


def validate_unit_weight(value: float, field_name: str) -> None:
    """Validate one scalar weight constrained to the closed unit interval."""

    if not 0.0 <= value <= 1.0:
        raise RulebookValidationError(f"{field_name} must be in [0, 1]")


def validate_weight_sum(values: list[float], field_name: str, tolerance: float) -> None:
    """Validate that a non-empty list of weights sums to one."""

    if not values:
        raise RulebookValidationError(f"{field_name} weights must not be empty")
    total = sum(values)
    if abs(total - 1.0) > tolerance:
        raise RulebookValidationError(f"{field_name} weights must sum to 1.0")
