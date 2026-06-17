"""Evaluation saga states and allowed transitions."""

from __future__ import annotations

from enum import StrEnum


class EvaluationSagaStatus(StrEnum):
    """Lifecycle states coordinated by the evaluation Process Manager."""

    INICIADA = "INICIADA"
    EXTRACCION_COMPLETADA = "EXTRACCION_COMPLETADA"
    EVALUACION_COMPLETADA = "EVALUACION_COMPLETADA"
    RECOMENDACION_COMPLETADA = "RECOMENDACION_COMPLETADA"
    FALLIDA = "FALLIDA"


VALID_TRANSITIONS: dict[str, set[str]] = {
    EvaluationSagaStatus.INICIADA.value: {EvaluationSagaStatus.EXTRACCION_COMPLETADA.value, EvaluationSagaStatus.FALLIDA.value},
    EvaluationSagaStatus.EXTRACCION_COMPLETADA.value: {
        EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
        EvaluationSagaStatus.FALLIDA.value,
    },
    EvaluationSagaStatus.EVALUACION_COMPLETADA.value: {
        EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value,
        EvaluationSagaStatus.FALLIDA.value,
    },
    EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value: {EvaluationSagaStatus.FALLIDA.value},
    EvaluationSagaStatus.FALLIDA.value: set(),
}


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """Return whether a saga can move between the supplied states."""

    return to_status in VALID_TRANSITIONS.get(from_status, set())
