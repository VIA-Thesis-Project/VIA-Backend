"""Unit tests for the deterministic gap analysis layer."""

from __future__ import annotations

import pytest

from via.bounded_contexts.recommendation.application.gap_analysis import analyse_gaps
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    GapClass,
    GapData,
)


# ─── Fixtures / builders ─────────────────────────────────────────────────────


def _gap(
    criterion_id: str = "deficit_hidrico",
    criterion_name: str | None = None,
    phase_id: str = "germinacion",
    phase_name: str | None = None,
    observed_value: float = 1500.0,
    optimal_limit: float = 600.0,
    gap_value: float = 900.0,
    gap_direction: str | None = "above_optimum",
    severity: str | None = "alta",
    most_limiting_period: str = "2023",
    intervention_class: str | None = None,
) -> GapData:
    return GapData(
        criterion_id=criterion_id,
        criterion_name=criterion_name or criterion_id,
        phase_id=phase_id,
        phase_name=phase_name or phase_id,
        most_limiting_period=most_limiting_period,
        observed_value=observed_value,
        optimal_limit=optimal_limit,
        gap_value=gap_value,
        gap_direction=gap_direction,
        severity=severity,
        intervention_class=intervention_class,
    )


def _result(
    gaps: list[GapData],
    viability_category: str = "CONDICIONAL",
    crop_id: str = "maiz_amarillo_duro",
) -> CropEvaluationResultData:
    return CropEvaluationResultData(
        crop_id=crop_id,
        score=0.6,
        rank_position=1,
        calc_condition="CONDICIONAL",
        viability_category=viability_category,
        gaps=gaps,
    )


# ─── Grouping ─────────────────────────────────────────────────────────────────


def test_gaps_with_same_criterion_grouped_into_one_group() -> None:
    gaps = [
        _gap(criterion_id="aptitud_termica", phase_id="germinacion"),
        _gap(criterion_id="aptitud_termica", phase_id="floracion"),
        _gap(criterion_id="aptitud_termica", phase_id="madurez"),
    ]
    result = analyse_gaps(_result(gaps))

    assert result.total_criteria_with_gaps == 1
    assert len(result.gap_groups) == 1
    group = result.gap_groups[0]
    assert group.criterion_id == "aptitud_termica"
    assert group.recurrence == 3


def test_different_criteria_produce_separate_groups() -> None:
    gaps = [
        _gap(criterion_id="aptitud_termica"),
        _gap(criterion_id="deficit_hidrico"),
        _gap(criterion_id="contenido_arena"),
    ]
    result = analyse_gaps(_result(gaps))

    ids = {g.criterion_id for g in result.gap_groups}
    assert ids == {"aptitud_termica", "deficit_hidrico", "contenido_arena"}
    assert result.total_criteria_with_gaps == 3


def test_all_phase_occurrences_preserved_in_group() -> None:
    phases = ["germinacion", "floracion", "llenado_grano"]
    gaps = [_gap(criterion_id="reaccion_suelo_ph", phase_id=p) for p in phases]

    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    occurrence_phases = {o.phase_id for o in group.occurrences}
    assert occurrence_phases == set(phases)
    assert group.recurrence == 3


def test_single_phase_gap_has_recurrence_one() -> None:
    result = analyse_gaps(_result([_gap(criterion_id="contenido_arcilla", phase_id="germinacion")]))

    assert result.gap_groups[0].recurrence == 1


# ─── Classification ───────────────────────────────────────────────────────────


def test_aptitud_altitudinal_is_structural_not_correctable() -> None:
    gaps = [_gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", intervention_class="STRUCTURAL")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE
    assert result.structural_count == 1


def test_cobertura_actual_auxiliar_is_structural_not_correctable() -> None:
    gaps = [_gap(criterion_id="cobertura_actual_auxiliar", criterion_name="cobertura_actual_auxiliar", intervention_class="STRUCTURAL")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE


def test_aptitud_termica_is_mitigable() -> None:
    gaps = [_gap(criterion_id="aptitud_termica", criterion_name="aptitud_termica", intervention_class="MITIGABLE")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.MITIGABLE
    assert result.mitigable_count == 1


def test_riesgo_frio_is_mitigable() -> None:
    gaps = [_gap(criterion_id="riesgo_frio", criterion_name="riesgo_frio", intervention_class="MITIGABLE")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.MITIGABLE


def test_riesgo_calor_is_mitigable() -> None:
    gaps = [_gap(criterion_id="riesgo_calor", criterion_name="riesgo_calor", intervention_class="MITIGABLE")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.MITIGABLE


def test_reaccion_suelo_ph_is_correctable() -> None:
    gaps = [_gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", observed_value=5.0, optimal_limit=6.5, gap_value=-1.5, intervention_class="CORRECTABLE")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE
    assert result.correctable_count == 1


def test_deficit_hidrico_is_correctable() -> None:
    # Use values clearly in hydric range (< 800 mm, well below altitude msnm range)
    gaps = [_gap(
        criterion_id="deficit_hidrico",
        criterion_name="deficit_hidrico",
        observed_value=350.0,
        optimal_limit=150.0,
        gap_value=200.0,
        intervention_class="CORRECTABLE",
    )]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE


def test_contenido_arena_is_correctable() -> None:
    gaps = [_gap(criterion_id="contenido_arena", criterion_name="contenido_arena", intervention_class="CORRECTABLE")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE


def test_unknown_criterion_defaults_to_mitigable() -> None:
    # No intervention_class, but has a name → conservative MITIGABLE fallback
    gaps = [_gap(criterion_id="criterio_desconocido", criterion_name="criterio_desconocido")]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.MITIGABLE


# ─── Correctability vocabulary ────────────────────────────────────────────────


def test_structural_correctability_is_no_corregible() -> None:
    gaps = [_gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="baja", intervention_class="STRUCTURAL")]
    result = analyse_gaps(_result(gaps))

    from via.bounded_contexts.recommendation.application.ports import Correctability
    assert result.gap_groups[0].correctability == Correctability.no_corregible


def test_mitigable_correctability_is_mitigable() -> None:
    gaps = [_gap(criterion_id="aptitud_termica", criterion_name="aptitud_termica", intervention_class="MITIGABLE")]
    result = analyse_gaps(_result(gaps))

    from via.bounded_contexts.recommendation.application.ports import Correctability
    assert result.gap_groups[0].correctability == Correctability.mitigable


def test_correctable_correctability_is_corregible() -> None:
    gaps = [_gap(criterion_id="contenido_arcilla", criterion_name="contenido_arcilla", intervention_class="CORRECTABLE")]
    result = analyse_gaps(_result(gaps))

    from via.bounded_contexts.recommendation.application.ports import Correctability
    assert result.gap_groups[0].correctability == Correctability.corregible


# ─── DATA_QUALITY_REVIEW detection ───────────────────────────────────────────


def test_reaccion_suelo_ph_with_zero_observed_is_data_quality() -> None:
    gaps = [_gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", observed_value=0.0, gap_value=-6.5)]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert len(group.data_quality_flags) > 0
    assert "0.0" in group.data_quality_flags[0]
    assert result.data_quality_count == 1


def test_carbono_organico_suelo_with_zero_observed_is_data_quality() -> None:
    gaps = [_gap(criterion_id="carbono_organico_suelo", criterion_name="carbono_organico_suelo", observed_value=0.0, gap_value=-10.0)]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert any("0.0" in f for f in group.data_quality_flags)


def test_all_occurrences_identical_zero_for_non_zero_impossible_is_data_quality() -> None:
    gaps = [
        _gap(criterion_id="disponibilidad_hidrica", criterion_name="disponibilidad_hidrica", observed_value=0.0, gap_value=-400.0, phase_id=f"fase_{i}", intervention_class="CORRECTABLE")
        for i in range(3)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert any("0.0" in f for f in group.data_quality_flags)


def test_nonzero_identical_temporal_values_for_temporal_variable_is_data_quality() -> None:
    gaps = [
        GapData(
            criterion_id="aptitud_termica",
            criterion_name="aptitud_termica",
            criterion_group="clima",
            phase_id=f"fase_{i}",
            most_limiting_period="2023",
            observed_value=17.5,
            optimal_limit=22.0,
            gap_value=-2.5,
            gap_direction="below_optimum",
            severity="alta",
            intervention_class="MITIGABLE",
        )
        for i in range(3)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert any("identico" in f.lower() for f in group.data_quality_flags)


def test_different_observed_values_across_phases_not_flagged_as_data_quality() -> None:
    gaps = [
        GapData(
            criterion_id="aptitud_termica",
            criterion_name="aptitud_termica",
            criterion_group="clima",
            phase_id=f"fase_{i}",
            most_limiting_period="2023",
            observed_value=17.0 + i,
            optimal_limit=22.0,
            gap_value=-5.0 + i,
            gap_direction="below_optimum",
            severity="alta",
            intervention_class="MITIGABLE",
        )
        for i in range(3)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.MITIGABLE
    assert len(group.data_quality_flags) == 0


# ─── RULEBOOK_REVIEW_REQUIRED ────────────────────────────────────────────────


def test_structural_alta_severity_recurrence_gte3_triggers_rulebook_review() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="alta", phase_id=f"fase_{i}", intervention_class="STRUCTURAL")
        for i in range(3)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.rulebook_review_required is True


def test_structural_alta_severity_recurrence_2_does_not_trigger_rulebook_review() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="alta", phase_id=f"fase_{i}", intervention_class="STRUCTURAL")
        for i in range(2)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.rulebook_review_required is False


def test_structural_baja_severity_recurrence_5_does_not_trigger_rulebook_review() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="baja", phase_id=f"fase_{i}", intervention_class="STRUCTURAL")
        for i in range(5)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.rulebook_review_required is False


def test_correctable_criterion_never_triggers_rulebook_review() -> None:
    gaps = [
        _gap(criterion_id="deficit_hidrico", criterion_name="deficit_hidrico", severity="alta", phase_id=f"fase_{i}", intervention_class="CORRECTABLE")
        for i in range(5)
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.rulebook_review_required is False


# ─── Priority scoring ─────────────────────────────────────────────────────────


def test_correctable_alta_scores_higher_than_mitigable_alta_same_recurrence() -> None:
    correctable = _gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", severity="alta", intervention_class="CORRECTABLE")
    mitigable = _gap(criterion_id="aptitud_termica", criterion_name="aptitud_termica", severity="alta", intervention_class="MITIGABLE")

    r_corr = analyse_gaps(_result([correctable]))
    r_mitig = analyse_gaps(_result([mitigable]))

    assert r_corr.gap_groups[0].priority_score > r_mitig.gap_groups[0].priority_score


def test_structural_criterion_has_lowest_priority_score() -> None:
    structural = _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="alta", intervention_class="STRUCTURAL")
    correctable = _gap(criterion_id="contenido_arcilla", criterion_name="contenido_arcilla", severity="alta", intervention_class="CORRECTABLE")

    r_struct = analyse_gaps(_result([structural]))
    r_corr = analyse_gaps(_result([correctable]))

    assert r_struct.gap_groups[0].priority_score < r_corr.gap_groups[0].priority_score


def test_groups_sorted_descending_by_priority_score() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="alta", intervention_class="STRUCTURAL"),
        _gap(criterion_id="contenido_arcilla", criterion_name="contenido_arcilla", severity="alta", intervention_class="CORRECTABLE"),
        _gap(criterion_id="aptitud_termica", criterion_name="aptitud_termica", severity="alta", intervention_class="MITIGABLE"),
    ]
    result = analyse_gaps(_result(gaps))

    scores = [g.priority_score for g in result.gap_groups]
    assert scores == sorted(scores, reverse=True)


def test_higher_recurrence_increases_priority_score_same_class() -> None:
    gaps_1 = [_gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", severity="alta", phase_id="germinacion", intervention_class="CORRECTABLE")]
    gaps_3 = [
        _gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", severity="alta", phase_id=f"fase_{i}", intervention_class="CORRECTABLE")
        for i in range(3)
    ]
    r1 = analyse_gaps(_result(gaps_1))
    r3 = analyse_gaps(_result(gaps_3))

    assert r3.gap_groups[0].priority_score > r1.gap_groups[0].priority_score


# ─── Representative values ───────────────────────────────────────────────────


def test_representative_gap_is_worst_by_severity_then_absolute_gap() -> None:
    gaps = [
        _gap(criterion_id="deficit_hidrico", criterion_name="deficit_hidrico", phase_id="germinacion",
             observed_value=700.0, optimal_limit=600.0, gap_value=100.0, severity="baja"),
        _gap(criterion_id="deficit_hidrico", criterion_name="deficit_hidrico", phase_id="floracion",
             observed_value=1500.0, optimal_limit=600.0, gap_value=900.0, severity="alta"),
    ]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.representative_severity == "alta"
    assert group.representative_observed == pytest.approx(1500.0)
    assert group.representative_gap == pytest.approx(900.0)


# ─── Ruling structural barriers ──────────────────────────────────────────────


def test_ruling_barriers_contains_structural_alta_criteria() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="alta", intervention_class="STRUCTURAL"),
        _gap(criterion_id="contenido_arcilla", criterion_name="contenido_arcilla", severity="alta", intervention_class="CORRECTABLE"),
    ]
    result = analyse_gaps(_result(gaps))

    assert "aptitud_altitudinal" in result.ruling_structural_barriers
    assert "contenido_arcilla" not in result.ruling_structural_barriers


def test_structural_baja_severity_not_in_ruling_barriers() -> None:
    gaps = [_gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", severity="baja", intervention_class="STRUCTURAL")]
    result = analyse_gaps(_result(gaps))

    assert result.ruling_structural_barriers == []


# ─── Viability interpretation ─────────────────────────────────────────────────


def test_no_viable_interpretation_forbids_installation_plan() -> None:
    result = analyse_gaps(_result([], viability_category="NO_VIABLE"))

    interp = result.viability_interpretation.lower()
    assert "no generar plan de instalacion" in interp or "no viable" in interp
    assert "descarte" in interp or "no_viable" in interp.replace(" ", "_") or "no generar" in interp


def test_condicional_interpretation_includes_plan_priorizado() -> None:
    result = analyse_gaps(_result([], viability_category="CONDICIONAL"))

    interp = result.viability_interpretation.lower()
    assert "condicional" in interp or "plan de manejo" in interp or "priorizado" in interp


def test_viable_interpretation_indicates_standard_management() -> None:
    result = analyse_gaps(_result([], viability_category="VIABLE"))

    interp = result.viability_interpretation.lower()
    assert "viable" in interp or "plan de manejo" in interp or "estandar" in interp


def test_unknown_viability_category_does_not_raise() -> None:
    result = analyse_gaps(_result([], viability_category="UNKNOWN_FUTURE_CATEGORY"))

    assert "UNKNOWN_FUTURE_CATEGORY" in result.viability_interpretation


# ─── Result metadata counts ───────────────────────────────────────────────────


def test_counts_match_group_classification() -> None:
    gaps = [
        _gap(criterion_id="aptitud_altitudinal", criterion_name="aptitud_altitudinal", intervention_class="STRUCTURAL"),
        _gap(criterion_id="aptitud_termica", criterion_name="aptitud_termica", intervention_class="MITIGABLE"),
        _gap(criterion_id="riesgo_frio", criterion_name="riesgo_frio", intervention_class="MITIGABLE"),
        _gap(criterion_id="contenido_arcilla", criterion_name="contenido_arcilla", intervention_class="CORRECTABLE"),
        _gap(criterion_id="reaccion_suelo_ph", criterion_name="reaccion_suelo_ph", observed_value=0.0, gap_value=-6.5, intervention_class="CORRECTABLE"),
    ]
    result = analyse_gaps(_result(gaps))

    assert result.structural_count == 1
    assert result.mitigable_count == 2
    assert result.correctable_count == 1
    assert result.data_quality_count == 1
    assert result.total_criteria_with_gaps == 5


def test_empty_gaps_produces_empty_result() -> None:
    result = analyse_gaps(_result([]))

    assert result.total_criteria_with_gaps == 0
    assert result.gap_groups == []
    assert result.ruling_structural_barriers == []
    assert result.structural_count == 0


# ─── GapAnalysisResult wired through command service ─────────────────────────


def test_analyse_gaps_result_passed_to_draft_context() -> None:
    """gap_analysis must be non-None in the context received by the drafting provider."""

    from uuid import uuid4
    from via.bounded_contexts.recommendation.application.command_service import (
        GenerateRecommendationCommand,
        RecommendationCommandService,
    )
    from via.bounded_contexts.recommendation.application.ports import (
        EvaluationRecommendationData,
        GapAnalysisResult,
        RecommendationDraftContext,
    )

    captured: list[RecommendationDraftContext] = []

    class CapturingProvider:
        def draft(self, ctx: RecommendationDraftContext) -> str:
            captured.append(ctx)
            return "mock text"

        @property
        def last_retrieved_results(self) -> list:
            return []

        @property
        def last_retrieved_text(self) -> str:
            return ""

        @property
        def last_structured_output(self) -> dict:
            return {}

    class FakeEvalPort:
        def get_results_for_recommendation(self, evaluation_id):
            return EvaluationRecommendationData(
                evaluation_id=evaluation_id,
                crop_results=[
                    CropEvaluationResultData(
                        crop_id="maiz_amarillo_duro",
                        score=0.65,
                        rank_position=1,
                        calc_condition="CONDICIONAL",
                        viability_category="CONDICIONAL",
                        gaps=[_gap(criterion_id="deficit_hidrico", criterion_name="deficit_hidrico")],
                    )
                ],
            )

    class FakeEvidPort:
        def search_evidence(self, crop_id, gaps, max_fragments):
            return []

    provider = CapturingProvider()
    service = RecommendationCommandService(
        evaluation_results_port=FakeEvalPort(),
        evidence_port=FakeEvidPort(),
        drafting_provider=provider,
        repository=None,
    )
    service.generate(GenerateRecommendationCommand(evaluation_id=uuid4(), persist=False))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.gap_analysis is not None
    assert isinstance(ctx.gap_analysis, GapAnalysisResult)
    assert ctx.gap_analysis.crop_id == "maiz_amarillo_duro"
    assert ctx.gap_analysis.total_criteria_with_gaps == 1


# ─── intervention_class-based classification (declarativa, desde rulebook) ────


def test_intervention_class_structural_produces_structural_not_correctable() -> None:
    gap = GapData(
        criterion_id="33850d2f-ab50-5319-b4b4-8e19c976f300",
        criterion_name=None,
        criterion_group="topografia",
        phase_id="germinacion",
        most_limiting_period="2023",
        observed_value=1808.12,
        optimal_limit=600.0,
        gap_value=1208.12,
        gap_direction="above_optimum",
        severity="alta",
        intervention_class="STRUCTURAL",
    )
    result = analyse_gaps(_result([gap]))

    assert result.gap_groups[0].gap_class == GapClass.STRUCTURAL_NOT_CORRECTABLE


def test_intervention_class_correctable_produces_correctable() -> None:
    gap = GapData(
        criterion_id="criterio_suelo_desconocido",
        criterion_name=None,
        criterion_group="suelo",
        phase_id="germinacion",
        most_limiting_period="2023",
        observed_value=4.5,
        optimal_limit=6.5,
        gap_value=-2.0,
        gap_direction="below_optimum",
        severity="media",
        intervention_class="CORRECTABLE",
    )
    result = analyse_gaps(_result([gap]))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE


def test_intervention_class_mitigable_produces_mitigable() -> None:
    gap = GapData(
        criterion_id="criterio_clima_desconocido",
        criterion_name=None,
        criterion_group="clima",
        phase_id="floracion",
        most_limiting_period="2023",
        observed_value=17.0,
        optimal_limit=22.0,
        gap_value=-5.0,
        gap_direction="below_optimum",
        severity="media",
        intervention_class="MITIGABLE",
    )
    result = analyse_gaps(_result([gap]))

    assert result.gap_groups[0].gap_class == GapClass.MITIGABLE


# ─── Completely unknown criterion → DATA_QUALITY_REVIEW ──────────────────────


def test_completely_unknown_criterion_no_name_no_group_is_data_quality() -> None:
    from via.bounded_contexts.recommendation.application.ports import GapData as _GapData
    gap = _GapData(
        criterion_id="33850d2f-ab50-5319-b4b4-8e19c976f300",
        criterion_name=None,
        criterion_group=None,
        phase_id="germinacion",
        most_limiting_period="2023",
        observed_value=1808.12,
        optimal_limit=600.0,
        gap_value=1208.12,
        gap_direction="above_optimum",
        severity="alta",
    )
    result = analyse_gaps(_result([gap]))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert any("completamente desconocido" in f.lower() for f in group.data_quality_flags)


# ─── Altitude-range detection for hydric criteria ─────────────────────────────


def test_deficit_hidrico_with_altitude_range_values_is_data_quality() -> None:
    """criterion_id 33850d2f with observed~1808/optimal~600 real case."""
    gaps = [_gap(
        criterion_id="deficit_hidrico",
        criterion_name="deficit_hidrico",
        observed_value=1808.12,
        optimal_limit=600.0,
        gap_value=1208.12,
        gap_direction="above_optimum",
        severity="alta",
    )]
    result = analyse_gaps(_result(gaps))

    group = result.gap_groups[0]
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert any("altitud" in f.lower() for f in group.data_quality_flags)
    assert any("rulebook" in f.lower() for f in group.data_quality_flags)


def test_deficit_hidrico_with_small_values_is_correctable() -> None:
    """Values clearly in hydric range (< 800 mm) should not trigger altitude detection."""
    gaps = [_gap(
        criterion_id="deficit_hidrico",
        criterion_name="deficit_hidrico",
        observed_value=350.0,
        optimal_limit=150.0,
        gap_value=200.0,
        gap_direction="above_optimum",
        severity="alta",
        intervention_class="CORRECTABLE",
    )]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE
    assert len(result.gap_groups[0].data_quality_flags) == 0


def test_deficit_hidrico_boundary_value_below_800_is_correctable() -> None:
    """At 799 mm (just below altitude threshold) → no flag, treat as hydric."""
    gaps = [_gap(
        criterion_id="deficit_hidrico",
        criterion_name="deficit_hidrico",
        observed_value=799.0,
        optimal_limit=500.0,
        gap_value=299.0,
        gap_direction="above_optimum",
        severity="media",
        intervention_class="CORRECTABLE",
    )]
    result = analyse_gaps(_result(gaps))

    assert result.gap_groups[0].gap_class == GapClass.CORRECTABLE


def test_real_criterion_uuid_with_altitude_values_detected_as_data_quality() -> None:
    """Full integration: the real UUID that appeared as deficit_hidrico in production."""
    from via.bounded_contexts.recommendation.application.ports import GapData as _GapData

    criterion_uuid = "33850d2f-ab50-5319-b4b4-8e19c976f300"
    gap = _GapData(
        criterion_id=criterion_uuid,
        criterion_name="deficit_hidrico",
        criterion_group=None,
        phase_id="germinacion",
        most_limiting_period="2023",
        observed_value=1808.12,
        optimal_limit=600.0,
        gap_value=1208.12,
        gap_direction="above_optimum",
        severity="alta",
    )
    result = analyse_gaps(_result([gap]))

    group = result.gap_groups[0]
    assert group.criterion_id == criterion_uuid
    assert group.gap_class == GapClass.DATA_QUALITY_REVIEW
    assert group.rulebook_review_required is False
    assert any("altitud" in f.lower() or "msnm" in f.lower() for f in group.data_quality_flags)


# ─── QC layer: suspect detection in command_service ──────────────────────────


def test_qc_flags_altitude_range_deficit_hidrico_as_suspect() -> None:
    """command_service QC must flag 1808/600 deficit_hidrico as criterion_mapping_suspect."""
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
    )
    from via.bounded_contexts.recommendation.application.ports import EvidenceData as _EvidenceData
    from uuid import uuid4

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Deficit hidrico critico en germinacion.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "deficit_hidrico|germinacion|1808.12|600.0|1208.12",
                "criterion_id": "33850d2f-ab50-5319-b4b4-8e19c976f300",
                "criterion_name": "deficit_hidrico",
                "criterion_label": "Deficit hidrico",
                "criterion_group": "clima",
                "unit": "mm",
                "phase_id": "germinacion",
                "phase_name": "germinacion",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "observed_value": 1808.12,
                "optimal_limit": 600.0,
                "gap_value": 1208.12,
                "recommendation": "Incrementar riego urgentemente.",
                "rationale": "Deficit hidrico severo.",
                "evidence_used": [{"source_file_id": "f1", "source_filename": "riego.md"}],
                "confidence": "alta",
                "limitations": None,
            }
        ],
    }
    evidence = [
        _EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Riego y agua disponible.",
            crop_tags=["maiz"],
            source_file_id="f1",
            source_filename="riego.md",
        )
    ]

    qc = _quality_control_structured_output(structured, evidence)
    item = qc["pending_methodological_validation"][0]

    assert item["criterion_mapping_suspect"] is True
    assert item["recommendation"] is None
    assert item["evidence_used"] == []
    assert "altitud" in item["mapping_validation_note"].lower() or "msnm" in item["mapping_validation_note"].lower()
    assert "revision" in item["mapping_validation_note"].lower()
    assert len(qc["gap_recommendations"]) == 0
    assert "pendiente" in qc["summary"].lower() or "metodologica" in qc["summary"].lower()
    assert "deficit_hidrico" in qc["summary"]


def test_qc_summary_contains_nota_via_for_suspect_items() -> None:
    """After QC, the summary must disclaim suspect criteria to prevent misinterpretation."""
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
    )
    from via.bounded_contexts.recommendation.application.ports import EvidenceData as _EvidenceData
    from uuid import uuid4

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "La principal brecha es el deficit hidrico con 1808 mm.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "deficit_hidrico|germinacion",
                "criterion_id": "deficit_hidrico",
                "criterion_name": "deficit_hidrico",
                "criterion_label": "Deficit hidrico",
                "criterion_group": "riego",
                "unit": "mm",
                "phase_id": "germinacion",
                "phase_name": "germinacion",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "observed_value": 1808.12,
                "optimal_limit": 600.0,
                "gap_value": 1208.12,
                "recommendation": "Aplicar riego masivo.",
                "rationale": "Hay deficit.",
                "evidence_used": [],
                "confidence": "alta",
                "limitations": None,
            }
        ],
    }

    qc = _quality_control_structured_output(structured, [], viability_category="CONDICIONAL")
    # Summary is now programmatic (no LLM text) when suspects are present
    assert "pendiente" in qc["summary"].lower() or "metodologica" in qc["summary"].lower()
    assert "deficit_hidrico" in qc["summary"]
    # Original LLM text is preserved in llm_raw_output for traceability
    assert "1808 mm" in (qc["llm_raw_output"]["summary"] or "")


def test_limitacion_none_string_not_rendered_in_visible_text() -> None:
    """'limitations': 'None' from LLM must not appear as 'Limitacion: None' in visible text."""
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )
    from via.bounded_contexts.recommendation.application.ports import EvidenceData as _EvidenceData
    from uuid import uuid4

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Brecha termica.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "aptitud_termica|floracion",
                "criterion_id": "aptitud_termica",
                "criterion_name": "aptitud_termica",
                "criterion_label": "Aptitud termica",
                "criterion_group": "clima",
                "unit": "celsius",
                "phase_id": "floracion",
                "phase_name": "floracion",
                "gap_direction": "below_optimum",
                "severity": "media",
                "observed_value": 17.0,
                "optimal_limit": 22.0,
                "gap_value": -5.0,
                "recommendation": "Ajustar ventana de siembra.",
                "rationale": "Temperatura baja.",
                "evidence_used": [{"source_file_id": "f1", "source_filename": "clima_fenologia.md"}],
                "confidence": "alta",
                "limitations": "None",
            }
        ],
    }
    evidence = [
        _EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Temperatura y floracion del cultivo.",
            crop_tags=["maiz"],
            source_file_id="f1",
            source_filename="clima_fenologia.md",
        )
    ]

    qc = _quality_control_structured_output(structured, evidence)
    visible = _render_visible_text(qc, "fallback")

    assert "Limitacion: None" not in visible
    assert "Limitacion: null" not in visible.lower()


def test_condicional_with_no_actionable_items_emits_conditional_summary() -> None:
    """CONDICIONAL with all-suspect items must give conditional guidance, not just 'no se pudo'."""
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "La brecha de altitud impide el cultivo.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "deficit_hidrico|germinacion",
                "criterion_id": "deficit_hidrico",
                "criterion_name": "deficit_hidrico",
                "criterion_label": "Deficit hidrico",
                "criterion_group": "riego",
                "unit": "mm",
                "phase_id": "germinacion",
                "phase_name": "germinacion",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "observed_value": 1808.12,
                "optimal_limit": 600.0,
                "gap_value": 1208.12,
                "recommendation": "Regar masivamente.",
                "rationale": "Deficit.",
                "evidence_used": [],
                "confidence": "alta",
                "limitations": None,
            }
        ],
    }

    qc = _quality_control_structured_output(structured, [], viability_category="CONDICIONAL")
    visible = _render_visible_text(qc, "fallback")

    assert "condicional" in visible.lower()
    assert "validacion" in visible.lower()
    assert "no se pudo emitir" not in visible.lower()
