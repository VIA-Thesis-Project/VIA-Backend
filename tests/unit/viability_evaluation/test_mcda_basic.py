"""Unit tests for Lote 8B.1 fuzzy MCDA basics."""

from __future__ import annotations

import math

import pytest

from via.bounded_contexts.viability_evaluation.domain.mcda_basic import (
    TrapezoidalMembershipFunction,
    aggregate_phases,
    aggregate_temporal,
    build_criterion_detail,
)
from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError


def test_trapezoid_returns_zero_for_low_value() -> None:
    membership_fn = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=40)

    assert membership_fn.membership(5) == 0.0


def test_trapezoid_lower_edge_a_is_zero_for_non_degenerate_ramp() -> None:
    membership_fn = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=40)

    assert membership_fn.membership(10) == 0.0


def test_trapezoid_returns_one_in_optimal_plateau() -> None:
    membership_fn = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=40)

    assert membership_fn.membership(25) == 1.0
    assert membership_fn.membership(20) == 1.0
    assert membership_fn.membership(30) == 1.0


def test_trapezoid_upper_edge_d_is_zero_for_non_degenerate_ramp() -> None:
    membership_fn = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=40)

    assert membership_fn.membership(40) == 0.0


def test_trapezoid_returns_zero_for_high_value() -> None:
    membership_fn = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=40)

    assert membership_fn.membership(45) == 0.0


def test_trapezoid_rejects_invalid_ordering() -> None:
    with pytest.raises(EvaluationDomainError):
        TrapezoidalMembershipFunction(a=10, b=30, c=20, d=40)


def test_trapezoid_handles_allowed_degenerate_edges_without_division_by_zero() -> None:
    left_step = TrapezoidalMembershipFunction(a=10, b=10, c=20, d=30)
    right_step = TrapezoidalMembershipFunction(a=10, b=20, c=30, d=30)
    triangular = TrapezoidalMembershipFunction(a=10, b=20, c=20, d=30)

    assert left_step.membership(10) == 1.0
    assert right_step.membership(30) == 1.0
    assert triangular.membership(20) == 1.0
    assert 0.0 <= triangular.membership(15) <= 1.0


def test_membership_function_is_phase_specific_for_same_criterion() -> None:
    establishment = TrapezoidalMembershipFunction(a=10, b=20, c=25, d=35)
    flowering = TrapezoidalMembershipFunction(a=20, b=30, c=35, d=45)

    assert establishment.membership(22) == 1.0
    assert flowering.membership(22) == pytest.approx(0.2)


def test_temporal_weighted_aggregation_uses_geometric_mean() -> None:
    result = aggregate_temporal(
        {"week_1": 0.25, "week_2": 1.0},
        {"week_1": 0.5, "week_2": 0.5},
    )

    assert result == pytest.approx(math.sqrt(0.25))


def test_temporal_weight_sum_is_validated() -> None:
    with pytest.raises(EvaluationDomainError):
        aggregate_temporal({"week_1": 0.5, "week_2": 0.8}, {"week_1": 0.4, "week_2": 0.4})


def test_phase_weighted_aggregation_uses_geometric_mean() -> None:
    result = aggregate_phases(
        {"establishment": 0.25, "flowering": 1.0},
        {"establishment": 0.5, "flowering": 0.5},
    )

    assert result == pytest.approx(0.5)


def test_phase_weight_sum_is_validated() -> None:
    with pytest.raises(EvaluationDomainError):
        aggregate_phases({"establishment": 0.5, "flowering": 0.8}, {"establishment": 0.7, "flowering": 0.7})


def test_build_criterion_detail_keeps_memberships_aggregations_and_ahp_traceability() -> None:
    detail = build_criterion_detail(
        criterion_id="rainfall",
        memberships_by_phase_period={
            "establishment": {"week_1": 0.25, "week_2": 1.0},
            "flowering": {"week_3": 0.81, "week_4": 1.0},
        },
        temporal_weights_by_phase={
            "establishment": {"week_1": 0.5, "week_2": 0.5},
            "flowering": {"week_3": 0.5, "week_4": 0.5},
        },
        phase_weights={"establishment": 0.4, "flowering": 0.6},
        w_ahp=0.35,
    )

    assert detail.memberships_by_period == {
        "establishment:week_1": 0.25,
        "establishment:week_2": 1.0,
        "flowering:week_3": 0.81,
        "flowering:week_4": 1.0,
    }
    assert detail.aggregated_by_phase["establishment"] == pytest.approx(0.5)
    assert detail.aggregated_by_phase["flowering"] == pytest.approx(0.9)
    assert detail.aggregated_membership == pytest.approx((0.5**0.4) * (0.9**0.6))
    assert detail.w_ahp == 0.35
    assert detail.w_entropy is None
    assert detail.w_hybrid == 0.35
    assert detail.entropy_used is False
    assert detail.entropy_fallback_reason is None
