"""Limiting factor traceability for viability evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import CriticalPolicy, ensure_non_empty, ensure_unit_interval


@dataclass(frozen=True)
class LimitingFactor:
    """Represent a critical agronomic limitation found during evaluation."""

    criterion_id: str
    phase_id: str
    policy: CriticalPolicy
    penalty_factor: Real | None
    observed_value: Real
    optimal_limit: Real
    membership: Real
    doc_source: str | None = None

    def __post_init__(self) -> None:
        """Validate limiting-factor metadata without applying penalties."""

        ensure_non_empty(self.criterion_id, "criterion_id")
        ensure_non_empty(self.phase_id, "phase_id")
        ensure_unit_interval(self.penalty_factor, "penalty_factor")
        ensure_unit_interval(self.membership, "membership")
