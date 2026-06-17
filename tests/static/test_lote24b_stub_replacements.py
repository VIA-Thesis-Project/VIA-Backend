"""Static architecture checks for VIA task 24B — Runtime stub replacements.

Verifies that:
- RuntimeExtractionAcl, RuntimeExtractionRepository and RuntimeEvaluationRepository
  class definitions have been removed (replaced by real adapters in 24B).
- ExtractionAcl, SqlAlchemyExtractionRepository and EvaluationRepository are now
  imported and wired in the application runtime.
- GEE stub and document evidence stub remain with documented reasons.
- Rulebook and agroenv vector stubs were further replaced in task 24B.1.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_RUNTIME_PY = ROOT / "via" / "shared" / "runtime" / "application_runtime.py"


# ─── Removed stubs ────────────────────────────────────────────────────────────


def test_extraction_acl_stub_class_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeExtractionAcl" not in source


def test_extraction_repository_stub_class_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeExtractionRepository" not in source


def test_evaluation_repository_stub_class_removed() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeEvaluationRepository" not in source


# ─── Real adapters wired ──────────────────────────────────────────────────────


def test_real_extraction_acl_imported() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl" in source


def test_real_extraction_acl_instantiated() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "ExtractionAcl()" in source


def test_real_extraction_repository_imported() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyExtractionRepository" in source


def test_real_extraction_repository_used_with_session() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "SqlAlchemyExtractionRepository(session)" in source


def test_real_evaluation_repository_imported() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository" in source


def test_real_evaluation_repository_used_with_session() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "EvaluationRepository(session)" in source


# ─── Remaining stubs documented ───────────────────────────────────────────────


def test_gee_stub_remains() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeGeeExtractionClient" in source


def test_gee_stub_has_reason_documented() -> None:
    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "GEE credentials" in source or "Google Earth Engine" in source


def test_rulebook_evaluation_stub_replaced_in_24b1() -> None:
    """RuntimeRulebookEvaluationPort was replaced by SqlAlchemyRulebookEvaluationBridge in 24B.1."""

    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeRulebookEvaluationPort" not in source


def test_agroenv_vector_stub_replaced_in_24b1() -> None:
    """RuntimeAgroenvVectorPort was replaced by SqlAlchemyAgroenvVectorBridge in 24B.1."""

    source = APPLICATION_RUNTIME_PY.read_text(encoding="utf-8")
    assert "class RuntimeAgroenvVectorPort" not in source
