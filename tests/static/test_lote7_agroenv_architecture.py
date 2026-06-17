"""Static architecture checks for VIA Lote 7 Agroenvironmental Extraction."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGROENV = ROOT / "via" / "bounded_contexts" / "agroenv_extraction"


def test_agroenv_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.bounded_contexts.agroenv_extraction.infrastructure",
        "via.bounded_contexts.agroenv_extraction.interfaces",
        "via.shared.outbox",
        "via.shared.event_bus",
    )
    offenders = []
    for path in (AGROENV / "domain").glob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_agroenv_extraction_does_not_import_rulebooks_or_downstream_contexts() -> None:
    forbidden_prefixes = (
        "via.bounded_contexts.rulebook_management",
        "via.bounded_contexts.viability_evaluation",
        "via.bounded_contexts.document_management",
        "via.bounded_contexts.recommendation",
    )
    offenders = []
    for path in AGROENV.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_agroenv_uses_required_extraction_spec_without_rulebook_interpretation() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in AGROENV.rglob("*.py"))

    assert "required_extraction_spec" in source
    for forbidden_term in ("membership_fn", "ahp_weight", "critical_policy", "penalty_factor"):
        assert forbidden_term not in source


def test_extraction_failure_event_has_single_canonical_name() -> None:
    events_text = (ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager" / "events.py").read_text(encoding="utf-8")
    service_text = (AGROENV / "application" / "command_service.py").read_text(encoding="utf-8")

    assert "EXTRACCION_FALLIDA" in events_text
    assert "EXTRACCION_FALLIDA" in service_text
    assert "ExtraccionAgroambientalFallida" not in events_text
    assert "ExtraccionAgroambientalFallida" not in service_text


def test_agroenv_orm_contains_required_traceability_columns() -> None:
    text = (AGROENV / "infrastructure" / "orm_models.py").read_text(encoding="utf-8")

    for column_name in (
        "variable_name",
        "criterion_id",
        "crop_id",
        "phase_id",
        "dataset_key",
        "band",
        "unit",
        "temporal_resolution",
        "spatial_resolution",
        "scale",
        "reducer",
        "aggregation_method",
        "quality_mask",
        "fallback_allowed",
        "period_key",
        "source",
        "extraction_date",
        "status",
    ):
        assert column_name in text


def test_agroenv_consumer_exposes_no_http_routes() -> None:
    tree = ast.parse((AGROENV / "interfaces" / "extraction_consumer.py").read_text(encoding="utf-8"))
    route_decorators = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router":
                        route_decorators.append(decorator.func.attr)

    assert route_decorators == []


def test_lote7_does_not_use_forbidden_infrastructure_stack() -> None:
    tokens = ("async" + "pg", "Async" + "Session", "create_" + "async_" + "engine", "Cel" + "ery", "Kaf" + "ka", "Rabbit" + "MQ", "Re" + "dis")
    offenders = []
    for path in AGROENV.rglob("*.py"):
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
