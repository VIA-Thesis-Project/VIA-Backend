"""Static architecture checks for VIA Lote 8B.2."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "via" / "bounded_contexts" / "viability_evaluation"
DOMAIN = EVALUATION / "domain"


def test_entropy_and_hybrid_domain_modules_have_no_forbidden_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.shared.database",
        "via.shared.event_bus",
        "via.shared.outbox",
        "via.bounded_contexts.rulebook_management",
        "via.bounded_contexts.agroenv_extraction",
    )
    offenders: list[str] = []
    for path in [DOMAIN / "entropy_weights.py", DOMAIN / "hybrid_weights.py", DOMAIN / "criterion_detail.py"]:
        for imported_name in _imports_from(path):
            if ".infrastructure" in imported_name or ".interfaces" in imported_name:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_lote8b2_does_not_add_infrastructure_http_or_external_calls() -> None:
    forbidden_tokens = (
        "Outbox",
        "Session",
        "create_engine",
        "APIRouter",
        "FastAPI",
        "requests.",
        "httpx.",
    )
    offenders = []
    for path in [DOMAIN / "entropy_weights.py", DOMAIN / "hybrid_weights.py"]:
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden_tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_lote8b2_does_not_implement_later_evaluation_steps() -> None:
    forbidden_tokens = (
        "MissingCriteriaService",
        "CriticalPolicyService",
        "GapCalculationService",
        "MulticriteriaAggregationService",
        "rank_position=",
        "score=",
        "EvaluacionCompletada",
        "VectorBrechasGenerado",
    )
    text = "\n".join((DOMAIN / filename).read_text(encoding="utf-8") for filename in ["entropy_weights.py", "hybrid_weights.py"])

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
