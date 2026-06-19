"""Tests for the data-sufficiency policy in the MCDA evaluation engine.

Objectives covered:
    - Objetivo 3: NO_CONCLUYENTE when missing_weight >= 0.30
    - Objetivo 3: NO_CONCLUYENTE when structural topo criteria are missing
    - Objetivo 3: NDVI missing alone does not block ranking
    - Objetivo 4: Partial score preserved; calc_condition=PARCIAL with NO_CONCLUYENTE category
    - Ranking: NO_CONCLUYENTE excluded from rank
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from via.bounded_contexts.viability_evaluation.application.command_service import (
    ExecuteEvaluationCommand,
    McdaRuntimeSettings,
    PureMcdaEvaluationEngine,
    _apply_sufficiency_policy,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableData,
    AgroenvVectorData,
    EvaluationCriterionSpec,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.mcda_policy import RankingService
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory


# ─── Helpers ──────────────────────────────────────────────────────────────────

_EVALUATION_ID = "00000000-0000-0000-0000-000000000999"
_AHP_WEIGHTS = {
    "aptitud_termica":          0.18,
    "riesgo_frio":              0.10,
    "riesgo_calor":             0.10,
    "disponibilidad_hidrica":   0.17,
    "deficit_hidrico":          0.12,
    "aptitud_altitudinal":      0.17,
    "aptitud_topografica":      0.11,
    "cobertura_actual_auxiliar": 0.05,
}
_CRITERIA_NAMES = list(_AHP_WEIGHTS)
_PHASES = ["establecimiento", "desarrollo", "floracion", "maduracion"]
_PHASE_WEIGHTS = [0.25, 0.40, 0.25, 0.10]


def _settings() -> McdaRuntimeSettings:
    return McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )


def _command() -> ExecuteEvaluationCommand:
    return ExecuteEvaluationCommand(
        evaluation_id=UUID(_EVALUATION_ID),
        extraction_result={
            "crop_candidates": ["demo_maiz"],
            "temporal_window": {"start": "2025-06-01", "end": "2026-06-01"},
        },
    )


def _spec(criterion_id: str, phase: str, phase_weight: float, critical_policy: str = "NONE") -> EvaluationCriterionSpec:
    return EvaluationCriterionSpec(
        criterion_id=criterion_id,
        crop_id="demo_maiz",
        phase_id=phase,
        variable_name=criterion_id,
        w_ahp=_AHP_WEIGHTS[criterion_id],
        phase_weight=phase_weight,
        temporal_periods=[{"period_key": f"{criterion_id}_{phase}", "temporal_weight": 1.0}],
        membership_fn={"type": "TRAPEZOIDAL", "a": 0.0, "b": 5.0, "c": 25.0, "d": 30.0},
        critical_policy=critical_policy,
        penalty_factor=None,
        doc_source="test",
    )


def _full_rulebook() -> RulebookEvaluationData:
    """Rulebook with all 8 criteria and 4 phases each, no critical policies."""
    criteria_specs = [
        _spec(c, phase, pw)
        for c in _CRITERIA_NAMES
        for phase, pw in zip(_PHASES, _PHASE_WEIGHTS)
    ]
    return RulebookEvaluationData(
        crop_id="demo_maiz",
        rulebook_id=uuid4(),
        version=1,
        criteria=criteria_specs,
    )


def _variable(criterion_id: str, phase: str, value: float | None, status: str = "OK") -> AgroenvVariableData:
    return AgroenvVariableData(
        variable_name=criterion_id,
        criterion_id=criterion_id,
        crop_id="demo_maiz",
        phase_id=phase,
        period_key=f"{criterion_id}_{phase}",
        value=value,
        unit="test_unit",
        status=status if value is not None else "CRITERIO_FALTANTE",
        dataset_key="test_dataset",
        band=criterion_id,
        source="test_source",
    )


def _vector_with_present(*present_criteria: str) -> AgroenvVectorData:
    """Build a vector where only the listed criteria have data (value=15.0, within optimal range)."""
    variables = [
        _variable(c, phase, 15.0)
        for c in present_criteria
        for phase in _PHASES
    ]
    return AgroenvVectorData(
        evaluation_id=UUID(_EVALUATION_ID),
        parcel_id=uuid4(),
        variables=variables,
    )


# ─── _apply_sufficiency_policy unit tests ─────────────────────────────────────


class _FakeBasicResult:
    def __init__(self, calc_condition, missing_criteria, viability_category=ViabilityCategory.VIABLE):
        self.calc_condition = calc_condition
        self.missing_criteria = missing_criteria
        self.viability_category = viability_category


class _FakeCriticalResult:
    def __init__(self, score, viability_category=ViabilityCategory.VIABLE):
        self.score = score
        self.viability_category = viability_category
        self.limiting_factors = []


def test_sufficiency_policy_no_missing_criteria_passes_through() -> None:
    basic = _FakeBasicResult(CalcCondition.DEFINITIVO, missing_criteria=[])
    critical = _FakeCriticalResult(score=0.85, viability_category=ViabilityCategory.VIABLE)

    score, condition, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert score == pytest.approx(0.85)
    assert condition == CalcCondition.DEFINITIVO
    assert category == ViabilityCategory.VIABLE


def test_sufficiency_policy_missing_weight_below_threshold_passes_through() -> None:
    # Only NDVI missing: weight=0.05 < 0.30
    basic = _FakeBasicResult(CalcCondition.PARCIAL, missing_criteria=["cobertura_actual_auxiliar"])
    critical = _FakeCriticalResult(score=0.75, viability_category=ViabilityCategory.VIABLE)

    score, condition, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert category == ViabilityCategory.VIABLE
    assert condition == CalcCondition.PARCIAL


def test_sufficiency_policy_missing_weight_above_threshold_returns_no_concluyente() -> None:
    # All 5 climate criteria missing: weight = 0.67 >= 0.30
    climate_criteria = ["aptitud_termica", "riesgo_frio", "riesgo_calor", "disponibilidad_hidrica", "deficit_hidrico"]
    basic = _FakeBasicResult(CalcCondition.PARCIAL, missing_criteria=climate_criteria)
    critical = _FakeCriticalResult(score=0.95, viability_category=ViabilityCategory.VIABLE)

    score, condition, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert category == ViabilityCategory.NO_CONCLUYENTE
    assert condition == CalcCondition.PARCIAL
    assert score == pytest.approx(0.95)  # partial score preserved for traceability


def test_sufficiency_policy_missing_structural_topo_returns_no_concluyente_even_below_threshold() -> None:
    # Only aptitud_altitudinal missing: weight=0.17 < 0.30, but structural
    basic = _FakeBasicResult(CalcCondition.PARCIAL, missing_criteria=["aptitud_altitudinal"])
    critical = _FakeCriticalResult(score=0.80, viability_category=ViabilityCategory.VIABLE)

    score, condition, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert category == ViabilityCategory.NO_CONCLUYENTE
    assert score == pytest.approx(0.80)


def test_sufficiency_policy_missing_pendiente_also_structural() -> None:
    basic = _FakeBasicResult(CalcCondition.PARCIAL, missing_criteria=["aptitud_topografica"])
    critical = _FakeCriticalResult(score=0.80, viability_category=ViabilityCategory.VIABLE)

    _, _, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert category == ViabilityCategory.NO_CONCLUYENTE


def test_sufficiency_policy_no_concluyente_calc_condition_overrides_to_no_concluyente_category() -> None:
    # CalcCondition.NO_CONCLUYENTE path (critical criteria missing)
    basic = _FakeBasicResult(CalcCondition.NO_CONCLUYENTE, missing_criteria=["aptitud_altitudinal"])
    critical = _FakeCriticalResult(score=None, viability_category=None)

    score, condition, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert score is None
    assert condition == CalcCondition.NO_CONCLUYENTE
    assert category == ViabilityCategory.NO_CONCLUYENTE


def test_sufficiency_policy_missing_ndvi_alone_does_not_block_result() -> None:
    basic = _FakeBasicResult(CalcCondition.PARCIAL, missing_criteria=["cobertura_actual_auxiliar"])
    critical = _FakeCriticalResult(score=0.82, viability_category=ViabilityCategory.VIABLE)

    _, _, category = _apply_sufficiency_policy(basic, critical, _AHP_WEIGHTS)

    assert category != ViabilityCategory.NO_CONCLUYENTE
    assert category == ViabilityCategory.VIABLE


# ─── PureMcdaEvaluationEngine integration tests ───────────────────────────────


def test_missing_all_climate_results_in_no_concluyente() -> None:
    """When all 5 climate criteria have no data (67% weight missing), category must be NO_CONCLUYENTE."""
    topo_and_ndvi = ["aptitud_altitudinal", "aptitud_topografica", "cobertura_actual_auxiliar"]
    vector = _vector_with_present(*topo_and_ndvi)

    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(), vector, [_full_rulebook()], _settings()
    )
    result = evaluation.crop_results[0]

    assert result.viability_category == ViabilityCategory.NO_CONCLUYENTE
    assert result.calc_condition == CalcCondition.PARCIAL
    assert result.rank_position is None
    climate = {"aptitud_termica", "riesgo_frio", "riesgo_calor", "disponibilidad_hidrica", "deficit_hidrico"}
    assert all(c in result.missing_criteria for c in climate)


def test_missing_elevation_results_in_no_concluyente_despite_small_weight() -> None:
    """Structural criterion: elevation missing alone triggers NO_CONCLUYENTE even if weight < 0.30."""
    # Provide all criteria EXCEPT aptitud_altitudinal
    present = [c for c in _CRITERIA_NAMES if c != "aptitud_altitudinal"]
    vector = _vector_with_present(*present)

    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(), vector, [_full_rulebook()], _settings()
    )
    result = evaluation.crop_results[0]

    assert result.viability_category == ViabilityCategory.NO_CONCLUYENTE
    assert "aptitud_altitudinal" in result.missing_criteria
    assert result.rank_position is None


def test_missing_ndvi_alone_does_not_block_definitive_result() -> None:
    """Auxiliary criterion: NDVI missing (5% weight) must not prevent a conclusive evaluation."""
    present = [c for c in _CRITERIA_NAMES if c != "cobertura_actual_auxiliar"]
    vector = _vector_with_present(*present)

    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(), vector, [_full_rulebook()], _settings()
    )
    result = evaluation.crop_results[0]

    assert result.viability_category != ViabilityCategory.NO_CONCLUYENTE
    assert "cobertura_actual_auxiliar" in result.missing_criteria
    assert result.score is not None


def test_no_concluyente_result_excluded_from_ranking() -> None:
    """Results with NO_CONCLUYENTE category must have rank_position=None."""
    ranked = RankingService().assign_rank_positions([
        CropResult(
            crop_id="cacao",
            score=0.9,
            rank_position=None,
            calc_condition=CalcCondition.PARCIAL,
            viability_category=ViabilityCategory.NO_CONCLUYENTE,
        ),
        CropResult(
            crop_id="maiz",
            score=0.75,
            rank_position=None,
            calc_condition=CalcCondition.DEFINITIVO,
            viability_category=ViabilityCategory.VIABLE,
        ),
    ])

    by_crop = {r.crop_id: r for r in ranked}
    assert by_crop["cacao"].rank_position is None
    assert by_crop["maiz"].rank_position == 1


def test_missing_weight_partial_score_preserved_for_traceability() -> None:
    """When climate is missing, the partial score (from topo+NDVI) is kept in the result."""
    topo_and_ndvi = ["aptitud_altitudinal", "aptitud_topografica", "cobertura_actual_auxiliar"]
    vector = _vector_with_present(*topo_and_ndvi)

    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(), vector, [_full_rulebook()], _settings()
    )
    result = evaluation.crop_results[0]

    assert result.viability_category == ViabilityCategory.NO_CONCLUYENTE
    assert result.score is not None, "Partial score should be preserved for traceability"
    assert 0.0 <= result.score <= 1.0


def test_two_climate_criteria_missing_above_threshold_returns_no_concluyente() -> None:
    """aptitud_termica (0.18) + disponibilidad_hidrica (0.17) = 0.35 >= 0.30."""
    present = [c for c in _CRITERIA_NAMES if c not in {"aptitud_termica", "disponibilidad_hidrica"}]
    vector = _vector_with_present(*present)

    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(), vector, [_full_rulebook()], _settings()
    )
    result = evaluation.crop_results[0]

    assert result.viability_category == ViabilityCategory.NO_CONCLUYENTE


# ─── Separation of concerns: domain must not depend on infrastructure ──────────


def test_viability_category_no_concluyente_is_available_as_enum_value() -> None:
    assert ViabilityCategory.NO_CONCLUYENTE == "NO_CONCLUYENTE"
    assert ViabilityCategory.NO_CONCLUYENTE in ViabilityCategory


def test_value_objects_do_not_import_sqlalchemy() -> None:
    import importlib
    import sys
    module = importlib.import_module(
        "via.bounded_contexts.viability_evaluation.domain.value_objects"
    )
    src = __import__("inspect").getsource(module)
    assert "sqlalchemy" not in src, "value_objects.py must not import sqlalchemy"
