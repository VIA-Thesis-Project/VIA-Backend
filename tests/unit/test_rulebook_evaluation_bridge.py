"""Unit tests for _rulebook_to_evaluation_data in via/shared/runtime/bridges.py.

These tests specifically verify that critical_policy and penalty_factor are
transported correctly from the Rulebook domain object to EvaluationCriterionSpec.

Root-cause context: a previous bug set non-critical criteria to
critical_policy="PENALIZE" (instead of "") so any zero membership triggered
"penalty_factor is required for PENALIZE policy".
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    CriticalPolicy,
    InterventionClass,
    MembershipFunction,
    RulebookStatus,
    TemporalPeriod,
)
from via.bounded_contexts.viability_evaluation.application.command_service import (
    PureMcdaEvaluationEngine,
    ExecuteEvaluationCommand,
    McdaRuntimeSettings,
)
from via.bounded_contexts.viability_evaluation.application.ports import AgroenvVariableData, AgroenvVectorData
from via.bounded_contexts.viability_evaluation.domain.value_objects import CriticalPolicy as EvalCriticalPolicy
from via.shared.runtime.bridges import _rulebook_to_evaluation_data


# ─── Fixture builders ─────────────────────────────────────────────────────────


def _criterion(
    name: str = "vegetacion_vigor",
    is_critical: bool = False,
    critical_policy: CriticalPolicy | None = None,
    penalty_factor: float | None = None,
    ahp_weight: float = 0.5,
) -> Criterion:
    return Criterion(
        id=uuid4(),
        name=name,
        is_critical=is_critical,
        critical_policy=critical_policy,
        penalty_factor=penalty_factor,
        ahp_weight=ahp_weight,
        intervention_class=InterventionClass.MITIGABLE,
        doc_source="test",
        technical_notes=None,
    )


def _phase(name: str = "establecimiento", sequence_order: int = 1) -> PhenologicalPhase:
    return PhenologicalPhase(
        id=uuid4(),
        name=name,
        duration_days=30,
        sequence_order=sequence_order,
    )


def _requirement(criterion: Criterion, phase: PhenologicalPhase, period_key: str = "2025-01") -> PhaseRequirement:
    return PhaseRequirement(
        id=uuid4(),
        criterion_id=criterion.id,
        phase_id=phase.id,
        membership_fn=MembershipFunction(
            function_type="TRAPEZOIDAL",
            a=3000.0, b=4000.0, c=8000.0, d=10000.0,
        ),
        phase_weight=1.0,
        temporal_periods=[TemporalPeriod(period_key=period_key, temporal_weight=1.0)],
        extraction_binding=ExtractionBinding(
            variable_name="nir_reflectancia",
            dataset_key="COPERNICUS/S2",
            band="B8",
            unit="reflectancia",
            temporal_resolution="16d",
            spatial_resolution=None,
            scale=30.0,
            reducer="mean",
            aggregation_method="mean",
            quality_mask=None,
            fallback_allowed=False,
        ),
    )


def _rulebook(
    crop_id: str,
    criteria: list[Criterion],
    phases: list[PhenologicalPhase],
    requirements: list[PhaseRequirement],
) -> Rulebook:
    return Rulebook(
        id=uuid4(),
        crop_id=crop_id,
        version=1,
        status=RulebookStatus.ACTIVE,
        criteria=criteria,
        phases=phases,
        phase_requirements=requirements,
    )


# ─── Tests: critical_policy mapping ───────────────────────────────────────────


def test_non_critical_criterion_maps_to_empty_critical_policy() -> None:
    """Non-critical criteria must get '' (not 'PENALIZE') in EvaluationCriterionSpec."""
    criterion = _criterion(is_critical=False, critical_policy=None, penalty_factor=None)
    phase = _phase()
    req = _requirement(criterion, phase)
    rb = _rulebook("demo_maiz", [criterion], [phase], [req])

    data = _rulebook_to_evaluation_data(rb)

    assert len(data.criteria) == 1
    spec = data.criteria[0]
    assert spec.critical_policy == "", (
        f"Non-critical criterion must map to critical_policy='', got {spec.critical_policy!r}. "
        "A value of 'PENALIZE' would cause 'penalty_factor is required' errors when membership=0.0."
    )
    assert spec.penalty_factor is None


def test_penalize_criterion_preserves_policy_and_penalty_factor() -> None:
    criterion = _criterion(
        is_critical=True,
        critical_policy=CriticalPolicy.PENALIZE,
        penalty_factor=0.5,
    )
    phase = _phase()
    req = _requirement(criterion, phase)
    rb = _rulebook("demo_papa", [criterion], [phase], [req])

    data = _rulebook_to_evaluation_data(rb)
    spec = data.criteria[0]

    assert spec.critical_policy == EvalCriticalPolicy.PENALIZE.value
    assert spec.penalty_factor == pytest.approx(0.5)


def test_no_viable_criterion_preserves_policy_and_has_no_penalty_factor() -> None:
    criterion = _criterion(
        is_critical=True,
        critical_policy=CriticalPolicy.NO_VIABLE,
        penalty_factor=None,
    )
    phase = _phase()
    req = _requirement(criterion, phase)
    rb = _rulebook("demo_arandano", [criterion], [phase], [req])

    data = _rulebook_to_evaluation_data(rb)
    spec = data.criteria[0]

    assert spec.critical_policy == EvalCriticalPolicy.NO_VIABLE.value
    assert spec.penalty_factor is None


def test_mixed_criteria_all_get_correct_policies() -> None:
    """Five criteria: one PENALIZE, one NO_VIABLE, three non-critical."""
    penalize_c = _criterion("estres_hidrico", is_critical=True, critical_policy=CriticalPolicy.PENALIZE, penalty_factor=0.4, ahp_weight=0.25)
    no_viable_c = _criterion("vegetacion_vigor", is_critical=True, critical_policy=CriticalPolicy.NO_VIABLE, penalty_factor=None, ahp_weight=0.35)
    non_c1 = _criterion("humedad_superficial", is_critical=False, critical_policy=None, penalty_factor=None, ahp_weight=0.20)
    non_c2 = _criterion("estabilidad_fenologica", is_critical=False, critical_policy=None, penalty_factor=None, ahp_weight=0.12)
    non_c3 = _criterion("aptitud_general", is_critical=False, critical_policy=None, penalty_factor=None, ahp_weight=0.08)

    phase = _phase()
    criteria = [penalize_c, no_viable_c, non_c1, non_c2, non_c3]
    requirements = [_requirement(c, phase, period_key=f"2025-0{i+1}") for i, c in enumerate(criteria)]
    rb = _rulebook("demo_quinua", criteria, [phase], requirements)

    data = _rulebook_to_evaluation_data(rb)
    policies_by_name = {spec.criterion_id: spec.critical_policy for spec in data.criteria}
    penalties_by_name = {spec.criterion_id: spec.penalty_factor for spec in data.criteria}

    assert policies_by_name[str(penalize_c.id)] == "PENALIZE"
    assert penalties_by_name[str(penalize_c.id)] == pytest.approx(0.4)

    assert policies_by_name[str(no_viable_c.id)] == "NO_VIABLE"
    assert penalties_by_name[str(no_viable_c.id)] is None

    for non_c in [non_c1, non_c2, non_c3]:
        assert policies_by_name[str(non_c.id)] == "", (
            f"Non-critical criterion {non_c.name} must map to '', got {policies_by_name[str(non_c.id)]!r}"
        )
        assert penalties_by_name[str(non_c.id)] is None


# ─── Integration: non-critical zero-membership does NOT raise ─────────────────


def test_non_critical_zero_membership_does_not_raise_policy_error() -> None:
    """Regression: a non-critical criterion with membership=0.0 must not raise
    'penalty_factor is required for PENALIZE policy'.

    This is the exact failure mode that brought down the E2E demo when GEE data
    produced a zero membership for a non-critical criterion that was incorrectly
    mapped to critical_policy='PENALIZE' with penalty_factor=None.
    """
    criterion = _criterion(is_critical=False, critical_policy=None, penalty_factor=None, ahp_weight=1.0)
    phase = _phase()
    req = _requirement(criterion, phase)
    rb = _rulebook("demo_maiz", [criterion], [phase], [req])

    data = _rulebook_to_evaluation_data(rb)

    evaluation_id = uuid4()
    command = ExecuteEvaluationCommand(
        evaluation_id=evaluation_id,
        extraction_result={"crop_candidates": ["demo_maiz"]},
    )
    # Value of -999.0 is well outside the trapezoid [3000, 4000, 8000, 10000]
    # so membership will be 0.0 — simulating what GEE might return.
    vector = AgroenvVectorData(
        evaluation_id=evaluation_id,
        parcel_id=uuid4(),
        variables=[
            AgroenvVariableData(
                variable_name="nir_reflectancia",
                criterion_id=str(criterion.id),
                crop_id="demo_maiz",
                phase_id=str(phase.id),
                period_key="2025-01",
                value=-999.0,
                unit="reflectancia",
                status="OK",
                dataset_key="COPERNICUS/S2",
                band="B8",
                source="stub",
            )
        ],
    )
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )

    # This must NOT raise EvaluationDomainError("penalty_factor is required for PENALIZE policy")
    evaluation = PureMcdaEvaluationEngine().evaluate(command, vector, [data], settings)
    assert len(evaluation.crop_results) == 1
    result = evaluation.crop_results[0]
    # No critical policy → no limiting factor triggered
    assert result.limiting_factors == []


def test_penalize_criterion_with_penalty_factor_applies_correctly_with_zero_membership() -> None:
    """PENALIZE criterion with penalty_factor=0.5 and zero membership reduces score."""
    criterion = _criterion(
        name="estres_hidrico",
        is_critical=True,
        critical_policy=CriticalPolicy.PENALIZE,
        penalty_factor=0.5,
        ahp_weight=1.0,
    )
    phase = _phase()
    req = _requirement(criterion, phase)
    rb = _rulebook("demo_papa", [criterion], [phase], [req])
    data = _rulebook_to_evaluation_data(rb)

    evaluation_id = uuid4()
    command = ExecuteEvaluationCommand(
        evaluation_id=evaluation_id,
        extraction_result={"crop_candidates": ["demo_papa"]},
    )
    # Zero membership → PENALIZE fires
    vector = AgroenvVectorData(
        evaluation_id=evaluation_id,
        parcel_id=uuid4(),
        variables=[
            AgroenvVariableData(
                variable_name="nir_reflectancia",
                criterion_id=str(criterion.id),
                crop_id="demo_papa",
                phase_id=str(phase.id),
                period_key="2025-01",
                value=-999.0,
                unit="reflectancia",
                status="OK",
                dataset_key="COPERNICUS/S2",
                band="B8",
                source="stub",
            )
        ],
    )
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )

    evaluation = PureMcdaEvaluationEngine().evaluate(command, vector, [data], settings)
    result = evaluation.crop_results[0]

    assert len(result.limiting_factors) == 1
    assert result.limiting_factors[0].policy == EvalCriticalPolicy.PENALIZE
    assert result.limiting_factors[0].penalty_factor == pytest.approx(0.5)
    # score = penalize_epsilon * penalty_factor = 0.01 * 0.5 = 0.005
    assert result.score == pytest.approx(0.005)


def test_multi_crop_with_diagnostic_like_profiles_does_not_raise() -> None:
    """Simulate demo_papa, demo_quinua, demo_palta, demo_maiz, demo_arandano
    with real diagnostic profiles where non-critical criteria can reach 0.0 membership."""
    _PENALTY_SPECS: dict[str, tuple[CriticalPolicy, float | None]] = {
        "demo_papa": (CriticalPolicy.PENALIZE, 0.50),
        "demo_quinua": (CriticalPolicy.PENALIZE, 0.40),
        "demo_palta": (CriticalPolicy.PENALIZE, 0.30),
        "demo_arandano": (CriticalPolicy.NO_VIABLE, None),
    }
    _CRITERION_NAMES = [
        "vegetacion_vigor",
        "estres_hidrico",
        "humedad_superficial",
        "estabilidad_fenologica",
        "aptitud_general",
    ]
    _AHP_WEIGHTS = [0.35, 0.25, 0.20, 0.12, 0.08]
    crops = ["demo_papa", "demo_quinua", "demo_palta", "demo_maiz", "demo_arandano"]

    evaluation_id = uuid4()
    command = ExecuteEvaluationCommand(
        evaluation_id=evaluation_id,
        extraction_result={"crop_candidates": crops},
    )
    settings = McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )

    all_rulebooks = []
    all_variables = []

    for crop_id in crops:
        phase = _phase()
        criteria = []
        requirements = []
        for cname, w in zip(_CRITERION_NAMES, _AHP_WEIGHTS):
            is_crit = crop_id in _PENALTY_SPECS and cname == "estres_hidrico" or (
                crop_id == "demo_arandano" and cname == "vegetacion_vigor"
            )
            if is_crit and crop_id in _PENALTY_SPECS:
                policy, pf = _PENALTY_SPECS[crop_id]
                if cname == "vegetacion_vigor" and crop_id == "demo_arandano":
                    policy, pf = CriticalPolicy.NO_VIABLE, None
                elif cname != "estres_hidrico":
                    is_crit = False
                    policy, pf = None, None
            else:
                policy, pf = None, None
            c = _criterion(cname, is_critical=is_crit, critical_policy=policy if is_crit else None, penalty_factor=pf, ahp_weight=w)
            criteria.append(c)
            req = _requirement(c, phase)
            requirements.append(req)
            # Use a value well outside the trapezoid to force 0.0 membership
            all_variables.append(
                AgroenvVariableData(
                    variable_name="nir_reflectancia",
                    criterion_id=str(c.id),
                    crop_id=crop_id,
                    phase_id=str(phase.id),
                    period_key="2025-01",
                    value=-999.0,
                    unit="reflectancia",
                    status="OK",
                    dataset_key="COPERNICUS/S2",
                    band="B8",
                    source="stub",
                )
            )
        rb = _rulebook(crop_id, criteria, [phase], requirements)
        all_rulebooks.append(_rulebook_to_evaluation_data(rb))

    vector = AgroenvVectorData(
        evaluation_id=evaluation_id,
        parcel_id=uuid4(),
        variables=all_variables,
    )

    # Must not raise — this was the error seen in the E2E demo trace
    evaluation = PureMcdaEvaluationEngine().evaluate(command, vector, all_rulebooks, settings)
    assert len(evaluation.crop_results) == 5
