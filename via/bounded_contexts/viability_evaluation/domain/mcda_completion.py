"""Missing-data resolution and basic final MCDA decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.mcda_basic import weighted_geometric_mean
from via.bounded_contexts.viability_evaluation.domain.value_objects import (
    CalcCondition,
    EvaluationDomainError,
    ViabilityCategory,
    ensure_non_empty,
    ensure_unit_interval,
)


DEFAULT_VIABLE_THRESHOLD = 0.70
DEFAULT_CONDICIONAL_THRESHOLD = 0.40
DEFAULT_NON_CRITICAL_MEMBERSHIP_FLOOR = 0.05


@dataclass(frozen=True)
class ParticipatingCriteria:
    """Criteria and weights that remain after missing-data resolution."""

    memberships: dict[str, float]
    weights: dict[str, float]
    calc_condition: CalcCondition
    missing_criteria: list[str] = field(default_factory=list)
    unrecognized_variables: list[str] = field(default_factory=list)
    should_calculate: bool = True


@dataclass(frozen=True)
class BasicCropEvaluationResult:
    """Pure in-memory crop result produced by basic MCDA completion."""

    crop_id: str
    score: float | None
    calc_condition: CalcCondition
    viability_category: ViabilityCategory | None
    missing_criteria: list[str] = field(default_factory=list)
    unrecognized_variables: list[str] = field(default_factory=list)


class MissingCriteriaService:
    """Resolve missing and unrecognized criteria before final aggregation."""

    def resolve(
        self,
        aggregated_memberships: dict[str, Real],
        hybrid_weights: dict[str, Real],
        missing_criteria: list[str],
        critical_criteria: set[str],
        criteria_with_alternative_rules: set[str] | None = None,
        unrecognized_variables: list[str] | None = None,
    ) -> ParticipatingCriteria:
        """Return participating criteria or a no-conclusive calculation state."""

        criteria_with_alternative_rules = criteria_with_alternative_rules or set()
        unrecognized_variables = unrecognized_variables or []
        self._validate_inputs(aggregated_memberships, hybrid_weights, critical_criteria)

        normalized_missing = _unique_non_empty(missing_criteria, "missing_criterion")
        normalized_unrecognized = _unique_non_empty(unrecognized_variables, "unrecognized_variable")
        critical_missing = [
            criterion_id
            for criterion_id in normalized_missing
            if criterion_id in critical_criteria and criterion_id not in criteria_with_alternative_rules
        ]
        if critical_missing:
            return ParticipatingCriteria(
                memberships={},
                weights={},
                calc_condition=CalcCondition.NO_CONCLUYENTE,
                missing_criteria=critical_missing,
                unrecognized_variables=normalized_unrecognized,
                should_calculate=False,
            )

        non_critical_missing = [criterion_id for criterion_id in normalized_missing if criterion_id not in critical_criteria]
        excluded = set(non_critical_missing)
        participating_memberships = {
            criterion_id: float(membership)
            for criterion_id, membership in aggregated_memberships.items()
            if criterion_id not in excluded
        }
        if not participating_memberships:
            raise EvaluationDomainError("at least one criterion must participate in the calculation")

        participating_weights = {
            criterion_id: float(hybrid_weights[criterion_id])
            for criterion_id in participating_memberships
        }
        return ParticipatingCriteria(
            memberships=participating_memberships,
            weights=_normalize_weights_once(participating_weights),
            calc_condition=CalcCondition.PARCIAL if non_critical_missing else CalcCondition.DEFINITIVO,
            missing_criteria=non_critical_missing,
            unrecognized_variables=normalized_unrecognized,
            should_calculate=True,
        )

    def _validate_inputs(
        self,
        aggregated_memberships: dict[str, Real],
        hybrid_weights: dict[str, Real],
        critical_criteria: set[str],
    ) -> None:
        """Validate maps used by missing-criteria resolution."""

        if not aggregated_memberships:
            raise EvaluationDomainError("aggregated_memberships must not be empty")
        if set(aggregated_memberships) != set(hybrid_weights):
            raise EvaluationDomainError("aggregated_memberships and hybrid_weights must use the same criteria")
        for criterion_id, membership in aggregated_memberships.items():
            ensure_non_empty(criterion_id, "criterion_id")
            ensure_unit_interval(membership, "membership")
        for criterion_id, weight in hybrid_weights.items():
            ensure_non_empty(criterion_id, "criterion_id")
            ensure_unit_interval(weight, "hybrid_weight")
        for criterion_id in critical_criteria:
            ensure_non_empty(criterion_id, "critical_criterion")


class MulticriteriaAggregationService:
    """Aggregate participating criterion memberships into a final score."""

    def aggregate(self, aggregated_memberships: dict[str, Real], hybrid_weights: dict[str, Real]) -> float:
        """Return the final score using weighted geometric mean."""

        return weighted_geometric_mean(aggregated_memberships, hybrid_weights)


class NonCriticalMembershipFloorService:
    """Apply a minimum membership floor only to non-critical criteria."""

    def apply(
        self,
        aggregated_memberships: dict[str, Real],
        critical_criteria: set[str],
        membership_floor: float = DEFAULT_NON_CRITICAL_MEMBERSHIP_FLOOR,
    ) -> dict[str, float]:
        """Return memberships where non-critical zero values remain strong penalties, not vetoes."""

        ensure_unit_interval(membership_floor, "non_critical_membership_floor")
        adjusted: dict[str, float] = {}
        for criterion_id, membership in aggregated_memberships.items():
            ensure_non_empty(criterion_id, "criterion_id")
            ensure_unit_interval(membership, "membership")
            value = float(membership)
            adjusted[criterion_id] = value if criterion_id in critical_criteria else max(value, membership_floor)
        return adjusted


class ViabilityClassifierService:
    """Classify final score using configurable viability thresholds."""

    def classify(
        self,
        score: Real | None,
        calc_condition: CalcCondition,
        viable_threshold: float = DEFAULT_VIABLE_THRESHOLD,
        condicional_threshold: float = DEFAULT_CONDICIONAL_THRESHOLD,
    ) -> ViabilityCategory | None:
        """Return a viability category, or None for no-conclusive calculations."""

        ensure_unit_interval(viable_threshold, "viable_threshold")
        ensure_unit_interval(condicional_threshold, "condicional_threshold")
        if condicional_threshold > viable_threshold:
            raise EvaluationDomainError("condicional_threshold must be <= viable_threshold")
        if calc_condition == CalcCondition.NO_CONCLUYENTE:
            return None
        ensure_unit_interval(score, "score")
        if score is None:
            raise EvaluationDomainError("score is required unless calculation is no-conclusive")
        if score >= viable_threshold:
            return ViabilityCategory.VIABLE
        if score >= condicional_threshold:
            return ViabilityCategory.CONDICIONAL
        return ViabilityCategory.NO_VIABLE


class BasicCropEvaluationService:
    """Run basic missing-data, aggregation and classification steps for one crop."""

    def __init__(
        self,
        missing_criteria_service: MissingCriteriaService | None = None,
        aggregation_service: MulticriteriaAggregationService | None = None,
        classifier_service: ViabilityClassifierService | None = None,
        floor_service: NonCriticalMembershipFloorService | None = None,
    ) -> None:
        """Create the pure domain service composition."""

        self._missing_criteria_service = missing_criteria_service or MissingCriteriaService()
        self._aggregation_service = aggregation_service or MulticriteriaAggregationService()
        self._classifier_service = classifier_service or ViabilityClassifierService()
        self._floor_service = floor_service or NonCriticalMembershipFloorService()

    def evaluate(
        self,
        crop_id: str,
        aggregated_memberships: dict[str, Real],
        hybrid_weights: dict[str, Real],
        missing_criteria: list[str],
        critical_criteria: set[str],
        unrecognized_variables: list[str] | None = None,
        viable_threshold: float = DEFAULT_VIABLE_THRESHOLD,
        condicional_threshold: float = DEFAULT_CONDICIONAL_THRESHOLD,
        non_critical_membership_floor: float = DEFAULT_NON_CRITICAL_MEMBERSHIP_FLOOR,
    ) -> BasicCropEvaluationResult:
        """Return the basic crop score and category without ranking or persistence."""

        ensure_non_empty(crop_id, "crop_id")
        participating = self._missing_criteria_service.resolve(
            aggregated_memberships=aggregated_memberships,
            hybrid_weights=hybrid_weights,
            missing_criteria=missing_criteria,
            critical_criteria=critical_criteria,
            unrecognized_variables=unrecognized_variables,
        )
        if not participating.should_calculate:
            return BasicCropEvaluationResult(
                crop_id=crop_id,
                score=None,
                calc_condition=participating.calc_condition,
                viability_category=None,
                missing_criteria=participating.missing_criteria,
                unrecognized_variables=participating.unrecognized_variables,
            )

        effective_memberships = self._floor_service.apply(
            participating.memberships,
            critical_criteria,
            non_critical_membership_floor,
        )
        score = self._aggregation_service.aggregate(effective_memberships, participating.weights)
        category = self._classifier_service.classify(score, participating.calc_condition, viable_threshold, condicional_threshold)
        return BasicCropEvaluationResult(
            crop_id=crop_id,
            score=score,
            calc_condition=participating.calc_condition,
            viability_category=category,
            missing_criteria=participating.missing_criteria,
            unrecognized_variables=participating.unrecognized_variables,
        )


def _normalize_weights_once(weights: dict[str, float]) -> dict[str, float]:
    """Normalize the remaining weights exactly once after exclusions."""

    total = sum(weights.values())
    if total <= 0.0:
        raise EvaluationDomainError("participating weights must have positive total")
    return {criterion_id: weight / total for criterion_id, weight in weights.items()}


def _unique_non_empty(values: list[str], field_name: str) -> list[str]:
    """Return unique non-empty values preserving input order."""

    unique_values: list[str] = []
    for value in values:
        ensure_non_empty(value, field_name)
        if value not in unique_values:
            unique_values.append(value)
    return unique_values
