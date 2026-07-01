"""Unit tests for the optional OpenAI Web Search drafting provider."""

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
from via.bounded_contexts.recommendation.infrastructure.openai_web_search_provider import (
    OpenAIWebSearchConfig,
    OpenAIWebSearchDraftingProvider,
)


class FakeWebSearchClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> str:
        return (
            '{"schema_version":"recommendation_structured_v1",'
            '"summary":"Recomendacion enriquecida con Jina.",'
            '"gap_recommendations":[{"gap_key":"suelo",'
            '"criterion_name":"reaccion_suelo_ph","criterion_group":"suelo",'
            '"recommendation":"Validar pH con fuente PDF completa.",'
            '"rationale":"Fuente PDF completa via Jina Reader.",'
            '"evidence_used":[{"source_file_id":"https://midagri.gob.pe/suelo",'
            '"source_filename":"midagri.gob.pe","quote_summary":"pH optimo citricos"}],'
            '"confidence":"alta"}],"overall_limitations":"Modo web con Jina."}'
        )

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "resp_web_123",
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_123",
                    "action": {
                        "sources": [
                            {
                                "url": "https://midagri.gob.pe/suelo",
                                "title": "MIDAGRI suelo",
                                "snippet": "suelo pH citricos",
                            }
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"schema_version":"recommendation_structured_v1",'
                                '"summary":"Recomendacion con web search.",'
                                '"gap_recommendations":[{"gap_key":"suelo",'
                                '"criterion_name":"reaccion_suelo_ph",'
                                '"criterion_group":"suelo",'
                                '"recommendation":"Validar pH con analisis de suelo.",'
                                '"rationale":"La evidencia web tecnica menciona suelo y pH.",'
                                '"evidence_used":[{"source_file_id":"https://midagri.gob.pe/suelo",'
                                '"source_filename":"midagri.gob.pe",'
                                '"quote_summary":"suelo pH"}],'
                                '"confidence":"media"}],'
                                '"overall_limitations":"Modo web experimental."}'
                            ),
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "start_index": 260,
                                    "end_index": 280,
                                    "url": "https://midagri.gob.pe/suelo",
                                    "title": "MIDAGRI suelo",
                                }
                            ],
                        }
                    ],
                },
            ],
        }


class FakeTextOnlyCitationClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "resp_web_text_only",
            "output": [
                {"type": "web_search_call", "id": "ws_text_only", "action": {}},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"schema_version":"recommendation_structured_v1",'
                                '"summary":"Recomendacion con URL textual.",'
                                '"gap_recommendations":[{"criterion_name":"contenido_arena",'
                                '"criterion_group":"suelo",'
                                '"recommendation":"Validar textura y drenaje con analisis de suelo.",'
                                '"evidence_used":[{"source_file_id":"https://edis.ifas.ufl.edu/publication/CH085",'
                                '"quote_summary":"suelo citricos textura arena drenaje"}],'
                                '"confidence":"baja"}]}'
                            ),
                        }
                    ],
                },
            ],
        }


def test_web_search_provider_builds_tool_and_trace() -> None:
    client = FakeWebSearchClient()
    provider = OpenAIWebSearchDraftingProvider(
        OpenAIWebSearchConfig(
            api_key="key",
            model="gpt-4o-mini",
            prompt_version="test",
            timeout_seconds=30,
            allowed_domains=("midagri.gob.pe", "fao.org"),
            search_context_size="high",
            user_country="PE",
            user_region="Lima",
            max_output_tokens=500,
        ),
        client=client,
    )

    text = provider.draft(_context())
    trace = provider.get_last_trace()

    assert "Recomendacion con web search" in text
    assert trace is not None
    assert trace.response_id == "resp_web_123"
    assert trace.web_search_call_ids == ["ws_123"]
    assert trace.source_urls == ["https://midagri.gob.pe/suelo"]
    assert trace.retrieved_results[0]["source_domain"] == "midagri.gob.pe"

    tool = client.calls[0]["tool"]
    assert tool["type"] == "web_search"
    assert tool["search_context_size"] == "high"
    assert "filters" not in tool
    assert tool["user_location"] == {
        "type": "approximate",
        "country": "PE",
        "region": "Lima",
    }


def test_web_search_provider_recovers_text_only_urls() -> None:
    provider = OpenAIWebSearchDraftingProvider(
        OpenAIWebSearchConfig(
            api_key="key",
            model="gpt-4o-mini",
            prompt_version="test",
            timeout_seconds=30,
            allowed_domains=(),
            search_context_size="medium",
            user_country=None,
            user_region=None,
            max_output_tokens=500,
        ),
        client=FakeTextOnlyCitationClient(),
    )

    provider.draft(_context())
    trace = provider.get_last_trace()

    assert trace is not None
    assert trace.source_urls == ["https://edis.ifas.ufl.edu/publication/CH085"]
    assert trace.retrieved_results[0]["source_domain"] == "edis.ifas.ufl.edu"
    assert "contenido_arena" in trace.retrieved_results[0]["text"]
    assert "suelo citricos textura arena drenaje" in trace.retrieved_results[0]["text"]


def test_web_search_provider_ignores_placeholder_urls() -> None:
    class FakePlaceholderClient:
        def create_response(self, **kwargs):
            return {
                "id": "resp_web_placeholder",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"schema_version":"recommendation_structured_v1",'
                                    '"summary":"Sin fuente real.",'
                                    '"gap_recommendations":[{"criterion_name":"contenido_arena",'
                                    '"evidence_used":[{"source_file_id":"https://example.com/soil"}]}]}'
                                ),
                            }
                        ],
                    }
                ],
            }

    provider = OpenAIWebSearchDraftingProvider(
        OpenAIWebSearchConfig(
            api_key="key",
            model="gpt-4o-mini",
            prompt_version="test",
            timeout_seconds=30,
            allowed_domains=(),
            search_context_size="medium",
            user_country=None,
            user_region=None,
            max_output_tokens=500,
        ),
        client=FakePlaceholderClient(),
    )

    provider.draft(_context())
    trace = provider.get_last_trace()

    assert trace is not None
    assert trace.source_urls == []
    assert trace.retrieved_results == []


def test_jina_second_pass_enriches_draft_and_records_urls() -> None:
    """Provider uses Jina Reader when jina_client is supplied and URLs are found."""

    def _fake_http_get(url: str, *, headers: dict, timeout: int) -> str:
        return ("# Documento técnico\nContenido sobre pH del suelo y cítricos de Perú. " * 30)

    fake_jina = JinaReaderClient(
        JinaReaderConfig(max_chars_per_doc=2000, min_chars_threshold=10, max_urls=3),
        http_get=_fake_http_get,
    )

    provider = OpenAIWebSearchDraftingProvider(
        OpenAIWebSearchConfig(
            api_key="key",
            model="gpt-4o-mini",
            prompt_version="test",
            timeout_seconds=30,
            allowed_domains=("midagri.gob.pe",),
            search_context_size="medium",
            user_country="PE",
            user_region=None,
            max_output_tokens=500,
        ),
        client=FakeWebSearchClient(),
        jina_client=fake_jina,
    )

    text = provider.draft(_context())
    trace = provider.get_last_trace()

    assert "enriquecida con Jina" in text
    assert trace is not None
    assert len(trace.jina_enriched_urls) == 1
    assert trace.jina_enriched_urls[0] == "https://midagri.gob.pe/suelo"


def _context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="mandarina_murcott",
            score=0.42,
            rank_position=2,
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
