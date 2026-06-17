"""Agroenvironmental vector ACL adapter for viability evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from via.bounded_contexts.viability_evaluation.application.ports import AgroenvVariableData, AgroenvVectorData


class AgroenvVectorAclAdapter:
    """Translate agroenvironmental vector data into evaluation DTOs."""

    def __init__(self, read_source: Callable[[UUID], Mapping[str, Any]]) -> None:
        """Store the vector read source used by the adapter."""

        self._read_source = read_source

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Return generated vector data translated to evaluation-facing DTOs."""

        raw_vector = self._read_source(evaluation_id)
        return AgroenvVectorData(
            evaluation_id=UUID(str(raw_vector["evaluation_id"])),
            parcel_id=UUID(str(raw_vector["parcel_id"])),
            variables=[_variable_from_mapping(item) for item in raw_vector.get("variables", [])],
        )


def _variable_from_mapping(item: Mapping[str, Any]) -> AgroenvVariableData:
    """Build one evaluation variable DTO from generic vector data."""

    return AgroenvVariableData(
        variable_name=str(item["variable_name"]),
        criterion_id=str(item["criterion_id"]),
        crop_id=str(item["crop_id"]),
        phase_id=str(item["phase_id"]),
        period_key=str(item["period_key"]),
        value=None if item.get("value") is None else float(item["value"]),
        unit=str(item["unit"]),
        status=str(item["status"]),
        dataset_key=str(item["dataset_key"]),
        band=str(item["band"]),
        source=str(item["source"]),
    )
