"""Centralized environment configuration for VIA."""

from __future__ import annotations

from dataclasses import dataclass
from os import environ as process_environ
from typing import Mapping


DEFAULT_APP_NAME = "VIA - Viabilidad Inteligente Agrícola"
DEFAULT_DATABASE_URL = "postgresql+psycopg2://user:pass@localhost:5432/agri_viability"
DEFAULT_TRANSACTIONAL_SCHEMA = "transactional"
DEFAULT_DOCUMENTAL_SCHEMA = "documental"
DEFAULT_JWT_SECRET_KEY = "dev-only-change-me-secret"
DEFAULT_JWT_ALGORITHM = "HS256"
DEFAULT_JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 60
DEFAULT_JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7
DEFAULT_PARCEL_MAX_AREA_HA = 50000.0
DEFAULT_RULEBOOK_WEIGHT_TOLERANCE = 0.001
DEFAULT_GEE_ENABLED = False
DEFAULT_GEE_TIMEOUT_SECONDS = 60
DEFAULT_GEE_MAX_RETRIES = 3
DEFAULT_MCDA_MIN_TEMPORAL_SERIES_LENGTH = 3
DEFAULT_MCDA_ENTROPY_MIN_DIVERGENCE = 1e-9
DEFAULT_MCDA_VIABLE_THRESHOLD = 0.70
DEFAULT_MCDA_CONDICIONAL_THRESHOLD = 0.40
DEFAULT_MCDA_PENALIZE_EPSILON = 0.01
DEFAULT_LLM_DRAFTING_PROVIDER = "template"
DEFAULT_LLM_TIMEOUT_SECONDS = 30
DEFAULT_LLM_MAX_PROMPT_CHARS = 12000
DEFAULT_VERTEX_AI_TIMEOUT_SECONDS = 30
DEFAULT_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_API_TIMEOUT_SECONDS = 30
DEFAULT_GEMINI_API_MAX_OUTPUT_TOKENS = 2048


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings loaded from environment variables."""

    app_name: str
    database_url: str
    db_schema_transactional: str
    db_schema_documental: str
    mcda_alpha: float
    mcda_min_temporal_series_length: int
    mcda_entropy_min_divergence: float
    mcda_viable_threshold: float
    mcda_condicional_threshold: float
    mcda_penalize_epsilon: float
    relay_worker_poll_interval_seconds: int
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_access_token_expire_minutes: int
    jwt_refresh_token_expire_days: int
    parcel_max_area_ha: float
    rulebook_weight_tolerance: float
    gee_enabled: bool
    gee_project: str | None
    gee_service_account: str | None
    gee_private_key_file: str | None
    gee_timeout_seconds: int
    gee_max_retries: int
    llm_drafting_provider: str
    llm_local_http_endpoint: str | None
    llm_model: str | None
    llm_timeout_seconds: int
    llm_max_prompt_chars: int
    vertex_ai_project_id: str | None
    vertex_ai_location: str | None
    vertex_ai_endpoint_id: str | None
    vertex_ai_timeout_seconds: int
    gemini_api_key: str | None
    gemini_api_model: str | None
    gemini_api_base_url: str
    gemini_api_timeout_seconds: int
    gemini_api_max_output_tokens: int


class ConfigurationError(ValueError):
    """Raised when critical VIA configuration is invalid."""


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load and validate settings from environment-like key/value data."""

    source = process_environ if environ is None else environ
    settings = Settings(
        app_name=source.get("APP_NAME", DEFAULT_APP_NAME),
        database_url=source.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        db_schema_transactional=source.get(
            "DB_SCHEMA_TRANSACTIONAL",
            DEFAULT_TRANSACTIONAL_SCHEMA,
        ),
        db_schema_documental=source.get("DB_SCHEMA_DOCUMENTAL", DEFAULT_DOCUMENTAL_SCHEMA),
        mcda_alpha=_read_float(source, "MCDA_ALPHA", "0.7"),
        mcda_min_temporal_series_length=_read_int(
            source,
            "MCDA_MIN_TEMPORAL_SERIES_LENGTH",
            str(DEFAULT_MCDA_MIN_TEMPORAL_SERIES_LENGTH),
        ),
        mcda_entropy_min_divergence=_read_float(
            source,
            "MCDA_ENTROPY_MIN_DIVERGENCE",
            str(DEFAULT_MCDA_ENTROPY_MIN_DIVERGENCE),
        ),
        mcda_viable_threshold=_read_float(source, "MCDA_VIABLE_THRESHOLD", str(DEFAULT_MCDA_VIABLE_THRESHOLD)),
        mcda_condicional_threshold=_read_float(source, "MCDA_CONDICIONAL_THRESHOLD", str(DEFAULT_MCDA_CONDICIONAL_THRESHOLD)),
        mcda_penalize_epsilon=_read_float(source, "MCDA_PENALIZE_EPSILON", str(DEFAULT_MCDA_PENALIZE_EPSILON)),
        relay_worker_poll_interval_seconds=_read_int(
            source,
            "RELAY_WORKER_POLL_INTERVAL_SECONDS",
            "5",
        ),
        jwt_secret_key=source.get("JWT_SECRET_KEY", DEFAULT_JWT_SECRET_KEY),
        jwt_algorithm=source.get("JWT_ALGORITHM", DEFAULT_JWT_ALGORITHM),
        jwt_access_token_expire_minutes=_read_int(
            source,
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            str(DEFAULT_JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        jwt_refresh_token_expire_days=_read_int(
            source,
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            str(DEFAULT_JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        ),
        parcel_max_area_ha=_read_float(source, "PARCEL_MAX_AREA_HA", str(DEFAULT_PARCEL_MAX_AREA_HA)),
        rulebook_weight_tolerance=_read_float(
            source,
            "RULEBOOK_WEIGHT_TOLERANCE",
            str(DEFAULT_RULEBOOK_WEIGHT_TOLERANCE),
        ),
        gee_enabled=_read_bool(source, "GEE_ENABLED", DEFAULT_GEE_ENABLED),
        gee_project=_read_optional_text(source, "GEE_PROJECT"),
        gee_service_account=_read_optional_text(source, "GEE_SERVICE_ACCOUNT"),
        gee_private_key_file=_read_optional_text(source, "GEE_PRIVATE_KEY_FILE"),
        gee_timeout_seconds=_read_int(source, "GEE_TIMEOUT_SECONDS", str(DEFAULT_GEE_TIMEOUT_SECONDS)),
        gee_max_retries=_read_int(source, "GEE_MAX_RETRIES", str(DEFAULT_GEE_MAX_RETRIES)),
        llm_drafting_provider=source.get("LLM_DRAFTING_PROVIDER", DEFAULT_LLM_DRAFTING_PROVIDER).strip().lower(),
        llm_local_http_endpoint=_read_optional_text(source, "LLM_LOCAL_HTTP_ENDPOINT"),
        llm_model=_read_optional_text(source, "LLM_MODEL"),
        llm_timeout_seconds=_read_int(source, "LLM_TIMEOUT_SECONDS", str(DEFAULT_LLM_TIMEOUT_SECONDS)),
        llm_max_prompt_chars=_read_int(source, "LLM_MAX_PROMPT_CHARS", str(DEFAULT_LLM_MAX_PROMPT_CHARS)),
        vertex_ai_project_id=_read_optional_text(source, "VERTEX_AI_PROJECT_ID"),
        vertex_ai_location=_read_optional_text(source, "VERTEX_AI_LOCATION"),
        vertex_ai_endpoint_id=_read_optional_text(source, "VERTEX_AI_ENDPOINT_ID"),
        vertex_ai_timeout_seconds=_read_int(source, "VERTEX_AI_TIMEOUT_SECONDS", str(DEFAULT_VERTEX_AI_TIMEOUT_SECONDS)),
        gemini_api_key=_read_optional_text(source, "GEMINI_API_KEY"),
        gemini_api_model=_read_optional_text(source, "GEMINI_API_MODEL"),
        gemini_api_base_url=source.get("GEMINI_API_BASE_URL", DEFAULT_GEMINI_API_BASE_URL).strip(),
        gemini_api_timeout_seconds=_read_int(
            source,
            "GEMINI_API_TIMEOUT_SECONDS",
            str(DEFAULT_GEMINI_API_TIMEOUT_SECONDS),
        ),
        gemini_api_max_output_tokens=_read_int(
            source,
            "GEMINI_API_MAX_OUTPUT_TOKENS",
            str(DEFAULT_GEMINI_API_MAX_OUTPUT_TOKENS),
        ),
    )
    validate_settings(settings)
    return settings


def get_settings() -> Settings:
    """Return the current process settings after validation."""

    return load_settings()


def validate_settings(settings: Settings) -> None:
    """Validate critical settings that can make the application unsafe to start."""

    if not settings.database_url.startswith("postgresql+psycopg2://"):
        raise ConfigurationError("DATABASE_URL must use postgresql+psycopg2://")
    if not 0.0 <= settings.mcda_alpha <= 1.0:
        raise ConfigurationError("MCDA_ALPHA must be in [0, 1]")
    if settings.mcda_min_temporal_series_length < 2:
        raise ConfigurationError("MCDA_MIN_TEMPORAL_SERIES_LENGTH must be >= 2")
    if settings.mcda_entropy_min_divergence <= 0:
        raise ConfigurationError("MCDA_ENTROPY_MIN_DIVERGENCE must be positive")
    if not 0.0 <= settings.mcda_viable_threshold <= 1.0:
        raise ConfigurationError("MCDA_VIABLE_THRESHOLD must be in [0, 1]")
    if not 0.0 <= settings.mcda_condicional_threshold <= 1.0:
        raise ConfigurationError("MCDA_CONDICIONAL_THRESHOLD must be in [0, 1]")
    if settings.mcda_viable_threshold < settings.mcda_condicional_threshold:
        raise ConfigurationError("MCDA_VIABLE_THRESHOLD must be >= MCDA_CONDICIONAL_THRESHOLD")
    if not 0.0 < settings.mcda_penalize_epsilon <= 1.0:
        raise ConfigurationError("MCDA_PENALIZE_EPSILON must be in (0, 1]")
    if settings.relay_worker_poll_interval_seconds > 60:
        raise ConfigurationError("RELAY_WORKER_POLL_INTERVAL_SECONDS must not exceed 60")
    if settings.relay_worker_poll_interval_seconds <= 0:
        raise ConfigurationError("RELAY_WORKER_POLL_INTERVAL_SECONDS must be positive")
    if not settings.db_schema_transactional.strip():
        raise ConfigurationError("DB_SCHEMA_TRANSACTIONAL must not be empty")
    if not settings.db_schema_documental.strip():
        raise ConfigurationError("DB_SCHEMA_DOCUMENTAL must not be empty")
    if settings.db_schema_transactional == settings.db_schema_documental:
        raise ConfigurationError("Database schemas must be isolated")
    if not settings.jwt_secret_key.strip():
        raise ConfigurationError("JWT_SECRET_KEY must not be empty")
    if settings.jwt_algorithm != "HS256":
        raise ConfigurationError("JWT_ALGORITHM must be HS256")
    if settings.jwt_access_token_expire_minutes <= 0:
        raise ConfigurationError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
    if settings.jwt_refresh_token_expire_days <= 0:
        raise ConfigurationError("JWT_REFRESH_TOKEN_EXPIRE_DAYS must be positive")
    if settings.parcel_max_area_ha <= 0:
        raise ConfigurationError("PARCEL_MAX_AREA_HA must be positive")
    if settings.rulebook_weight_tolerance <= 0:
        raise ConfigurationError("RULEBOOK_WEIGHT_TOLERANCE must be positive")
    if settings.gee_timeout_seconds <= 0:
        raise ConfigurationError("GEE_TIMEOUT_SECONDS must be positive")
    if settings.gee_max_retries < 0:
        raise ConfigurationError("GEE_MAX_RETRIES must be >= 0")
    if settings.llm_drafting_provider not in {"template", "local_http", "vertex_gemma", "gemini_api"}:
        raise ConfigurationError("LLM_DRAFTING_PROVIDER must be template, local_http, vertex_gemma or gemini_api")
    if settings.llm_timeout_seconds <= 0:
        raise ConfigurationError("LLM_TIMEOUT_SECONDS must be positive")
    if settings.llm_max_prompt_chars <= 0:
        raise ConfigurationError("LLM_MAX_PROMPT_CHARS must be positive")
    if settings.llm_drafting_provider == "local_http":
        if not settings.llm_local_http_endpoint:
            raise ConfigurationError("LLM_LOCAL_HTTP_ENDPOINT is required when LLM_DRAFTING_PROVIDER=local_http")
        if not settings.llm_model:
            raise ConfigurationError("LLM_MODEL is required when LLM_DRAFTING_PROVIDER=local_http")
    if settings.vertex_ai_timeout_seconds <= 0:
        raise ConfigurationError("VERTEX_AI_TIMEOUT_SECONDS must be positive")
    if settings.llm_drafting_provider == "vertex_gemma":
        if not settings.vertex_ai_project_id:
            raise ConfigurationError("VERTEX_AI_PROJECT_ID is required when LLM_DRAFTING_PROVIDER=vertex_gemma")
        if not settings.vertex_ai_location:
            raise ConfigurationError("VERTEX_AI_LOCATION is required when LLM_DRAFTING_PROVIDER=vertex_gemma")
        if not settings.vertex_ai_endpoint_id:
            raise ConfigurationError("VERTEX_AI_ENDPOINT_ID is required when LLM_DRAFTING_PROVIDER=vertex_gemma")
        if not settings.llm_model:
            raise ConfigurationError("LLM_MODEL is required when LLM_DRAFTING_PROVIDER=vertex_gemma")
    if settings.gemini_api_timeout_seconds <= 0:
        raise ConfigurationError("GEMINI_API_TIMEOUT_SECONDS must be positive")
    if settings.gemini_api_max_output_tokens <= 0:
        raise ConfigurationError("GEMINI_API_MAX_OUTPUT_TOKENS must be positive")
    if not settings.gemini_api_base_url:
        raise ConfigurationError("GEMINI_API_BASE_URL must not be empty")
    if settings.llm_drafting_provider == "gemini_api":
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required when LLM_DRAFTING_PROVIDER=gemini_api")
        if not settings.gemini_api_model:
            raise ConfigurationError("GEMINI_API_MODEL is required when LLM_DRAFTING_PROVIDER=gemini_api")
    if settings.gee_enabled:
        if not settings.gee_project:
            raise ConfigurationError("GEE_PROJECT is required when GEE_ENABLED=True")
        if not settings.gee_service_account:
            raise ConfigurationError("GEE_SERVICE_ACCOUNT is required when GEE_ENABLED=True")
        if not settings.gee_private_key_file:
            raise ConfigurationError("GEE_PRIVATE_KEY_FILE is required when GEE_ENABLED=True")


def _read_float(source: Mapping[str, str], key: str, default: str) -> float:
    try:
        return float(source.get(key, default))
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be a float") from exc


def _read_int(source: Mapping[str, str], key: str, default: str) -> int:
    try:
        return int(source.get(key, default))
    except ValueError as exc:
        raise ConfigurationError(f"{key} must be an integer") from exc


def _read_bool(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw_value = source.get(key)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{key} must be a boolean")


def _read_optional_text(source: Mapping[str, str], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
