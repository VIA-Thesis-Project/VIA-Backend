"""SQLAlchemy read repository for persisted recommendations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.recommendation.application.ports import (
    EvidenceReadModel,
    FinalRecommendationResult,
    RecommendationReadModel,
)
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel
from via.shared.orchestration.evaluation_process_manager.saga_orm import EvaluationSagaModel


class RecommendationQueryRepository:
    """Concrete read repository implementing IRecommendationQueryPort.

    Owns all SQLAlchemy SELECT concerns; the query service depends on
    IRecommendationQueryPort, never on this class directly.
    """

    def __init__(self, session: Session) -> None:
        """Create the repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def find_by_id(self, recommendation_id: UUID) -> RecommendationReadModel | None:
        """Return recommendation by its primary key, or None when not found."""

        row = self._session.get(RecommendationModel, recommendation_id)
        if row is None:
            return None
        parcel_id = self._get_parcel_id(row.evaluation_id)
        return self._build(row, parcel_id)

    def find_by_evaluation_id(self, evaluation_id: UUID) -> list[RecommendationReadModel]:
        """Return all recommendations for an evaluation (may be empty)."""

        rows = self._session.execute(
            select(RecommendationModel)
            .where(RecommendationModel.evaluation_id == evaluation_id)
            .order_by(RecommendationModel.generated_at.asc())
        ).scalars().all()

        if not rows:
            return []
        parcel_id = self._get_parcel_id(evaluation_id)
        return [self._build(row, parcel_id) for row in rows]

    def find_final_for_evaluation(self, evaluation_id: UUID) -> FinalRecommendationResult:
        """Return whether the evaluation exists and its most recent recommendation."""

        saga = self._session.get(EvaluationSagaModel, evaluation_id)
        if saga is None:
            return FinalRecommendationResult(evaluation_found=False, recommendation=None)

        row = self._session.execute(
            select(RecommendationModel)
            .where(RecommendationModel.evaluation_id == evaluation_id)
            .order_by(RecommendationModel.generated_at.desc())
            .limit(1)
        ).scalars().first()

        if row is None:
            return FinalRecommendationResult(evaluation_found=True, recommendation=None)

        return FinalRecommendationResult(
            evaluation_found=True,
            recommendation=self._build(row, saga.parcel_id),
        )

    def _get_parcel_id(self, evaluation_id: UUID) -> UUID | None:
        saga = self._session.get(EvaluationSagaModel, evaluation_id)
        return saga.parcel_id if saga else None

    def _build(self, row: RecommendationModel, parcel_id: UUID | None) -> RecommendationReadModel:
        return RecommendationReadModel(
            recommendation_id=row.id,
            evaluation_id=row.evaluation_id,
            parcel_id=parcel_id,
            crop_id=row.crop_id,
            status="GENERATED",
            title=f"Recomendación para {row.crop_id}",
            text=row.text,
            evidence=[_evidence_from_json(item) for item in (row.fragment_ids or [])],
            structured_output=row.structured_output or {},
            created_at=row.generated_at,
            provider=row.provider,
        )


def _evidence_from_json(item) -> EvidenceReadModel:
    if isinstance(item, dict):
        return EvidenceReadModel(
            fragment_id=UUID(str(item["fragment_id"])),
            document_id=UUID(str(item["document_id"])) if item.get("document_id") else None,
            text=item.get("text"),
            crop_tags=list(item.get("crop_tags") or []),
            page_ref=item.get("page_ref"),
            score=item.get("score"),
            source_filename=item.get("source_filename"),
            source_file_id=item.get("source_file_id"),
        )
    return EvidenceReadModel(fragment_id=UUID(str(item)))
