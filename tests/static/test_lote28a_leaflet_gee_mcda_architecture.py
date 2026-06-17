"""Static architecture tests for lote 28A: Leaflet → GEE real → resultado MCDA.

These tests always run (no opt-in needed) and verify:
- The E2E test file exists and has the required test function name
- The documentation file exists and covers key topics
- No hardcoded credentials or absolute paths
- No prohibited imports (asyncpg, AsyncSession, LockFreeRelayWorker, etc.)
- Real DB bridges are used (not controlled stubs)
- GeoJSON [lng, lat] coordinate order is documented
- GEE_TEST_RUN_REAL opt-in guard is implemented

All checks are static — no database, no GEE, no HTTP server required.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_E2E_FILE = _REPO_ROOT / "tests" / "integration" / "postgres" / "test_postgres_e2e_leaflet_gee_mcda.py"
_DOCS_FILE = _REPO_ROOT / "docs" / "leaflet_to_gee_mcda_demo.md"
_SCRIPT_FILE = _REPO_ROOT / "scripts" / "leaflet_to_gee_mcda_demo.py"


# ──────────────────────────── helpers ────────────────────────────────────────


def _e2e_src() -> str:
    return _E2E_FILE.read_text(encoding="utf-8")


def _e2e_tree() -> ast.Module:
    return ast.parse(_e2e_src())


def _docs_src() -> str:
    return _DOCS_FILE.read_text(encoding="utf-8")


def _collect_imports(tree: ast.Module) -> list[str]:
    """Return all module names imported in an AST tree (flattened)."""
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name.lower())
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            imported.append(module)
            for alias in node.names:
                imported.append(f"{module}.{alias.name.lower()}" if module else alias.name.lower())
    return imported


def _top_level_function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and isinstance(getattr(node, "parent", None), ast.Module)
    }


def _all_function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ──────────────────────────── file existence ────────────────────────────────


def test_28a_e2e_file_exists() -> None:
    assert _E2E_FILE.exists(), (
        f"28A E2E test file missing: {_E2E_FILE.relative_to(_REPO_ROOT)}"
    )


def test_28a_docs_file_exists() -> None:
    assert _DOCS_FILE.exists(), (
        f"28A docs file missing: {_DOCS_FILE.relative_to(_REPO_ROOT)}"
    )


# ──────────────────────────── required test function ─────────────────────────


def test_28a_required_test_function_exists() -> None:
    """The primary E2E test function must have the exact required name."""
    tree = _e2e_tree()
    names = _all_function_names(tree)
    assert "test_leaflet_geojson_to_gee_mcda_real_flow_opt_in" in names, (
        "test_leaflet_geojson_to_gee_mcda_real_flow_opt_in not found in E2E file. "
        "This function name is required by the 28A specification."
    )


def test_28a_standalone_credentials_check_exists() -> None:
    """A standalone opt-in credentials check test must be present."""
    tree = _e2e_tree()
    names = _all_function_names(tree)
    credential_tests = [n for n in names if n.startswith("test_") and "credential" in n.lower()]
    assert credential_tests, (
        "No standalone credentials-check test found in E2E file. "
        "Expected a test_*credential* function that always collects but skips gracefully."
    )


# ──────────────────────────── opt-in guard ───────────────────────────────────


def test_28a_gee_test_run_real_guard_present() -> None:
    """GEE_TEST_RUN_REAL must appear as the opt-in guard variable."""
    src = _e2e_src()
    assert "GEE_TEST_RUN_REAL" in src, (
        "GEE_TEST_RUN_REAL not found in E2E file. "
        "All 28A real tests must be opt-in via this environment variable."
    )


def test_28a_skip_not_fail_on_missing_opt_in() -> None:
    """pytest.skip must be called when GEE_TEST_RUN_REAL is not set."""
    src = _e2e_src()
    assert "pytest.skip" in src, (
        "pytest.skip not found in E2E file. "
        "Tests must SKIP (not fail) when GEE_TEST_RUN_REAL is not set."
    )


def test_28a_gee_required_env_vars_checked() -> None:
    """GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_PRIVATE_KEY_FILE must be checked."""
    src = _e2e_src()
    for var in ("GEE_PROJECT", "GEE_SERVICE_ACCOUNT", "GEE_PRIVATE_KEY_FILE"):
        assert var in src, (
            f"{var} not checked in E2E file. "
            "All GEE credentials must be validated before real tests run."
        )


# ──────────────────────────── real DB bridges ─────────────────────────────────


def test_28a_uses_sqlalchemy_parcel_geometry_bridge() -> None:
    """SqlAlchemyParcelGeometryBridge must be imported and used (not a controlled stub)."""
    src = _e2e_src()
    assert "SqlAlchemyParcelGeometryBridge" in src, (
        "SqlAlchemyParcelGeometryBridge not found in E2E file. "
        "28A must read parcel geometry from real PostgreSQL, not a controlled port."
    )


def test_28a_uses_sqlalchemy_rulebook_read_model_bridge() -> None:
    """SqlAlchemyRulebookReadModelBridge must be imported and used (not a controlled stub)."""
    src = _e2e_src()
    assert "SqlAlchemyRulebookReadModelBridge" in src, (
        "SqlAlchemyRulebookReadModelBridge not found in E2E file. "
        "28A must read the rulebook extraction spec from real PostgreSQL."
    )


def test_28a_uses_sqlalchemy_rulebook_evaluation_bridge() -> None:
    """SqlAlchemyRulebookEvaluationBridge must be imported and used for MCDA."""
    src = _e2e_src()
    assert "SqlAlchemyRulebookEvaluationBridge" in src, (
        "SqlAlchemyRulebookEvaluationBridge not found in E2E file. "
        "28A must read the active rulebook from real PostgreSQL for MCDA evaluation."
    )


def test_28a_does_not_use_controlled_geometry_port() -> None:
    """28A must not use GeeRealParcelGeometryPort (27A controlled stub)."""
    src = _e2e_src()
    assert "GeeRealParcelGeometryPort" not in src, (
        "GeeRealParcelGeometryPort found in 28A E2E file. "
        "28A must use SqlAlchemyParcelGeometryBridge instead."
    )


def test_28a_does_not_use_controlled_rulebook_read_port() -> None:
    """28A must not use GeeRealRulebookReadModelPort (27A controlled stub)."""
    src = _e2e_src()
    assert "GeeRealRulebookReadModelPort" not in src, (
        "GeeRealRulebookReadModelPort found in 28A E2E file. "
        "28A must use SqlAlchemyRulebookReadModelBridge instead."
    )


def test_28a_does_not_use_controlled_evaluation_port() -> None:
    """28A must not use GeeRealRulebookEvaluationPort (27A controlled stub)."""
    src = _e2e_src()
    assert "GeeRealRulebookEvaluationPort" not in src, (
        "GeeRealRulebookEvaluationPort found in 28A E2E file. "
        "28A must use SqlAlchemyRulebookEvaluationBridge instead."
    )


# ──────────────────────────── real parcel + rulebook creation ─────────────────


def test_28a_creates_parcel_via_command_service() -> None:
    """ParcelCommandService must be used to create the parcel in PostgreSQL."""
    src = _e2e_src()
    assert "ParcelCommandService" in src, (
        "ParcelCommandService not found in E2E file. "
        "28A must register a real parcel via ParcelCommandService."
    )


def test_28a_creates_rulebook_via_command_service() -> None:
    """RulebookCommandService must be used to create and publish the rulebook."""
    src = _e2e_src()
    assert "RulebookCommandService" in src, (
        "RulebookCommandService not found in E2E file. "
        "28A must create and publish a real rulebook via RulebookCommandService."
    )


def test_28a_uses_real_gee_extraction_client() -> None:
    """GeeExtractionClient must be used (not ControlledExtractionClient)."""
    src = _e2e_src()
    assert "GeeExtractionClient" in src, (
        "GeeExtractionClient not found in E2E file. "
        "28A must use real GEE extraction."
    )
    assert "ControlledExtractionClient" not in src, (
        "ControlledExtractionClient found in 28A E2E file. "
        "28A must use GeeExtractionClient, not a controlled stub."
    )


# ──────────────────────────── GeoJSON coordinate order ───────────────────────


def test_28a_geojson_uses_lng_lat_order() -> None:
    """The Lima polygon in the E2E file must use GeoJSON [lng, lat] — not Leaflet [lat, lng]."""
    src = _e2e_src()
    # Lima, Peru coordinates in correct [lng, lat] order: lng ~ -76, lat ~ -12
    assert "-76.0" in src or "-76," in src, (
        "Expected Lima longitude (-76.xxx) not found in E2E file. "
        "Polygon must use GeoJSON [lng, lat] format."
    )
    # Latitude should appear as -12.xxx
    assert "-12.0" in src or "-12," in src, (
        "Expected Lima latitude (-12.xxx) not found in E2E file. "
        "Polygon must use GeoJSON [lng, lat] format."
    )


def test_28a_docs_warns_about_leaflet_vs_geojson() -> None:
    """Documentation must warn about Leaflet [lat, lng] vs GeoJSON [lng, lat]."""
    docs = _docs_src()
    assert "lng" in docs.lower() and "lat" in docs.lower(), (
        "Documentation must mention [lng, lat] and [lat, lng] coordinate order difference."
    )
    leaflet_warning = "leaflet" in docs.lower() and "geojson" in docs.lower()
    assert leaflet_warning, (
        "Documentation must explicitly warn about Leaflet vs GeoJSON coordinate order."
    )


# ──────────────────────────── GEE dataset ────────────────────────────────────


def test_28a_uses_copernicus_s2_dataset() -> None:
    """E2E file must reference COPERNICUS/S2_SR_HARMONIZED."""
    src = _e2e_src()
    assert "COPERNICUS/S2_SR_HARMONIZED" in src, (
        "COPERNICUS/S2_SR_HARMONIZED not found in E2E file."
    )


def test_28a_uses_band_b8() -> None:
    """E2E file must reference band B8 (NIR)."""
    src = _e2e_src()
    assert '"B8"' in src or "'B8'" in src, (
        "Band B8 not found in E2E file. Must use Sentinel-2 NIR band B8."
    )


def test_28a_docs_references_gee_dataset() -> None:
    """Documentation must mention COPERNICUS/S2_SR_HARMONIZED."""
    docs = _docs_src()
    assert "COPERNICUS/S2_SR_HARMONIZED" in docs, (
        "COPERNICUS/S2_SR_HARMONIZED not found in documentation."
    )


# ──────────────────────────── resultado-mcda endpoint ────────────────────────


def test_28a_queries_resultado_mcda_endpoint() -> None:
    """resultado-mcda endpoint must be queried in the E2E test."""
    src = _e2e_src()
    assert "resultado-mcda" in src, (
        "resultado-mcda endpoint not referenced in E2E file. "
        "The final result must come from GET /evaluaciones/{id}/resultado-mcda."
    )


def test_28a_docs_shows_resultado_mcda_example() -> None:
    """Documentation must show the resultado-mcda endpoint and response example."""
    docs = _docs_src()
    assert "resultado-mcda" in docs, (
        "resultado-mcda not found in documentation."
    )


# ──────────────────────────── security: no hardcoded credentials ──────────────


def test_28a_no_hardcoded_service_account_email() -> None:
    """No service account email pattern must appear in the E2E source."""
    src = _e2e_src()
    matches = re.findall(r"[a-z0-9_\-]+@[a-z0-9\-]+\.iam\.gserviceaccount\.com", src)
    assert not matches, (
        f"Hardcoded service account email(s) found in E2E file: {matches}. "
        "Use environment variables only."
    )


def test_28a_no_private_key_pem_content() -> None:
    """No PEM private key content must appear in the E2E source."""
    src = _e2e_src()
    assert "BEGIN RSA PRIVATE KEY" not in src, (
        "PEM private key content found in E2E file. Never hardcode key material."
    )
    assert "BEGIN PRIVATE KEY" not in src, (
        "PEM private key content found in E2E file. Never hardcode key material."
    )


def test_28a_no_absolute_user_path_in_e2e() -> None:
    """No Windows or Linux user home directory paths must appear in the E2E source."""
    src = _e2e_src()
    forbidden = re.findall(r"C:\\Users\\[A-Za-z]+\\", src) + re.findall(r"/home/[a-z]+/", src)
    assert not forbidden, (
        f"Absolute user path(s) found in E2E file: {forbidden}. "
        "Use environment variables or relative paths."
    )


def test_28a_no_hardcoded_credentials_in_docs() -> None:
    """No service account email must appear in the documentation."""
    docs = _docs_src()
    matches = re.findall(r"[a-z0-9_\-]+@[a-z0-9\-]+\.iam\.gserviceaccount\.com", docs)
    # Exclude placeholder examples (containing 'tu-' or 'example')
    real_matches = [m for m in matches if "tu-" not in m and "example" not in m]
    assert not real_matches, (
        f"Potentially real service account email(s) found in docs: {real_matches}. "
        "Use placeholder values (e.g. tu-cuenta@proyecto.iam.gserviceaccount.com)."
    )


def test_28a_no_absolute_user_path_in_docs() -> None:
    """No absolute user home directory paths must appear in the documentation."""
    docs = _docs_src()
    forbidden = re.findall(r"C:\\Users\\[A-Za-z]+\\", docs) + re.findall(r"/home/[a-z]+/", docs)
    # Allow '/home/' only if it looks like a placeholder example
    real_forbidden = [p for p in forbidden if "usuario" not in p.lower() and "user" not in p.lower()]
    assert not real_forbidden, (
        f"Absolute user path(s) found in docs: {real_forbidden}."
    )


# ──────────────────────────── prohibited imports (AST-based) ─────────────────


def test_28a_does_not_import_asyncpg() -> None:
    tree = _e2e_tree()
    for mod in _collect_imports(tree):
        assert "asyncpg" not in mod, (
            f"asyncpg imported in E2E file ({mod}). 28A must use synchronous psycopg2 only."
        )


def test_28a_does_not_import_asyncsession() -> None:
    tree = _e2e_tree()
    imports = _collect_imports(tree)
    for mod in imports:
        assert "asyncsession" not in mod, (
            f"AsyncSession imported in E2E file ({mod}). 28A must use synchronous Session."
        )


def test_28a_does_not_import_create_async_engine() -> None:
    tree = _e2e_tree()
    imports = _collect_imports(tree)
    for mod in imports:
        assert "create_async_engine" not in mod, (
            f"create_async_engine imported in E2E file ({mod}). "
            "28A must use synchronous create_engine."
        )


def test_28a_does_not_import_lockfree_relay() -> None:
    tree = _e2e_tree()
    src = _e2e_src()
    assert "LockFreeRelayWorker" not in src, (
        "LockFreeRelayWorker found in E2E file. "
        "28A must use RelayWorker with FOR UPDATE SKIP LOCKED."
    )


def test_28a_does_not_import_sqlite() -> None:
    tree = _e2e_tree()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = (getattr(node, "module", "") or "").lower()
            if "sqlite" in module:
                raise AssertionError(
                    f"sqlite imported as module in E2E file: {module}. "
                    "28A must use real PostgreSQL only."
                )
            for alias in node.names:
                if "sqlite" in alias.name.lower():
                    raise AssertionError(
                        f"sqlite imported as name in E2E file: {alias.name}. "
                        "28A must use real PostgreSQL only."
                    )


def test_28a_does_not_import_celery() -> None:
    tree = _e2e_tree()
    for mod in _collect_imports(tree):
        assert "celery" not in mod, (
            f"celery imported in E2E file ({mod}). 28A does not use Celery."
        )


def test_28a_does_not_import_kafka() -> None:
    tree = _e2e_tree()
    for mod in _collect_imports(tree):
        assert "kafka" not in mod, (
            f"kafka imported in E2E file ({mod}). 28A does not use Kafka."
        )


def test_28a_does_not_import_redis() -> None:
    tree = _e2e_tree()
    for mod in _collect_imports(tree):
        assert "redis" not in mod, (
            f"redis imported in E2E file ({mod}). 28A does not use Redis."
        )


# ──────────────────────────── no LLM / Recommendation ────────────────────────


def test_28a_does_not_import_recommendation_consumer() -> None:
    """28A must not import or use the Recommendation consumer."""
    src = _e2e_src()
    assert "RecommendationConsumer" not in src, (
        "RecommendationConsumer found in 28A E2E file. 28A stops at EVALUACION_COMPLETADA."
    )
    assert "recommendation_consumer" not in src.lower(), (
        "recommendation_consumer reference found in 28A E2E file."
    )


def test_28a_docs_states_no_llm() -> None:
    """Documentation must explicitly state that no LLM or Recommendation is used."""
    docs = _docs_src()
    no_llm_mentioned = (
        "llm" in docs.lower()
        or "recommendation" in docs.lower()
        or "gemini" in docs.lower()
        or "vertex" in docs.lower()
    )
    assert no_llm_mentioned, (
        "Documentation must mention LLM/Recommendation scope as out-of-scope "
        "so readers understand the MVP boundaries."
    )


# ──────────────────────────── MVP framing ────────────────────────────────────


def test_28a_docs_frames_as_mvp() -> None:
    """Documentation must not claim this is a complete production system."""
    docs = _docs_src()
    mvp_framing = (
        "mvp" in docs.lower()
        or "técnico" in docs.lower()
        or "limitaciones" in docs.lower()
        or "demo" in docs.lower()
    )
    assert mvp_framing, (
        "Documentation must frame this as MVP/demo, not production-complete."
    )


def test_28a_docs_has_run_instructions() -> None:
    """Documentation must include how to run the opt-in test."""
    docs = _docs_src()
    assert "GEE_TEST_RUN_REAL" in docs, (
        "Documentation must show how to activate the opt-in test (GEE_TEST_RUN_REAL=1)."
    )
    assert "pytest" in docs, (
        "Documentation must show the pytest command to run the test."
    )


# ──────────────────────────── UUID validity (28A.1 fix) ──────────────────────


def test_28a_script_uuids_are_valid() -> None:
    """All UUID() calls in the demo script must use valid hex-only strings.

    Non-hex characters like 'm' or 'o' cause ValueError at import time.
    """
    from uuid import UUID as _UUID

    if not _SCRIPT_FILE.exists():
        pytest.skip(f"Script file not found: {_SCRIPT_FILE.name}")

    script = _SCRIPT_FILE.read_text(encoding="utf-8")
    uuid_call_pattern = re.compile(r'UUID\("([^"]+)"\)')
    invalid: list[str] = []
    for match in uuid_call_pattern.finditer(script):
        raw = match.group(1)
        try:
            _UUID(raw)
        except ValueError:
            invalid.append(raw)
    assert not invalid, (
        f"Invalid UUID(s) found in demo script — non-hex characters detected: {invalid}. "
        "UUID segments must only contain 0-9 and a-f."
    )


def test_28a_e2e_uuids_are_valid() -> None:
    """All UUID() calls in the E2E test must use valid hex-only strings."""
    from uuid import UUID as _UUID

    src = _e2e_src()
    uuid_call_pattern = re.compile(r'UUID\("([^"]+)"\)')
    invalid: list[str] = []
    for match in uuid_call_pattern.finditer(src):
        raw = match.group(1)
        try:
            _UUID(raw)
        except ValueError:
            invalid.append(raw)
    assert not invalid, (
        f"Invalid UUID(s) found in E2E test file: {invalid}. "
        "UUID segments must only contain 0-9 and a-f."
    )
