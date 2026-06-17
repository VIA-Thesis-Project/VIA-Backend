"""Agroenvironmental vector aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError, TemporalWindow
from via.bounded_contexts.agroenv_extraction.domain.variable_entry import VariableEntry


@dataclass(frozen=True)
class AgroenvVector:
    """Aggregate containing all extracted variables for one evaluation."""

    evaluation_id: UUID
    parcel_id: UUID
    temporal_window: TemporalWindow
    variables: list[VariableEntry]
    id: UUID = field(default_factory=uuid4)
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate vector completeness."""

        if not self.variables:
            raise AgroenvExtractionError("agroenv vector requires at least one variable entry")

    def to_event_payload(self) -> dict[str, Any]:
        """Serialize vector summary for the saga event."""

        return {
            "evaluation_id": str(self.evaluation_id),
            "parcel_id": str(self.parcel_id),
            "vector_id": str(self.id),
            "temporal_window": self.temporal_window.to_mapping(),
            "variables": [entry.to_payload() for entry in self.variables],
            "extracted_at": self.extracted_at.isoformat(),
        }
