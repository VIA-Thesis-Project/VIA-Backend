"""Command contracts emitted by the evaluation Process Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


INICIAR_EXTRACCION_AGROAMBIENTAL = "IniciarExtraccionAgroambiental"
EJECUTAR_EVALUACION_VIABILIDAD = "EjecutarEvaluacionViabilidad"
GENERAR_RECOMENDACION_SUSTENTADA = "GenerarRecomendacionSustentada"
GENERAR_RECOMENDACION_SOLICITADA = "GenerarRecomendacionSolicitada"


@dataclass(frozen=True)
class IniciarExtraccionAgroambiental:
    """Command payload for the agro-environmental extraction bounded context."""

    evaluation_id: UUID
    parcel_id: UUID
    parcel_geometry: dict[str, Any]
    crop_candidates: list[str]
    temporal_window: dict[str, Any]
    required_extraction_spec: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Serialize the command as JSON-compatible data."""

        return {
            "evaluation_id": str(self.evaluation_id),
            "parcel_id": str(self.parcel_id),
            "parcel_geometry": self.parcel_geometry,
            "crop_candidates": self.crop_candidates,
            "temporal_window": self.temporal_window,
            "required_extraction_spec": self.required_extraction_spec,
        }


@dataclass(frozen=True)
class EjecutarEvaluacionViabilidad:
    """Command payload for the viability evaluation bounded context."""

    evaluation_id: UUID
    extraction_result: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Serialize the command as JSON-compatible data."""

        return {"evaluation_id": str(self.evaluation_id), "extraction_result": self.extraction_result}


@dataclass(frozen=True)
class GenerarRecomendacionSustentada:
    """Command payload for the recommendation bounded context."""

    evaluation_id: UUID
    evaluation_result: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Serialize the command as JSON-compatible data."""

        return {"evaluation_id": str(self.evaluation_id), "evaluation_result": self.evaluation_result}


@dataclass(frozen=True)
class GenerarRecomendacionSolicitada:
    """Command payload for the recommendation bounded context."""

    evaluation_id: UUID
    parcel_id: UUID | None = None
    crop_id: str | None = None
    max_fragments: int = 8

    def to_payload(self) -> dict[str, Any]:
        """Serialize the command as JSON-compatible data."""

        return {
            "evaluation_id": str(self.evaluation_id),
            "parcel_id": str(self.parcel_id) if self.parcel_id is not None else None,
            "crop_id": self.crop_id,
            "max_fragments": self.max_fragments,
        }
