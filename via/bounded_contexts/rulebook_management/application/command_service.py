"""Command services for Rulebook Management."""

from __future__ import annotations

import uuid

from via.bounded_contexts.rulebook_management.application.exceptions import RulebookNotFoundError
from via.bounded_contexts.rulebook_management.application.ports import IRulebookRepository, IRulebookUnitOfWork
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import RulebookStatus


class RulebookCommandService:
    """Coordinate creation and publication of rulebook versions."""

    def __init__(
        self,
        repository: IRulebookRepository | None = None,
        unit_of_work: IRulebookUnitOfWork | None = None,
        weight_tolerance: float = 0.001,
    ) -> None:
        if repository is None and unit_of_work is None:
            raise ValueError("repository or unit_of_work is required")
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._weight_tolerance = weight_tolerance

    def create_rulebook(
        self,
        crop_id: str,
        criteria: list[Criterion],
        phases: list[PhenologicalPhase],
        phase_requirements: list[PhaseRequirement],
    ) -> Rulebook:
        """Create a draft rulebook version with precalculated weights."""

        if self._unit_of_work is not None:
            with self._unit_of_work as uow:
                rulebook = self._build_rulebook(crop_id, criteria, phases, phase_requirements, uow.rulebooks)
                uow.rulebooks.add(rulebook)
                uow.commit()
                return rulebook

        repository = self._require_repository()
        rulebook = self._build_rulebook(crop_id, criteria, phases, phase_requirements, repository)
        repository.add(rulebook)
        return rulebook

    def publish_rulebook(self, rulebook_id: uuid.UUID) -> Rulebook:
        """Activate one rulebook and deactivate the previous active version in the same transaction."""

        if self._unit_of_work is not None:
            with self._unit_of_work as uow:
                rulebook = self._load_rulebook(uow.rulebooks, rulebook_id)
                uow.rulebooks.deactivate_active_for_crop(rulebook.crop_id)
                rulebook.publish()
                uow.rulebooks.save(rulebook)
                uow.commit()
                return rulebook

        repository = self._require_repository()
        rulebook = self._load_rulebook(repository, rulebook_id)
        repository.deactivate_active_for_crop(rulebook.crop_id)
        rulebook.publish()
        repository.save(rulebook)
        return rulebook

    def _build_rulebook(self, crop_id: str, criteria: list[Criterion], phases: list[PhenologicalPhase], phase_requirements: list[PhaseRequirement], repository: IRulebookRepository) -> Rulebook:
        rulebook = Rulebook(uuid.uuid4(), crop_id, repository.next_version_for_crop(crop_id), RulebookStatus.DRAFT, criteria, phases, phase_requirements)
        rulebook.validate(self._weight_tolerance)
        return rulebook

    def _load_rulebook(self, repository: IRulebookRepository, rulebook_id: uuid.UUID) -> Rulebook:
        rulebook = repository.get_by_id(rulebook_id)
        if rulebook is None:
            raise RulebookNotFoundError("Rulebook not found")
        return rulebook

    def _require_repository(self) -> IRulebookRepository:
        if self._repository is None:
            raise RuntimeError("Rulebook repository is not configured")
        return self._repository
