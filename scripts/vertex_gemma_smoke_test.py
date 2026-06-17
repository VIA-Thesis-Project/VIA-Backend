"""Manual Vertex AI Gemma smoke test for VIA recommendation drafting."""

from __future__ import annotations

import json
from uuid import UUID

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvidenceData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import (
    LlmDraftingError,
    VertexGemmaConfig,
    VertexGemmaDraftingProvider,
)
from via.config import ConfigurationError, Settings, load_settings


def main() -> int:
    """Run one manual draft request against a configured Vertex AI Gemma endpoint."""

    try:
        settings = load_settings()
        provider = _provider_from_settings(settings)
        text = provider.draft(_example_context())
    except ConfigurationError as exc:
        print(f"Vertex Gemma smoke test configuration error: {exc}")
        return 2
    except LlmDraftingError as exc:
        print(f"Vertex Gemma smoke test drafting error: {exc}")
        return 3
    except Exception as exc:
        print(f"Vertex Gemma smoke test unexpected error: {exc.__class__.__name__}")
        return 4

    print(json.dumps({"status": "ok", "text": text}, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _provider_from_settings(settings: Settings) -> VertexGemmaDraftingProvider:
    if settings.llm_drafting_provider != "vertex_gemma":
        raise ConfigurationError("LLM_DRAFTING_PROVIDER must be vertex_gemma for the Vertex smoke test")
    if not settings.vertex_ai_project_id or not settings.vertex_ai_location or not settings.vertex_ai_endpoint_id:
        raise ConfigurationError("VERTEX_AI_PROJECT_ID, VERTEX_AI_LOCATION and VERTEX_AI_ENDPOINT_ID are required")
    if not settings.llm_model:
        raise ConfigurationError("LLM_MODEL is required")
    return VertexGemmaDraftingProvider(
        VertexGemmaConfig(
            project_id=settings.vertex_ai_project_id,
            location=settings.vertex_ai_location,
            endpoint_id=settings.vertex_ai_endpoint_id,
            model=settings.llm_model,
            timeout_seconds=settings.vertex_ai_timeout_seconds,
            max_prompt_chars=settings.llm_max_prompt_chars,
        )
    )


def _example_context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=UUID("00000000-0000-0000-0000-0000000010d2"),
        crop_result=CropEvaluationResultData(
            crop_id="cacao",
            score=0.82,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="VIABLE",
            gaps=[
                GapData(
                    criterion_id="agua",
                    phase_id="floracion",
                    most_limiting_period="2026-02",
                    observed_value=18.0,
                    optimal_limit=22.0,
                    gap_value=-4.0,
                )
            ],
            limiting_factors=[
                LimitingFactorData(
                    criterion_id="temperatura",
                    phase_id="establecimiento",
                    policy="PENALIZE",
                    penalty_factor=0.5,
                    observed_value=35.0,
                    optimal_limit=30.0,
                    membership=0.0,
                    doc_source="Manual tecnico de cacao",
                )
            ],
        ),
        evidence=[
            EvidenceData(
                fragment_id=UUID("00000000-0000-0000-0000-00000000cafe"),
                document_id=UUID("00000000-0000-0000-0000-00000000b00c"),
                text="El cacao requiere manejo cuidadoso del agua durante floracion y temperaturas moderadas.",
                crop_tags=["cacao"],
                page_ref=12,
                score=0.91,
            )
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
