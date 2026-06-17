"""Tests for the manual Vertex Gemma smoke script without Google Cloud calls."""

from __future__ import annotations

from pathlib import Path

from scripts import vertex_gemma_smoke_test
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import VertexGemmaDraftingProvider
from via.config import ConfigurationError, load_settings


ROOT = Path(__file__).resolve().parents[3]


def test_vertex_smoke_script_requires_vertex_gemma_provider() -> None:
    settings = load_settings({})

    try:
        vertex_gemma_smoke_test._provider_from_settings(settings)
    except ConfigurationError as exc:
        assert "LLM_DRAFTING_PROVIDER must be vertex_gemma" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError")


def test_vertex_smoke_script_builds_provider_from_settings_without_calling_vertex() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "vertex_gemma",
            "VERTEX_AI_PROJECT_ID": "via-project",
            "VERTEX_AI_LOCATION": "us-central1",
            "VERTEX_AI_ENDPOINT_ID": "123456789",
            "VERTEX_AI_TIMEOUT_SECONDS": "12",
            "LLM_MODEL": "gemma-2-9b-it",
        }
    )

    provider = vertex_gemma_smoke_test._provider_from_settings(settings)

    assert isinstance(provider, VertexGemmaDraftingProvider)


def test_vertex_smoke_script_context_contains_only_precomputed_recommendation_data() -> None:
    context = vertex_gemma_smoke_test._example_context()

    assert context.crop_result.score == 0.82
    assert context.crop_result.rank_position == 1
    assert context.crop_result.gaps[0].gap_value == -4.0
    assert context.evidence[0].text


def test_vertex_smoke_documentation_records_contract() -> None:
    source = (ROOT / "docs" / "vertex_gemma_smoke_test.md").read_text(encoding="utf-8")

    assert "PredictionServiceClient.predict" in source
    assert "projects/{VERTEX_AI_PROJECT_ID}" in source
    assert '"prompt"' in source
    assert '"response"' in source
