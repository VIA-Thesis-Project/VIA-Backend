"""SQLAlchemy read repository for evaluation status and MCDA results."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableReadModel,
    AgroenvVectorData,
    AgroenvVectorReadModel,
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

RulebookMetadataByCrop = dict[str, dict[tuple[str, str], dict[str, str]]]


class EvaluationQueryRepository:
    """Concrete read repository implementing IEvaluationQueryPort.

    Owns all SQLAlchemy SELECT concerns; the application query service
    depends on IEvaluationQueryPort, never on this class directly.

    Cross-context reads (rulebook display metadata, agroenvironmental
    vector) are injected as callables wired at the composition root
    (via.shared.runtime.bridges), so this module never imports other
    bounded contexts. Without them the repository still works and simply
    omits the optional display metadata / vector.
    """

    def __init__(
        self,
        session: Session,
        rulebook_metadata_source: Callable[[list[str]], RulebookMetadataByCrop] | None = None,
        agroenv_vector_source: Callable[[UUID], AgroenvVectorData | None] | None = None,
    ) -> None:
        """Create the repository bound to a synchronous SQLAlchemy session."""

        self._session = session
        self._rulebook_metadata_source = rulebook_metadata_source
        self._agroenv_vector_source = agroenv_vector_source

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
        metadata = self._load_rulebook_metadata([row.crop_id for row in result_rows])

        return [self._build_crop_result(row, metadata.get(row.crop_id, {})) for row in result_rows]

    def find_agroenv_vector(self, evaluation_id: UUID) -> AgroenvVectorReadModel | None:
        """Return the persisted agroenvironmental vector for an evaluation."""

        if self._agroenv_vector_source is None:
            return None
        vector = self._agroenv_vector_source(evaluation_id)
        if vector is None:
            return None

        metadata = self._load_rulebook_metadata([v.crop_id for v in vector.variables])
        return AgroenvVectorReadModel(
            evaluation_id=vector.evaluation_id,
            parcel_id=vector.parcel_id,
            variables=[
                AgroenvVariableReadModel(
                    variable_name=v.variable_name,
                    criterion_id=v.criterion_id,
                    crop_id=v.crop_id,
                    phase_id=v.phase_id,
                    period_key=v.period_key,
                    value=v.value,
                    unit=v.unit,
                    status=v.status,
                    dataset_key=v.dataset_key,
                    band=v.band,
                    source=v.source,
                    **_metadata_for_vector(metadata, v.crop_id, v.criterion_id, v.phase_id),
                )
                for v in vector.variables
            ],
        )

    def _load_rulebook_metadata(self, crop_ids: list[str]) -> RulebookMetadataByCrop:
        if self._rulebook_metadata_source is None:
            return {}
        return self._rulebook_metadata_source(crop_ids)

    def _build_crop_result(
        self,
        row: EvaluationResultModel,
        metadata_by_pair: dict[tuple[str, str], dict[str, str]],
    ) -> CropResultReadModel:
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
                    membership=float(g.membership) if g.membership is not None else None,
                    **metadata_by_pair.get((g.criterion_id, g.phase_id), {}),
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
                    **metadata_by_pair.get((lf.criterion_id, lf.phase_id), {}),
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


def _metadata_for_pair(
    metadata: RulebookMetadataByCrop,
    crop_id: str,
    criterion_id: str,
    phase_id: str,
) -> dict[str, str]:
    return dict(metadata.get(crop_id, {}).get((criterion_id, phase_id), {}))


def _metadata_for_vector(
    metadata: RulebookMetadataByCrop,
    crop_id: str,
    criterion_id: str,
    phase_id: str,
) -> dict[str, str]:
    values = _metadata_for_pair(metadata, crop_id, criterion_id, phase_id)
    values.pop("unit", None)
    return values
