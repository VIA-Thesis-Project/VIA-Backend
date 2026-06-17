"""Static architecture checks for VIA Lote 8A."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "via" / "bounded_contexts" / "viability_evaluation"
DOMAIN = EVALUATION / "domain"
APPLICATION = EVALUATION / "application"
INFRASTRUCTURE = EVALUATION / "infrastructure"


def test_evaluation_domain_has_no_external_layer_or_context_imports() -> None:
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
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if ".infrastructure" in imported_name or ".interfaces" in imported_name:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_acl_ports_are_declared_in_application_not_domain() -> None:
    ports_text = (APPLICATION / "ports.py").read_text(encoding="utf-8")
    domain_text = "\n".join(path.read_text(encoding="utf-8") for path in DOMAIN.rglob("*.py"))

    assert "class IRulebookEvaluationPort(Protocol)" in ports_text
    assert "class IAgroenvVectorPort(Protocol)" in ports_text
    assert "Protocol" not in domain_text
    assert "Port" not in domain_text


def test_acl_adapters_live_in_infrastructure() -> None:
    assert (INFRASTRUCTURE / "rulebook_acl_adapter.py").exists()
    assert (INFRASTRUCTURE / "agroenv_acl_adapter.py").exists()


def test_evaluation_does_not_import_rulebook_or_extraction_internals() -> None:
    forbidden = ("via.bounded_contexts.rulebook_management", "via.bounded_contexts.agroenv_extraction")
    offenders = []
    for path in EVALUATION.rglob("*.py"):
        imports = _imports_from(path)
        if any(any(imported_name.startswith(prefix) for prefix in forbidden) for imported_name in imports):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_lote8a_does_not_add_mcda_services_or_events() -> None:
    forbidden_tokens = (
        "FuzzificationService",
        "EvaluacionViabilidadCompletada",
        "EvaluacionViabilidadFallida",
        "VectorBrechasGenerado",
    )
    offenders = []
    for path in EVALUATION.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden_tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
    assert not (DOMAIN / "services").exists()


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
