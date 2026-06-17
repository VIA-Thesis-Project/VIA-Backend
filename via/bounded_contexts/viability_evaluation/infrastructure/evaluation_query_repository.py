"""SQLAlchemy read repository for evaluation status and MCDA results."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.viability_evaluation.application.ports import (
    CropResultReadModel,
    GapReadModel,
    LimitingFactorReadModel,
    SagaSnapshot,
)
from via.bounded_contexts.viability_evaluation.infrastructure.orm_models import (
    AgronomyGapModel,
    EvaluationResultModel,
    LimitingFactorModel,
)
from via.shared.orchestration.evaluation_process_manager.saga_orm import (
    EvaluationSagaModel,
    SagaTransitionModel,
)
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


class EvaluationQueryRepository:
    """Concrete read repository implementing IEvaluationQueryPort.

    Owns all SQLAlchemy SELECT concerns; the application query service
    depends on IEvaluationQueryPort, never on this class directly.
    """

    def __init__(self, session: Session) -> None:
        """Create the repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def find_saga_snapshot(self, evaluation_id: UUID) -> SagaSnapshot | None:
        """Return current saga status, last transition and failure reason, or None."""

        saga = self._session.get(EvaluationSagaModel, evaluation_id)
        if saga is None:
            return None

        last_t = self._session.execute(
            select(SagaTransitionModel)
            .where(SagaTransitionModel.saga_id == evaluation_id)
            .order_by(SagaTransitionModel.occurred_at.desc())
            .limit(1)
        ).scalars().first()

        failure_reason: str | None = None
        if saga.status == EvaluationSagaStatus.FALLIDA.value:
            failure_reason = self._query_failure_reason(evaluation_id)

        return SagaSnapshot(
            status=saga.status,
            last_transition=last_t.occurred_at if last_t else None,
            failure_reason=failure_reason,
        )

    def find_crop_results(self, evaluation_id: UUID) -> list[CropResultReadModel]:
        """Return all persisted crop results with gaps and limiting factors."""

        result_rows = self._session.execute(
            select(EvaluationResultModel)
            .where(EvaluationResultModel.evaluation_id == evaluation_id)
        ).scalars().all()

        return [self._build_crop_result(row) for row in result_rows]

    def _build_crop_result(self, row: EvaluationResultModel) -> CropResultReadModel:
        gaps = self._session.execute(
            select(AgronomyGapModel).where(AgronomyGapModel.result_id == row.id)
        ).scalars().all()
        factors = self._session.execute(
            select(LimitingFactorModel).where(LimitingFactorModel.result_id == row.id)
        ).scalars().all()

        return CropResultReadModel(
            crop_id=row.crop_id,
            score=float(row.score) if row.score is not None else None,
            rank_position=row.rank_position,
            calc_condition=row.calc_condition,
            viability_category=row.viability_category,
            gaps=[
                GapReadModel(
                    criterion_id=g.criterion_id,
                    phase_id=g.phase_id,
                    most_limiting_period=g.most_limiting_period,
                    observed_value=float(g.observed_value),
                    optimal_limit=float(g.optimal_limit),
                    gap_value=float(g.gap_value),
                )
                for g in gaps
            ],
            limiting_factors=[
                LimitingFactorReadModel(
                    criterion_id=lf.criterion_id,
                    phase_id=lf.phase_id,
                    policy=lf.policy,
                    penalty_factor=float(lf.penalty_factor) if lf.penalty_factor is not None else None,
                    observed_value=float(lf.observed_value),
                    optimal_limit=float(lf.optimal_limit),
                    membership=float(lf.membership),
                    doc_source=lf.doc_source,
                )
                for lf in factors
            ],
        )

    def _query_failure_reason(self, evaluation_id: UUID) -> str | None:
        t = self._session.execute(
            select(SagaTransitionModel)
            .where(SagaTransitionModel.saga_id == evaluation_id)
            .where(SagaTransitionModel.to_status == EvaluationSagaStatus.FALLIDA.value)
            .order_by(SagaTransitionModel.occurred_at.desc())
            .limit(1)
        ).scalars().first()
        return t.failure_cause if t else None
