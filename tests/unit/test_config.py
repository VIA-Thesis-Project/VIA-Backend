"""Unit tests for centralized VIA configuration."""

from __future__ import annotations

import pytest

from via.config import (
    DEFAULT_APP_NAME,
    DEFAULT_DOCUMENTAL_SCHEMA,
    DEFAULT_MCDA_CONDICIONAL_THRESHOLD,
    DEFAULT_MCDA_ENTROPY_MIN_DIVERGENCE,
    DEFAULT_MCDA_MIN_TEMPORAL_SERIES_LENGTH,
    DEFAULT_MCDA_PENALIZE_EPSILON,
    DEFAULT_MCDA_VIABLE_THRESHOLD,
    DEFAULT_RULEBOOK_WEIGHT_TOLERANCE,
    DEFAULT_TRANSACTIONAL_SCHEMA,
    ConfigurationError,
    load_settings,
)


def test_default_settings_match_lote1_contract() -> None:
    settings = load_settings({})

    assert settings.app_name == DEFAULT_APP_NAME
    assert settings.app_name == "VIA - Viabilidad Inteligente Agrícola"
    assert settings.database_url.startswith("postgresql+psycopg2://")
    assert settings.db_schema_transactional == DEFAULT_TRANSACTIONAL_SCHEMA
    assert settings.db_schema_documental == DEFAULT_DOCUMENTAL_SCHEMA
    assert settings.mcda_alpha == 0.7
    assert settings.mcda_min_temporal_series_length == DEFAULT_MCDA_MIN_TEMPORAL_SERIES_LENGTH
    assert settings.mcda_entropy_min_divergence == DEFAULT_MCDA_ENTROPY_MIN_DIVERGENCE
    assert settings.mcda_viable_threshold == DEFAULT_MCDA_VIABLE_THRESHOLD
    assert settings.mcda_condicional_threshold == DEFAULT_MCDA_CONDICIONAL_THRESHOLD
    assert settings.mcda_penalize_epsilon == DEFAULT_MCDA_PENALIZE_EPSILON
    assert settings.rulebook_weight_tolerance == DEFAULT_RULEBOOK_WEIGHT_TOLERANCE
    assert settings.gee_enabled is False
    assert settings.gee_project is None
    assert settings.gee_service_account is None
    assert settings.gee_private_key_file is None
    assert settings.gee_timeout_seconds == 60
    assert settings.gee_max_retries == 3
    assert settings.llm_drafting_provider == "template"
    assert settings.llm_local_http_endpoint is None
    assert settings.llm_model is None
    assert settings.llm_timeout_seconds == 30
    assert settings.llm_max_prompt_chars == 12000
    assert settings.vertex_ai_project_id is None
    assert settings.vertex_ai_location is None
    assert settings.vertex_ai_endpoint_id is None
    assert settings.vertex_ai_timeout_seconds == 30
    assert settings.gemini_api_key is None
    assert settings.gemini_api_model is None
    assert settings.gemini_api_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert settings.gemini_api_timeout_seconds == 30
    assert settings.gemini_api_max_output_tokens == 2048


def test_gee_disabled_does_not_require_credentials() -> None:
    settings = load_settings({"GEE_ENABLED": "false"})

    assert settings.gee_enabled is False
    assert settings.gee_project is None


def test_gee_settings_are_loaded_when_enabled() -> None:
    settings = load_settings(
        {
            "GEE_ENABLED": "true",
            "GEE_PROJECT": "via-project",
            "GEE_SERVICE_ACCOUNT": "via@example.iam.gserviceaccount.com",
            "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
            "GEE_TIMEOUT_SECONDS": "45",
            "GEE_MAX_RETRIES": "2",
        }
    )

    assert settings.gee_enabled is True
    assert settings.gee_project == "via-project"
    assert settings.gee_service_account == "via@example.iam.gserviceaccount.com"
    assert settings.gee_private_key_file == "C:/keys/gee.json"
    assert settings.gee_timeout_seconds == 45
    assert settings.gee_max_retries == 2


def test_llm_local_http_settings_are_loaded() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "local_http",
            "LLM_LOCAL_HTTP_ENDPOINT": "http://localhost:11434/api/generate",
            "LLM_MODEL": "gemma:2b",
            "LLM_TIMEOUT_SECONDS": "45",
            "LLM_MAX_PROMPT_CHARS": "4000",
        }
    )

    assert settings.llm_drafting_provider == "local_http"
    assert settings.llm_local_http_endpoint == "http://localhost:11434/api/generate"
    assert settings.llm_model == "gemma:2b"
    assert settings.llm_timeout_seconds == 45
    assert settings.llm_max_prompt_chars == 4000


def test_vertex_gemma_settings_are_loaded() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "vertex_gemma",
            "VERTEX_AI_PROJECT_ID": "via-project",
            "VERTEX_AI_LOCATION": "us-central1",
            "VERTEX_AI_ENDPOINT_ID": "123456789",
            "VERTEX_AI_TIMEOUT_SECONDS": "55",
            "LLM_MODEL": "gemma-2-9b-it",
        }
    )

    assert settings.llm_drafting_provider == "vertex_gemma"
    assert settings.vertex_ai_project_id == "via-project"
    assert settings.vertex_ai_location == "us-central1"
    assert settings.vertex_ai_endpoint_id == "123456789"
    assert settings.vertex_ai_timeout_seconds == 55
    assert settings.llm_model == "gemma-2-9b-it"


def test_gemini_api_settings_are_loaded() -> None:
    settings = load_settings(
        {
            "LLM_DRAFTING_PROVIDER": "gemini_api",
            "GEMINI_API_KEY": "secret-key",
            "GEMINI_API_MODEL": "gemma-3-27b-it",
            "GEMINI_API_BASE_URL": "https://example.test/v1beta",
            "GEMINI_API_TIMEOUT_SECONDS": "42",
            "GEMINI_API_MAX_OUTPUT_TOKENS": "3000",
            "LLM_MAX_PROMPT_CHARS": "6000",
        }
    )

    assert settings.llm_drafting_provider == "gemini_api"
    assert settings.gemini_api_key == "secret-key"
    assert settings.gemini_api_model == "gemma-3-27b-it"
    assert settings.gemini_api_base_url == "https://example.test/v1beta"
    assert settings.gemini_api_timeout_seconds == 42
    assert settings.gemini_api_max_output_tokens == 3000
    assert settings.llm_max_prompt_chars == 6000


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LLM_DRAFTING_PROVIDER", "unknown"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_MAX_PROMPT_CHARS", "0"),
        ("VERTEX_AI_TIMEOUT_SECONDS", "0"),
        ("GEMINI_API_TIMEOUT_SECONDS", "0"),
        ("GEMINI_API_MAX_OUTPUT_TOKENS", "0"),
        ("GEMINI_API_BASE_URL", " "),
    ],
)
def test_llm_settings_reject_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({key: value})


@pytest.mark.parametrize("missing_key", ["LLM_LOCAL_HTTP_ENDPOINT", "LLM_MODEL"])
def test_llm_local_http_requires_endpoint_and_model(missing_key: str) -> None:
    environ = {
        "LLM_DRAFTING_PROVIDER": "local_http",
        "LLM_LOCAL_HTTP_ENDPOINT": "http://localhost:11434/api/generate",
        "LLM_MODEL": "gemma:2b",
    }
    environ.pop(missing_key)

    with pytest.raises(ConfigurationError, match=missing_key):
        load_settings(environ)


@pytest.mark.parametrize("missing_key", ["VERTEX_AI_PROJECT_ID", "VERTEX_AI_LOCATION", "VERTEX_AI_ENDPOINT_ID", "LLM_MODEL"])
def test_vertex_gemma_requires_project_location_endpoint_and_model(missing_key: str) -> None:
    environ = {
        "LLM_DRAFTING_PROVIDER": "vertex_gemma",
        "VERTEX_AI_PROJECT_ID": "via-project",
        "VERTEX_AI_LOCATION": "us-central1",
        "VERTEX_AI_ENDPOINT_ID": "123456789",
        "LLM_MODEL": "gemma-2-9b-it",
    }
    environ.pop(missing_key)

    with pytest.raises(ConfigurationError, match=missing_key):
        load_settings(environ)


@pytest.mark.parametrize("missing_key", ["GEMINI_API_KEY", "GEMINI_API_MODEL"])
def test_gemini_api_requires_key_and_model(missing_key: str) -> None:
    environ = {
        "LLM_DRAFTING_PROVIDER": "gemini_api",
        "GEMINI_API_KEY": "secret-key",
        "GEMINI_API_MODEL": "gemma-3-27b-it",
    }
    environ.pop(missing_key)

    with pytest.raises(ConfigurationError, match=missing_key):
        load_settings(environ)


@pytest.mark.parametrize("missing_key", ["GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE"])
def test_gee_enabled_requires_project_and_credentials(missing_key: str) -> None:
    environ = {
        "GEE_ENABLED": "true",
        "GEE_PROJECT": "via-project",
        "GEE_SERVICE_ACCOUNT": "via@example.iam.gserviceaccount.com",
        "GEE_PRIVATE_KEY_FILE": "C:/keys/gee.json",
    }
    environ.pop(missing_key)

    with pytest.raises(ConfigurationError, match=missing_key):
        load_settings(environ)


@pytest.mark.parametrize(("key", "value"), [("GEE_TIMEOUT_SECONDS", "0"), ("GEE_MAX_RETRIES", "-1")])
def test_gee_numeric_settings_reject_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({key: value})


@pytest.mark.parametrize("alpha", ["-0.1", "1.1", "invalid"])
def test_mcda_alpha_must_be_in_closed_unit_interval(alpha: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"MCDA_ALPHA": alpha})


def test_mcda_additional_settings_are_loaded_from_environment() -> None:
    settings = load_settings(
        {
            "MCDA_MIN_TEMPORAL_SERIES_LENGTH": "4",
            "MCDA_ENTROPY_MIN_DIVERGENCE": "0.000001",
            "MCDA_VIABLE_THRESHOLD": "0.8",
            "MCDA_CONDICIONAL_THRESHOLD": "0.5",
            "MCDA_PENALIZE_EPSILON": "0.02",
        }
    )

    assert settings.mcda_min_temporal_series_length == 4
    assert settings.mcda_entropy_min_divergence == 0.000001
    assert settings.mcda_viable_threshold == 0.8
    assert settings.mcda_condicional_threshold == 0.5
    assert settings.mcda_penalize_epsilon == 0.02


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MCDA_MIN_TEMPORAL_SERIES_LENGTH", "1"),
        ("MCDA_ENTROPY_MIN_DIVERGENCE", "0"),
        ("MCDA_VIABLE_THRESHOLD", "1.1"),
        ("MCDA_CONDICIONAL_THRESHOLD", "-0.1"),
        ("MCDA_PENALIZE_EPSILON", "0"),
        ("MCDA_PENALIZE_EPSILON", "1.1"),
    ],
)
def test_additional_mcda_settings_reject_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({key: value})


def test_mcda_viable_threshold_must_not_be_below_condicional_threshold() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"MCDA_VIABLE_THRESHOLD": "0.3", "MCDA_CONDICIONAL_THRESHOLD": "0.4"})


def test_relay_worker_poll_interval_must_not_exceed_sixty_seconds() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"RELAY_WORKER_POLL_INTERVAL_SECONDS": "61"})


def test_database_url_must_use_psycopg2_driver() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"DATABASE_URL": "postgresql+" + "async" + "pg://user:pass@localhost/db"})


def test_database_schemas_must_be_isolated() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"DB_SCHEMA_TRANSACTIONAL": "same", "DB_SCHEMA_DOCUMENTAL": "same"})


def test_rulebook_weight_tolerance_must_be_positive() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"RULEBOOK_WEIGHT_TOLERANCE": "0"})
