"""Unit tests for Agroenvironmental Extraction ACL."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from via.bounded_contexts.agroenv_extraction.application.ports import (
    ExtractionClientResult,
    ExtractionContractError,
    ExtractionRequest,
    StartExtractionCommand,
)
from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError, VariableStatus
from via.bounded_contexts.agroenv_extraction.infrastructure.extraction_acl import ExtractionAcl


ROOT = Path(__file__).resolve().parents[3]
AGROENV = ROOT / "via" / "bounded_contexts" / "agroenv_extraction"


def test_acl_builds_vector_from_required_extraction_spec_only() -> None:
    client = FakeExtractionClient(ExtractionClientResult(0.82, "stub-gee", date(2026, 1, 15)))
    command = _command(fallback_allowed=True)

    vector = ExtractionAcl().build_vector(command, client)

    assert vector.evaluation_id == command.evaluation_id
    assert len(vector.variables) == 1
    entry = vector.variables[0]
    assert entry.variable_name == "ndvi"
    assert entry.criterion_id == "vigor"
    assert entry.crop_id == "cacao"
    assert entry.phase_id == "floracion"
    assert entry.dataset_key == "sentinel-2"
    assert entry.band == "B08"
    assert entry.unit == "index"
    assert entry.quality_mask == {"cloud": "masked"}
    assert entry.fallback_allowed is True
    assert entry.period_key == "2026-01"
    assert entry.value == 0.82
    assert client.requests[0].dataset_key == "sentinel-2"
    assert client.requests[0].parcel_geometry["type"] == "MultiPolygon"


def test_acl_marks_missing_variable_when_fallback_is_allowed() -> None:
    client = FakeExtractionClient(None)

    vector = ExtractionAcl().build_vector(_command(fallback_allowed=True), client)

    entry = vector.variables[0]
    assert entry.status == VariableStatus.CRITERIO_FALTANTE
    assert entry.value is None
    assert entry.source == "unavailable"


def test_acl_fails_when_variable_is_missing_without_fallback() -> None:
    client = FakeExtractionClient(None)

    with pytest.raises(AgroenvExtractionError):
        ExtractionAcl().build_vector(_command(fallback_allowed=False), client)


def test_start_command_normalizes_polygon_parcel_geometry() -> None:
    command = StartExtractionCommand.from_payload(_payload(fallback_allowed=True, parcel_geometry=_polygon()))

    assert command.parcel_geometry["type"] == "MultiPolygon"


def test_start_command_accepts_multipolygon_parcel_geometry() -> None:
    geometry = {"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]}

    command = StartExtractionCommand.from_payload(_payload(fallback_allowed=True, parcel_geometry=geometry))

    assert command.parcel_geometry == geometry


def test_start_command_rejects_missing_parcel_geometry_before_external_client() -> None:
    payload = _payload(fallback_allowed=True, parcel_geometry=None)

    with pytest.raises(ExtractionContractError, match="parcel_geometry is required"):
        StartExtractionCommand.from_payload(payload)


def test_start_command_rejects_invalid_parcel_geometry() -> None:
    payload = _payload(fallback_allowed=True, parcel_geometry={"type": "Point", "coordinates": [0, 0]})

    with pytest.raises(ExtractionContractError, match="Polygon or MultiPolygon"):
        StartExtractionCommand.from_payload(payload)


def test_agroenv_extraction_does_not_import_parcel_management_domain() -> None:
    offenders: list[str] = []
    for path in AGROENV.rglob("*.py"):
        for imported_name in _imports_from(path):
            if imported_name.startswith("via.bounded_contexts.parcel_management.domain"):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


class FakeExtractionClient:
    """External extraction client test double."""

    def __init__(self, result: ExtractionClientResult | None) -> None:
        self.result = result
        self.requests: list[ExtractionRequest] = []

    def extract_variable(self, request: ExtractionRequest) -> ExtractionClientResult | None:
        self.requests.append(request)
        return self.result


def _command(fallback_allowed: bool) -> StartExtractionCommand:
    return StartExtractionCommand.from_payload(_payload(fallback_allowed=fallback_allowed, parcel_geometry=_polygon()))


def _payload(fallback_allowed: bool, parcel_geometry: dict | None) -> dict:
    return {
        "evaluation_id": str(uuid4()),
        "parcel_id": str(uuid4()),
        "parcel_geometry": parcel_geometry,
        "crop_candidates": ["cacao"],
        "temporal_window": {"start": "2026-01-01", "end": "2026-01-31"},
        "required_extraction_spec": {
            "variables": [
                {
                    "variable_name": "ndvi",
                    "criterion_id": "vigor",
                    "crop_id": "cacao",
                    "phase_id": "floracion",
                    "dataset_key": "sentinel-2",
                    "band": "B08",
                    "unit": "index",
                    "temporal_resolution": "monthly",
                    "spatial_resolution": "10m",
                    "scale": 10,
                    "reducer": "median",
                    "aggregation_method": "mean",
                    "quality_mask": {"cloud": "masked"},
                    "fallback_allowed": fallback_allowed,
                    "temporal_periods": [{"period_key": "2026-01", "temporal_weight": 1.0}],
                }
            ]
        },
    }


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[-76.0, -12.0], [-76.0, -12.01], [-75.99, -12.01], [-75.99, -12.0], [-76.0, -12.0]]
        ],
    }


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
