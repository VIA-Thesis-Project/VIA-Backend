"""Rulebook aggregate for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    InterventionClass,
    RulebookStatus,
    RulebookValidationError,
    validate_weight_sum,
)


_COLD_INDUCTION_MAX_C: float = 18.0


@dataclass
class Rulebook:
    """Versioned set of criteria and phase requirements for one crop."""

    id: UUID
    crop_id: str
    version: int
    status: RulebookStatus
    criteria: list[Criterion]
    phases: list[PhenologicalPhase]
    phase_requirements: list[PhaseRequirement]

    def __post_init__(self) -> None:
        """Validate identity and version data."""

        if not self.crop_id.strip():
            raise RulebookValidationError("crop_id must not be empty")
        if self.version <= 0:
            raise RulebookValidationError("rulebook version must be positive")
        if not isinstance(self.status, RulebookStatus):
            raise RulebookValidationError("rulebook status is invalid")

    def validate(self, weight_tolerance: float) -> None:
        """Validate aggregate consistency and approved weight sums."""

        if not self.criteria:
            raise RulebookValidationError("rulebook requires at least one criterion")
        if not self.phases:
            raise RulebookValidationError("rulebook requires at least one phase")
        if not self.phase_requirements:
            raise RulebookValidationError("rulebook requires phase requirements")

        for criterion in self.criteria:
            if not isinstance(criterion.intervention_class, InterventionClass):
                raise RulebookValidationError(
                    f"criterion '{criterion.name}' is missing a valid intervention_class"
                )

        criterion_ids = {criterion.id for criterion in self.criteria}
        phase_ids = {phase.id for phase in self.phases}
        validate_weight_sum([criterion.ahp_weight for criterion in self.criteria], "ahp", weight_tolerance)

        requirements_by_criterion: dict[UUID, list[PhaseRequirement]] = {criterion_id: [] for criterion_id in criterion_ids}
        for requirement in self.phase_requirements:
            if requirement.criterion_id not in criterion_ids:
                raise RulebookValidationError("phase requirement references unknown criterion")
            if requirement.phase_id not in phase_ids:
                raise RulebookValidationError("phase requirement references unknown phase")
            requirements_by_criterion[requirement.criterion_id].append(requirement)
            validate_weight_sum(
                [period.temporal_weight for period in requirement.temporal_periods],
                "temporal",
                weight_tolerance,
            )

        for criterion_id, requirements in requirements_by_criterion.items():
            if not requirements:
                raise RulebookValidationError(f"criterion {criterion_id} has no phase requirements")
            validate_weight_sum([requirement.phase_weight for requirement in requirements], "phase", weight_tolerance)

    def validate_semantic(self) -> None:
        """Check semantic coherence between criterion names, phases, and membership functions.

        Invariant: riesgo_frio in any induction phase must model cold temperatures as optimal
        (c <= _COLD_INDUCTION_MAX_C), enforcing the inverted trapezoid design for cold induction.
        """
        for criterion in self.criteria:
            if "riesgo_frio" not in criterion.name.lower():
                continue
            for requirement in self.phase_requirements:
                if requirement.criterion_id != criterion.id:
                    continue
                phase = next((p for p in self.phases if p.id == requirement.phase_id), None)
                if phase is None or "induccion" not in phase.name.lower():
                    continue
                if requirement.membership_fn.c > _COLD_INDUCTION_MAX_C:
                    raise RulebookValidationError(
                        f"Criterio '{criterion.name}' en fase '{phase.name}': "
                        f"c={requirement.membership_fn.c}°C excede el limite fisiologico "
                        f"de induccion por frio ({_COLD_INDUCTION_MAX_C}°C). "
                        "El trapecio debe modelar temperaturas nocturnas bajas como optimo."
                    )

    def publish(self) -> None:
        """Mark this version as active."""

        self.status = RulebookStatus.ACTIVE

    def deactivate(self) -> None:
        """Mark this version as inactive."""

        self.status = RulebookStatus.INACTIVE
