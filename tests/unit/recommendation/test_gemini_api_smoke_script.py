"""Tests for the manual Gemini API smoke script without real API calls."""

from __future__ import annotations

from pathlib import Path

from scripts import gemini_api_smoke_test
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import GeminiApiDraftingProvider
from via.config import ConfigurationError, load_settings


ROOT = Path(__file__).resolve().parents[3]


def test_gemini_smoke_script_requires_gemini_api_provider() -> None:
    settings = load_settings({})

    try:
        gemini_api_smoke_test._provider_from_settings(settings)
    except ConfigurationError as exc:
        assert "LLM_DRAFTING_PROVIDER must be gemini_api" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError")


def test_gemini_smoke_script_builds_provider_from_settings_without_calling_gemini() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "gemini_api",
            "GEMINI_API_KEY": "secret-key",
            "GEMINI_API_MODEL": "gemma-3-27b-it",
            "GEMINI_API_TIMEOUT_SECONDS": "12",
        }
    )

    provider = gemini_api_smoke_test._provider_from_settings(settings)

    assert isinstance(provider, GeminiApiDraftingProvider)


def test_gemini_smoke_script_context_contains_only_precomputed_recommendation_data() -> None:
    context = gemini_api_smoke_test._example_context()

    assert context.crop_result.score == 0.82
    assert context.crop_result.rank_position == 1
    assert context.crop_result.gaps[0].gap_value == -4.0
    assert context.evidence[0].text


def test_gemini_smoke_documentation_records_generate_content_contract() -> None:
    source = (ROOT / "docs" / "gemini_api_smoke_test.md").read_text(encoding="utf-8")

    assert "/models/{GEMINI_API_MODEL}:generateContent" in source
    assert "x-goog-api-key" in source
    assert '"contents"' in source
    assert '"parts"' in source
    assert '"candidates"' in source
