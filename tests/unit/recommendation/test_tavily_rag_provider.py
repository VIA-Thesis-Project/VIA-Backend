"""Unit tests for TavilyRagDraftingProvider."""

from __future__ import annotations

from uuid import uuid4

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    GapData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.infrastructure.jina_reader_client import (
    JinaReaderClient,
    JinaReaderConfig,
)
from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
    TavilySearchClient,
    TavilySearchConfig,
)
from via.bounded_contexts.recommendation.infrastructure.tavily_rag_provider import (
    TavilyRagConfig,
    TavilyRagDraftingProvider,
    _actionable_gaps,
    _build_tavily_queries,
    _build_tavily_query,
)

_VALID_JSON = (
    '{"schema_version":"recommendation_structured_v1",'
    '"summary":"Recomendacion Tavily RAG.",'
    '"gap_recommendations":[{"gap_key":"reaccion_suelo_ph|instalacion_establecimiento",'
    '"criterion_name":"reaccion_suelo_ph","criterion_group":"suelo",'
    '"recommendation":"Aplicar enmiendas calcáreas para corregir pH.",'
    '"rationale":"Fuente INIA indica pH óptimo 5.5-7.0 para cítricos.",'
    '"evidence_used":[{"source_file_id":"https://inia.gob.pe/citricos-ph",'
    '"source_filename":"inia.gob.pe","quote_summary":"pH óptimo 5.5-7.0 cítricos"}],'
    '"confidence":"media"}],'
    '"overall_limitations":"Evidencia de dominio restringido."}'
)


class FakeTavilyClient:
    def __init__(self, results=None) -> None:
        self.calls: list[str] = []
        self._results = results if results is not None else [
            {"url": "https://inia.gob.pe/citricos-ph", "title": "INIA Cítricos pH", "content": "pH óptimo 5.5-7.0", "score": 0.9},
        ]

    def search(self, query: str):
        self.calls.append(query)
        from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
            TavilySearchResponse, TavilySearchResult,
        )
        return TavilySearchResponse(
            query=query,
            results=[
                TavilySearchResult(
                    url=r["url"], title=r["title"], content=r["content"], score=r["score"]
                )
                for r in self._results
            ],
        )


class FakeOpenAIClient:
    def __init__(self, response: str = _VALID_JSON) -> None:
        self.calls: list[dict] = []
        self._response = response

    def create_completion(self, *, model, messages, timeout, max_output_tokens=None) -> str:
        self.calls.append({"model": model, "messages": messages})
        return self._response


def _config() -> TavilyRagConfig:
    return TavilyRagConfig(
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
        prompt_version="test",
        timeout_seconds=30,
        tavily_api_key="tvly-test",
        include_domains=("inia.gob.pe", "fao.org"),
        max_output_tokens=500,
    )


def _context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="mandarina_murcott",
            score=0.42,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="ph",
                    phase_id="instalacion",
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
                )
            ],
        ),
        evidence=[],
    )


def test_provider_calls_tavily_then_llm() -> None:
    tavily = FakeTavilyClient()
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(_config(), tavily_client=tavily, openai_client=openai)

    text = provider.draft(_context())

    assert len(tavily.calls) >= 1
    assert all("mandarina murcott" in q for q in tavily.calls)
    assert len(openai.calls) == 1
    assert "Recomendacion Tavily RAG" in text


def test_provider_trace_records_tavily_results_and_urls() -> None:
    tavily = FakeTavilyClient()
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(_config(), tavily_client=tavily, openai_client=openai)

    provider.draft(_context())
    trace = provider.get_last_trace()

    assert trace is not None
    assert "https://inia.gob.pe/citricos-ph" in trace.source_urls
    assert any(r["url"] == "https://inia.gob.pe/citricos-ph" for r in trace.tavily_results)
    assert len(trace.tavily_queries) >= 1
    assert trace.jina_enriched_urls == []


def test_provider_with_jina_enrichment() -> None:
    def _fake_http_get(url: str, *, headers: dict, timeout: int) -> str:
        return "# INIA Cítricos\nPH óptimo 5.5 a 7.0. " * 30

    fake_jina = JinaReaderClient(
        JinaReaderConfig(max_chars_per_doc=2000, min_chars_threshold=10, max_urls=3),
        http_get=_fake_http_get,
    )

    tavily = FakeTavilyClient()
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(
        _config(), tavily_client=tavily, jina_client=fake_jina, openai_client=openai
    )

    provider.draft(_context())
    trace = provider.get_last_trace()

    assert trace is not None
    assert trace.jina_enriched_urls == ["https://inia.gob.pe/citricos-ph"]
    user_msg = openai.calls[0]["messages"][1]["content"]
    assert "CONTENIDO COMPLETO" in user_msg
    assert "Jina Reader" in user_msg


def test_provider_warns_when_tavily_returns_no_results() -> None:
    tavily = FakeTavilyClient(results=[])
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(_config(), tavily_client=tavily, openai_client=openai)

    provider.draft(_context())
    trace = provider.get_last_trace()

    assert trace is not None
    assert any("Tavily" in w for w in trace.warnings)
    assert trace.source_urls == []


def test_provider_includes_domain_list_in_user_prompt() -> None:
    tavily = FakeTavilyClient()
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(_config(), tavily_client=tavily, openai_client=openai)

    provider.draft(_context())

    user_msg = openai.calls[0]["messages"][1]["content"]
    assert "inia.gob.pe" in user_msg
    assert "fao.org" in user_msg


def test_build_tavily_query_includes_crop_and_criterion_groups() -> None:
    ctx = _context()
    query = _build_tavily_query(ctx)

    assert "mandarina murcott" in query
    assert "reaccion_suelo_ph" not in query  # criterion names must not leak into search query
    assert "Reaccion suelo pH" not in query  # criterion labels must not leak into search query


def test_build_tavily_queries_returns_one_per_group() -> None:
    from via.bounded_contexts.recommendation.application.ports import (
        CropEvaluationResultData,
        GapData,
        RecommendationDraftContext,
    )
    from dataclasses import replace
    from uuid import uuid4

    clima_gap = GapData(
        criterion_id="deficit_hidrico",
        phase_id="instalacion",
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
    )
    ctx = _context()
    ctx_multi = replace(
        ctx,
        crop_result=replace(ctx.crop_result, gaps=ctx.crop_result.gaps + [clima_gap]),
    )

    queries = _build_tavily_queries(ctx_multi)

    assert len(queries) == 2  # suelo + clima
    groups_in_queries = " ".join(queries)
    assert "riego" in groups_in_queries or "deficit" in groups_in_queries  # clima template
    assert "materia organica" in groups_in_queries or "suelo" in groups_in_queries  # suelo template
    assert all("mandarina murcott" in q for q in queries)


def test_structural_gaps_are_excluded_from_actionable() -> None:
    from via.bounded_contexts.recommendation.application.ports import (
        CropEvaluationResultData,
        GapData,
        RecommendationDraftContext,
    )
    from dataclasses import replace

    ctx = _context()
    structural_gap = GapData(
        criterion_id="aptitud_altitudinal",
        phase_id="instalacion",
        most_limiting_period="site_static",
        observed_value=3500.0,
        optimal_limit=1800.0,
        gap_value=1700.0,
        criterion_name="aptitud_altitudinal",
        criterion_label="Aptitud altitudinal",
        criterion_group="suelo",
        unit="msnm",
        phase_name="instalacion_establecimiento",
        gap_direction="above_optimum",
        severity="alta",
        intervention_class="STRUCTURAL",
    )
    ctx_with_structural = replace(
        ctx,
        crop_result=replace(ctx.crop_result, gaps=ctx.crop_result.gaps + [structural_gap]),
    )

    actionable = _actionable_gaps(ctx_with_structural)

    assert len(actionable) == len(ctx.crop_result.gaps)  # structural gap excluded
    assert all(g.criterion_id != "aptitud_altitudinal" for g in actionable)


def test_structural_gaps_generate_warning_in_trace() -> None:
    from via.bounded_contexts.recommendation.application.ports import GapData
    from dataclasses import replace

    structural_gap = GapData(
        criterion_id="aptitud_altitudinal",
        phase_id="instalacion",
        most_limiting_period="site_static",
        observed_value=3500.0,
        optimal_limit=1800.0,
        gap_value=1700.0,
        criterion_name="aptitud_altitudinal",
        criterion_label="Aptitud altitudinal",
        criterion_group="suelo",
        unit="msnm",
        phase_name="instalacion_establecimiento",
        gap_direction="above_optimum",
        severity="alta",
        intervention_class="STRUCTURAL",
    )
    ctx = _context()
    ctx_with_structural = replace(
        ctx,
        crop_result=replace(ctx.crop_result, gaps=ctx.crop_result.gaps + [structural_gap]),
    )

    tavily = FakeTavilyClient()
    openai = FakeOpenAIClient()
    provider = TavilyRagDraftingProvider(_config(), tavily_client=tavily, openai_client=openai)
    provider.draft(ctx_with_structural)
    trace = provider.get_last_trace()

    assert trace is not None
    assert any("STRUCTURAL" in w for w in trace.warnings)
