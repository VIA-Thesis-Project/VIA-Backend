"""HTTP interface to start and query viability evaluation sagas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.viability_evaluation.application.query_service import (
    MCDA_READY_STATUSES,
    EvaluationMcdaResultReadModel,
    EvaluationQueryService,
)
from via.bounded_contexts.viability_evaluation.interfaces.resources import (
    AgroenvVariableResponse,
    AgroenvVectorResponse,
    CropResultResponse,
    EvaluationMcdaResultResponse,
    EvaluationStatusResponse,
    EvaluationSummaryResponse,
    GapResponse,
    LimitingFactorResponse,
)
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus


router = APIRouter(prefix="/evaluaciones", tags=["evaluations"])
START_EVALUATION_ROLES = {Role.ADMINISTRADOR, Role.USUARIO_AGRICOLA}


class StartEvaluationRequest(BaseModel):
    """Request body for creating an evaluation saga.

    requested_by is intentionally NOT part of this contract: it is taken
    from the authenticated user resolved by get_current_user.
    """

    parcel_id: UUID
    crop_candidates: list[str] = Field(min_length=1)
    temporal_window: dict[str, Any]


class StartEvaluationAccepted(BaseModel):
    """Accepted response for an asynchronously coordinated evaluation."""

    evaluation_id: UUID
    status: EvaluationSagaStatus


def get_current_user() -> User:
    """Return the authenticated user dependency."""

    raise RuntimeError("Authenticated user dependency is not configured")


def get_process_manager() -> EvaluationProcessManager:
    """Return the configured Process Manager dependency."""

    raise RuntimeError("Evaluation Process Manager dependency is not configured")


def get_evaluation_query_service() -> EvaluationQueryService:
    """Return the configured Evaluation Query Service dependency."""

    raise RuntimeError("Evaluation Query Service dependency is not configured")


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=StartEvaluationAccepted)
def start_evaluation(
    request: StartEvaluationRequest,
    current_user: User = Depends(get_current_user),
    process_manager: EvaluationProcessManager = Depends(get_process_manager),
) -> StartEvaluationAccepted:
    """Start an evaluation saga on behalf of the authenticated user."""

    if current_user.role not in START_EVALUATION_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    evaluation_id = process_manager.start_evaluation(
        parcel_id=request.parcel_id,
        requested_by=current_user.id,
        crop_candidates=request.crop_candidates,
        temporal_window=request.temporal_window,
    )
    return StartEvaluationAccepted(evaluation_id=evaluation_id, status=EvaluationSagaStatus.INICIADA)


@router.get("", response_model=list[EvaluationSummaryResponse])
def list_evaluations(
    parcel_id: UUID,
    query_service: EvaluationQueryService = Depends(get_evaluation_query_service),
    current_user: User = Depends(get_current_user),
) -> list[EvaluationSummaryResponse]:
    """Return the authenticated user's evaluation history for one parcel.

    Scoped to evaluations requested by the current user, newest first.
    Returns an empty list when the parcel has no evaluations for this user.
    """

    summaries = query_service.list_evaluations_for_parcel(parcel_id, current_user.id)
    return [
        EvaluationSummaryResponse(
            evaluation_id=s.evaluation_id,
            parcel_id=s.parcel_id,
            status=s.status,
            created_at=s.created_at,
            crop_candidates=s.crop_candidates,
            top_crop_id=s.top_crop_id,
            top_score=s.top_score,
            top_viability_category=s.top_viability_category,
        )
        for s in summaries
    ]


@router.get("/{evaluation_id}/estado", response_model=EvaluationStatusResponse)
def get_evaluation_status(
    evaluation_id: UUID,
    query_service: EvaluationQueryService = Depends(get_evaluation_query_service),
    current_user: User = Depends(get_current_user),
) -> EvaluationStatusResponse:
    """Return the current status and last transition of an evaluation saga.

    Returns 404 if the evaluation does not exist.
    Never exposes outbox IDs or internal stack traces.
    """

    rm = query_service.get_evaluation_status(evaluation_id)
    if rm is None:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    return EvaluationStatusResponse(
        evaluation_id=rm.evaluation_id,
        status=rm.status,
        current_phase=rm.current_phase,
        last_transition=rm.last_transition,
        failure_reason=rm.failure_reason,
    )


@router.get("/{evaluation_id}/resultado-mcda", response_model=None)
def get_mcda_result(
    evaluation_id: UUID,
    query_service: EvaluationQueryService = Depends(get_evaluation_query_service),
    current_user: User = Depends(get_current_user),
) -> EvaluationMcdaResultResponse | JSONResponse:
    """Return persisted MCDA ranking, scores, gaps and limiting factors.

    - 202 when the evaluation is still in progress.
    - 200 with full results when EVALUACION_COMPLETADA or RECOMENDACION_COMPLETADA.
    - 200 with failure_reason (sanitized) when FALLIDA.
    - 404 when the evaluation does not exist.

    Does not include Recommendation. Does not recalculate scores or gaps.
    """

    rm = query_service.get_mcda_result(evaluation_id)
    if rm is None:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")

    if rm.status not in MCDA_READY_STATUSES and rm.status != EvaluationSagaStatus.FALLIDA.value:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "evaluation_id": str(evaluation_id),
                "status": rm.status,
                "results": [],
                "failure_reason": None,
            },
        )

    return EvaluationMcdaResultResponse(
        evaluation_id=rm.evaluation_id,
        status=rm.status,
        results=_to_crop_responses(rm),
        failure_reason=rm.failure_reason,
    )


@router.get("/{evaluation_id}/vector-agroambiental", response_model=AgroenvVectorResponse)
def get_agroenv_vector(
    evaluation_id: UUID,
    query_service: EvaluationQueryService = Depends(get_evaluation_query_service),
    current_user: User = Depends(get_current_user),
) -> AgroenvVectorResponse:
    """Return the persisted GEE/agroenvironmental vector used by the evaluation."""

    rm = query_service.get_agroenv_vector(evaluation_id)
    if rm is None:
        raise HTTPException(status_code=404, detail="Vector agroambiental no encontrado")

    return AgroenvVectorResponse(
        evaluation_id=rm.evaluation_id,
        parcel_id=rm.parcel_id,
        variables=[
            AgroenvVariableResponse(
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
                criterion_name=v.criterion_name,
                criterion_label=v.criterion_label,
                criterion_group=v.criterion_group,
                phase_name=v.phase_name,
                intervention_class=v.intervention_class,
            )
            for v in rm.variables
        ],
    )


# ─── private helpers ───────────────────────────────────────────────────────────


def _to_crop_responses(rm: EvaluationMcdaResultReadModel) -> list[CropResultResponse]:
    return [
        CropResultResponse(
            crop_id=r.crop_id,
            score=r.score,
            rank_position=r.rank_position,
            calc_condition=r.calc_condition,
            viability_category=r.viability_category,
            gaps=[
                GapResponse(
                    criterion_id=g.criterion_id,
                    phase_id=g.phase_id,
                    most_limiting_period=g.most_limiting_period,
                    observed_value=g.observed_value,
                    optimal_limit=g.optimal_limit,
                    gap_value=g.gap_value,
                    criterion_name=g.criterion_name,
                    criterion_label=g.criterion_label,
                    criterion_group=g.criterion_group,
                    phase_name=g.phase_name,
                    unit=g.unit,
                    intervention_class=g.intervention_class,
                )
                for g in r.gaps
            ],
            limiting_factors=[
                LimitingFactorResponse(
                    criterion_id=lf.criterion_id,
                    phase_id=lf.phase_id,
                    policy=lf.policy,
                    penalty_factor=lf.penalty_factor,
                    observed_value=lf.observed_value,
                    optimal_limit=lf.optimal_limit,
                    membership=lf.membership,
                    doc_source=lf.doc_source,
                    criterion_name=lf.criterion_name,
                    criterion_label=lf.criterion_label,
                    criterion_group=lf.criterion_group,
                    phase_name=lf.phase_name,
                    unit=lf.unit,
                    intervention_class=lf.intervention_class,
                )
                for lf in r.limiting_factors
            ],
            missing_criteria=r.missing_criteria,
            unrecognized_variables=r.unrecognized_variables,
        )
        for r in rm.results
    ]
