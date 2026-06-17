"""Template-based recommendation drafting provider."""

from __future__ import annotations

from via.bounded_contexts.recommendation.application.ports import IRecommendationDraftingProvider, RecommendationDraftContext


class TemplateRecommendationDraftingProvider(IRecommendationDraftingProvider):
    """Draft deterministic recommendation text without external services."""

    def draft(self, context: RecommendationDraftContext) -> str:
        """Return a deterministic draft from precomputed evaluation data."""

        result = context.crop_result
        evidence_count = len(context.evidence)
        return (
            f"Recomendacion para {result.crop_id}: score={result.score}, "
            f"categoria={result.viability_category}, condicion={result.calc_condition}. "
            f"Se usaron {evidence_count} fragmentos documentales."
        )
