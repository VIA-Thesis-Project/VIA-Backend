"""SQLAlchemy repository for recommendations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from via.bounded_contexts.recommendation.application.ports import IRecommendationRepository
from via.bounded_contexts.recommendation.domain.recommendation import Recommendation
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel


class SQLAlchemyRecommendationRepository(IRecommendationRepository):
    """Persist recommendations in the transactional schema."""

    def __init__(self, session: Session, provider: str = "template") -> None:
        """Create the repository with a synchronous SQLAlchemy session."""

        self._session = session
        self._provider = provider

    def save(self, recommendation: Recommendation) -> None:
        """Persist a recommendation without committing."""

        self._session.add(recommendation_to_model(recommendation, self._provider))


def recommendation_to_model(recommendation: Recommendation, provider: str = "template") -> RecommendationModel:
    """Map a recommendation aggregate to its ORM row."""

    return RecommendationModel(
        id=recommendation.id,
        evaluation_id=recommendation.evaluation_id,
        crop_id=recommendation.crop_id,
        text=recommendation.text,
        fragment_ids=[_evidence_to_json(item) for item in recommendation.evidence],
        structured_output=recommendation.structured_output or {},
        provider=provider,
    )


def _evidence_to_json(item) -> dict:
    return {
        "fragment_id": str(item.fragment_id),
        "document_id": str(item.document_id),
        "text": item.text,
        "crop_tags": item.crop_tags,
        "page_ref": item.page_ref,
        "score": item.score,
        "source_filename": item.source_filename,
        "source_file_id": item.source_file_id,
    }
