"""Static architecture checks for VIA task 24B.1 — Bridge adapter replacements.

Verifies that:
- The 5 remaining runtime stubs were replaced by real bridge adapters in bridges.py.
- All bridges are wired in configure_application_runtime().
- The only remaining stubs have explicit documented reasons.
- bridges.py does not import domain logic or FastAPI.
- application_runtime.py does not import asyncio, asyncpg or AsyncSession.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_RUNTIME_PY = ROOT / "via" / "shared" / "runtime" / "application_runtime.py"
BRIDGES_PY = ROOT / "via" / "shared" / "runtime" / "bridges.py"


# ─── Removed stubs (replaced by bridges) ──────────────────────────────────────


def test_rulebook_read_model_stub_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeRulebookReadModelPort" not in source


def test_parcel_geometry_stub_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeParcelGeometryReadModelPort" not in source


def test_rulebook_evaluation_stub_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeRulebookEvaluationPort" not in source


def test_agroenv_vector_stub_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeAgroenvVectorPort" not in source


def test_evaluation_results_stub_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeEvaluationResultsPort" not in source


# ─── Bridge adapters exist in bridges.py ──────────────────────────────────────


def test_bridges_module_exists() -> None:
    assert BRIDGES_PY.exists(), "via/shared/runtime/bridges.py must exist"


def test_rulebook_read_model_bridge_exists() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "class SqlAlchemyRulebookReadModelBridge" in source


def test_parcel_geometry_bridge_exists() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "class SqlAlchemyParcelGeometryBridge" in source


def test_rulebook_evaluation_bridge_exists() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "class SqlAlchemyRulebookEvaluationBridge" in source


def test_agroenv_vector_bridge_exists() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "class SqlAlchemyAgroenvVectorBridge" in source


def test_evaluation_results_bridge_exists() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "class SqlAlchemyEvaluationResultsBridge" in source


# ─── Bridges wired in configure_application_runtime() ─────────────────────────


def test_rulebook_read_model_bridge_wired_in_process_manager() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyRulebookReadModelBridge" in source


def test_parcel_geometry_bridge_wired_in_process_manager() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyParcelGeometryBridge" in source


def test_rulebook_evaluation_bridge_wired_in_evaluation_consumer() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyRulebookEvaluationBridge" in source


def test_agroenv_vector_bridge_wired_in_evaluation_consumer() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyAgroenvVectorBridge" in source


def test_evaluation_results_bridge_wired_in_recommendation_consumer() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyEvaluationResultsBridge" in source


# ─── Remaining stubs documented ───────────────────────────────────────────────


def test_gee_stub_remains_documented() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeGeeExtractionClient" in source
    assert "Google Earth Engine" in source


def test_document_evidence_stub_remains_documented() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeDocumentEvidencePort" in source
    assert "embedding" in source.lower()


# ─── Architecture constraints on bridges.py ───────────────────────────────────


def test_bridges_does_not_import_fastapi() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "fastapi" not in source.lower()


def test_bridges_does_not_import_asyncpg() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "asyncpg" not in source


def test_bridges_does_not_use_async_session() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "AsyncSession" not in source


def test_bridges_does_not_import_event_bus() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "event_bus" not in source


def test_application_runtime_does_not_use_asyncio_after_24b1() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "asyncio" not in source


def test_application_runtime_does_not_use_asyncpg_after_24b1() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "asyncpg" not in source


# ─── Bridge imports are from real infrastructure ───────────────────────────────


def test_bridges_imports_parcel_geometry_read_model_adapter() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "ParcelGeometryReadModelAdapter" in source


def test_bridges_imports_rulebook_query_service() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "RulebookQueryService" in source


def test_bridges_imports_evaluation_query_repository() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "EvaluationQueryRepository" in source


def test_bridges_imports_agroenv_orm_models() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "AgroenvVectorModel" in source
    assert "AgroenvVariableEntryModel" in source


def test_bridges_imports_sqlalchemy_parcel_repository() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "SQLAlchemyParcelRepository" in source


def test_bridges_imports_sqlalchemy_rulebook_repository() -> None:
    source = BRIDGES_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyRulebookRepository" in source
