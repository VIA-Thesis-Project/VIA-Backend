"""Static architecture checks for VIA Lote 5 Parcel Management."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PARCEL = ROOT / "via" / "bounded_contexts" / "parcel_management"


def test_parcel_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.bounded_contexts.parcel_management.infrastructure",
        "via.bounded_contexts.parcel_management.interfaces",
    )
    offenders = []
    for path in (PARCEL / "domain").glob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_parcel_router_exposes_only_required_routes() -> None:
    tree = ast.parse((PARCEL / "interfaces" / "parcel_router.py").read_text(encoding="utf-8"))
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
        ("get", "/{parcel_id}"),
        ("patch", "/{parcel_id}"),
    ])


def test_parcel_repository_uses_existing_transactional_parcels_geometry() -> None:
    orm_text = (PARCEL / "infrastructure" / "orm_models.py").read_text(encoding="utf-8")
    repository_text = (PARCEL / "infrastructure" / "parcel_repository.py").read_text(encoding="utf-8")

    assert '__tablename__ = "parcels"' in orm_text
    assert 'Geometry("MULTIPOLYGON", 4326)' in orm_text
    assert "SRID=4326;MULTIPOLYGON" in repository_text


def test_lote5_does_not_use_forbidden_infrastructure_stack() -> None:
    tokens = ("async" + "pg", "Async" + "Session", "create_" + "async_" + "engine", "Cel" + "ery", "Kaf" + "ka", "Rabbit" + "MQ", "Re" + "dis")
    offenders = []
    for path in PARCEL.rglob("*.py"):
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
