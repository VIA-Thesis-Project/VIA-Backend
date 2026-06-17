"""Manual Gemini API smoke test for VIA recommendation drafting."""

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
    GeminiApiConfig,
    GeminiApiDraftingProvider,
    LlmDraftingError,
)
from via.config import ConfigurationError, Settings, load_settings


def main() -> int:
    """Run one manual draft request against the configured Gemini API."""

    try:
        settings = load_settings()
        provider = _provider_from_settings(settings)
        text = provider.draft(_example_context())
    except ConfigurationError as exc:
        print(f"Gemini API smoke test configuration error: {exc}")
        return 2
    except LlmDraftingError as exc:
        print(f"Gemini API smoke test drafting error: {exc}")
        return 3
    except Exception as exc:
        print(f"Gemini API smoke test unexpected error: {exc.__class__.__name__}")
        return 4

    print(json.dumps({"status": "ok", "text": text}, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _provider_from_settings(settings: Settings) -> GeminiApiDraftingProvider:
    if settings.llm_drafting_provider != "gemini_api":
        raise ConfigurationError("LLM_DRAFTING_PROVIDER must be gemini_api for the Gemini smoke test")
    if not settings.gemini_api_key:
        raise ConfigurationError("GEMINI_API_KEY is required")
    if not settings.gemini_api_model:
        raise ConfigurationError("GEMINI_API_MODEL is required")
    return GeminiApiDraftingProvider(
        GeminiApiConfig(
            api_key=settings.gemini_api_key,
            model=settings.gemini_api_model,
            base_url=settings.gemini_api_base_url,
            timeout_seconds=settings.gemini_api_timeout_seconds,
            max_prompt_chars=settings.llm_max_prompt_chars,
            max_output_tokens=settings.gemini_api_max_output_tokens,
        )
    )


def _example_context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=UUID("00000000-0000-0000-0000-0000000010d3"),
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
                text=(
                    "Para cacao, el periodo de floracion requiere suministro hidrico estable. "
                    "Cuando se detecta deficit de agua, se recomienda priorizar manejo de cobertura, "
                    "monitoreo de humedad y riego suplementario si esta disponible."
                ),
                crop_tags=["cacao"],
                page_ref=12,
                score=0.91,
            ),
            EvidenceData(
                fragment_id=UUID("00000000-0000-0000-0000-00000000babe"),
                document_id=UUID("00000000-0000-0000-0000-00000000b00c"),
                text=(
                    "Las temperaturas elevadas durante establecimiento pueden afectar prendimiento y vigor. "
                    "La sombra temporal y el mantenimiento de humedad del suelo reducen estres termico."
                ),
                crop_tags=["cacao"],
                page_ref=18,
                score=0.87,
            ),
            EvidenceData(
                fragment_id=UUID("00000000-0000-0000-0000-00000000f00d"),
                document_id=UUID("00000000-0000-0000-0000-00000000b00c"),
                text=(
                    "Las recomendaciones tecnicas deben priorizar acciones verificables en campo, "
                    "seguimiento periodico y registro de cambios cuando existan brechas hidricas o termicas."
                ),
                crop_tags=["cacao"],
                page_ref=24,
                score=0.84,
            ),
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
