"""Static architecture checks for VIA task 20A.1.

Verifies that application/query_service.py and application/ports.py
do not import from infrastructure or SQLAlchemy, and that the concrete
read repository lives in infrastructure as required by Clean Architecture.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "via" / "bounded_contexts" / "viability_evaluation"
APPLICATION = EVALUATION / "application"
INFRASTRUCTURE = EVALUATION / "infrastructure"


def test_query_service_has_no_orm_or_infrastructure_imports() -> None:
    """application/query_service.py must not import ORM or infrastructure."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.viability_evaluation.infrastructure",
        "via.shared.orchestration.evaluation_process_manager.saga_orm",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(APPLICATION / "query_service.py"):
        if any(
            imported_name == prefix or imported_name.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        ):
            offenders.append(f"query_service.py imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_ports_has_no_orm_or_infrastructure_imports() -> None:
    """application/ports.py must not import ORM or infrastructure."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.viability_evaluation.infrastructure",
        "via.shared.orchestration.evaluation_process_manager.saga_orm",
    )
    offenders: list[str] = []
    for imported_name in _imports_from(APPLICATION / "ports.py"):
        if any(
            imported_name == prefix or imported_name.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        ):
            offenders.append(f"ports.py imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_query_service_and_ports_have_no_infrastructure_imports() -> None:
    """query_service.py and ports.py (the 20A.1 scope) must be infrastructure-free."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.viability_evaluation.infrastructure",
        "via.shared.orchestration.evaluation_process_manager.saga_orm",
    )
    scope_files = [APPLICATION / "query_service.py", APPLICATION / "ports.py"]
    offenders: list[str] = []
    for path in scope_files:
        for imported_name in _imports_from(path):
            if any(
                imported_name == prefix or imported_name.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            ):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == [], "\n".join(offenders)


def test_evaluation_query_repository_exists_in_infrastructure() -> None:
    """The concrete read repository must live in infrastructure, not in application."""

    assert (INFRASTRUCTURE / "evaluation_query_repository.py").is_file(), (
        "evaluation_query_repository.py must exist in infrastructure/"
    )


def test_evaluation_query_repository_imports_orm_and_session() -> None:
    """The infrastructure repository must use SQLAlchemy and ORM models."""

    source = (INFRASTRUCTURE / "evaluation_query_repository.py").read_text(encoding="utf-8")
    assert "sqlalchemy" in source, "Repository should import from sqlalchemy"
    assert "orm_models" in source, "Repository should import from orm_models"


def test_query_service_does_not_reference_session_or_select() -> None:
    """Verify query_service.py no longer contains SQLAlchemy-specific calls."""

    source = (APPLICATION / "query_service.py").read_text(encoding="utf-8")
    forbidden_tokens = ("Session", "select(", "scalars()", "orm_models")
    offenders = [t for t in forbidden_tokens if t in source]
    assert offenders == [], f"query_service.py still references SQLAlchemy: {offenders}"


# ─────────────────────────── helpers ──────────────────────────────────────────


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
