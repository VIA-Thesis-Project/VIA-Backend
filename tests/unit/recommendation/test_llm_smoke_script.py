"""Tests for the manual LLM smoke script without real HTTP calls."""

from __future__ import annotations

from pathlib import Path

from scripts import llm_smoke_test
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import LocalHttpLlmDraftingProvider
from via.config import ConfigurationError, load_settings


ROOT = Path(__file__).resolve().parents[3]


def test_smoke_script_provider_requires_local_http() -> None:
    settings = load_settings({})

    try:
        llm_smoke_test._provider_from_settings(settings)
    except ConfigurationError as exc:
        assert "LLM_DRAFTING_PROVIDER must be local_http" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError")


def test_smoke_script_builds_local_http_provider_from_settings() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "local_http",
            "LLM_LOCAL_HTTP_ENDPOINT": "http://localhost:11434/api/generate",
            "LLM_MODEL": "gemma:2b",
            "LLM_TIMEOUT_SECONDS": "9",
            "LLM_MAX_PROMPT_CHARS": "5000",
        }
    )

    provider = llm_smoke_test._provider_from_settings(settings)

    assert isinstance(provider, LocalHttpLlmDraftingProvider)


def test_smoke_script_context_contains_only_precomputed_recommendation_data() -> None:
    context = llm_smoke_test._example_context()

    assert context.crop_result.score == 0.82
    assert context.crop_result.rank_position == 1
    assert context.crop_result.gaps[0].gap_value == -4.0
    assert context.evidence[0].text


def test_smoke_script_documentation_records_http_contract() -> None:
    source = (ROOT / "docs" / "llm_smoke_test.md").read_text(encoding="utf-8")

    assert '"model"' in source
    assert '"prompt"' in source
    assert '"stream": false' in source
    assert '"response"' in source
    assert "Ollama-style" in source
