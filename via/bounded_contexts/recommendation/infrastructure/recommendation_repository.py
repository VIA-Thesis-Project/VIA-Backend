"""SQLAlchemy repository for recommendations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from via.bounded_contexts.recommendation.application.ports import IRecommendationRepository
from via.bounded_contexts.recommendation.domain.recommendation import Recommendation
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel


class SQLAlchemyRecommendationRepository(IRecommendationRepository):
    """Persist recommendations in the transactional schema."""

    def __init__(self, session: Session) -> None:
        """Create the repository with a synchronous SQLAlchemy session."""

        self._session = session

    def save(self, recommendation: Recommendation) -> None:
        """Persist a recommendation without committing."""

        self._session.add(recommendation_to_model(recommendation))


def recommendation_to_model(recommendation: Recommendation) -> RecommendationModel:
    """Map a recommendation aggregate to its ORM row."""

    return RecommendationModel(
        id=recommendation.id,
        evaluation_id=recommendation.evaluation_id,
        crop_id=recommendation.crop_id,
        text=recommendation.text,
        fragment_ids=[str(fragment_id) for fragment_id in recommendation.fragment_ids],
    )
