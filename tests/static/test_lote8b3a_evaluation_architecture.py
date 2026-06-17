"""Static architecture checks for VIA Lote 8B.3A."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "via" / "bounded_contexts" / "viability_evaluation"
DOMAIN = EVALUATION / "domain"


def test_mcda_completion_has_no_forbidden_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.config",
        "via.shared.database",
        "via.shared.event_bus",
        "via.shared.outbox",
        "via.bounded_contexts.rulebook_management",
        "via.bounded_contexts.agroenv_extraction",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(DOMAIN / "mcda_completion.py"):
        if ".infrastructure" in imported_name or ".interfaces" in imported_name:
            offenders.append(f"mcda_completion.py imports {imported_name}")
        if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
            offenders.append(f"mcda_completion.py imports {imported_name}")

    assert offenders == []


def test_lote8b3a_does_not_add_infrastructure_http_or_external_calls() -> None:
    forbidden_tokens = (
        "Outbox",
        "Session",
        "create_engine",
        "APIRouter",
        "FastAPI",
        "requests.",
        "httpx.",
    )
    text = (DOMAIN / "mcda_completion.py").read_text(encoding="utf-8")

    assert [token for token in forbidden_tokens if token in text] == []


def test_lote8b3a_does_not_implement_later_steps() -> None:
    forbidden_tokens = (
        "CriticalPolicyService",
        "GapCalculationService",
        "LimitingFactor(",
        "AgronomyGap(",
        "rank_position=",
        "EvaluacionCompletada",
        "VectorBrechasGenerado",
    )
    text = (DOMAIN / "mcda_completion.py").read_text(encoding="utf-8")

    assert [token for token in forbidden_tokens if token in text] == []


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
