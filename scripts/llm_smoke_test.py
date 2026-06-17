"""Manual local HTTP LLM smoke test for VIA recommendations."""

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
    LocalHttpLlmConfig,
    LocalHttpLlmDraftingProvider,
)
from via.config import ConfigurationError, Settings, load_settings


def main() -> int:
    """Run one manual draft request against a configured local HTTP LLM."""

    try:
        settings = load_settings()
        provider = _provider_from_settings(settings)
        text = provider.draft(_example_context())
    except ConfigurationError as exc:
        print(f"LLM smoke test configuration error: {exc}")
        return 2
    except LlmDraftingError as exc:
        print(f"LLM smoke test drafting error: {exc}")
        return 3
    except Exception as exc:
        print(f"LLM smoke test unexpected error: {exc}")
        return 4

    print(json.dumps({"status": "ok", "text": text}, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _provider_from_settings(settings: Settings) -> LocalHttpLlmDraftingProvider:
    if settings.llm_drafting_provider != "local_http":
        raise ConfigurationError("LLM_DRAFTING_PROVIDER must be local_http for the manual smoke test")
    if settings.llm_local_http_endpoint is None or settings.llm_model is None:
        raise ConfigurationError("LLM_LOCAL_HTTP_ENDPOINT and LLM_MODEL are required")
    return LocalHttpLlmDraftingProvider(
        LocalHttpLlmConfig(
            endpoint=settings.llm_local_http_endpoint,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_prompt_chars=settings.llm_max_prompt_chars,
        )
    )


def _example_context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=UUID("00000000-0000-0000-0000-0000000010d1"),
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
