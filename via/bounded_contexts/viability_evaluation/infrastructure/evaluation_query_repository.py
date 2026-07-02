"""SQLAlchemy read repository for evaluation status and MCDA results."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.agroenv_extraction.infrastructure.orm_models import (
    AgroenvVariableEntryModel,
    AgroenvVectorModel,
)
from via.bounded_contexts.rulebook_management.domain.phase_requirement import PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import (
    SqlAlchemyRulebookRepository,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableReadModel,
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
        metadata = _load_rulebook_metadata(self._session, [row.crop_id for row in result_rows])

        return [self._build_crop_result(row, metadata.get(row.crop_id, {})) for row in result_rows]

    def find_agroenv_vector(self, evaluation_id: UUID) -> AgroenvVectorReadModel | None:
        """Return the persisted agroenvironmental vector for an evaluation."""

        vector = self._session.execute(
            select(AgroenvVectorModel).where(AgroenvVectorModel.evaluation_id == evaluation_id)
        ).scalars().first()
        if vector is None:
            return None

        entries = self._session.execute(
            select(AgroenvVariableEntryModel).where(AgroenvVariableEntryModel.vector_id == vector.id)
        ).scalars().all()
        metadata = _load_rulebook_metadata(self._session, [entry.crop_id for entry in entries])
        return AgroenvVectorReadModel(
            evaluation_id=vector.evaluation_id,
            parcel_id=vector.parcel_id,
            variables=[
                AgroenvVariableReadModel(
                    variable_name=entry.variable_name,
                    criterion_id=entry.criterion_id,
                    crop_id=entry.crop_id,
                    phase_id=entry.phase_id,
                    period_key=entry.period_key,
                    value=float(entry.value) if entry.value is not None else None,
                    unit=entry.unit,
                    status=entry.status,
                    dataset_key=entry.dataset_key,
                    band=entry.band,
                    source=entry.source,
                    **_metadata_for_vector(metadata, entry.crop_id, entry.criterion_id, entry.phase_id),
                )
                for entry in entries
            ],
        )

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


def _load_rulebook_metadata(
    session: Session,
    crop_ids: list[str],
) -> dict[str, dict[tuple[str, str], dict[str, str]]]:
    metadata: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    repo = SqlAlchemyRulebookRepository(session)
    for crop_id in dict.fromkeys(crop_ids):
        rulebook = repo.get_active_by_crop(crop_id)
        metadata[crop_id] = _rulebook_metadata(rulebook) if rulebook is not None else {}
    return metadata


def _rulebook_metadata(rulebook: Rulebook) -> dict[tuple[str, str], dict[str, str]]:
    criteria_by_id = {str(c.id): c for c in rulebook.criteria}
    phases_by_id = {str(p.id): p for p in rulebook.phases}
    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for requirement in rulebook.phase_requirements:
        criterion_id = str(requirement.criterion_id)
        phase_id = str(requirement.phase_id)
        criterion = criteria_by_id.get(criterion_id)
        phase = phases_by_id.get(phase_id)
        if criterion is None or phase is None:
            continue
        metadata[(criterion_id, phase_id)] = {
            "criterion_name": criterion.name,
            "criterion_label": _humanize_label(criterion.name),
            "criterion_group": _criterion_group(requirement),
            "phase_name": phase.name,
            "unit": requirement.extraction_binding.unit,
            "intervention_class": criterion.intervention_class.value,
        }
    return metadata


def _metadata_for_pair(
    metadata: dict[str, dict[tuple[str, str], dict[str, str]]],
    crop_id: str,
    criterion_id: str,
    phase_id: str,
) -> dict[str, str]:
    return dict(metadata.get(crop_id, {}).get((criterion_id, phase_id), {}))


def _metadata_for_vector(
    metadata: dict[str, dict[tuple[str, str], dict[str, str]]],
    crop_id: str,
    criterion_id: str,
    phase_id: str,
) -> dict[str, str]:
    values = _metadata_for_pair(metadata, crop_id, criterion_id, phase_id)
    values.pop("unit", None)
    return values


def _humanize_label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _criterion_group(requirement: PhaseRequirement) -> str:
    source = " ".join(
        [
            requirement.extraction_binding.variable_name,
            requirement.extraction_binding.dataset_key,
            requirement.extraction_binding.band,
            requirement.extraction_binding.unit,
        ]
    ).lower()
    if any(term in source for term in ("temp", "precip", "rain", "clima", "chirps", "era5")):
        return "clima"
    if any(term in source for term in ("ece", "conductividad", "salinity", "salinidad")):
        return "salinidad"
    if any(term in source for term in ("soil", "ph", "arcilla", "arena", "carbon", "suelo")):
        return "suelo"
    if any(term in source for term in ("elevation", "altitud", "slope", "pendiente", "dem")):
        return "topografia"
    if any(term in source for term in ("ndvi", "evi", "savi", "veget")):
        return "vegetacion"
    return "agroambiental"
