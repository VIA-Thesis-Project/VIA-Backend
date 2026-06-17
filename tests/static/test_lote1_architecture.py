"""Static architecture tests for VIA Lote 1."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIA = ROOT / "via"
BOUNDED_CONTEXTS = VIA / "bounded_contexts"
APPROVED_CONTEXTS = {
    "iam",
    "parcel_management",
    "rulebook_management",
    "document_management",
    "agroenv_extraction",
    "viability_evaluation",
    "recommendation",
}
LAYERS = {"domain", "application", "infrastructure", "interfaces"}
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "via.shared.database",
    "via.shared.event_bus",
    "via.shared.outbox",
)


def test_exactly_approved_bounded_contexts_exist() -> None:
    contexts = {path.name for path in BOUNDED_CONTEXTS.iterdir() if path.is_dir() and path.name != "__pycache__"}

    assert contexts == APPROVED_CONTEXTS


def test_each_bounded_context_has_clean_architecture_layers() -> None:
    for context_name in APPROVED_CONTEXTS:
        layers = {path.name for path in (BOUNDED_CONTEXTS / context_name).iterdir() if path.is_dir() and path.name != "__pycache__"}
        assert layers == LAYERS


def test_single_fastapi_entrypoint_exists() -> None:
    main_files = [path for path in VIA.rglob("*.py") if _contains_text(path, "FastAPI(")]

    assert [path.relative_to(ROOT).as_posix() for path in main_files] == ["via/main.py"]


def test_no_async_database_stack_is_used() -> None:
    forbidden_tokens = (
        "async" + "pg",
        "Async" + "Session",
        "create_" + "async_" + "engine",
    )
    offenders = []
    for path in _python_files(VIA):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden_tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_domain_layers_do_not_import_forbidden_dependencies() -> None:
    offenders: list[str] = []
    for path in BOUNDED_CONTEXTS.glob("*/domain/**/*.py"):
        for imported_name in _imports_from(path):
            if imported_name.endswith(".infrastructure") or imported_name.endswith(".interfaces"):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in FORBIDDEN_DOMAIN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def _python_files(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*.py") if "__pycache__" not in item.parts)


def _contains_text(path: Path, needle: str) -> bool:
    return needle in path.read_text(encoding="utf-8")


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
