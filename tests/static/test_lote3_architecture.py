"""Static architecture checks for VIA Lote 3."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "via" / "shared" / "orchestration" / "evaluation_process_manager"


def test_process_manager_does_not_interpret_rulebook_details() -> None:
    text = (PM / "process_manager.py").read_text(encoding="utf-8")

    forbidden_terms = ("criterion_id", "phase_id", "dataset_key", "band", "quality_mask", "membership_fn")
    assert [term for term in forbidden_terms if term in text] == []


def test_process_manager_uses_required_rulebook_read_port_and_spec() -> None:
    text = (PM / "process_manager.py").read_text(encoding="utf-8")

    assert "get_required_extraction_spec" in text
    assert "required_extraction_spec" in text
    assert "correlation_id=evaluation_id" in text


def test_lote3_keeps_synchronous_infrastructure_only() -> None:
    tokens = ("async" + "pg", "Async" + "Session", "create_" + "async_" + "engine", "async" + "io")
    offenders = []
    for path in PM.rglob("*.py"):
        if any(token in path.read_text(encoding="utf-8") for token in tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_router_exposes_only_minimal_start_endpoint() -> None:
    tree = ast.parse((ROOT / "via" / "bounded_contexts" / "viability_evaluation" / "interfaces" / "evaluation_router.py").read_text(encoding="utf-8"))
    route_functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_evaluation"]

    assert route_functions == ["start_evaluation"]
