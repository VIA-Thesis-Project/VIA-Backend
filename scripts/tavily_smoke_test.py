"""Diagnóstico directo de Tavily Search — muestra raw API response.

Uso:
    python scripts/tavily_smoke_test.py

Requiere:
    TAVILY_API_KEY, OPENAI_API_KEY, OPENAI_RAG_MODEL,
    LLM_DRAFTING_PROVIDER=tavily_rag
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
from via.bounded_contexts.recommendation.infrastructure.tavily_rag_provider import (
    _build_tavily_query,
)
from via.config import load_settings
from via.shared.runtime.application_runtime import build_recommendation_drafting_provider


_GAPS = [
    GapData(
        criterion_id="contenido_arena",
        phase_id="instalacion_establecimiento",
        most_limiting_period="site_static",
        observed_value=6.4,
        optimal_limit=25.0,
        gap_value=-18.6,
        criterion_name="contenido_arena",
        criterion_label="Contenido arena",
        criterion_group="suelo",
        unit="%",
        phase_name="instalacion_establecimiento",
        gap_direction="below_optimum",
        severity="alta",
    ),
    GapData(
        criterion_id="deficit_hidrico",
        phase_id="instalacion_establecimiento",
        most_limiting_period="site_static",
        observed_value=1808.0,
        optimal_limit=400.0,
        gap_value=1408.0,
        criterion_name="deficit_hidrico",
        criterion_label="Deficit hidrico",
        criterion_group="clima",
        unit="mm",
        phase_name="instalacion_establecimiento",
        gap_direction="above_optimum",
        severity="alta",
    ),
    GapData(
        criterion_id="carbono_organico_suelo",
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
    ),
    GapData(
        criterion_id="reaccion_suelo_ph",
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
    ),
]


def main() -> None:
    print("=== VIA - Tavily Smoke Test ===\n")

    settings = load_settings()
    if settings.llm_drafting_provider != "tavily_rag":
        print(
            f"ERROR: LLM_DRAFTING_PROVIDER={settings.llm_drafting_provider!r}. "
            "Debe ser 'tavily_rag'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Tavily key : {str(settings.tavily_api_key or '')[:12]}...")
    print(f"Max results: {settings.tavily_max_results}")
    print(f"Depth      : {settings.tavily_search_depth}")
    domains = settings.openai_web_search_allowed_domains
    print(f"Domains    : {', '.join(domains) or '(sin filtro — búsqueda libre)'}")
    print()

    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="mandarina_murcott",
            score=0.4142,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=_GAPS,
        ),
        evidence=[],
    )

    query = _build_tavily_query(context)
    print(f"Query generada:\n  {query!r}\n")

    # ── Paso 1: Tavily solo (sin LLM) ─────────────────────────────────────────
    from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
        TavilySearchClient,
        TavilySearchConfig,
    )

    tavily = TavilySearchClient(
        TavilySearchConfig(
            api_key=str(settings.tavily_api_key),
            max_results=settings.tavily_max_results,
            search_depth=settings.tavily_search_depth,
            include_domains=domains,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )

    print("Llamando a Tavily API...")
    response = tavily.search(query)

    print(f"\n=== RESULTADOS TAVILY ({len(response.results)} resultado(s)) ===")
    if not response.results:
        print("  (sin resultados — dominio o query sin match en Tavily)")
        print("\n>>> DIAGNÓSTICO: Tavily devolvió 0 resultados.")
        print("    Posibles causas:")
        print("    1. Los dominios en OPENAI_WEB_SEARCH_ALLOWED_DOMAINS no están indexados por Tavily.")
        print("    2. La query no matchea contenido en esos dominios.")
        print("    3. Free tier limitado. Prueba con include_domains vacío.")
    else:
        for i, r in enumerate(response.results, 1):
            print(f"\n[{i}] {r.title}")
            print(f"    URL  : {r.url}")
            print(f"    Score: {r.score:.3f}")
            print(f"    Texto: {r.content[:200]}...")

    # ── Paso 2: Si no hay resultados, prueba sin filtro de dominios ───────────
    if not response.results and domains:
        print("\n>>> Probando sin include_domains para diagnóstico...")
        tavily_libre = TavilySearchClient(
            TavilySearchConfig(
                api_key=str(settings.tavily_api_key),
                max_results=3,
                search_depth="basic",
                include_domains=(),
                timeout_seconds=settings.llm_timeout_seconds,
            )
        )
        libre_response = tavily_libre.search(query)
        print(f"\n=== SIN FILTRO DE DOMINIOS ({len(libre_response.results)} resultado(s)) ===")
        for i, r in enumerate(libre_response.results, 1):
            print(f"\n[{i}] {r.title}")
            print(f"    URL  : {r.url}")
            print(f"    Score: {r.score:.3f}")
            print(f"    Texto: {r.content[:200]}...")

    # ── Paso 3: Full pipeline con LLM (solo si hay resultados) ───────────────
    if response.results:
        print("\n>>> Corriendo pipeline completo (Tavily -> LLM)...")
        provider = build_recommendation_drafting_provider(settings)
        try:
            text = provider.draft(context)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        trace = getattr(provider, "get_last_trace", lambda: None)()
        print("\n=== RECOMENDACION GENERADA ===")
        print(text)

        if trace:
            artifact_dir = ROOT / "artifacts" / "tavily_rag"
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
