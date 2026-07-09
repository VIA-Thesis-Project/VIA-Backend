"""Critical policies, agronomic gaps and ranking for viability evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.agronomy_gap import AgronomyGap
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.limiting_factor import LimitingFactor
from via.bounded_contexts.viability_evaluation.domain.mcda_completion import (
    DEFAULT_CONDICIONAL_THRESHOLD,
    DEFAULT_NON_CRITICAL_MEMBERSHIP_FLOOR,
    DEFAULT_VIABLE_THRESHOLD,
    MulticriteriaAggregationService,
    NonCriticalMembershipFloorService,
    ViabilityClassifierService,
)
from via.bounded_contexts.viability_evaluation.domain.value_objects import (
    CalcCondition,
    CriticalPolicy,
    EvaluationDomainError,
    ViabilityCategory,
    ensure_non_empty,
    ensure_unit_interval,
)


DEFAULT_PENALIZE_EPSILON = 0.01


@dataclass(frozen=True)
class CriticalCriterionTrace:
    """Critical criterion data required to apply a critical policy."""

    criterion_id: str
    phase_id: str
    policy: CriticalPolicy
    penalty_factor: Real | None
    observed_value: Real
    optimal_limit: Real
    membership: Real
    doc_source: str | None = None

    def __post_init__(self) -> None:
        """Validate critical criterion trace data."""

        ensure_non_empty(self.criterion_id, "criterion_id")
        ensure_non_empty(self.phase_id, "phase_id")
        ensure_unit_interval(self.penalty_factor, "penalty_factor")
        ensure_unit_interval(self.membership, "membership")
        if self.policy == CriticalPolicy.PENALIZE and self.penalty_factor is None:
            raise EvaluationDomainError("penalty_factor is required for PENALIZE policy")


@dataclass(frozen=True)
class CriticalPolicyResult:
    """Result of applying critical policies to an already prepared calculation."""

    score: float | None
    viability_category: ViabilityCategory | None
    limiting_factors: list[LimitingFactor] = field(default_factory=list)
    effective_memberships: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseGapTrace:
    """Phase data required to calculate one agronomic gap."""

    criterion_id: str
    phase_id: str
    aggregated_membership: Real
    period_memberships: dict[str, Real]
    observed_values: dict[str, Real]
    optimal_limits: dict[str, Real]

    def __post_init__(self) -> None:
        """Validate gap trace data."""

        ensure_non_empty(self.criterion_id, "criterion_id")
        ensure_non_empty(self.phase_id, "phase_id")
        ensure_unit_interval(self.aggregated_membership, "aggregated_membership")
        if not self.period_memberships:
            raise EvaluationDomainError("period_memberships must not be empty")
        if set(self.period_memberships) != set(self.observed_values) or set(self.period_memberships) != set(self.optimal_limits):
            raise EvaluationDomainError("period memberships, observed values and optimal limits must use the same periods")
        for period_key, membership in self.period_memberships.items():
            ensure_non_empty(period_key, "period_key")
            ensure_unit_interval(membership, "period_membership")


class CriticalPolicyService:
    """Apply critical policies without persistence or external dependencies."""

    def __init__(
        self,
        aggregation_service: MulticriteriaAggregationService | None = None,
        classifier_service: ViabilityClassifierService | None = None,
        floor_service: NonCriticalMembershipFloorService | None = None,
    ) -> None:
        """Create the pure critical-policy service."""

        self._aggregation_service = aggregation_service or MulticriteriaAggregationService()
        self._classifier_service = classifier_service or ViabilityClassifierService()
        self._floor_service = floor_service or NonCriticalMembershipFloorService()

    def apply(
        self,
        aggregated_memberships: dict[str, Real],
        hybrid_weights: dict[str, Real],
        calc_condition: CalcCondition,
        critical_traces: list[CriticalCriterionTrace],
        critical_criteria: set[str] | None = None,
        penalize_epsilon: float = DEFAULT_PENALIZE_EPSILON,
        non_critical_membership_floor: float = DEFAULT_NON_CRITICAL_MEMBERSHIP_FLOOR,
        viable_threshold: float = DEFAULT_VIABLE_THRESHOLD,
        condicional_threshold: float = DEFAULT_CONDICIONAL_THRESHOLD,
    ) -> CriticalPolicyResult:
        """Apply NO_VIABLE and PENALIZE rules to the final crop calculation."""

        ensure_unit_interval(penalize_epsilon, "penalize_epsilon")
        if penalize_epsilon == 0.0:
            raise EvaluationDomainError("penalize_epsilon must be greater than zero")
        if calc_condition == CalcCondition.NO_CONCLUYENTE:
            return CriticalPolicyResult(score=None, viability_category=None)

        critical_criteria = critical_criteria or {trace.criterion_id for trace in critical_traces}
        effective_memberships = self._floor_service.apply(
            aggregated_memberships,
            critical_criteria,
            non_critical_membership_floor,
        )
        limiting_factors: list[LimitingFactor] = []
        no_viable_forced = False
        penalty_factors: list[float] = []
        penalized_criteria: set[str] = set()

        for trace in critical_traces:
            if float(trace.membership) != 0.0:
                continue
            if trace.criterion_id in penalized_criteria:
                continue
            penalized_criteria.add(trace.criterion_id)
            limiting_factors.append(_limiting_factor_from_trace(trace))
            if trace.policy == CriticalPolicy.NO_VIABLE:
                no_viable_forced = True
            elif trace.policy == CriticalPolicy.PENALIZE:
                effective_memberships[trace.criterion_id] = penalize_epsilon
                penalty_factors.append(float(trace.penalty_factor))

        score = self._aggregation_service.aggregate(effective_memberships, hybrid_weights)
        for penalty_factor in penalty_factors:
            score *= penalty_factor
        score = _clamp_unit(score)
        if no_viable_forced:
            return CriticalPolicyResult(
                score=score,
                viability_category=ViabilityCategory.NO_VIABLE,
                limiting_factors=limiting_factors,
                effective_memberships=effective_memberships,
            )

        return CriticalPolicyResult(
            score=score,
            viability_category=self._classifier_service.classify(score, calc_condition, viable_threshold, condicional_threshold),
            limiting_factors=limiting_factors,
            effective_memberships=effective_memberships,
        )


class GapCalculationService:
    """Calculate agronomic gaps using the most limiting period in each phase."""

    def calculate(self, phase_traces: list[PhaseGapTrace]) -> list[AgronomyGap]:
        """Return gaps for phases whose aggregated membership is below one."""

        gaps: list[AgronomyGap] = []
        for trace in phase_traces:
            if float(trace.aggregated_membership) >= 1.0:
                continue
            most_limiting_period = min(trace.period_memberships, key=lambda period: (float(trace.period_memberships[period]), period))
            observed_value = trace.observed_values[most_limiting_period]
            optimal_limit = trace.optimal_limits[most_limiting_period]
            gaps.append(
                AgronomyGap(
                    criterion_id=trace.criterion_id,
                    phase_id=trace.phase_id,
                    most_limiting_period=most_limiting_period,
                    observed_value=observed_value,
                    optimal_limit=optimal_limit,
                    gap_value=float(observed_value) - float(optimal_limit),
                    membership=float(trace.period_memberships[most_limiting_period]),
                )
            )
        return gaps


class RankingService:
    """Assign deterministic rank positions to eligible crop results."""

    def assign_rank_positions(self, crop_results: list[CropResult]) -> list[CropResult]:
        """Return crop results with rank positions assigned in input order."""

        indexed_results = list(enumerate(crop_results))
        eligible = [
            (index, result)
            for index, result in indexed_results
            if result.calc_condition != CalcCondition.NO_CONCLUYENTE
            and result.viability_category not in {ViabilityCategory.NO_VIABLE, ViabilityCategory.NO_CONCLUYENTE}
            and result.score is not None
        ]
        sorted_eligible = sorted(eligible, key=lambda item: (-float(item[1].score), item[1].crop_id))
        ranks_by_index = {index: rank for rank, (index, _result) in enumerate(sorted_eligible, start=1)}

        ranked_results: list[CropResult] = []
        for index, result in indexed_results:
            ranked_results.append(replace(result, rank_position=ranks_by_index.get(index)))
        return ranked_results


def _limiting_factor_from_trace(trace: CriticalCriterionTrace) -> LimitingFactor:
    """Build a limiting factor preserving critical traceability."""

    return LimitingFactor(
        criterion_id=trace.criterion_id,
        phase_id=trace.phase_id,
        policy=trace.policy,
        penalty_factor=trace.penalty_factor,
        observed_value=trace.observed_value,
        optimal_limit=trace.optimal_limit,
        membership=trace.membership,
        doc_source=trace.doc_source,
    )


def _clamp_unit(value: float) -> float:
    """Clamp small floating point drift into the unit interval."""

    return min(1.0, max(0.0, value))
