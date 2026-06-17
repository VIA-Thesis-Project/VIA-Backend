"""Value objects for Agroenvironmental Extraction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AgroenvExtractionError(ValueError):
    """Raised when agroenvironmental extraction data is invalid."""


class VariableStatus(StrEnum):
    """Allowed extraction status for one variable entry."""

    OK = "OK"
    CRITERIO_FALTANTE = "CRITERIO_FALTANTE"


@dataclass(frozen=True)
class TemporalWindow:
    """Temporal window requested for extraction."""

    data: dict[str, Any]

    def __post_init__(self) -> None:
        """Validate temporal window payload shape."""

        if not isinstance(self.data, dict) or not self.data:
            raise AgroenvExtractionError("temporal_window must be a non-empty mapping")

    def to_mapping(self) -> dict[str, Any]:
        """Serialize the temporal window."""

        return dict(self.data)
