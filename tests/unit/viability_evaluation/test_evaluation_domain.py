"""Unit tests for Lote 8A evaluation domain objects."""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.viability_evaluation.domain.agronomy_gap import AgronomyGap
from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.limiting_factor import LimitingFactor
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, EvaluationDomainError, ViabilityCategory


def test_crop_result_allows_pending_rank_position() -> None:
    result = CropResult(
        crop_id="cacao",
        score=None,
        rank_position=None,
        calc_condition=CalcCondition.PARCIAL,
        viability_category=ViabilityCategory.CONDICIONAL,
        criterion_details=[],
        gaps=[],
        limiting_factors=[],
        missing_criteria=["precipitation"],
        unrecognized_variables=[],
        entropy_series_sufficient=False,
    )

    assert result.rank_position is None


def test_criterion_detail_keeps_entropy_fallback_reason() -> None:
    detail = CriterionDetail(
        criterion_id="soil_moisture",
        memberships_by_period={"2026-01": 0.7},
        aggregated_by_phase={"flowering": 0.6},
        aggregated_membership=0.65,
        w_ahp=0.4,
        w_entropy=None,
        w_hybrid=0.4,
        entropy_used=False,
        entropy_fallback_reason="serie insuficiente",
    )

    assert detail.entropy_fallback_reason == "serie insuficiente"


def test_agronomy_gap_keeps_most_limiting_period() -> None:
    gap = AgronomyGap(
        criterion_id="temperature",
        phase_id="germination",
        most_limiting_period="2026-W02",
        observed_value=12.0,
        optimal_limit=18.0,
        gap_value=6.0,
    )

    assert gap.most_limiting_period == "2026-W02"


def test_limiting_factor_keeps_policy_penalty_membership_and_source() -> None:
    factor = LimitingFactor(
        criterion_id="temperature",
        phase_id="germination",
        policy=CriticalPolicy.PENALIZE,
        penalty_factor=0.5,
        observed_value=12.0,
        optimal_limit=18.0,
        membership=0.2,
        doc_source="rulebook-v1",
    )

    assert factor.policy == CriticalPolicy.PENALIZE
    assert factor.penalty_factor == 0.5
    assert factor.doc_source == "rulebook-v1"


def test_evaluation_records_only_candidate_crop_results() -> None:
    evaluation = Evaluation(
        id=uuid4(),
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
    )
    result = CropResult(
        crop_id="cacao",
        score=0.8,
        rank_position=1,
        calc_condition=CalcCondition.DEFINITIVO,
        viability_category=ViabilityCategory.VIABLE,
    )

    evaluation.record_crop_result(result)

    assert evaluation.crop_results == [result]


def test_evaluation_rejects_non_candidate_crop_results() -> None:
    evaluation = Evaluation(
        id=uuid4(),
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={},
    )
    result = CropResult(
        crop_id="maiz",
        score=0.8,
        rank_position=1,
        calc_condition=CalcCondition.DEFINITIVO,
        viability_category=ViabilityCategory.VIABLE,
    )

    with pytest.raises(EvaluationDomainError):
        evaluation.record_crop_result(result)
