"""Static architecture checks for VIA Lote 6 Rulebook Management."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULEBOOK = ROOT / "via" / "bounded_contexts" / "rulebook_management"
PM = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "process_manager.py"


def test_rulebook_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.bounded_contexts.rulebook_management.infrastructure",
        "via.bounded_contexts.rulebook_management.interfaces",
    )
    offenders = []
    for path in (RULEBOOK / "domain").glob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_rulebook_management_does_not_depend_on_evaluation_or_extraction_contexts() -> None:
    forbidden_prefixes = (
        "via.bounded_contexts.viability_evaluation",
        "via.bounded_contexts.agroenv_extraction",
    )
    offenders = []
    for path in RULEBOOK.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_membership_function_is_not_part_of_criterion() -> None:
    criterion_text = (RULEBOOK / "domain" / "criterion.py").read_text(encoding="utf-8")
    requirement_text = (RULEBOOK / "domain" / "phase_requirement.py").read_text(encoding="utf-8")

    assert "membership_fn" not in criterion_text
    assert "membership_fn" in requirement_text


def test_rulebook_router_exposes_only_required_routes() -> None:
    tree = ast.parse((RULEBOOK / "interfaces" / "rulebook_router.py").read_text(encoding="utf-8"))
    route_decorators = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router":
                        route_decorators.append((decorator.func.attr, decorator.args[0].value if decorator.args else ""))

    assert sorted(route_decorators) == sorted([
        ("get", ""),
        ("post", ""),
        ("post", "/{rulebook_id}/publish"),
        ("get", "/{crop_id}/active"),
    ])


def test_rulebook_phase_requirements_has_dedicated_extraction_binding_column() -> None:
    migration_text = (ROOT / "migrations" / "versions" / "20260614_0002_initial_tables.py").read_text(encoding="utf-8")
    orm_text = (RULEBOOK / "infrastructure" / "orm_models.py").read_text(encoding="utf-8")

    assert "extraction_binding JSONB NOT NULL" in migration_text
    assert "extraction_binding" in orm_text


def test_rulebook_repository_does_not_store_extraction_data_inside_temporal_periods() -> None:
    repository_text = (RULEBOOK / "infrastructure" / "rulebook_repository.py").read_text(encoding="utf-8")

    temporal_assignment = re.search(r"temporal_periods=(?P<expr>[^,\n]+)", repository_text)
    assert temporal_assignment is not None
    assert "temporal_period_payload" in temporal_assignment.group("expr")
    assert '"extraction"' not in repository_text
    assert "extraction_binding=requirement.extraction_binding.to_mapping()" in repository_text


def test_temporal_periods_column_is_documented_as_temporal_only() -> None:
    migration_text = (ROOT / "migrations" / "versions" / "20260614_0002_initial_tables.py").read_text(encoding="utf-8")

    assert "temporal_periods JSONB NOT NULL" in migration_text
    assert "extraction_binding JSONB NOT NULL" in migration_text


def test_required_extraction_spec_is_shared_read_model_without_rulebook_orm_exposure() -> None:
    query_text = (RULEBOOK / "application" / "query_service.py").read_text(encoding="utf-8")

    assert "RequiredExtractionSpec" in query_text
    assert "orm_models" not in query_text
    assert "RulebookModel" not in query_text


def test_process_manager_only_invokes_rulebook_read_model_port() -> None:
    text = PM.read_text(encoding="utf-8")

    assert "get_required_extraction_spec" in text
    for forbidden_term in ("membership_fn", "critical_policy", "penalty_factor", "ahp_weight"):
        assert forbidden_term not in text


def test_lote6_does_not_use_forbidden_infrastructure_stack() -> None:
    tokens = ("async" + "pg", "Async" + "Session", "create_" + "async_" + "engine", "Cel" + "ery", "Kaf" + "ka", "Rabbit" + "MQ", "Re" + "dis")
    offenders = []
    for path in RULEBOOK.rglob("*.py"):
        if any(token in path.read_text(encoding="utf-8") for token in tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
