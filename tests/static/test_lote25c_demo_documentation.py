"""25C: Static tests for the E2E PostgreSQL MCDA demo documentation.

Verifies:
- docs/e2e_postgres_mcda_demo.md exists
- Documentation mentions key validated components
- Documentation explicitly states what is NOT validated (GEE real, LLM, RAG)
- Documentation uses honest language (parcial/controlado)
- No API key patterns or real credentials
- JSON example is present in the documentation
- docker-compose.postgres.yml is referenced
"""

from __future__ import annotations

import re
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_DEMO_DOC = _REPO_ROOT / "docs" / "e2e_postgres_mcda_demo.md"
_DOCKER_COMPOSE = _REPO_ROOT / "docker-compose.postgres.yml"


# ─────────────────── file existence ──────────────────────────────────────────


def test_demo_doc_exists() -> None:
    assert _DEMO_DOC.exists(), (
        "docs/e2e_postgres_mcda_demo.md does not exist. Run lote 25C implementation."
    )


def test_docker_compose_exists() -> None:
    assert _DOCKER_COMPOSE.exists(), (
        "docker-compose.postgres.yml does not exist. Required for reproducible demo."
    )


# ─────────────────── required content: validated components ──────────────────


def _doc_text() -> str:
    return _DEMO_DOC.read_text(encoding="utf-8")


def test_demo_doc_mentions_postgresql() -> None:
    assert "PostgreSQL" in _doc_text(), "Demo doc must mention PostgreSQL"


def test_demo_doc_mentions_alembic() -> None:
    assert "Alembic" in _doc_text(), "Demo doc must mention Alembic (real migrations)"


def test_demo_doc_mentions_outbox() -> None:
    text = _doc_text()
    assert "Outbox" in text or "outbox" in text, "Demo doc must mention Transactional Outbox"


def test_demo_doc_mentions_relay_worker() -> None:
    text = _doc_text()
    assert "RelayWorker" in text or "Relay Worker" in text or "relay_worker" in text, (
        "Demo doc must mention RelayWorker (real implementation)"
    )


def test_demo_doc_mentions_mcda() -> None:
    assert "MCDA" in _doc_text(), "Demo doc must mention MCDA"


def test_demo_doc_mentions_ranking() -> None:
    text = _doc_text()
    assert "ranking" in text.lower(), "Demo doc must mention ranking de cultivos"


def test_demo_doc_mentions_brechas() -> None:
    text = _doc_text()
    assert "brecha" in text.lower() or "gap" in text.lower(), (
        "Demo doc must mention brechas agronómicas (gaps)"
    )


def test_demo_doc_mentions_for_update_skip_locked() -> None:
    text = _doc_text()
    has_locking = (
        "FOR UPDATE SKIP LOCKED" in text
        or "SKIP LOCKED" in text
        or "skip_locked" in text
    )
    assert has_locking, (
        "Demo doc must mention FOR UPDATE SKIP LOCKED (real PostgreSQL row locking)"
    )


def test_demo_doc_mentions_resultado_mcda_endpoint() -> None:
    assert "resultado-mcda" in _doc_text(), (
        "Demo doc must mention the resultado-mcda endpoint"
    )


# ─────────────────── required content: honest language ───────────────────────


def test_demo_doc_uses_honest_language_parcial() -> None:
    text = _doc_text()
    assert "parcial" in text.lower() or "controlado" in text.lower(), (
        "Demo doc must use honest language: 'E2E parcial' or 'controlado'"
    )


def test_demo_doc_does_not_claim_complete_e2e() -> None:
    text = _doc_text().lower()
    forbidden_phrases = [
        "e2e completo",
        "end-to-end completo",
        "sistema completo",
        "completamente integrado",
        "gee integrado en la saga",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in text, (
            f"Demo doc contains misleading claim: '{phrase}'. Use honest language."
        )


# ─────────────────── required content: what is NOT validated ─────────────────


def test_demo_doc_declares_gee_not_validated() -> None:
    text = _doc_text()
    has_gee_disclaimer = (
        ("GEE" in text or "Google Earth Engine" in text)
        and (
            "No validado" in text
            or "no validado" in text
            or "no está validado" in text
            or "no está integrado" in text
            or "no forman parte" in text
            or "aislar" in text
            or "controlado" in text.lower()
        )
    )
    assert has_gee_disclaimer, (
        "Demo doc must explicitly state that GEE real is not yet validated in the saga"
    )


def test_demo_doc_declares_llm_not_validated() -> None:
    text = _doc_text()
    has_llm_disclaimer = "LLM" in text and (
        "No validado" in text
        or "no validado" in text
        or "no está validado" in text
        or "no se llama" in text.lower()
    )
    assert has_llm_disclaimer, (
        "Demo doc must explicitly state that LLM external is not yet validated"
    )


def test_demo_doc_declares_rag_not_validated() -> None:
    text = _doc_text()
    has_rag_disclaimer = "RAG" in text and (
        "No validado" in text
        or "no validado" in text
        or "no está validado" in text
    )
    assert has_rag_disclaimer, (
        "Demo doc must explicitly state that RAG documental real is not yet validated"
    )


# ─────────────────── required content: commands ──────────────────────────────


def test_demo_doc_has_docker_compose_command() -> None:
    text = _doc_text()
    assert "docker compose" in text.lower() or "docker-compose" in text.lower(), (
        "Demo doc must include docker compose command to start PostgreSQL"
    )


def test_demo_doc_has_database_url_variable() -> None:
    assert "DATABASE_URL" in _doc_text(), (
        "Demo doc must include DATABASE_URL environment variable configuration"
    )


def test_demo_doc_has_pytest_integration_command() -> None:
    text = _doc_text()
    assert "pytest tests/integration/postgres" in text or "pytest tests/integration" in text, (
        "Demo doc must include pytest command for integration tests"
    )


def test_demo_doc_has_pytest_e2e_command() -> None:
    text = _doc_text()
    assert "test_postgres_e2e_mcda" in text, (
        "Demo doc must include command to run the 25B E2E MCDA tests"
    )


def test_demo_doc_has_pytest_full_suite_command() -> None:
    text = _doc_text()
    assert "pytest -q" in text or "pytest -v" in text, (
        "Demo doc must include command to run the full test suite"
    )


# ─────────────────── required content: JSON example ─────────────────────────


def test_demo_doc_has_json_example() -> None:
    text = _doc_text()
    assert "rank_position" in text and "viability_category" in text, (
        "Demo doc must include a JSON example with rank_position and viability_category fields"
    )


def test_demo_doc_json_example_has_gaps() -> None:
    text = _doc_text()
    assert "gap_value" in text and "most_limiting_period" in text, (
        "Demo doc must include a JSON example with gap_value and most_limiting_period fields"
    )


def test_demo_doc_json_example_has_two_crops() -> None:
    text = _doc_text()
    assert "maiz_amarillo_duro" in text and "papa" in text, (
        "Demo doc must include JSON example with both evaluated crops"
    )


# ─────────────────── security: no real credentials or API keys ───────────────


def test_demo_doc_has_no_openai_api_key_pattern() -> None:
    text = _doc_text()
    matches = re.findall(r'\bsk-[A-Za-z0-9]{20,}\b', text)
    assert not matches, (
        f"Demo doc contains what looks like an OpenAI API key: {matches}"
    )


def test_demo_doc_has_no_google_api_key_pattern() -> None:
    text = _doc_text()
    matches = re.findall(r'\bAIza[A-Za-z0-9_\-]{35}\b', text)
    assert not matches, (
        f"Demo doc contains what looks like a Google API key: {matches}"
    )


def test_demo_doc_has_no_bearer_token_pattern() -> None:
    text = _doc_text()
    matches = re.findall(r'\bya29\.[A-Za-z0-9_\-]+\b', text)
    assert not matches, (
        f"Demo doc contains what looks like a Google OAuth token: {matches}"
    )


def test_demo_doc_has_no_private_absolute_path() -> None:
    text = _doc_text()
    suspicious_patterns = [
        r'C:\\Users\\[A-Za-z][A-Za-z0-9_]+\\',
        r'/home/[a-z][a-z0-9_]+/',
        r'/Users/[A-Za-z][A-Za-z0-9_]+/',
    ]
    for pattern in suspicious_patterns:
        matches = re.findall(pattern, text)
        assert not matches, (
            f"Demo doc contains absolute private path (pattern {pattern!r}): {matches}"
        )


def test_demo_doc_has_no_gee_key_file_content() -> None:
    text = _doc_text()
    suspicious = re.findall(r'"private_key"\s*:\s*"-----BEGIN', text)
    assert not suspicious, (
        "Demo doc appears to contain GEE service account private key content"
    )


# ─────────────────── docker-compose content ──────────────────────────────────


def test_docker_compose_uses_dummy_credentials() -> None:
    dc_text = _DOCKER_COMPOSE.read_text(encoding="utf-8")
    assert "POSTGRES_USER" in dc_text, "docker-compose.postgres.yml must define POSTGRES_USER"
    assert "POSTGRES_PASSWORD" in dc_text, "docker-compose.postgres.yml must define POSTGRES_PASSWORD"
    assert "POSTGRES_DB" in dc_text, "docker-compose.postgres.yml must define POSTGRES_DB"


def test_docker_compose_has_no_real_api_key() -> None:
    dc_text = _DOCKER_COMPOSE.read_text(encoding="utf-8")
    openai_keys = re.findall(r'\bsk-[A-Za-z0-9]{20,}\b', dc_text)
    google_keys = re.findall(r'\bAIza[A-Za-z0-9_\-]{35}\b', dc_text)
    assert not openai_keys and not google_keys, (
        "docker-compose.postgres.yml must not contain real API keys"
    )


def test_docker_compose_exposes_local_port() -> None:
    dc_text = _DOCKER_COMPOSE.read_text(encoding="utf-8")
    has_port = "5432" in dc_text or "5433" in dc_text
    assert has_port, "docker-compose.postgres.yml must expose a local PostgreSQL port"
