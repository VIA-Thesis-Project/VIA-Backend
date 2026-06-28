"""Unit tests for Rulebook Management domain rules."""

from __future__ import annotations

import uuid

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
    RulebookValidationError,
    TemporalPeriod,
)


def test_membership_function_belongs_to_phase_requirement_not_criterion() -> None:
    criterion = _criterion(ahp_weight=1.0)
    requirement = _requirement(criterion.id, uuid.uuid4())

    assert not hasattr(criterion, "membership_fn")
    assert requirement.membership_fn == MembershipFunction(a=0, b=1, c=2, d=3)


@pytest.mark.parametrize("points", [(2, 1, 3, 4), (1, 3, 2, 4), (1, 2, 4, 3)])
def test_trapezoid_must_be_ordered(points: tuple[int, int, int, int]) -> None:
    with pytest.raises(RulebookValidationError):
        MembershipFunction(a=points[0], b=points[1], c=points[2], d=points[3])


def test_critical_policy_must_be_approved_value() -> None:
    with pytest.raises(RulebookValidationError):
        Criterion(
            id=uuid.uuid4(),
            name="Suelo",
            is_critical=True,
            critical_policy="BLOCK",  # type: ignore[arg-type]
            penalty_factor=None,
            ahp_weight=1.0,
            intervention_class=InterventionClass.MITIGABLE,
        )


def test_penalty_factor_is_required_and_bounded_when_policy_penalize() -> None:
    with pytest.raises(RulebookValidationError):
        _criterion(is_critical=True, critical_policy=CriticalPolicy.PENALIZE, penalty_factor=None)

    with pytest.raises(RulebookValidationError):
        _criterion(is_critical=True, critical_policy=CriticalPolicy.PENALIZE, penalty_factor=1.5)


def test_rulebook_validates_ahp_phase_and_temporal_weight_sums() -> None:
    criterion_one = _criterion(ahp_weight=0.4)
    criterion_two = _criterion(ahp_weight=0.6)
    phase_one = _phase(sequence_order=1)
    phase_two = _phase(sequence_order=2)
    rulebook = Rulebook(
        id=uuid.uuid4(),
        crop_id="cacao",
        version=1,
        status=RulebookStatus.DRAFT,
        criteria=[criterion_one, criterion_two],
        phases=[phase_one, phase_two],
        phase_requirements=[
            _requirement(criterion_one.id, phase_one.id, phase_weight=0.25),
            _requirement(criterion_one.id, phase_two.id, phase_weight=0.75),
            _requirement(criterion_two.id, phase_one.id, phase_weight=0.5),
            _requirement(criterion_two.id, phase_two.id, phase_weight=0.5),
        ],
    )

    rulebook.validate(0.001)


def test_rulebook_rejects_invalid_weight_sums() -> None:
    criterion = _criterion(ahp_weight=0.8)
    phase = _phase()
    rulebook = Rulebook(
        id=uuid.uuid4(),
        crop_id="cacao",
        version=1,
        status=RulebookStatus.DRAFT,
        criteria=[criterion],
        phases=[phase],
        phase_requirements=[_requirement(criterion.id, phase.id)],
    )

    with pytest.raises(RulebookValidationError, match="ahp"):
        rulebook.validate(0.001)


def test_validate_semantic_passes_for_riesgo_frio_with_cold_induction_trapezoid() -> None:
    criterion = Criterion(uuid.uuid4(), "riesgo_frio", False, None, None, 1.0, InterventionClass.MITIGABLE)
    phase = PhenologicalPhase(uuid.uuid4(), "induccion_floral", 30, 1)
    rulebook = Rulebook(
        id=uuid.uuid4(),
        crop_id="mandarina_murcott",
        version=1,
        status=RulebookStatus.DRAFT,
        criteria=[criterion],
        phases=[phase],
        phase_requirements=[_requirement(criterion.id, phase.id, membership_fn=MembershipFunction(a=4, b=8, c=15, d=22))],
    )

    rulebook.validate_semantic()  # must not raise


def test_validate_semantic_rejects_riesgo_frio_with_warm_induction_trapezoid() -> None:
    criterion = Criterion(uuid.uuid4(), "riesgo_frio", False, None, None, 1.0, InterventionClass.MITIGABLE)
    phase = PhenologicalPhase(uuid.uuid4(), "induccion_floral", 30, 1)
    rulebook = Rulebook(
        id=uuid.uuid4(),
        crop_id="mandarina_murcott",
        version=1,
        status=RulebookStatus.DRAFT,
        criteria=[criterion],
        phases=[phase],
        phase_requirements=[_requirement(criterion.id, phase.id, membership_fn=MembershipFunction(a=10, b=14, c=20, d=26))],
    )

    with pytest.raises(RulebookValidationError, match="induccion"):
        rulebook.validate_semantic()


def _criterion(
    ahp_weight: float = 1.0,
    is_critical: bool = False,
    critical_policy: CriticalPolicy | None = None,
    penalty_factor: float | None = None,
) -> Criterion:
    return Criterion(uuid.uuid4(), "Clima", is_critical, critical_policy, penalty_factor, ahp_weight, InterventionClass.MITIGABLE)


def _phase(sequence_order: int = 1) -> PhenologicalPhase:
    return PhenologicalPhase(uuid.uuid4(), f"Fase {sequence_order}", 30, sequence_order)


def _requirement(
    criterion_id: uuid.UUID,
    phase_id: uuid.UUID,
    phase_weight: float = 1.0,
    membership_fn: MembershipFunction | None = None,
) -> PhaseRequirement:
    return PhaseRequirement(
        id=uuid.uuid4(),
        criterion_id=criterion_id,
        phase_id=phase_id,
        membership_fn=membership_fn or MembershipFunction(a=0, b=1, c=2, d=3),
        phase_weight=phase_weight,
        temporal_periods=[TemporalPeriod("mensual", 1.0)],
        extraction_binding=ExtractionBinding("ndvi", "sentinel-2", "B08", "index", "monthly"),
    )
