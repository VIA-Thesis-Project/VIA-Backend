"""HTTP interface for reading persisted recommendations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.recommendation.application.recommendation_query_service import (
    RecommendationQueryService,
)
from via.bounded_contexts.recommendation.interfaces.resources import (
    EvidenceResponse,
    RecommendationResponse,
    SectionResponse,
)


router = APIRouter(tags=["recommendations"])


def get_current_user() -> User:
    """Return the authenticated user dependency."""

    raise RuntimeError("Authenticated user dependency is not configured")


def get_recommendation_query_service() -> RecommendationQueryService:
    """Return the configured Recommendation Query Service dependency."""

    raise RuntimeError("Recommendation Query Service dependency is not configured")


@router.get("/recomendaciones/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(
    recommendation_id: UUID,
    query_service: RecommendationQueryService = Depends(get_recommendation_query_service),
    current_user: User = Depends(get_current_user),
) -> RecommendationResponse:
    """Return a recommendation by ID.

    Returns 404 if the recommendation does not exist.
    Does not invoke LLM, GEE, or any generation code.
    """

    rm = query_service.get_recommendation(recommendation_id)
    if rm is None:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")
    return _to_response(rm)


@router.get("/evaluaciones/{evaluation_id}/recomendaciones", response_model=list[RecommendationResponse])
def get_recommendations_for_evaluation(
    evaluation_id: UUID,
    query_service: RecommendationQueryService = Depends(get_recommendation_query_service),
    current_user: User = Depends(get_current_user),
) -> list[RecommendationResponse]:
    """Return all recommendations for an evaluation.

    Returns 200 with an empty list when no recommendations exist yet.
    Does not invoke LLM, GEE, or any generation code.
    """

    rms = query_service.get_recommendations_for_evaluation(evaluation_id)
    return [_to_response(rm) for rm in rms]


@router.get("/evaluaciones/{evaluation_id}/recomendacion-final", response_model=None)
def get_final_recommendation(
    evaluation_id: UUID,
    query_service: RecommendationQueryService = Depends(get_recommendation_query_service),
    current_user: User = Depends(get_current_user),
) -> RecommendationResponse | JSONResponse:
    """Return the most recent recommendation for an evaluation.

    - 404 when the evaluation does not exist.
    - 202 when the evaluation exists but no recommendation has been generated yet.
    - 200 with the recommendation when available.

    Does not invoke LLM, GEE, or any generation code.
    """

    result = query_service.get_final_recommendation(evaluation_id)
    if not result.evaluation_found:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    if result.recommendation is None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "evaluation_id": str(evaluation_id),
                "status": "pending",
                "detail": "Recomendación aún no disponible",
            },
        )
    return _to_response(result.recommendation)


# ─── private helpers ───────────────────────────────────────────────────────────


def _to_response(rm) -> RecommendationResponse:
    return RecommendationResponse(
        recommendation_id=rm.recommendation_id,
        evaluation_id=rm.evaluation_id,
        parcel_id=rm.parcel_id,
        crop_id=rm.crop_id,
        status=rm.status,
        title=rm.title,
        sections=[
            SectionResponse(
                section_type="recommendation_text",
                title=rm.title,
                content=rm.text,
            )
        ],
        evidence=[_evidence_to_response(item) for item in rm.evidence],
        structured_output=rm.structured_output,
        gap_recommendations=list((rm.structured_output or {}).get("gap_recommendations") or []),
        created_at=rm.created_at,
        provider=rm.provider,
    )


def _evidence_to_response(item) -> EvidenceResponse:
    return EvidenceResponse(
        fragment_id=item.fragment_id,
        document_id=item.document_id,
        text=item.text,
        crop_tags=item.crop_tags,
        page_ref=item.page_ref,
        score=item.score,
        source_filename=item.source_filename,
        source_file_id=item.source_file_id,
    )
