"""Smoke test directo del OpenAI File Search provider.

Prueba el provider con datos MCDA sintéticos de maiz_amarillo_duro sin
necesitar GEE, base de datos ni la saga completa.

Uso:
    python scripts/openai_file_search_smoke_test.py

Requiere en el entorno:
    OPENAI_API_KEY, OPENAI_RAG_MODEL, LLM_DRAFTING_PROVIDER=openai_file_search
    VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from uuid import uuid4

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.config import load_settings
from via.shared.runtime.application_runtime import build_recommendation_drafting_provider


def main() -> None:
    print("=== VIA — OpenAI File Search Smoke Test ===\n")

    settings = load_settings()

    if settings.llm_drafting_provider != "openai_file_search":
        print(
            f"ERROR: LLM_DRAFTING_PROVIDER={settings.llm_drafting_provider!r}. "
            "Debe ser 'openai_file_search'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.openai_vector_store_maiz_amarillo_duro_id:
        print(
            "ERROR: VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID no configurado.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Provider : {settings.llm_drafting_provider}")
    print(f"Model    : {settings.openai_rag_model}")
    print(f"VS maiz  : {settings.openai_vector_store_maiz_amarillo_duro_id}")
    print(f"Max res  : {settings.openai_file_search_max_results}")
    print()

    provider = build_recommendation_drafting_provider(settings)

    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maiz_amarillo_duro",
            score=0.74,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="VIABLE",
            gaps=[
                GapData(
                    criterion_id="precipitacion",
                    phase_id="crecimiento_vegetativo",
                    most_limiting_period="2025-03",
                    observed_value=42.0,
                    optimal_limit=80.0,
                    gap_value=-38.0,
                    criterion_name="deficit_hidrico",
                    criterion_label="Deficit hidrico",
                    criterion_group="riego",
                    unit="mm",
                    phase_name="crecimiento vegetativo",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="riego agua humedad requerimiento hidrico",
                ),
                GapData(
                    criterion_id="temperatura_media",
                    phase_id="floracion",
                    most_limiting_period="2025-05",
                    observed_value=29.5,
                    optimal_limit=26.0,
                    gap_value=3.5,
                    criterion_name="aptitud_termica",
                    criterion_label="Aptitud termica",
                    criterion_group="clima",
                    unit="celsius",
                    phase_name="floracion",
                    gap_direction="above_optimum",
                    severity="media",
                    recommendation_topic="temperatura floracion clima fenologia",
                ),
            ],
            limiting_factors=[
                LimitingFactorData(
                    criterion_id="precipitacion",
                    phase_id="crecimiento_vegetativo",
                    policy="PENALIZE",
                    penalty_factor=0.7,
                    observed_value=42.0,
                    optimal_limit=80.0,
                    membership=0.35,
                    criterion_name="deficit_hidrico",
                    criterion_label="Deficit hidrico",
                    criterion_group="riego",
                    unit="mm",
                    phase_name="crecimiento vegetativo",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="riego agua humedad requerimiento hidrico",
                ),
            ],
        ),
        evidence=[],
    )

    print("Llamando a OpenAI Responses API con File Search ...")
    print(f"  evaluation_id : {context.evaluation_id}")
    print(f"  crop_id       : maiz_amarillo_duro")
    print(f"  score         : 0.74  |  categoria: VIABLE  |  rank: 1")
    print()

    try:
        text = provider.draft(context)
    except Exception as exc:
        print(f"ERROR al llamar al provider: {exc}", file=sys.stderr)
        sys.exit(1)

    trace = getattr(provider, "get_last_trace", lambda: None)()

    print("=== RECOMENDACIÓN GENERADA ===")
    print(text)
    print()

    if trace:
        print("=== TRAZABILIDAD ===")
        print(f"  response_id          : {trace.response_id}")
        print(f"  file_search_call_id  : {trace.file_search_call_id}")
        print(f"  validation_status    : {trace.raw_output_validation_status}")
        print(f"  source_filenames     : {trace.source_filenames}")
        print(f"  retrieved_results    : {len(trace.retrieved_results)} resultado(s)")
        if trace.warnings:
            for w in trace.warnings:
                print(f"  AVISO: {w}")

        artifact_path = ROOT / "artifacts" / "openai_file_search" / "smoke_test_trace.json"
        artifact_path.write_text(
            json.dumps(trace.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nTrace guardado en: {artifact_path}")

    print("\n[OK] Smoke test completado.")


if __name__ == "__main__":
    main()
