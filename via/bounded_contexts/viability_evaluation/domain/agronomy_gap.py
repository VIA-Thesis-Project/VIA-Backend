"""Agronomic gap traceability for viability evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import ensure_non_empty, ensure_unit_interval


@dataclass(frozen=True)
class AgronomyGap:
    """Represent the most limiting period for one criterion and phase."""

    criterion_id: str
    phase_id: str
    most_limiting_period: str
    observed_value: Real
    optimal_limit: Real
    gap_value: Real
    membership: Real
    """Fuzzy membership of the most limiting period. Severity is 1 - membership."""

    def __post_init__(self) -> None:
        """Validate identifiers required to interpret the gap."""

        ensure_non_empty(self.criterion_id, "criterion_id")
        ensure_non_empty(self.phase_id, "phase_id")
        ensure_non_empty(self.most_limiting_period, "most_limiting_period")
        ensure_unit_interval(self.membership, "membership")
