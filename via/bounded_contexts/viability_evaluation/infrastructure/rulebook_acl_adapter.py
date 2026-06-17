"""Rulebook ACL adapter for viability evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

from via.bounded_contexts.viability_evaluation.application.ports import EvaluationCriterionSpec, RulebookEvaluationData


class RulebookAclAdapter:
    """Translate rulebook read data into viability-evaluation DTOs."""

    def __init__(self, read_source: Callable[[str], Mapping[str, Any]]) -> None:
        """Store the rulebook read source used by the adapter."""

        self._read_source = read_source

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        """Return active rulebook data translated to evaluation-facing DTOs."""

        raw_rulebook = self._read_source(crop_id)
        criteria = [_criterion_from_mapping(item) for item in raw_rulebook.get("criteria", [])]
        return RulebookEvaluationData(
            crop_id=str(raw_rulebook["crop_id"]),
            rulebook_id=UUID(str(raw_rulebook["rulebook_id"])),
            version=int(raw_rulebook["version"]),
            criteria=criteria,
        )


def _criterion_from_mapping(item: Mapping[str, Any]) -> EvaluationCriterionSpec:
    """Build one evaluation criterion DTO from generic rulebook data."""

    temporal_periods = item.get("temporal_periods", [])
    if not isinstance(temporal_periods, Sequence) or isinstance(temporal_periods, (str, bytes)):
        temporal_periods = []
    return EvaluationCriterionSpec(
        criterion_id=str(item["criterion_id"]),
        crop_id=str(item["crop_id"]),
        phase_id=str(item["phase_id"]),
        variable_name=str(item["variable_name"]),
        w_ahp=float(item["w_ahp"]),
        phase_weight=float(item["phase_weight"]),
        temporal_periods=[dict(period) for period in temporal_periods],
        membership_fn=dict(item["membership_fn"]),
        critical_policy=str(item["critical_policy"]),
        penalty_factor=None if item.get("penalty_factor") is None else float(item["penalty_factor"]),
        doc_source=None if item.get("doc_source") is None else str(item["doc_source"]),
    )
