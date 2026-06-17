"""Criterion entity for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.value_objects import (
    CriticalPolicy,
    RulebookValidationError,
    validate_unit_weight,
)


@dataclass(frozen=True)
class Criterion:
    """Crop viability criterion with a precalculated Fuzzy AHP weight."""

    id: UUID
    name: str
    is_critical: bool
    critical_policy: CriticalPolicy | None
    penalty_factor: float | None
    ahp_weight: float
    doc_source: str | None = None
    technical_notes: str | None = None

    def __post_init__(self) -> None:
        """Validate the approved criterion constraints."""

        if not self.name.strip():
            raise RulebookValidationError("criterion name must not be empty")
        validate_unit_weight(self.ahp_weight, "ahp_weight")
        if self.critical_policy is not None and not isinstance(self.critical_policy, CriticalPolicy):
            raise RulebookValidationError("critical_policy must be NO_VIABLE or PENALIZE")
        if self.is_critical and self.critical_policy is None:
            raise RulebookValidationError("critical criteria require critical_policy")
        if self.critical_policy == CriticalPolicy.PENALIZE and self.penalty_factor is None:
            raise RulebookValidationError("penalty_factor is required when critical_policy is PENALIZE")
        if self.penalty_factor is not None:
            validate_unit_weight(self.penalty_factor, "penalty_factor")
