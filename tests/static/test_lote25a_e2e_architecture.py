"""Static architecture checks for lote 25A: E2E test infrastructure.

Verifies that the E2E conftest and test module respect the lote constraints:
- No GEE imports (no ee, no earthengine-api)
- No LLM imports (no Gemini, Vertex, OpenAI, etc.)
- No Recommendation imports in the E2E test module
- No duplicate MCDA logic (no import of PureMcdaEvaluationEngine from test code)
- No asyncpg / AsyncSession / Celery / Kafka imports
- No use of scripts/evaluation_smoke_test.py as a data source
- ControlledExtractionClient must be defined (extraction is fake)
- LockFreeRelayWorker must be defined (SQLite compatibility)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
E2E_CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"
E2E_TEST = ROOT / "tests" / "e2e" / "test_mcda_evaluation_e2e.py"


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _all_names_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


# ──────────────────────────── file existence ──────────────────────────────────


def test_e2e_conftest_exists() -> None:
    assert E2E_CONFTEST.exists(), f"E2E conftest not found at {E2E_CONFTEST}"


def test_e2e_test_file_exists() -> None:
    assert E2E_TEST.exists(), f"E2E test file not found at {E2E_TEST}"


# ──────────────────────────── no GEE ─────────────────────────────────────────


def test_conftest_does_not_import_gee() -> None:
    imports = _imports_from(E2E_CONFTEST)
    gee = [m for m in imports if "earthengine" in m or m == "ee" or m.startswith("ee.")]
    assert gee == [], f"conftest imports GEE: {gee}"


def test_e2e_test_does_not_import_gee() -> None:
    imports = _imports_from(E2E_TEST)
    gee = [m for m in imports if "earthengine" in m or m == "ee" or m.startswith("ee.")]
    assert gee == [], f"e2e test imports GEE: {gee}"


# ──────────────────────────── no LLM ─────────────────────────────────────────


_LLM_INDICATORS = ("gemini", "vertex", "openai", "anthropic", "llm", "langchain", "transformers")


def test_conftest_does_not_import_llm() -> None:
    imports = _imports_from(E2E_CONFTEST)
    llm = [m for m in imports if any(ind in m.lower() for ind in _LLM_INDICATORS)]
    assert llm == [], f"conftest imports LLM module: {llm}"


def test_e2e_test_does_not_import_llm() -> None:
    imports = _imports_from(E2E_TEST)
    llm = [m for m in imports if any(ind in m.lower() for ind in _LLM_INDICATORS)]
    assert llm == [], f"e2e test imports LLM module: {llm}"


# ──────────────────────────── no Recommendation ───────────────────────────────


def test_e2e_test_does_not_import_recommendation_bc() -> None:
    imports = _imports_from(E2E_TEST)
    rec = [m for m in imports if "recommendation" in m.lower()]
    assert rec == [], f"e2e test imports Recommendation BC: {rec}"


# ──────────────────────────── no async ───────────────────────────────────────


_ASYNC_INDICATORS = ("asyncpg", "aiohttp", "celery", "kafka", "AsyncSession")


def test_conftest_does_not_import_async_infra() -> None:
    imports = _imports_from(E2E_CONFTEST)
    found = [m for m in imports if any(ind.lower() in m.lower() for ind in _ASYNC_INDICATORS)]
    assert found == [], f"conftest imports async/Celery/Kafka infra: {found}"


def test_e2e_test_does_not_import_async_infra() -> None:
    imports = _imports_from(E2E_TEST)
    found = [m for m in imports if any(ind.lower() in m.lower() for ind in _ASYNC_INDICATORS)]
    assert found == [], f"e2e test imports async/Celery/Kafka infra: {found}"


# ──────────────────────────── no smoke test as source ────────────────────────


def test_conftest_does_not_import_smoke_test_script() -> None:
    imports = _imports_from(E2E_CONFTEST)
    found = [m for m in imports if "smoke_test" in m or "evaluation_smoke_test" in m]
    assert found == [], f"conftest imports smoke test script: {found}"


def test_e2e_test_does_not_import_smoke_test_script() -> None:
    imports = _imports_from(E2E_TEST)
    found = [m for m in imports if "smoke_test" in m or "evaluation_smoke_test" in m]
    assert found == [], f"e2e test imports smoke test script: {found}"


# ──────────────────────────── controlled stubs exist ─────────────────────────


def test_controlled_extraction_client_defined_in_conftest() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "ControlledExtractionClient" in classes, (
        "ControlledExtractionClient not defined in conftest — GEE call is not faked"
    )


def test_lock_free_relay_worker_defined_in_conftest() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "LockFreeRelayWorker" in classes, (
        "LockFreeRelayWorker not defined in conftest — FOR UPDATE SKIP LOCKED will fail on SQLite"
    )


def test_controlled_rulebook_read_model_port_defined_in_conftest() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "ControlledRulebookReadModelPort" in classes


def test_controlled_parcel_geometry_port_defined_in_conftest() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "ControlledParcelGeometryPort" in classes


def test_controlled_rulebook_evaluation_port_defined_in_conftest() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "ControlledRulebookEvaluationPort" in classes


# ──────────────────────────── no duplicate MCDA logic ────────────────────────


def test_conftest_does_not_define_mcda_engine() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "PureMcdaEvaluationEngine" not in classes, (
        "conftest must NOT reimplement PureMcdaEvaluationEngine — use the real domain service"
    )


def test_conftest_does_not_reimplement_membership_function() -> None:
    classes = _all_names_from(E2E_CONFTEST)
    assert "TrapezoidalMembershipFunction" not in classes, (
        "conftest must NOT reimplement TrapezoidalMembershipFunction"
    )


# ──────────────────────────── drive_saga helper ───────────────────────────────


def test_drive_saga_helper_defined_in_conftest() -> None:
    tree = ast.parse(E2E_CONFTEST.read_text(encoding="utf-8"))
    func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "drive_saga_to_completion" in func_names, "drive_saga_to_completion helper not found in conftest"
