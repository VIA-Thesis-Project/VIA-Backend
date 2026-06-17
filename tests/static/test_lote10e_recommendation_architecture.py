"""Static architecture checks for VIA task 10E.

Verifies that application-layer query service and ports do not import
infrastructure or SQLAlchemy, and that the concrete read repository lives
in infrastructure as required by Clean Architecture.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECOMMENDATION = ROOT / "via" / "bounded_contexts" / "recommendation"
APPLICATION = RECOMMENDATION / "application"
INFRASTRUCTURE = RECOMMENDATION / "infrastructure"
INTERFACES = RECOMMENDATION / "interfaces"


def test_recommendation_query_service_has_no_orm_or_infrastructure_imports() -> None:
    """application/recommendation_query_service.py must not import ORM or infrastructure."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.recommendation.infrastructure",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(APPLICATION / "recommendation_query_service.py"):
        if any(imported_name == p or imported_name.startswith(p + ".") for p in forbidden_prefixes):
            offenders.append(f"recommendation_query_service.py imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_recommendation_ports_has_no_orm_or_infrastructure_imports() -> None:
    """application/ports.py must not import ORM or infrastructure."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.recommendation.infrastructure",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(APPLICATION / "ports.py"):
        if any(imported_name == p or imported_name.startswith(p + ".") for p in forbidden_prefixes):
            offenders.append(f"ports.py imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_recommendation_router_has_no_llm_or_generation_imports() -> None:
    """interfaces/recommendation_router.py must not import LLM or generation code."""

    forbidden_prefixes = (
        "via.bounded_contexts.recommendation.infrastructure.llm_adapter",
        "via.bounded_contexts.recommendation.infrastructure.template_drafting_provider",
        "via.bounded_contexts.recommendation.application.command_service",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(INTERFACES / "recommendation_router.py"):
        if any(imported_name == p or imported_name.startswith(p + ".") for p in forbidden_prefixes):
            offenders.append(f"recommendation_router.py imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_recommendation_query_repository_exists_in_infrastructure() -> None:
    """The concrete read repository must live in infrastructure, not in application."""

    assert (INFRASTRUCTURE / "recommendation_query_repository.py").is_file(), (
        "recommendation_query_repository.py must exist in infrastructure/"
    )


def test_recommendation_query_repository_imports_orm_and_session() -> None:
    """The infrastructure repository must use SQLAlchemy and ORM models."""

    source = (INFRASTRUCTURE / "recommendation_query_repository.py").read_text(encoding="utf-8")
    assert "sqlalchemy" in source, "Repository should import from sqlalchemy"
    assert "RecommendationModel" in source, "Repository should import RecommendationModel"


def test_recommendation_query_service_does_not_reference_session_or_select() -> None:
    """Verify recommendation_query_service.py contains no SQLAlchemy-specific calls."""

    source = (APPLICATION / "recommendation_query_service.py").read_text(encoding="utf-8")
    forbidden_tokens = ("Session", "select(", "scalars()", "RecommendationModel")
    offenders = [t for t in forbidden_tokens if t in source]
    assert offenders == [], f"recommendation_query_service.py still references SQLAlchemy: {offenders}"


# ─────────────────────── helpers ──────────────────────────────────────────────


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
