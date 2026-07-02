"""Query service for viability evaluation state and persisted MCDA results."""

from __future__ import annotations

from uuid import UUID

from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVectorReadModel,
    CropResultReadModel,
    EvaluationMcdaResultReadModel,
    EvaluationStatusReadModel,
    GapReadModel,
    IEvaluationQueryPort,
    LimitingFactorReadModel,
)
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


MCDA_READY_STATUSES: frozenset[str] = frozenset({
    EvaluationSagaStatus.EVALUACION_COMPLETADA.value,
    EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value,
})

# Re-export read models so existing callers of query_service keep working.
__all__ = [
    "MCDA_READY_STATUSES",
    "AgroenvVectorReadModel",
    "CropResultReadModel",
    "EvaluationMcdaResultReadModel",
    "EvaluationStatusReadModel",
    "EvaluationQueryService",
    "GapReadModel",
    "IEvaluationQueryPort",
    "LimitingFactorReadModel",
]


class EvaluationQueryService:
    """Read-only service for evaluation status and persisted MCDA results.

    Delegates all persistence reads to IEvaluationQueryPort; does not import
    ORM models, SQLAlchemy, or any infrastructure module.
    Does not recalculate scores, memberships, weights, ranking, or gaps.
    """

    def __init__(self, query_port: IEvaluationQueryPort) -> None:
        """Create query service with an injected persistence port."""

        self._port = query_port

    def get_evaluation_status(self, evaluation_id: UUID) -> EvaluationStatusReadModel | None:
        """Return the current saga status snapshot, or None when not found."""

        snapshot = self._port.find_saga_snapshot(evaluation_id)
        if snapshot is None:
            return None
        return EvaluationStatusReadModel(
            evaluation_id=evaluation_id,
            status=snapshot.status,
            current_phase=snapshot.status,
            last_transition=snapshot.last_transition,
            failure_reason=snapshot.failure_reason,
        )

    def get_mcda_result(self, evaluation_id: UUID) -> EvaluationMcdaResultReadModel | None:
        """Return persisted MCDA results, or a status-only model when not ready."""

        snapshot = self._port.find_saga_snapshot(evaluation_id)
        if snapshot is None:
            return None

        if snapshot.status not in MCDA_READY_STATUSES:
            return EvaluationMcdaResultReadModel(
                evaluation_id=evaluation_id,
                status=snapshot.status,
                failure_reason=snapshot.failure_reason,
            )

        crop_results = sorted(
            self._port.find_crop_results(evaluation_id),
            key=lambda r: (r.rank_position is None, r.rank_position or 0, r.crop_id),
        )
        return EvaluationMcdaResultReadModel(
            evaluation_id=evaluation_id,
            status=snapshot.status,
            results=crop_results,
        )

    def get_agroenv_vector(self, evaluation_id: UUID) -> AgroenvVectorReadModel | None:
        """Return the persisted agroenvironmental vector for an evaluation."""

        if self._port.find_saga_snapshot(evaluation_id) is None:
            return None
        return self._port.find_agroenv_vector(evaluation_id)
