"""Criterion traceability captured by the evaluation domain."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import ensure_non_empty, ensure_unit_interval


@dataclass(frozen=True)
class CriterionDetail:
    """Trace memberships and weights used for one criterion."""

    criterion_id: str
    memberships_by_period: dict[str, Real] = field(default_factory=dict)
    aggregated_by_phase: dict[str, Real] = field(default_factory=dict)
    aggregated_membership: Real | None = None
    w_ahp: Real | None = None
    w_entropy: Real | None = None
    w_hybrid: Real | None = None
    entropy_used: bool = False
    entropy_fallback_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate stored trace values without deriving new scores."""

        ensure_non_empty(self.criterion_id, "criterion_id")
        for period_key, membership in self.memberships_by_period.items():
            ensure_non_empty(period_key, "period_key")
            ensure_unit_interval(membership, "memberships_by_period")
        for phase_id, membership in self.aggregated_by_phase.items():
            ensure_non_empty(phase_id, "phase_id")
            ensure_unit_interval(membership, "aggregated_by_phase")
        ensure_unit_interval(self.aggregated_membership, "aggregated_membership")
        ensure_unit_interval(self.w_ahp, "w_ahp")
        ensure_unit_interval(self.w_entropy, "w_entropy")
        ensure_unit_interval(self.w_hybrid, "w_hybrid")

    def with_entropy_weights(
        self,
        w_entropy: Real | None,
        w_hybrid: Real,
        entropy_used: bool,
        entropy_fallback_reason: str | None,
    ) -> "CriterionDetail":
        """Return this detail with entropy and hybrid-weight traceability."""

        return replace(
            self,
            w_entropy=w_entropy,
            w_hybrid=w_hybrid,
            entropy_used=entropy_used,
            entropy_fallback_reason=entropy_fallback_reason,
        )
