"""Query services and read models for Rulebook Management."""

from __future__ import annotations

from typing import Any

from via.bounded_contexts.rulebook_management.application.exceptions import ActiveRulebookNotFoundError
from via.bounded_contexts.rulebook_management.application.ports import IRulebookRepository
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.shared.orchestration.evaluation_process_manager.ports import (
    RequiredExtractionSpec,
    RequiredVariableForEvaluation,
)


class RulebookQueryService:
    """Serve rulebook reads and the required extraction read model."""

    def __init__(self, repository: IRulebookRepository) -> None:
        self._repository = repository

    def list_rulebooks(self) -> list[Rulebook]:
        """Return all rulebook versions."""

        return self._repository.list_all()

    def get_active_rulebook(self, crop_id: str) -> Rulebook:
        """Return the active rulebook for one crop."""

        rulebook = self._repository.get_active_by_crop(crop_id)
        if rulebook is None:
            raise ActiveRulebookNotFoundError("Active rulebook not found")
        return rulebook

    def get_required_extraction_spec(
        self,
        crop_candidates: list[str],
        temporal_window: dict[str, Any],
    ) -> RequiredExtractionSpec:
        """Project active rulebooks into RequiredExtractionSpec without exposing ORM."""

        variables: list[RequiredVariableForEvaluation] = []
        for crop_id in crop_candidates:
            active_rulebook = self._repository.get_active_by_crop(crop_id)
            if active_rulebook is None:
                continue
            variables.extend(self._variables_for_rulebook(active_rulebook, temporal_window))
        return RequiredExtractionSpec(variables=variables)

    def _variables_for_rulebook(
        self,
        rulebook: Rulebook,
        temporal_window: dict[str, Any],
    ) -> list[RequiredVariableForEvaluation]:
        criteria_by_id: dict[str, Criterion] = {str(criterion.id): criterion for criterion in rulebook.criteria}
        variables: list[RequiredVariableForEvaluation] = []

        for requirement in rulebook.phase_requirements:
            criterion = criteria_by_id[str(requirement.criterion_id)]
            binding = requirement.extraction_binding
            variables.append(
                RequiredVariableForEvaluation(
                    variable_name=binding.variable_name,
                    criterion_id=str(criterion.id),
                    crop_id=rulebook.crop_id,
                    phase_id=str(requirement.phase_id),
                    dataset_key=binding.dataset_key,
                    band=binding.band,
                    unit=binding.unit,
                    temporal_resolution=binding.temporal_resolution,
                    spatial_resolution=binding.spatial_resolution,
                    scale=binding.scale,
                    reducer=binding.reducer,
                    aggregation_method=binding.aggregation_method,
                    temporal_window=temporal_window,
                    temporal_periods=requirement.temporal_period_payload(),
                    quality_mask=binding.quality_mask,
                    fallback_allowed=binding.fallback_allowed,
                )
            )
        return variables
