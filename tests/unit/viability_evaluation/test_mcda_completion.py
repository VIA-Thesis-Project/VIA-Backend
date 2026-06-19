"""Unit tests for Lote 8B.3A basic MCDA completion."""

from __future__ import annotations

import pytest

from via.bounded_contexts.viability_evaluation.domain.mcda_completion import (
    BasicCropEvaluationService,
    MissingCriteriaService,
    MulticriteriaAggregationService,
    NonCriticalMembershipFloorService,
    ViabilityClassifierService,
)
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, ViabilityCategory


def test_critical_missing_criterion_produces_no_conclusive_result() -> None:
    result = BasicCropEvaluationService().evaluate(
        crop_id="cacao",
        aggregated_memberships={"rain": 0.8, "temp": 0.7},
        hybrid_weights={"rain": 0.6, "temp": 0.4},
        missing_criteria=["rain"],
        critical_criteria={"rain"},
    )

    assert result.calc_condition == CalcCondition.NO_CONCLUYENTE
    assert result.score is None
    assert result.viability_category is None
    assert result.missing_criteria == ["rain"]


def test_non_critical_missing_criterion_produces_partial_result() -> None:
    result = BasicCropEvaluationService().evaluate(
        crop_id="cacao",
        aggregated_memberships={"rain": 0.8, "temp": 0.7},
        hybrid_weights={"rain": 0.6, "temp": 0.4},
        missing_criteria=["temp"],
        critical_criteria={"rain"},
    )

    assert result.calc_condition == CalcCondition.PARCIAL
    assert result.missing_criteria == ["temp"]
    assert result.score == pytest.approx(0.8)


def test_non_critical_missing_is_excluded_and_weights_are_renormalized_once() -> None:
    participating = MissingCriteriaService().resolve(
        aggregated_memberships={"rain": 0.8, "temp": 0.1, "soil": 0.6},
        hybrid_weights={"rain": 0.5, "temp": 0.3, "soil": 0.2},
        missing_criteria=["temp"],
        critical_criteria={"rain"},
    )

    assert participating.memberships == {"rain": 0.8, "soil": 0.6}
    assert participating.weights == {"rain": pytest.approx(0.5 / 0.7), "soil": pytest.approx(0.2 / 0.7)}
    assert sum(participating.weights.values()) == pytest.approx(1.0)


def test_non_critical_missing_is_not_treated_as_zero_membership() -> None:
    result = BasicCropEvaluationService().evaluate(
        crop_id="cacao",
        aggregated_memberships={"rain": 1.0, "temp": 0.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        missing_criteria=["temp"],
        critical_criteria={"rain"},
    )

    assert result.score == pytest.approx(1.0)
    assert result.calc_condition == CalcCondition.PARCIAL


def test_non_critical_zero_membership_uses_floor_before_geometric_mean() -> None:
    result = BasicCropEvaluationService().evaluate(
        crop_id="cacao",
        aggregated_memberships={"rain": 1.0, "deficit_hidrico": 0.0},
        hybrid_weights={"rain": 0.5, "deficit_hidrico": 0.5},
        missing_criteria=[],
        critical_criteria=set(),
        non_critical_membership_floor=0.05,
    )

    assert result.score == pytest.approx(0.05**0.5)
    assert result.score > 0.0


def test_membership_floor_applies_only_to_non_critical_criteria() -> None:
    adjusted = NonCriticalMembershipFloorService().apply(
        aggregated_memberships={"altitud": 0.0, "deficit_hidrico": 0.0, "temperatura": 0.8},
        critical_criteria={"altitud"},
        membership_floor=0.05,
    )

    assert adjusted["altitud"] == 0.0
    assert adjusted["deficit_hidrico"] == pytest.approx(0.05)
    assert adjusted["temperatura"] == pytest.approx(0.8)


def test_unrecognized_variable_is_recorded_and_ignored() -> None:
    result = BasicCropEvaluationService().evaluate(
        crop_id="cacao",
        aggregated_memberships={"rain": 0.9},
        hybrid_weights={"rain": 1.0},
        missing_criteria=[],
        critical_criteria=set(),
        unrecognized_variables=["wind_speed"],
    )

    assert result.unrecognized_variables == ["wind_speed"]
    assert result.score == pytest.approx(0.9)


def test_multicriteria_score_uses_weighted_geometric_mean_with_hybrid_weights() -> None:
    score = MulticriteriaAggregationService().aggregate(
        aggregated_memberships={"rain": 0.25, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
    )

    assert score == pytest.approx(0.5)


def test_multicriteria_score_is_one_when_all_memberships_are_one() -> None:
    score = MulticriteriaAggregationService().aggregate(
        aggregated_memberships={"rain": 1.0, "temp": 1.0},
        hybrid_weights={"rain": 0.3, "temp": 0.7},
    )

    assert score == pytest.approx(1.0)


def test_classifier_returns_viable() -> None:
    category = ViabilityClassifierService().classify(0.70, CalcCondition.DEFINITIVO)

    assert category == ViabilityCategory.VIABLE


def test_classifier_returns_condicional() -> None:
    category = ViabilityClassifierService().classify(0.40, CalcCondition.PARCIAL)

    assert category == ViabilityCategory.CONDICIONAL


def test_classifier_returns_no_viable() -> None:
    category = ViabilityClassifierService().classify(0.39, CalcCondition.DEFINITIVO)

    assert category == ViabilityCategory.NO_VIABLE


def test_no_conclusive_classifier_does_not_force_score_or_category() -> None:
    category = ViabilityClassifierService().classify(None, CalcCondition.NO_CONCLUYENTE)

    assert category is None
