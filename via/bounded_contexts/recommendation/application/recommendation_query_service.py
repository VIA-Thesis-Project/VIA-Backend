"""Query service for persisted recommendations."""

from __future__ import annotations

from uuid import UUID

from via.bounded_contexts.recommendation.application.ports import (
    FinalRecommendationResult,
    IRecommendationQueryPort,
    RecommendationReadModel,
)


class RecommendationQueryService:
    """Read-only service for querying already-persisted recommendations.

    Delegates all persistence reads to IRecommendationQueryPort; does not
    import ORM models, SQLAlchemy, or any infrastructure module.
    Does not invoke LLM, GEE, RAG, or any generation code.
    """

    def __init__(self, query_port: IRecommendationQueryPort) -> None:
        """Create query service with an injected persistence port."""

        self._port = query_port

    def get_recommendation(self, recommendation_id: UUID) -> RecommendationReadModel | None:
        """Return a recommendation by ID, or None when not found."""

        return self._port.find_by_id(recommendation_id)

    def get_recommendations_for_evaluation(self, evaluation_id: UUID) -> list[RecommendationReadModel]:
        """Return all recommendations for an evaluation (may be empty)."""

        return self._port.find_by_evaluation_id(evaluation_id)

    def get_final_recommendation(self, evaluation_id: UUID) -> FinalRecommendationResult:
        """Return whether the evaluation exists and its most recent recommendation."""

        return self._port.find_final_for_evaluation(evaluation_id)
