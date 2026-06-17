"""Basic fuzzy MCDA operations for viability evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError, ensure_non_empty, ensure_unit_interval


DEFAULT_WEIGHT_TOLERANCE = 0.001


@dataclass(frozen=True)
class TrapezoidalMembershipFunction:
    """Trapezoidal membership function defined for one criterion and phase."""

    a: Real
    b: Real
    c: Real
    d: Real

    def __post_init__(self) -> None:
        """Validate trapezoid ordering."""

        if not self.a <= self.b <= self.c <= self.d:
            raise EvaluationDomainError("trapezoid must satisfy a <= b <= c <= d")

    @classmethod
    def from_mapping(cls, data: dict[str, Real | str]) -> "TrapezoidalMembershipFunction":
        """Build a trapezoid from ACL-translated rulebook data."""

        function_type = str(data.get("type", data.get("function_type", "TRAPEZOIDAL")))
        if function_type != "TRAPEZOIDAL":
            raise EvaluationDomainError("membership_fn type must be TRAPEZOIDAL")
        return cls(a=float(data["a"]), b=float(data["b"]), c=float(data["c"]), d=float(data["d"]))

    def membership(self, observed_value: Real) -> float:
        """Return the fuzzy membership for an observed value."""

        value = float(observed_value)
        a = float(self.a)
        b = float(self.b)
        c = float(self.c)
        d = float(self.d)

        if value < a or value > d:
            return 0.0
        if b <= value <= c:
            return 1.0
        if value < b:
            return _clamp_unit((value - a) / (b - a)) if b != a else 1.0
        return _clamp_unit((d - value) / (d - c)) if d != c else 1.0


def aggregate_temporal(period_memberships: dict[str, Real], temporal_weights: dict[str, Real], tolerance: float = DEFAULT_WEIGHT_TOLERANCE) -> float:
    """Aggregate period memberships within a phase using weighted geometric mean."""

    return weighted_geometric_mean(period_memberships, temporal_weights, tolerance)


def aggregate_phases(phase_memberships: dict[str, Real], phase_weights: dict[str, Real], tolerance: float = DEFAULT_WEIGHT_TOLERANCE) -> float:
    """Aggregate phase memberships for one criterion using weighted geometric mean."""

    return weighted_geometric_mean(phase_memberships, phase_weights, tolerance)


def weighted_geometric_mean(values: dict[str, Real], weights: dict[str, Real], tolerance: float = DEFAULT_WEIGHT_TOLERANCE) -> float:
    """Compute a weighted geometric mean for values constrained to [0, 1]."""

    _validate_weighted_inputs(values, weights, tolerance)
    if any(float(value) == 0.0 for value in values.values()):
        return 0.0
    weighted_logs = [float(weights[key]) * math.log(float(value)) for key, value in values.items()]
    return _clamp_unit(math.exp(sum(weighted_logs)))


def build_criterion_detail(
    criterion_id: str,
    memberships_by_phase_period: dict[str, dict[str, Real]],
    temporal_weights_by_phase: dict[str, dict[str, Real]],
    phase_weights: dict[str, Real],
    w_ahp: Real,
    tolerance: float = DEFAULT_WEIGHT_TOLERANCE,
) -> CriterionDetail:
    """Build traceability for one criterion using fuzzy memberships and AHP weight."""

    ensure_non_empty(criterion_id, "criterion_id")
    ensure_unit_interval(w_ahp, "w_ahp")
    flat_memberships: dict[str, Real] = {}
    aggregated_by_phase: dict[str, float] = {}
    for phase_id, period_memberships in memberships_by_phase_period.items():
        ensure_non_empty(phase_id, "phase_id")
        temporal_weights = temporal_weights_by_phase.get(phase_id)
        if temporal_weights is None:
            raise EvaluationDomainError(f"missing temporal weights for phase {phase_id}")
        aggregated_by_phase[phase_id] = aggregate_temporal(period_memberships, temporal_weights, tolerance)
        for period_key, membership in period_memberships.items():
            flat_memberships[f"{phase_id}:{period_key}"] = membership

    aggregated_membership = aggregate_phases(aggregated_by_phase, phase_weights, tolerance)
    return CriterionDetail(
        criterion_id=criterion_id,
        memberships_by_period=flat_memberships,
        aggregated_by_phase=aggregated_by_phase,
        aggregated_membership=aggregated_membership,
        w_ahp=w_ahp,
        w_entropy=None,
        w_hybrid=w_ahp,
        entropy_used=False,
        entropy_fallback_reason=None,
    )


def _validate_weighted_inputs(values: dict[str, Real], weights: dict[str, Real], tolerance: float) -> None:
    """Validate weighted aggregation inputs."""

    if not values:
        raise EvaluationDomainError("values must not be empty")
    if set(values) != set(weights):
        raise EvaluationDomainError("values and weights must use the same keys")
    for key, value in values.items():
        ensure_non_empty(key, "weight_key")
        ensure_unit_interval(value, "membership")
    for key, weight in weights.items():
        ensure_non_empty(key, "weight_key")
        ensure_unit_interval(weight, "weight")
    total_weight = sum(float(weight) for weight in weights.values())
    if abs(total_weight - 1.0) > tolerance:
        raise EvaluationDomainError("weights must sum to 1.0")


def _clamp_unit(value: float) -> float:
    """Clamp small floating point drift into the unit interval."""

    return min(1.0, max(0.0, value))
