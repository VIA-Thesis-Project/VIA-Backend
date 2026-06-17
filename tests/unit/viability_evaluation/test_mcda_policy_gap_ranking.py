"""Unit tests for Lote 8B.3B critical policies, gaps and ranking."""

from __future__ import annotations

import pytest

from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.mcda_policy import (
    CriticalCriterionTrace,
    CriticalPolicyService,
    GapCalculationService,
    PhaseGapTrace,
    RankingService,
)
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory


def test_critical_no_viable_policy_assigns_no_viable_and_limiting_factor() -> None:
    result = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 0.8},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.NO_VIABLE)],
    )

    assert result.viability_category == ViabilityCategory.NO_VIABLE
    assert result.limiting_factors[0].criterion_id == "rain"
    assert result.limiting_factors[0].policy == CriticalPolicy.NO_VIABLE


def test_critical_penalize_policy_applies_penalty_and_limiting_factor() -> None:
    result = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.PENALIZE, penalty_factor=0.5)],
    )

    assert result.limiting_factors[0].policy == CriticalPolicy.PENALIZE
    assert result.score == pytest.approx(0.05)
    assert result.viability_category == ViabilityCategory.NO_VIABLE


def test_penalize_epsilon_is_used_before_geometric_mean() -> None:
    result = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.PENALIZE, penalty_factor=1.0)],
        penalize_epsilon=0.04,
    )

    assert result.effective_memberships["rain"] == pytest.approx(0.04)
    assert result.score == pytest.approx(0.2)


def test_penalty_factor_modifies_score_after_epsilon_aggregation() -> None:
    no_penalty = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.PENALIZE, penalty_factor=1.0)],
    )
    penalized = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.PENALIZE, penalty_factor=0.5)],
    )

    assert penalized.score == pytest.approx(no_penalty.score * 0.5)


def test_limiting_factor_keeps_all_required_fields() -> None:
    result = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0},
        hybrid_weights={"rain": 1.0},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.NO_VIABLE)],
    )
    factor = result.limiting_factors[0]

    assert factor.criterion_id == "rain"
    assert factor.phase_id == "flowering"
    assert factor.policy == CriticalPolicy.NO_VIABLE
    assert factor.penalty_factor is None
    assert factor.observed_value == 12.0
    assert factor.optimal_limit == 20.0
    assert factor.membership == 0.0
    assert factor.doc_source == "manual"


def test_gap_uses_most_limiting_period() -> None:
    gaps = GapCalculationService().calculate([
        PhaseGapTrace(
            criterion_id="rain",
            phase_id="flowering",
            aggregated_membership=0.5,
            period_memberships={"week_1": 0.8, "week_2": 0.2},
            observed_values={"week_1": 30.0, "week_2": 12.0},
            optimal_limits={"week_1": 25.0, "week_2": 20.0},
        )
    ])

    assert gaps[0].most_limiting_period == "week_2"
    assert gaps[0].observed_value == 12.0


def test_gap_preserves_deficit_sign() -> None:
    gaps = GapCalculationService().calculate([
        PhaseGapTrace(
            criterion_id="rain",
            phase_id="flowering",
            aggregated_membership=0.5,
            period_memberships={"week_1": 0.2},
            observed_values={"week_1": 12.0},
            optimal_limits={"week_1": 20.0},
        )
    ])

    assert gaps[0].gap_value == pytest.approx(-8.0)


def test_gap_preserves_excess_sign() -> None:
    gaps = GapCalculationService().calculate([
        PhaseGapTrace(
            criterion_id="rain",
            phase_id="flowering",
            aggregated_membership=0.5,
            period_memberships={"week_1": 0.2},
            observed_values={"week_1": 32.0},
            optimal_limits={"week_1": 20.0},
        )
    ])

    assert gaps[0].gap_value == pytest.approx(12.0)


def test_classification_after_penalization_uses_penalized_score() -> None:
    result = CriticalPolicyService().apply(
        aggregated_memberships={"rain": 0.0, "temp": 1.0},
        hybrid_weights={"rain": 0.5, "temp": 0.5},
        calc_condition=CalcCondition.DEFINITIVO,
        critical_traces=[_trace(policy=CriticalPolicy.PENALIZE, penalty_factor=1.0)],
        penalize_epsilon=0.25,
    )

    assert result.score == pytest.approx(0.5)
    assert result.viability_category == ViabilityCategory.CONDICIONAL


def test_ranking_orders_by_score_descending() -> None:
    ranked = RankingService().assign_rank_positions([
        _crop("maiz", 0.7),
        _crop("cacao", 0.9),
    ])

    assert _rank_by_crop(ranked) == {"cacao": 1, "maiz": 2}


def test_ranking_tie_breaks_by_crop_id_ascending() -> None:
    ranked = RankingService().assign_rank_positions([
        _crop("maiz", 0.8),
        _crop("cacao", 0.8),
    ])

    assert _rank_by_crop(ranked) == {"cacao": 1, "maiz": 2}


def test_ranking_excludes_no_conclusive_crops() -> None:
    ranked = RankingService().assign_rank_positions([
        _crop("cacao", 0.9, calc_condition=CalcCondition.NO_CONCLUYENTE),
        _crop("maiz", 0.7),
    ])

    assert _by_crop(ranked)["cacao"].rank_position is None
    assert _by_crop(ranked)["maiz"].rank_position == 1


def test_ranking_excludes_no_viable_crops() -> None:
    ranked = RankingService().assign_rank_positions([
        _crop("cacao", 0.9, viability_category=ViabilityCategory.NO_VIABLE),
        _crop("maiz", 0.7),
    ])

    assert _by_crop(ranked)["cacao"].rank_position is None
    assert _by_crop(ranked)["maiz"].rank_position == 1


def test_rank_position_is_assigned_only_to_included_crops() -> None:
    ranked = RankingService().assign_rank_positions([
        _crop("cacao", 0.9),
        _crop("maiz", 0.7, viability_category=ViabilityCategory.NO_VIABLE),
        _crop("papa", 0.8),
    ])

    by_crop = _by_crop(ranked)
    assert by_crop["cacao"].rank_position == 1
    assert by_crop["papa"].rank_position == 2
    assert by_crop["maiz"].rank_position is None


def _trace(policy: CriticalPolicy, penalty_factor: float | None = None) -> CriticalCriterionTrace:
    return CriticalCriterionTrace(
        criterion_id="rain",
        phase_id="flowering",
        policy=policy,
        penalty_factor=penalty_factor,
        observed_value=12.0,
        optimal_limit=20.0,
        membership=0.0,
        doc_source="manual",
    )


def _crop(
    crop_id: str,
    score: float,
    calc_condition: CalcCondition = CalcCondition.DEFINITIVO,
    viability_category: ViabilityCategory = ViabilityCategory.VIABLE,
) -> CropResult:
    return CropResult(
        crop_id=crop_id,
        score=score,
        rank_position=None,
        calc_condition=calc_condition,
        viability_category=viability_category,
    )


def _by_crop(crop_results: list[CropResult]) -> dict[str, CropResult]:
    return {result.crop_id: result for result in crop_results}


def _rank_by_crop(crop_results: list[CropResult]) -> dict[str, int | None]:
    return {result.crop_id: result.rank_position for result in crop_results}
