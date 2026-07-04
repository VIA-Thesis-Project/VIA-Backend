"""Smoke test directo del OpenAI Web Search provider.

Uso:
    python scripts/openai_web_search_smoke_test.py

Requiere:
    OPENAI_API_KEY, OPENAI_RAG_MODEL,
    LLM_DRAFTING_PROVIDER=openai_web_search,
    OPENAI_WEB_SEARCH_ENABLED=true
"""

from __future__ import annotations

import json
import pathlib
import sys
from uuid import uuid4

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    GapData,
    RecommendationDraftContext,
)
from via.config import load_settings
from via.shared.runtime.application_runtime import build_recommendation_drafting_provider


def main() -> None:
    print("=== VIA - OpenAI Web Search Smoke Test ===\n")

    settings = load_settings()
    if settings.llm_drafting_provider != "openai_web_search":
        print(
            f"ERROR: LLM_DRAFTING_PROVIDER={settings.llm_drafting_provider!r}. "
            "Debe ser 'openai_web_search'.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not settings.openai_web_search_enabled:
        print("ERROR: OPENAI_WEB_SEARCH_ENABLED debe ser true.", file=sys.stderr)
        sys.exit(1)

    print(f"Provider : {settings.llm_drafting_provider}")
    print(f"Model    : {settings.openai_rag_model}")
    print(f"Domains  : {', '.join(settings.openai_web_search_allowed_domains) or '(sin filtro)'}")
    print(f"Context  : {settings.openai_web_search_context_size}")
    print()

    provider = build_recommendation_drafting_provider(settings)
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="mandarina_murcott",
            score=0.4142,
            rank_position=2,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="suelo_ph",
                    phase_id="instalacion_establecimiento",
                    most_limiting_period="site_static",
                    observed_value=7.33,
                    optimal_limit=7.0,
                    gap_value=0.33,
                    criterion_name="reaccion_suelo_ph",
                    criterion_label="Reaccion suelo pH",
                    criterion_group="suelo",
                    unit="pH",
                    phase_name="instalacion_establecimiento",
                    gap_direction="above_optimum",
                    severity="baja",
                    recommendation_topic="suelo pH citricos mandarina",
                ),
                GapData(
                    criterion_id="carbono_organico",
                    phase_id="instalacion_establecimiento",
                    most_limiting_period="site_static",
                    observed_value=0.0,
                    optimal_limit=8.0,
                    gap_value=-8.0,
                    criterion_name="carbono_organico_suelo",
                    criterion_label="Carbono organico suelo",
                    criterion_group="suelo",
                    unit="g/kg",
                    phase_name="instalacion_establecimiento",
                    gap_direction="below_optimum",
                    severity="media",
                    recommendation_topic="materia organica suelo citricos mandarina",
                ),
            ],
        ),
        evidence=[],
    )

    print("Llamando a OpenAI Responses API con Web Search ...")
    try:
        text = provider.draft(context)
    except Exception as exc:
        print(f"ERROR al llamar al provider: {exc}", file=sys.stderr)
        sys.exit(1)

    trace = getattr(provider, "get_last_trace", lambda: None)()
    print("\n=== RECOMENDACION GENERADA ===")
    print(text)
    print()

    if trace:
        print("=== TRAZABILIDAD ===")
        print(f"  response_id       : {trace.response_id}")
        print(f"  web_search_calls  : {trace.web_search_call_ids}")
        print(f"  validation_status : {trace.raw_output_validation_status}")
        print(f"  source_urls       : {trace.source_urls}")
        print(f"  retrieved_results : {len(trace.retrieved_results)} resultado(s)")
        if trace.warnings:
            for warning in trace.warnings:
                print(f"  AVISO: {warning}")

        artifact_dir = ROOT / "artifacts" / "openai_web_search"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "smoke_test_trace.json"
        artifact_path.write_text(
            json.dumps(trace.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nTrace guardado en: {artifact_path}")

    print("\n[OK] Smoke test completado.")


if __name__ == "__main__":
    main()
