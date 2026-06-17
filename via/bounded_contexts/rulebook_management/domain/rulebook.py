"""Rulebook aggregate for Rulebook Management."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.value_objects import (
    RulebookStatus,
    RulebookValidationError,
    validate_weight_sum,
)


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

    def publish(self) -> None:
        """Mark this version as active."""

        self.status = RulebookStatus.ACTIVE

    def deactivate(self) -> None:
        """Mark this version as inactive."""

        self.status = RulebookStatus.INACTIVE
