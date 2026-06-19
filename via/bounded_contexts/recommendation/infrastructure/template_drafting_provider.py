"""Template-based recommendation drafting provider."""

from __future__ import annotations

from via.bounded_contexts.recommendation.application.ports import IRecommendationDraftingProvider, RecommendationDraftContext


class TemplateRecommendationDraftingProvider(IRecommendationDraftingProvider):
    """Draft deterministic recommendation text without external services."""

    def draft(self, context: RecommendationDraftContext) -> str:
        """Return a deterministic draft from precomputed evaluation data."""

        result = context.crop_result
        evidence_count = len(context.evidence)

        parts = [
            f"Recomendacion agronomica sustentada para {result.crop_id}.",
            f"Score MCDA calculado: {result.score}. "
            f"Categoria de viabilidad: {result.viability_category}. "
            f"Condicion de calculo: {result.calc_condition}. "
            f"Posicion en ranking: {result.rank_position}.",
        ]

        if result.gaps:
            brechas = "; ".join(
                f"{g.criterion_id}/{g.phase_id}: brecha={g.gap_value}"
                for g in result.gaps
            )
            parts.append(f"Brechas agronomicas identificadas: {brechas}.")
        else:
            parts.append("No se identificaron brechas agronomicas.")

        if result.limiting_factors:
            factores = "; ".join(
                f"{f.criterion_id}/{f.phase_id}: {f.policy}"
                for f in result.limiting_factors
            )
            parts.append(f"Factores limitantes activados: {factores}.")

        if evidence_count > 0:
            parts.append(f"Sustentado con {evidence_count} fragmentos documentales.")
        else:
            parts.append(
                "No se encontro evidencia documental suficiente para esta recomendacion. "
                "Se omite cita bibliografica."
            )

        return " ".join(parts)
